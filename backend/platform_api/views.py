import secrets
import string
import threading
import json
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.contrib.auth import login as django_login
from django.db import close_old_connections, transaction
from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncDate
from django.http import HttpResponseBadRequest, HttpResponseRedirect
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken

from .constants import BUSINESS_MODULE_NAMES
from .data_factory import DataFactoryError, bet_cancel, execute_account_add, execute_account_balance, push_order_result, rollback_bet_cancel, rollback_bet_settlement
from .interface_import import InterfaceImportError, parse_fetch_text
from .models import ApiInterface, AutomationModule, AutomationTask, AutomationTaskResult, DataFactoryExecution, Environment, MonitorAlarm, MonitorApiConfig, MonitorExecution, MonitorExecutionDetail, MonitorTask, Role, User, UserEnvironmentAccount
from .pagination import StandardPagination
from .permissions import ActionPermissionMixin
from .responses import success
from .serializers import ApiInterfaceSerializer, AutomationModuleSerializer, AutomationTaskResultSerializer, AutomationTaskSerializer, DataFactoryExecutionSerializer, EnvironmentSerializer, MonitorAlarmSerializer, MonitorApiConfigSerializer, MonitorExecutionDetailSerializer, MonitorExecutionSerializer, MonitorTaskSerializer, PermissionSerializer, ResetPasswordSerializer, RoleSerializer, UserCreateSerializer, UserEnvironmentAccountUpdateSerializer, UserSerializer
from .services import execute_monitor_task, execute_task, retry_monitor_detail, retry_task_result, sync_monitor_next_run_time


class DashboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        permissions = request.user.role.permissions if isinstance(request.user.role.permissions, list) else []
        if not (request.user.is_superuser or request.user.role.code == 'admin' or 'home.view' in permissions):
            raise PermissionDenied('当前账号没有查看首页的权限')
        interface_by_method = list(ApiInterface.objects.values('method').annotate(count=Count('id')).order_by('method'))
        interface_by_module = list(ApiInterface.objects.values('module_name').annotate(count=Count('id')).order_by('-count', 'module_name'))
        task_status = {item['status']: item['count'] for item in AutomationTask.objects.values('status').annotate(count=Count('id'))}
        detail_total = AutomationTaskResult.objects.count()
        detail_passed = AutomationTaskResult.objects.filter(status='passed').count()
        detail_failed = AutomationTaskResult.objects.filter(status='failed').count()
        average_duration = AutomationTaskResult.objects.exclude(duration_ms=None).aggregate(value=Avg('duration_ms'))['value'] or 0

        today = timezone.localdate()
        start_date = today - timezone.timedelta(days=6)
        trend_rows = AutomationTaskResult.objects.filter(executed_at__date__gte=start_date).annotate(
            day=TruncDate('executed_at')
        ).values('day', 'status').annotate(count=Count('id'))
        trend_map = {(row['day'], row['status']): row['count'] for row in trend_rows}
        trend = []
        for offset in range(7):
            day = start_date + timezone.timedelta(days=offset)
            trend.append({
                'date': day.isoformat(),
                'passed': trend_map.get((day, 'passed'), 0),
                'failed': trend_map.get((day, 'failed'), 0),
            })

        recent_tasks = []
        for task in AutomationTask.objects.select_related('module', 'environment', 'owner').prefetch_related('modules').order_by('-updated_at')[:6]:
            module_names = list(task.modules.values_list('name', flat=True))
            if not module_names and task.module_id:
                module_names = [task.module.name]
            recent_tasks.append({
                'id': task.id,
                'name': task.name,
                'module_name': '、'.join(module_names),
                'environment_name': task.environment.name,
                'status': task.status,
                'status_name': task.get_status_display(),
                'owner_name': task.owner.display_name,
                'updated_at': task.updated_at,
            })

        data = {
            'interfaces': {
                'total': ApiInterface.objects.count(),
                'by_method': interface_by_method,
                'by_module': interface_by_module,
            },
            'execution': {
                'task_total': AutomationTask.objects.count(),
                'task_passed': task_status.get('passed', 0),
                'task_failed': task_status.get('failed', 0),
                'task_running': task_status.get('running', 0),
                'detail_total': detail_total,
                'detail_passed': detail_passed,
                'detail_failed': detail_failed,
                'pass_rate': round(detail_passed * 100 / detail_total, 1) if detail_total else 0,
                'average_duration_ms': round(average_duration),
                'today_total': AutomationTaskResult.objects.filter(executed_at__date=today).count(),
            },
            'trend': trend,
            'recent_tasks': recent_tasks,
        }
        return success(data)


class LoginSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        data['user'] = UserSerializer(self.user).data
        return data


class LoginView(TokenObtainPairView):
    permission_classes = [AllowAny]
    serializer_class = LoginSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return success(serializer.validated_data, '登录成功')


def lark_request(path, *, payload=None, access_token=''):
    headers = {'Content-Type': 'application/json'}
    if access_token:
        headers['Authorization'] = f'Bearer {access_token}'
    request = Request(
        f'{settings.LARK_OPEN_BASE_URL}{path}',
        data=json.dumps(payload).encode('utf-8') if payload is not None else None,
        headers=headers,
        method='POST' if payload is not None else 'GET',
    )
    try:
        with urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ValidationError('Lark 身份验证服务暂时不可用') from exc
    if data.get('code', 0) != 0:
        raise ValidationError(data.get('msg') or 'Lark 身份验证失败')
    # Lark identity APIs return their payload under data, while the app-token
    # endpoint returns app_access_token at the top level.
    return data.get('data') or data


def lark_redirect_uri(request):
    return settings.LARK_REDIRECT_URI or request.build_absolute_uri('/api/auth/lark/callback/')


def lark_token(data, key, label):
    token = str(data.get(key, '')).strip()
    if not token:
        raise ValidationError(f'Lark 未返回有效的{label}')
    return token


def lark_username(union_id):
    base = f'lark_{union_id[:16]}'
    username = base
    suffix = 2
    while User.objects.filter(username=username).exists():
        username = f'{base}_{suffix}'
        suffix += 1
    return username


def provision_lark_user(user_info):
    union_id = str(user_info.get('union_id', '')).strip()
    if not union_id:
        raise ValidationError('Lark 未返回 union_id，无法确认平台身份')
    open_id = str(user_info.get('open_id', '')).strip()
    name = str(user_info.get('name', '')).strip() or 'Lark 用户'
    email = str(user_info.get('email', '')).strip().lower()
    with transaction.atomic():
        user = User.objects.select_for_update().filter(lark_union_id=union_id).first()
        if user:
            changed = []
            for field, value in [('name', name), ('lark_open_id', open_id), ('email', email)]:
                if value and getattr(user, field) != value:
                    setattr(user, field, value)
                    changed.append(field)
            if changed:
                user.save(update_fields=[*changed, 'updated_at'])
            return user
        # A previously manual account can be safely bound only when it has no Lark identity.
        user = User.objects.select_for_update().filter(email__iexact=email, lark_union_id__isnull=True).first() if email else None
        if user:
            user.lark_union_id = union_id
            user.lark_open_id = open_id
            if name:
                user.name = name
            user.save(update_fields=['lark_union_id', 'lark_open_id', 'name', 'updated_at'])
            return user
        role = Role.objects.filter(code=settings.LARK_DEFAULT_ROLE_CODE).first()
        if not role:
            raise ValidationError('未配置 Lark 新用户默认角色')
        return User.objects.create(
            username=lark_username(union_id), name=name, email=email,
            role=role, lark_union_id=union_id, lark_open_id=open_id,
            created_via='lark_sso', is_active=True,
        )


def lark_platform_login_redirect(user):
    refresh = RefreshToken.for_user(user)
    params = urlencode({
        'access': str(refresh.access_token),
        'refresh': str(refresh),
        'user': json.dumps(UserSerializer(user).data, ensure_ascii=False),
    })
    return HttpResponseRedirect(f'{settings.LARK_FRONTEND_URL}/login#{params}')


class LarkLoginView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    def get(self, request):
        if not settings.LARK_APP_ID or not settings.LARK_APP_SECRET:
            return HttpResponseBadRequest('Lark AppID 或 AppSecret 未配置')
        # A successful first Lark login leaves a server-side session in this browser.
        # Reuse only a user whose identity has been bound to Lark.
        if request.user.is_authenticated and request.user.is_active and request.user.lark_union_id:
            return lark_platform_login_redirect(request.user)
        state = secrets.token_urlsafe(32)
        request.session['lark_oauth_state'] = state
        params = urlencode({'app_id': settings.LARK_APP_ID, 'redirect_uri': lark_redirect_uri(request), 'state': state})
        return HttpResponseRedirect(f'{settings.LARK_OPEN_BASE_URL}/open-apis/authen/v1/authorize?{params}')


class LarkCallbackView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        code = str(request.query_params.get('code', '')).strip()
        state = str(request.query_params.get('state', '')).strip()
        expected_state = request.session.pop('lark_oauth_state', '')
        if not code or not expected_state or not secrets.compare_digest(state, expected_state):
            return HttpResponseBadRequest('Lark 登录请求无效或已过期')
        try:
            app_token = lark_token(lark_request('/open-apis/auth/v3/app_access_token/internal', payload={
                'app_id': settings.LARK_APP_ID,
                'app_secret': settings.LARK_APP_SECRET,
            }), 'app_access_token', '应用访问令牌')
            user_token = lark_token(lark_request('/open-apis/authen/v1/access_token', payload={
                'grant_type': 'authorization_code',
                'code': code,
            }, access_token=app_token), 'access_token', '用户访问令牌')
            user = provision_lark_user(lark_request('/open-apis/authen/v1/user_info', access_token=user_token))
        except ValidationError as exc:
            return HttpResponseBadRequest(str(exc.detail[0] if isinstance(exc.detail, list) else exc.detail))
        django_login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        return lark_platform_login_redirect(user)


class MeViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def list(self, request):
        return success(UserSerializer(request.user).data)


class MeEnvironmentAccountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        accounts = [
            {
                'environment_id': mapping.environment_id,
                'environment_name': mapping.environment.name,
                'account': mapping.account,
            }
            for mapping in UserEnvironmentAccount.objects.filter(
                user=request.user,
                account__gt='',
            ).select_related('environment').order_by(
                '-environment__is_default', 'environment__created_at', 'environment_id',
            )
        ]
        environments = [
            {'id': environment.id, 'name': environment.name}
            for environment in Environment.objects.all()
        ]
        return success({'accounts': accounts, 'environments': environments})

    def put(self, request):
        serializer = UserEnvironmentAccountUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account_items = serializer.validated_data['accounts']
        environment_ids = {item['environment_id'] for item in account_items}
        existing_ids = set(Environment.objects.filter(id__in=environment_ids).values_list('id', flat=True))
        unknown_ids = sorted(environment_ids - existing_ids)
        if unknown_ids:
            raise ValidationError({'accounts': f'运行环境不存在：{", ".join(map(str, unknown_ids))}'})
        with transaction.atomic():
            for item in account_items:
                environment_id = item['environment_id']
                account = item['account']
                if account:
                    UserEnvironmentAccount.objects.update_or_create(
                        user=request.user,
                        environment_id=environment_id,
                        defaults={'account': account},
                    )
                else:
                    UserEnvironmentAccount.objects.filter(
                        user=request.user, environment_id=environment_id,
                    ).delete()
        return self.get(request)


class DataFactoryAccountBalanceView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        require_data_factory_permission(request)
        email = str(request.data.get('email', '')).strip().lower()
        if not email or '@' not in email:
            raise ValidationError({'email': '请输入有效邮箱'})
        try:
            amount = Decimal(str(request.data.get('amount', '')))
        except Exception as exc:
            raise ValidationError({'amount': '请输入有效金额'}) from exc
        if not amount.is_finite() or amount <= 0 or amount > Decimal('1000000'):
            raise ValidationError({'amount': '金额必须大于 0 且不超过 1000000'})
        environment_id = request.data.get('environment')
        if not Environment.objects.filter(pk=environment_id).exists():
            raise ValidationError({'environment': '请选择有效运行环境'})
        execution = DataFactoryExecution.objects.create(tool_name='账户余额', operator=request.user, environment_id=environment_id, email=email, amount=amount)
        try:
            result = execute_account_balance(environment_id, email, amount)
        except DataFactoryError as exc:
            execution.status = 'failed'
            execution.message = str(exc)
            execution.save(update_fields=['status', 'message', 'updated_at'])
            raise ValidationError(str(exc)) from exc
        except Exception as exc:
            execution.status = 'failed'
            execution.message = str(exc)
            execution.save(update_fields=['status', 'message', 'updated_at'])
            raise ValidationError(f'账户余额执行异常：{exc}') from exc
        execution.status = 'passed'
        execution.member_id = result['member_id']
        execution.adjustment_id = result['adjustment_id']
        execution.message = '加款单据已创建并审批'
        execution.save(update_fields=['status', 'member_id', 'adjustment_id', 'message', 'updated_at'])
        return success(result, '账户余额已加款并审批')


def resolve_account_add_environment_ids(data):
    frontend_environment_id = data.get('frontend_environment') or data.get('front_environment')
    backend_environment_id = data.get('backend_environment') or data.get('back_environment')
    if frontend_environment_id and backend_environment_id:
        return frontend_environment_id, backend_environment_id

    selected = data.get('environments')
    if selected in (None, ''):
        selected = data.get('environment')
    if hasattr(data, 'getlist'):
        selected_list = data.getlist('environments') or data.getlist('environment')
        if selected_list:
            selected = selected_list
    if isinstance(selected, (list, tuple)):
        selected_ids = [item for item in selected if item not in (None, '')]
        if len(selected_ids) != 2:
            raise ValidationError({'environment': '请选择前台和后台两个运行环境'})
        return selected_ids[0], selected_ids[1]
    return selected, selected


class DataFactoryAccountAddView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        require_data_factory_account_add_permission(request)
        frontend_environment_id, backend_environment_id = resolve_account_add_environment_ids(request.data)
        frontend_environment = Environment.objects.filter(pk=frontend_environment_id).first()
        if not frontend_environment:
            raise ValidationError({'frontend_environment': '请选择有效前台运行环境'})
        backend_environment = Environment.objects.filter(pk=backend_environment_id).first()
        if not backend_environment:
            raise ValidationError({'backend_environment': '请选择有效后台运行环境'})
        if not frontend_environment.base_url:
            raise ValidationError({'frontend_environment': '请选择已配置前台地址的运行环境'})
        if not backend_environment.login_url:
            raise ValidationError({'backend_environment': '请选择已配置后台登录地址的运行环境'})
        email = str(request.data.get('email', '')).strip().lower()
        raw_amount = request.data.get('amount')
        if raw_amount in (None, ''):
            amount = Decimal('0')
        else:
            try:
                amount = Decimal(str(raw_amount))
            except Exception as exc:
                raise ValidationError({'amount': '请输入有效金额'}) from exc
        if not amount.is_finite() or amount < 0 or amount > Decimal('1000000'):
            raise ValidationError({'amount': '金额不能小于 0 且不超过 1000000'})
        try:
            quantity = int(request.data.get('quantity', 1))
        except (TypeError, ValueError) as exc:
            raise ValidationError({'quantity': '请输入有效数量'}) from exc
        if quantity <= 0:
            raise ValidationError({'quantity': '数量必须大于 0'})
        execution = DataFactoryExecution.objects.create(
            tool_name='账户添加', operator=request.user, environment=frontend_environment, email=email, amount=amount,
        )
        execution_id = execution.id
        frontend_environment_id = frontend_environment.id
        backend_environment_id = backend_environment.id
        def execute_created_account_add():
            close_old_connections()
            execution_record = execution
            try:
                result = execute_account_add(
                    frontend_environment_id,
                    backend_environment_id,
                    email,
                    amount,
                    quantity,
                )
                generated_emails = [
                    str(item).strip().lower()
                    for item in result.get('emails', [])
                    if str(item or '').strip()
                ] if not email else []
                execution_record.status = 'passed'
                execution_record.generated_emails = generated_emails
                if generated_emails:
                    execution_record.email = generated_emails[0]
                execution_record.member_id = str(result.get('member_id') or '')
                execution_record.adjustment_id = str(result.get('adjustment_id') or '')
                execution_record.message = f'账户添加执行成功（前台：{frontend_environment.name}；后台：{backend_environment.name}）'
                execution_record.save(update_fields=['status', 'email', 'generated_emails', 'member_id', 'adjustment_id', 'message', 'updated_at'])
            except DataFactoryError as exc:
                if execution_record:
                    execution_record.status = 'failed'
                    execution_record.message = str(exc)
                    execution_record.save(update_fields=['status', 'message', 'updated_at'])
            except Exception as exc:
                if execution_record:
                    execution_record.status = 'failed'
                    execution_record.message = f'账户添加执行异常：{exc}'
                    execution_record.save(update_fields=['status', 'message', 'updated_at'])
            finally:
                close_old_connections()

        transaction.on_commit(lambda: threading.Thread(target=execute_created_account_add, daemon=True).start())
        return success(
            {
                'execution_id': execution.id,
                'environment_name': f'{frontend_environment.name} / {backend_environment.name}',
                'frontend_environment_name': frontend_environment.name,
                'backend_environment_name': backend_environment.name,
                'email': email,
                'amount': str(amount),
                'quantity': quantity,
                'status': 'running',
            },
            '账户添加已提交，正在后台执行',
            status.HTTP_202_ACCEPTED,
        )


class DataFactoryOrderResultPushView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        require_order_result_push_permission(request)
        required_fields = ('certainty', 'product', 'event_id', 'market_id', 'outcome_id', 'result', 'void_factor')
        params = {field: str(request.data.get(field, '')).strip() for field in required_fields}
        missing = [field for field, value in params.items() if not value]
        if missing:
            raise ValidationError({field: '此字段不能为空' for field in missing})
        params['specifiers'] = str(request.data.get('specifiers', '')).strip()
        timestamp = request.data.get('timestamp')
        if timestamp not in (None, ''):
            try:
                params['timestamp'] = int(timestamp)
            except (TypeError, ValueError) as exc:
                raise ValidationError({'timestamp': '请输入有效的毫秒时间戳'}) from exc
            if params['timestamp'] <= 0:
                raise ValidationError({'timestamp': '请输入有效的毫秒时间戳'})
        execution = DataFactoryExecution.objects.create(
            tool_name='订单结果推送', operator=request.user, email=params['event_id'], amount=0,
            adjustment_id=params['market_id'],
        )
        try:
            result = push_order_result(**params)
        except DataFactoryError as exc:
            execution.status = 'failed'
            execution.message = str(exc)
            execution.save(update_fields=['status', 'message', 'updated_at'])
            raise ValidationError(str(exc)) from exc
        execution.status = 'passed'
        execution.email = result['event_id']
        execution.member_id = result['key']
        execution.message = result['message']
        execution.save(update_fields=['status', 'email', 'member_id', 'message', 'updated_at'])
        return success(result, '订单结果已推送')


def _format_cancel_message(result_message, params, timestamp):
    extra_fields = []
    for field in ('product', 'specifiers', 'start_time', 'end_time'):
        value = params.get(field)
        if value not in (None, ''):
            extra_fields.append(f'{field}={value}')
    if timestamp not in (None, ''):
        extra_fields.append(f'timestamp={timestamp}')
    return f"{result_message}；{'；'.join(extra_fields)}" if extra_fields else result_message


def _optional_millis(value, field_name):
    if value in (None, ''):
        return ''
    text = str(value).strip()
    if not text:
        return ''
    try:
        parsed = int(text)
    except (TypeError, ValueError) as exc:
        raise ValidationError({field_name: '请输入有效的毫秒时间戳'}) from exc
    if parsed <= 0:
        raise ValidationError({field_name: '请输入有效的毫秒时间戳'})
    return str(parsed)


class DataFactoryBetCancelView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        require_data_factory_bet_cancel_permission(request)
        required_fields = ('product', 'event_id', 'market_id')
        params = {field: str(request.data.get(field, '')).strip() for field in required_fields}
        missing = [field for field, value in params.items() if not value]
        if missing:
            raise ValidationError({field: '此字段不能为空' for field in missing})
        params['specifiers'] = str(request.data.get('specifiers', '')).strip()
        params['start_time'] = _optional_millis(request.data.get('start_time', ''), 'start_time')
        params['end_time'] = _optional_millis(request.data.get('end_time', ''), 'end_time')
        timestamp = request.data.get('timestamp')
        if timestamp not in (None, ''):
            try:
                params['timestamp'] = int(timestamp)
            except (TypeError, ValueError) as exc:
                raise ValidationError({'timestamp': '请输入有效的毫秒时间戳'}) from exc
            if params['timestamp'] <= 0:
                raise ValidationError({'timestamp': '请输入有效的毫秒时间戳'})
        execution = DataFactoryExecution.objects.create(
            tool_name='取消', operator=request.user, email=params['event_id'], amount=0,
            adjustment_id=params['market_id'],
        )
        try:
            result = bet_cancel(**params)
        except DataFactoryError as exc:
            execution.status = 'failed'
            execution.message = str(exc)
            execution.save(update_fields=['status', 'message', 'updated_at'])
            raise ValidationError(str(exc)) from exc
        execution.status = 'passed'
        execution.email = result['event_id']
        execution.member_id = result['key']
        execution.message = _format_cancel_message(result['message'], params, result['timestamp'])
        execution.save(update_fields=['status', 'email', 'member_id', 'message', 'updated_at'])
        return success(result, '取消已提交')


class DataFactoryRollbackBetCancelView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        require_data_factory_rollback_bet_cancel_permission(request)
        required_fields = ('product', 'event_id', 'market_id')
        params = {field: str(request.data.get(field, '')).strip() for field in required_fields}
        missing = [field for field, value in params.items() if not value]
        if missing:
            raise ValidationError({field: '此字段不能为空' for field in missing})
        params['specifiers'] = str(request.data.get('specifiers', '')).strip()
        params['start_time'] = _optional_millis(request.data.get('start_time', ''), 'start_time')
        params['end_time'] = _optional_millis(request.data.get('end_time', ''), 'end_time')
        timestamp = request.data.get('timestamp')
        if timestamp not in (None, ''):
            try:
                params['timestamp'] = int(timestamp)
            except (TypeError, ValueError) as exc:
                raise ValidationError({'timestamp': '请输入有效的毫秒时间戳'}) from exc
            if params['timestamp'] <= 0:
                raise ValidationError({'timestamp': '请输入有效的毫秒时间戳'})
        execution = DataFactoryExecution.objects.create(
            tool_name='回滚取消', operator=request.user, email=params['event_id'], amount=0,
            adjustment_id=params['market_id'],
        )
        try:
            result = rollback_bet_cancel(**params)
        except DataFactoryError as exc:
            execution.status = 'failed'
            execution.message = str(exc)
            execution.save(update_fields=['status', 'message', 'updated_at'])
            raise ValidationError(str(exc)) from exc
        execution.status = 'passed'
        execution.email = result['event_id']
        execution.member_id = result['key']
        execution.message = _format_cancel_message(result['message'], params, result['timestamp'])
        execution.save(update_fields=['status', 'email', 'member_id', 'message', 'updated_at'])
        return success(result, '回滚取消已提交')


class DataFactoryRollbackSettlementView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        require_data_factory_rollback_settlement_permission(request)
        required_fields = ('product', 'event_id', 'market_id')
        params = {field: str(request.data.get(field, '')).strip() for field in required_fields}
        missing = [field for field, value in params.items() if not value]
        if missing:
            raise ValidationError({field: '此字段不能为空' for field in missing})
        params['specifiers'] = str(request.data.get('specifiers', '')).strip()
        timestamp = request.data.get('timestamp')
        if timestamp not in (None, ''):
            try:
                params['timestamp'] = int(timestamp)
            except (TypeError, ValueError) as exc:
                raise ValidationError({'timestamp': '请输入有效的毫秒时间戳'}) from exc
            if params['timestamp'] <= 0:
                raise ValidationError({'timestamp': '请输入有效的毫秒时间戳'})
        execution = DataFactoryExecution.objects.create(
            tool_name='回滚结算', operator=request.user, email=params['event_id'], amount=0,
            adjustment_id=params['market_id'],
        )
        try:
            result = rollback_bet_settlement(**params)
        except DataFactoryError as exc:
            execution.status = 'failed'
            execution.message = str(exc)
            execution.save(update_fields=['status', 'message', 'updated_at'])
            raise ValidationError(str(exc)) from exc
        execution.status = 'passed'
        execution.email = result['event_id']
        execution.member_id = result['key']
        execution.message = result['message']
        execution.save(update_fields=['status', 'email', 'member_id', 'message', 'updated_at'])
        return success(result, '回滚结算已提交')


def require_data_factory_permission(request):
    permissions = request.user.role.permissions if isinstance(request.user.role.permissions, list) else []
    if not (request.user.is_superuser or request.user.role.code == 'admin' or 'data_factory.account_balance' in permissions):
        raise PermissionDenied('当前账号没有账户余额工具权限')


def require_data_factory_account_add_permission(request):
    permissions = request.user.role.permissions if isinstance(request.user.role.permissions, list) else []
    if not (request.user.is_superuser or request.user.role.code == 'admin' or 'data_factory.account_add' in permissions):
        raise PermissionDenied('当前账号没有账户添加工具权限')


def require_order_result_push_permission(request):
    permissions = request.user.role.permissions if isinstance(request.user.role.permissions, list) else []
    if not (request.user.is_superuser or request.user.role.code == 'admin' or 'data_factory.order_result_push' in permissions):
        raise PermissionDenied('当前账号没有订单结果推送工具权限')


def require_data_factory_rollback_settlement_permission(request):
    permissions = request.user.role.permissions if isinstance(request.user.role.permissions, list) else []
    if not (request.user.is_superuser or request.user.role.code == 'admin' or 'data_factory.rollback_settlement' in permissions):
        raise PermissionDenied('当前账号没有回滚结算工具权限')


def require_data_factory_bet_cancel_permission(request):
    permissions = request.user.role.permissions if isinstance(request.user.role.permissions, list) else []
    if not (request.user.is_superuser or request.user.role.code == 'admin' or 'data_factory.bet_cancel' in permissions):
        raise PermissionDenied('当前账号没有取消工具权限')


def require_data_factory_rollback_bet_cancel_permission(request):
    permissions = request.user.role.permissions if isinstance(request.user.role.permissions, list) else []
    if not (request.user.is_superuser or request.user.role.code == 'admin' or 'data_factory.rollback_bet_cancel' in permissions):
        raise PermissionDenied('当前账号没有回滚取消工具权限')


def require_data_factory_view_permission(request):
    permissions = request.user.role.permissions if isinstance(request.user.role.permissions, list) else []
    if not (request.user.is_superuser or request.user.role.code == 'admin' or {
        'data_factory.view',
        'data_factory.account_add',
        'data_factory.account_balance',
        'data_factory.order_result_push',
        'data_factory.rollback_settlement',
        'data_factory.bet_cancel',
        'data_factory.rollback_bet_cancel',
    } & set(permissions)):
        raise PermissionDenied('当前账号没有查看数据工厂权限')


class DataFactoryExecutionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_data_factory_view_permission(request)
        queryset = DataFactoryExecution.objects.select_related('operator', 'environment').all()
        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request)
        return paginator.get_paginated_response(DataFactoryExecutionSerializer(page, many=True).data)


class DataFactoryEnvironmentView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_data_factory_view_permission(request)
        environments = Environment.objects.order_by('-is_default', 'name').values(
            'id', 'name', 'description', 'base_url', 'login_url', 'is_default',
        )
        return success([
            {
                **environment,
                # Tool users need the selected environment's addresses, never its secrets.
                'variables': [],
            }
            for environment in environments
        ])


class RoleViewSet(ActionPermissionMixin, viewsets.ModelViewSet):
    queryset = Role.objects.prefetch_related('users').all()
    serializer_class = RoleSerializer
    action_permissions = {'list':'roles.view','retrieve':'roles.view','create':'roles.manage','update':'roles.manage','partial_update':'roles.manage','destroy':'roles.delete','set_permissions':'roles.grant'}

    def get_queryset(self):
        queryset = super().get_queryset()
        keyword = self.request.query_params.get('keyword', '').strip()
        return queryset.filter(Q(name__icontains=keyword)|Q(code__icontains=keyword)) if keyword else queryset

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        role = serializer.save()
        return success(self.get_serializer(role).data, '角色创建成功', status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        role = self.get_object()
        serializer = self.get_serializer(role, data=request.data, partial=kwargs.get('partial', False))
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success(serializer.data, '角色更新成功')

    def destroy(self, request, *args, **kwargs):
        role = self.get_object()
        if role.is_system or role.code == 'admin':
            raise ValidationError('系统角色不允许删除')
        if role.users.exists():
            raise ValidationError('该角色仍有关联用户，不能删除')
        role.delete()
        return success(message='角色删除成功')

    @action(detail=True, methods=['post'], url_path='permissions')
    def set_permissions(self, request, pk=None):
        role = self.get_object()
        if role.is_system or role.code == 'admin':
            raise ValidationError('系统管理员默认拥有全部权限，无需配置')
        serializer = PermissionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        role.permissions = list(dict.fromkeys(serializer.validated_data['permissions']))
        role.save(update_fields=['permissions', 'updated_at'])
        return success(self.get_serializer(role).data, '权限保存成功')


class UserViewSet(ActionPermissionMixin, viewsets.ModelViewSet):
    queryset = User.objects.select_related('role').all().order_by('-created_at')
    action_permissions = {'list':'users.view','retrieve':'users.view','create':'users.manage','update':'users.manage','partial_update':'users.manage','destroy':'users.delete','reset_password':'users.manage','toggle_status':'users.status'}

    def get_serializer_class(self):
        return UserCreateSerializer if self.action == 'create' else UserSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        keyword = self.request.query_params.get('keyword', '').strip()
        role = self.request.query_params.get('role', '').strip()
        if keyword:
            queryset = queryset.filter(Q(name__icontains=keyword)|Q(username__icontains=keyword)|Q(email__icontains=keyword))
        if role:
            queryset = queryset.filter(role__code=role)
        return queryset

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return success(UserSerializer(user).data, '用户创建成功', status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        user = self.get_object()
        serializer = self.get_serializer(user, data=request.data, partial=kwargs.get('partial', False))
        serializer.is_valid(raise_exception=True)
        next_role = serializer.validated_data.get('role', user.role)
        if user.username == 'admin' and next_role.code != 'admin':
            raise ValidationError('admin 账号必须保留系统管理员角色')
        serializer.save()
        return success(serializer.data, '用户更新成功')

    @action(detail=True, methods=['post'], url_path='toggle-status')
    def toggle_status(self, request, pk=None):
        user = self.get_object()
        is_active = request.data.get('is_active')
        if not isinstance(is_active, bool):
            raise ValidationError({'is_active': '请传入布尔值'})
        if not is_active and user.pk == request.user.pk:
            raise ValidationError('不能停用当前登录账号')
        if not is_active and (user.username == 'admin' or user.role.code == 'admin'):
            raise ValidationError('管理员账号不允许停用')
        user.is_active = is_active
        user.save(update_fields=['is_active', 'updated_at'])
        return success(UserSerializer(user).data, '用户状态已更新')

    def destroy(self, request, *args, **kwargs):
        user = self.get_object()
        if user.pk == request.user.pk:
            raise ValidationError('不能删除当前登录用户')
        if user.username == 'admin' or user.role.code == 'admin':
            raise ValidationError('管理员账号不允许删除')
        user.delete()
        return success(message='用户删除成功')

    @action(detail=True, methods=['post'], url_path='reset-password')
    def reset_password(self, request, pk=None):
        user = self.get_object()
        payload = request.data.copy()
        if not payload.get('new_password'):
            alphabet = string.ascii_letters + string.digits
            payload['new_password'] = 'Aibet@' + ''.join(secrets.choice(alphabet) for _ in range(8))
        serializer = ResetPasswordSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        password = serializer.validated_data['new_password']
        user.set_password(password)
        user.save(update_fields=['password'])
        return success({'temporary_password': password}, '密码重置成功')


class EnvironmentViewSet(ActionPermissionMixin, viewsets.ModelViewSet):
    queryset = Environment.objects.all()
    serializer_class = EnvironmentSerializer
    pagination_class = None
    action_permissions = {'list':'environment.view','retrieve':'environment.view','create':'environment.manage','update':'environment.manage','partial_update':'environment.manage','destroy':'environment.manage','copy':'environment.manage','set_default':'environment.manage'}

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        return success(self.get_serializer(queryset, many=True).data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            environment = serializer.save()
            if environment.is_default:
                Environment.objects.exclude(pk=environment.pk).update(is_default=False)
        return success(self.get_serializer(environment).data, '环境创建成功', status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        environment = self.get_object()
        serializer = self.get_serializer(environment, data=request.data, partial=kwargs.get('partial', False))
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            environment = serializer.save()
            if environment.is_default:
                Environment.objects.exclude(pk=environment.pk).update(is_default=False)
        return success(self.get_serializer(environment).data, '环境更新成功')

    def destroy(self, request, *args, **kwargs):
        environment = self.get_object()
        if environment.is_default:
            raise ValidationError('默认环境不允许删除，请先设置其他默认环境')
        environment.delete()
        return success(message='环境删除成功')

    @action(detail=True, methods=['post'], url_path='copy')
    def copy(self, request, pk=None):
        source = self.get_object()
        base_name = f'{source.name} 副本'
        name, index = base_name, 2
        while Environment.objects.filter(name=name).exists():
            name, index = f'{base_name} {index}', index + 1
        copied = Environment.objects.create(name=name, description=source.description, base_url=source.base_url, login_url=source.login_url, variables=source.variables, is_default=False)
        return success(self.get_serializer(copied).data, '环境复制成功', status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='default')
    def set_default(self, request, pk=None):
        environment = self.get_object()
        with transaction.atomic():
            Environment.objects.update(is_default=False)
            environment.is_default = True
            environment.save(update_fields=['is_default', 'updated_at'])
        return success(self.get_serializer(environment).data, '默认环境设置成功')


class AutomationModuleViewSet(ActionPermissionMixin, viewsets.ReadOnlyModelViewSet):
    queryset = AutomationModule.objects.prefetch_related('tasks').all()
    serializer_class = AutomationModuleSerializer
    pagination_class = None
    action_permissions = {'list': 'automation.view', 'retrieve': 'automation.view'}

    def get_queryset(self):
        queryset = super().get_queryset()
        app = self.request.query_params.get('app', '').strip()
        return queryset.filter(app=app) if app else queryset

    def ensure_business_modules(self):
        for app in ['frontend', 'backend']:
            for sort_order, name in enumerate(BUSINESS_MODULE_NAMES):
                module, _ = AutomationModule.objects.get_or_create(
                    app=app,
                    name=name,
                    defaults={'sort_order': sort_order},
                )
                if module.sort_order != sort_order:
                    module.sort_order = sort_order
                    module.save(update_fields=['sort_order'])

    def list(self, request, *args, **kwargs):
        self.ensure_business_modules()
        return success(self.get_serializer(self.filter_queryset(self.get_queryset()), many=True).data)


class ApiInterfaceViewSet(ActionPermissionMixin, viewsets.ModelViewSet):
    queryset = ApiInterface.objects.select_related('created_by').all()
    serializer_class = ApiInterfaceSerializer
    action_permissions = {'list':'automation.view','retrieve':'automation.view','create':'automation.create','update':'automation.edit','partial_update':'automation.edit','destroy':'automation.delete','batch_import':'automation.create'}

    def get_queryset(self):
        queryset = super().get_queryset()
        keyword = self.request.query_params.get('keyword', '').strip()
        method = self.request.query_params.get('method', '').strip().upper()
        module_name = self.request.query_params.get('module_name', '').strip()
        api_type = self.request.query_params.get('api_type', '').strip()
        can_execute = self.request.query_params.get('can_execute_in_task', '').strip()
        if keyword:
            queryset = queryset.filter(Q(name__icontains=keyword) | Q(path__icontains=keyword) | Q(module_name__icontains=keyword))
        if method:
            queryset = queryset.filter(method=method)
        if module_name:
            queryset = queryset.filter(module_name__in=[item.strip() for item in module_name.split(',') if item.strip()])
        if api_type:
            queryset = queryset.filter(api_type=api_type)
        if can_execute in {'true', 'false'}:
            queryset = queryset.filter(can_execute_in_task=can_execute == 'true')
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return success(serializer.data, '接口创建成功', status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object(), data=request.data, partial=kwargs.get('partial', False))
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success(serializer.data, '接口更新成功')

    def destroy(self, request, *args, **kwargs):
        self.get_object().delete()
        return success(message='接口删除成功')

    @action(detail=False, methods=['post'], url_path='batch-import')
    def batch_import(self, request):
        try:
            payloads = parse_fetch_text(request.data.get('text', ''), request.data.get('module_name', ''))
        except InterfaceImportError as exc:
            raise ValidationError(str(exc)) from exc

        imported, skipped, failed = [], [], []
        for index, payload in enumerate(payloads, start=1):
            serializer = self.get_serializer(data=payload)
            if serializer.is_valid():
                item = self.perform_create(serializer)
                imported.append({'index': index, 'name': serializer.data['name'], 'id': serializer.instance.id})
                continue
            message = serializer.errors
            first_error = next(iter(message.values()), message) if isinstance(message, dict) and message else message
            rendered = str(first_error[0] if isinstance(first_error, (list, tuple)) and first_error else first_error)
            if '相同 URL 和请求参数' in rendered:
                skipped.append({'index': index, 'name': payload['name'], 'message': '重复接口，已跳过'})
            else:
                failed.append({'index': index, 'name': payload['name'], 'message': rendered})
        return success(
            {'imported': imported, 'skipped': skipped, 'failed': failed, 'total': len(payloads)},
            f'批量录入完成，成功 {len(imported)} 条，重复跳过 {len(skipped)} 条，失败 {len(failed)} 条',
        )


class AutomationTaskViewSet(ActionPermissionMixin, viewsets.ModelViewSet):
    queryset = AutomationTask.objects.select_related('module', 'environment', 'owner').prefetch_related('modules', 'interfaces', 'execution_details').all()
    serializer_class = AutomationTaskSerializer
    action_permissions = {'list':'automation.view','retrieve':'automation.view','create':'automation.create','update':'automation.edit','partial_update':'automation.edit','destroy':'automation.delete','run':'automation.run','stop':'automation.run'}

    def get_queryset(self):
        queryset = super().get_queryset()
        keyword = self.request.query_params.get('keyword', '').strip()
        app = self.request.query_params.get('app', '').strip()
        module_id = self.request.query_params.get('module', '').strip()
        task_type = self.request.query_params.get('task_type', '').strip()
        if keyword:
            queryset = queryset.filter(name__icontains=keyword)
        if app:
            queryset = queryset.filter(Q(modules__app=app) | Q(module__app=app)).distinct()
        if module_id:
            queryset = queryset.filter(Q(modules__id=module_id) | Q(module_id=module_id)).distinct()
        if task_type:
            queryset = queryset.filter(task_type=task_type)
        return queryset

    def create(self, request, *args, **kwargs):
        login_password = request.data.get('login_password', '')
        if not login_password:
            raise ValidationError({'login_password': '请输入目标系统登录密码'})
        payload = request.data.copy()
        payload.pop('login_password', None)
        serializer = self.get_serializer(data=payload)
        serializer.is_valid(raise_exception=True)
        task = serializer.save()
        task_id = task.pk
        operator = request.user

        def execute_created_task():
            close_old_connections()
            try:
                execute_task(AutomationTask.objects.get(pk=task_id), operator, login_password)
            finally:
                close_old_connections()

        transaction.on_commit(lambda: threading.Thread(target=execute_created_task, daemon=True).start())
        return success(self.get_serializer(task).data, '任务已创建，正在执行', status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object(), data=request.data, partial=kwargs.get('partial', False))
        serializer.is_valid(raise_exception=True)
        task = serializer.save()
        return success(self.get_serializer(task).data, '任务更新成功')

    def destroy(self, request, *args, **kwargs):
        self.get_object().delete()
        return success(message='任务删除成功')

    @action(detail=True, methods=['post'])
    def run(self, request, pk=None):
        task = self.get_object()
        login_password = request.data.get('login_password', '')
        if not login_password:
            raise ValidationError({'login_password': '请输入目标系统登录密码'})
        results = execute_task(task, request.user, login_password)
        login_result = next((item for item in results if item.interface_name == '系统登录' and item.status == 'failed'), None)
        if login_result:
            raise ValidationError(login_result.response_message)
        return success(self.get_serializer(task).data, '任务执行完成')

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        task = self.get_object()
        task.status = 'pending'
        task.save(update_fields=['status', 'updated_at'])
        task.execution_details.filter(status='running').update(status='pending')
        return success(self.get_serializer(task).data, '任务已暂停')


class AutomationTaskResultViewSet(ActionPermissionMixin, viewsets.ReadOnlyModelViewSet):
    queryset = AutomationTaskResult.objects.select_related('task').all()
    serializer_class = AutomationTaskResultSerializer
    action_permissions = {'list':'automation.view','retrieve':'automation.view','retry':'automation.run'}

    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        login_password = request.data.get('login_password', '')
        if not login_password:
            raise ValidationError({'login_password': '请输入目标系统登录密码'})
        try:
            result = retry_task_result(self.get_object(), request.user, login_password)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        if result.status == 'failed' and result.interface_name == '系统登录':
            raise ValidationError(result.response_message)
        return success(self.get_serializer(result).data, '接口重试完成')


class MonitorApiConfigViewSet(ActionPermissionMixin, viewsets.ModelViewSet):
    queryset = MonitorApiConfig.objects.select_related('source_interface', 'created_by').all()
    serializer_class = MonitorApiConfigSerializer
    action_permissions = {
        'list': 'monitor.api.view',
        'retrieve': 'monitor.api.view',
        'create': 'monitor.api.manage',
        'update': 'monitor.api.manage',
        'partial_update': 'monitor.api.manage',
        'destroy': 'monitor.api.manage',
        'toggle': 'monitor.api.manage',
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        keyword = self.request.query_params.get('keyword', '').strip()
        module_name = self.request.query_params.get('module_name', '').strip()
        api_type = self.request.query_params.get('api_type', '').strip()
        enabled = self.request.query_params.get('enabled', '').strip()
        if keyword:
            queryset = queryset.filter(Q(name__icontains=keyword) | Q(path__icontains=keyword) | Q(module_name__icontains=keyword))
        if module_name:
            queryset = queryset.filter(module_name=module_name)
        if api_type:
            queryset = queryset.filter(api_type=api_type)
        if enabled in {'true', 'false'}:
            queryset = queryset.filter(enabled=enabled == 'true')
        return queryset

    def _coerce_bool(self, value, default):
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {'1', 'true', 'yes', 'on'}:
                return True
            if lowered in {'0', 'false', 'no', 'off'}:
                return False
        return bool(value)

    def _apply_source_interface(self, payload):
        source_ids = payload.get('source_interface_ids') or []
        if source_ids and not isinstance(source_ids, list):
            raise ValidationError('来源接口ID必须是数组')
        source_id = payload.get('source_interface') or (source_ids[0] if source_ids else None)
        if not source_id:
            return payload
        source = ApiInterface.objects.filter(pk=source_id).first()
        if not source:
            raise ValidationError('选择的接口不存在')
        if source_ids:
            payload['source_interface'] = source.id
            payload['source_interface_ids'] = source_ids
        else:
            payload['source_interface_ids'] = [source.id]
        payload.setdefault('name', source.name)
        payload.setdefault('method', source.method)
        payload.setdefault('path', source.path)
        payload.setdefault('module_name', source.module_name)
        payload.setdefault('api_type', '系统录入')
        payload.setdefault('description', source.description)
        payload.setdefault('headers', source.headers)
        payload.setdefault('request_params', source.request_params)
        payload.setdefault('assertions', source.assertions)
        return payload

    def create(self, request, *args, **kwargs):
        payload = self._apply_source_interface(request.data.copy())
        serializer = self.get_serializer(data=payload)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save(created_by=request.user)
        return success(self.get_serializer(instance).data, '监控接口创建成功', status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object(), data=request.data, partial=kwargs.get('partial', False))
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        return success(self.get_serializer(instance).data, '监控接口更新成功')

    def destroy(self, request, *args, **kwargs):
        self.get_object().delete()
        return success(message='监控接口删除成功')

    @action(detail=True, methods=['post'])
    def toggle(self, request, pk=None):
        instance = self.get_object()
        enabled = request.data.get('enabled')
        instance.enabled = self._coerce_bool(enabled, not instance.enabled)
        instance.save(update_fields=['enabled', 'updated_at'])
        return success(self.get_serializer(instance).data, '状态更新成功')


class MonitorTaskViewSet(ActionPermissionMixin, viewsets.ModelViewSet):
    queryset = MonitorTask.objects.select_related('environment', 'created_by').prefetch_related('api_configs', 'automation_interfaces', 'executions__details').all()
    serializer_class = MonitorTaskSerializer
    action_permissions = {
        'list': 'monitor.task.view',
        'retrieve': 'monitor.task.view',
        'history': 'monitor.task.view',
        'create': 'monitor.task.manage',
        'update': 'monitor.task.manage',
        'partial_update': 'monitor.task.manage',
        'destroy': 'monitor.task.manage',
        'toggle': 'monitor.task.manage',
        'run': 'monitor.task.run',
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        keyword = self.request.query_params.get('keyword', '').strip()
        api_type = self.request.query_params.get('api_type', '').strip()
        enabled = self.request.query_params.get('enabled', '').strip()
        if keyword:
            queryset = queryset.filter(Q(name__icontains=keyword) | Q(module_name__icontains=keyword))
        if api_type:
            queryset = queryset.filter(api_type=api_type)
        if enabled in {'true', 'false'}:
            queryset = queryset.filter(enabled=enabled == 'true')
        return queryset

    def _coerce_bool(self, value, default):
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {'1', 'true', 'yes', 'on'}:
                return True
            if lowered in {'0', 'false', 'no', 'off'}:
                return False
        return bool(value)

    def perform_create(self, serializer):
        task = serializer.save(created_by=self.request.user)
        sync_monitor_next_run_time(task)
        return task

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = self.perform_create(serializer)
        return success(self.get_serializer(task).data, '监控任务创建成功', status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object(), data=request.data, partial=kwargs.get('partial', False))
        serializer.is_valid(raise_exception=True)
        task = serializer.save()
        sync_monitor_next_run_time(task)
        return success(self.get_serializer(task).data, '监控任务更新成功')

    def destroy(self, request, *args, **kwargs):
        self.get_object().delete()
        return success(message='监控任务删除成功')

    @action(detail=True, methods=['post'])
    def toggle(self, request, pk=None):
        task = self.get_object()
        enabled = request.data.get('enabled')
        task.enabled = self._coerce_bool(enabled, not task.enabled)
        task.save(update_fields=['enabled', 'updated_at'])
        sync_monitor_next_run_time(task)
        return success(self.get_serializer(task).data, '状态更新成功')

    @action(detail=True, methods=['post'])
    def run(self, request, pk=None):
        execution = execute_monitor_task(self.get_object())
        return success(MonitorExecutionSerializer(execution).data, '监控任务执行完成')

    @action(detail=True, methods=['get'])
    def history(self, request, pk=None):
        queryset = self.get_object().executions.prefetch_related('details').all()
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = MonitorExecutionSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        return success(MonitorExecutionSerializer(queryset, many=True).data)


class MonitorExecutionViewSet(ActionPermissionMixin, viewsets.ReadOnlyModelViewSet):
    queryset = MonitorExecution.objects.select_related('task', 'task__environment').prefetch_related('details').all()
    serializer_class = MonitorExecutionSerializer
    action_permissions = {'list': 'monitor.task.view', 'retrieve': 'monitor.task.view'}

    def get_queryset(self):
        queryset = super().get_queryset()
        task_id = self.request.query_params.get('task')
        if task_id:
            queryset = queryset.filter(task_id=task_id)
        return queryset


class MonitorExecutionDetailViewSet(ActionPermissionMixin, viewsets.ReadOnlyModelViewSet):
    queryset = MonitorExecutionDetail.objects.select_related('execution', 'execution__task', 'execution__task__environment').all()
    serializer_class = MonitorExecutionDetailSerializer
    action_permissions = {'list': 'monitor.task.view', 'retrieve': 'monitor.task.view', 'retry': 'monitor.task.run'}

    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        try:
            detail = retry_monitor_detail(self.get_object())
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        return success(self.get_serializer(detail).data, '监控接口重试完成')


class MonitorAlarmViewSet(ActionPermissionMixin, viewsets.ModelViewSet):
    queryset = MonitorAlarm.objects.select_related('task', 'execution', 'detail', 'handled_by').all()
    serializer_class = MonitorAlarmSerializer
    http_method_names = ['get', 'patch', 'head', 'options']
    action_permissions = {
        'list': 'monitor.alarm.view',
        'retrieve': 'monitor.alarm.view',
        'partial_update': 'monitor.alarm.handle',
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        keyword = self.request.query_params.get('keyword', '').strip()
        status_value = self.request.query_params.get('status', '').strip()
        level = self.request.query_params.get('level', '').strip()
        if keyword:
            queryset = queryset.filter(Q(task__name__icontains=keyword) | Q(message__icontains=keyword) | Q(detail__interface_name__icontains=keyword))
        if status_value:
            queryset = queryset.filter(status=status_value)
        if level:
            queryset = queryset.filter(level=level)
        return queryset

    def partial_update(self, request, *args, **kwargs):
        alarm = self.get_object()
        next_status = request.data.get('status')
        if next_status not in {'open', 'handled'}:
            raise ValidationError('请选择有效的处理状态')
        alarm.status = next_status
        if next_status == 'handled':
            alarm.handled_by = request.user
            alarm.handled_at = timezone.now()
        else:
            alarm.handled_by = None
            alarm.handled_at = None
        alarm.save(update_fields=['status', 'handled_by', 'handled_at', 'updated_at'])
        return success(self.get_serializer(alarm).data, '报警状态更新成功')
