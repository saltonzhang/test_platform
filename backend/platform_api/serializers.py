import json
import re
from urllib.parse import unquote

from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .constants import BUSINESS_MODULE_NAMES
from .models import ApiInterface, AutomationModule, AutomationTask, AutomationTaskResult, DataFactoryExecution, Environment, MonitorAlarm, MonitorApiConfig, MonitorExecution, MonitorExecutionDetail, MonitorTask, Role, User

ALLOWED_PERMISSIONS = {
    'home.view',
    'automation.view', 'automation.create', 'automation.run', 'automation.edit', 'automation.delete',
    'monitor.api.view', 'monitor.api.manage',
    'monitor.task.view', 'monitor.task.manage', 'monitor.task.run',
    'monitor.alarm.view', 'monitor.alarm.handle',
    'environment.view', 'environment.manage',
    'users.view', 'users.manage', 'users.status', 'users.delete',
    'roles.view', 'roles.manage', 'roles.grant', 'roles.delete',
    'data_factory.view',
    'data_factory.account_add',
    'data_factory.account_balance',
    'data_factory.order_result_push',
    'data_factory.rollback_settlement',
    'data_factory.bet_cancel',
    'data_factory.rollback_bet_cancel',
}

PARAMETERIZATION_TYPES = {'name', 'time', 'location', 'phone', 'id_card', 'email', 'custom'}
TIME_PARAMETER_FORMATS = {'timestamp', 'datetime', 'date', 'year_month', 'month_day', 'year'}
FULL_PARAMETER_PATH = re.compile(r'^(?:query|body)\.(?:[A-Za-z_][A-Za-z0-9_]*|\d+)(?:\.(?:[A-Za-z_][A-Za-z0-9_]*|\d+))*$')
FULL_CUSTOM_VALUE_PLACEHOLDER = re.compile(
    r'\$\{[A-Za-z_][A-Za-z0-9_]*'
    r'(?:\.[A-Za-z_][A-Za-z0-9_]*|\[(?:\*|\d+(?:,\d+)*|\d*:\d*)\])*\}'
)


def validate_custom_value_template(parameter_path, raw_value):
    custom_value = str(raw_value).strip()
    if not custom_value:
        raise serializers.ValidationError(f'自定义变量 {parameter_path} 必须填写值')
    if '${' in FULL_CUSTOM_VALUE_PLACEHOLDER.sub('', custom_value):
        raise serializers.ValidationError(
            f'自定义变量 {parameter_path} 的关联变量表达式无效，'
            '支持 ${bit[0].uid}、${bit[0,2].uid}、${bit[0:2].uid} 或 ${bit[*].uid}'
        )
    return custom_value


def normalize_full_parameterizations_for_compare(value):
    normalized = []
    for item in value or []:
        if not isinstance(item, dict):
            normalized.append(item)
            continue
        value_mode = str(item.get('value_mode', '')).strip()
        normalized_item = {'path': str(item.get('path', '')).strip(), 'value_mode': value_mode}
        if value_mode == 'fixed':
            if isinstance(item.get('values'), list):
                normalized_item['values'] = item['values']
            elif 'value' in item:
                normalized_item['values'] = [item['value']]
        else:
            variable_type = str(item.get('variable_type', '')).strip()
            normalized_item['variable_type'] = variable_type
            if variable_type == 'custom':
                if 'value' in item:
                    normalized_item['value'] = str(item.get('value', '')).strip()
            elif variable_type == 'time':
                normalized_item['time_format'] = str(item.get('time_format', 'date')).strip() or 'date'
                normalized_item['time_offset'] = int(item.get('time_offset') or 0)
        normalized.append(normalized_item)
    return normalized


class RoleSerializer(serializers.ModelSerializer):
    user_count = serializers.IntegerField(source='users.count', read_only=True)

    class Meta:
        model = Role
        fields = ['id', 'name', 'code', 'description', 'permissions', 'is_system', 'user_count', 'created_at', 'updated_at']
        read_only_fields = ['id', 'is_system', 'user_count', 'created_at', 'updated_at']

    def validate_code(self, value):
        if self.instance and value != self.instance.code:
            raise serializers.ValidationError('角色编码创建后不可修改')
        return value


class UserSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(required=False, allow_blank=True)
    role = serializers.SlugRelatedField(slug_field='code', queryset=Role.objects.all())
    role_name = serializers.CharField(source='role.name', read_only=True)
    permissions = serializers.JSONField(source='role.permissions', read_only=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'name', 'email', 'role', 'role_name', 'permissions', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'username', 'created_at', 'updated_at']


class UserCreateSerializer(UserSerializer):
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta(UserSerializer.Meta):
        fields = UserSerializer.Meta.fields + ['password']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        password = validated_data.pop('password')
        return User.objects.create_user(password=password, **validated_data)


class UserEnvironmentAccountItemSerializer(serializers.Serializer):
    environment_id = serializers.IntegerField()
    account = serializers.CharField(max_length=100, allow_blank=True, trim_whitespace=True)


class UserEnvironmentAccountUpdateSerializer(serializers.Serializer):
    accounts = UserEnvironmentAccountItemSerializer(many=True)

    def validate_accounts(self, value):
        environment_ids = [item['environment_id'] for item in value]
        if len(environment_ids) != len(set(environment_ids)):
            raise serializers.ValidationError('同一运行环境只能配置一个账号')
        return value


class ResetPasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(min_length=6)

    def validate_new_password(self, value):
        validate_password(value)
        return value


class PermissionSerializer(serializers.Serializer):
    permissions = serializers.ListField(child=serializers.CharField(max_length=100), allow_empty=True)

    def validate_permissions(self, value):
        invalid = sorted(set(value) - ALLOWED_PERMISSIONS)
        if invalid:
            raise serializers.ValidationError(f'包含未知权限：{", ".join(invalid)}')
        return value


class EnvironmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Environment
        fields = ['id', 'name', 'description', 'base_url', 'login_url', 'variables', 'is_default', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_variables(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('环境变量必须是数组')
        for item in value:
            if not isinstance(item, dict) or not item.get('key'):
                raise serializers.ValidationError('每个环境变量都必须包含 key')
        return value


class DataFactoryExecutionSerializer(serializers.ModelSerializer):
    operator_name = serializers.CharField(source='operator.display_name', read_only=True)
    execution_content = serializers.SerializerMethodField()

    def get_execution_content(self, obj):
        if obj.tool_name in {'订单结果推送', '回滚结算', '取消', '回滚取消'}:
            content = {'事件 ID': obj.email, '市场 ID': obj.adjustment_id, '消息 Key': obj.member_id, '执行结果': obj.get_status_display()}
            if obj.message:
                content['信息'] = obj.message
            return content
        content = {'金额': str(obj.amount), '执行结果': obj.get_status_display()}
        if obj.tool_name == '账户添加' and obj.generated_emails:
            content['生成邮箱'] = '、'.join(str(item) for item in obj.generated_emails)
        else:
            content['会员邮箱'] = obj.email
        if obj.member_id:
            content['Member ID'] = obj.member_id
        if obj.adjustment_id:
            content['审批单据 ID'] = obj.adjustment_id
        if obj.message:
            content['信息'] = obj.message
        return content

    class Meta:
        model = DataFactoryExecution
        fields = ['id', 'tool_name', 'operator_name', 'execution_content', 'executed_at']
        read_only_fields = fields


class AutomationModuleSerializer(serializers.ModelSerializer):
    app_name = serializers.CharField(source='get_app_display', read_only=True)
    task_count = serializers.IntegerField(source='tasks.count', read_only=True)

    class Meta:
        model = AutomationModule
        fields = ['id', 'app', 'app_name', 'name', 'sort_order', 'task_count']


class ApiInterfaceSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source='created_by.display_name', read_only=True)
    reference_interface_name = serializers.CharField(source='reference_interface.name', read_only=True)

    class Meta:
        model = ApiInterface
        fields = ['id', 'name', 'method', 'path', 'module_name', 'api_type', 'description', 'headers', 'request_params', 'parameterizations', 'request_parameter_mode', 'full_parameterizations', 'assertions', 'reference_enabled', 'reference_interface', 'reference_interface_name', 'response_extracts', 'can_execute_in_task', 'created_by', 'created_by_name', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_by', 'created_by_name', 'created_at', 'updated_at']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['api_type'] = '系统录入'
        return data

    def validate_headers(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Headers 必须是 JSON 对象')
        return value

    def validate_request_params(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('请求参数必须是 JSON 对象')
        return value

    def validate_parameterizations(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('参数化配置必须是数组')
        normalized, names = [], set()
        for item in value:
            if not isinstance(item, dict):
                raise serializers.ValidationError('每条参数化配置必须是对象')
            name = str(item.get('name', '')).strip()
            kind = str(item.get('type', '')).strip()
            if not name or not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', name):
                raise serializers.ValidationError('参数化变量名必须以字母或下划线开头，只能包含字母、数字和下划线')
            if name in names:
                raise serializers.ValidationError(f'参数化变量名重复：{name}')
            if kind not in PARAMETERIZATION_TYPES:
                raise serializers.ValidationError(f'不支持的参数化类型：{kind}')
            if kind == 'custom' and not str(item.get('value', '')).strip():
                raise serializers.ValidationError(f'自定义参数 {name} 必须填写值')
            normalized_item = {'name': name, 'type': kind}
            if kind == 'custom':
                normalized_item['value'] = item.get('value', '')
            if kind == 'time':
                time_format = str(item.get('time_format', 'date')).strip() or 'date'
                if time_format not in TIME_PARAMETER_FORMATS:
                    raise serializers.ValidationError(f'参数化变量 {name} 的时间格式无效')
                try:
                    time_offset = int(item.get('time_offset') or 0)
                except (TypeError, ValueError) as exc:
                    raise serializers.ValidationError(f'参数化变量 {name} 的加减天数必须是整数') from exc
                normalized_item.update({'time_format': time_format, 'time_offset': time_offset})
            names.add(name)
            normalized.append(normalized_item)
        return normalized

    def validate_request_parameter_mode(self, value):
        if value not in {'template', 'full'}:
            raise serializers.ValidationError('请求参数模式必须是模板参数化或全参数化')
        return value

    def validate_full_parameterizations(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('全参数化配置必须是数组')
        normalized, paths = [], set()
        missing = object()
        for item in value:
            if not isinstance(item, dict):
                raise serializers.ValidationError('每条全参数化配置必须是对象')
            parameter_path = str(item.get('path', '')).strip()
            if not FULL_PARAMETER_PATH.fullmatch(parameter_path):
                raise serializers.ValidationError('参数路径必须以 query 或 body 开头，例如 query.page 或 body.user.name')
            if parameter_path in paths:
                raise serializers.ValidationError(f'参数路径重复：{parameter_path}')
            value_mode = str(item.get('value_mode', '')).strip()
            if value_mode not in {'fixed', 'variable'}:
                raise serializers.ValidationError(f'参数 {parameter_path} 的取值方式无效')
            normalized_item = {'path': parameter_path, 'value_mode': value_mode}
            if value_mode == 'fixed':
                fixed_values = item.get('values', missing)
                if fixed_values is missing and 'value' in item:
                    fixed_values = [item['value']]
                if fixed_values is missing or not isinstance(fixed_values, list) or not fixed_values:
                    raise serializers.ValidationError(f'固定参数 {parameter_path} 必须填写至少一个 JSON 值')
                normalized_item['values'] = fixed_values
            else:
                variable_type = str(item.get('variable_type', '')).strip()
                if variable_type not in PARAMETERIZATION_TYPES:
                    raise serializers.ValidationError(f'参数 {parameter_path} 的变量类型无效')
                normalized_item['variable_type'] = variable_type
                if variable_type == 'custom':
                    custom_value = validate_custom_value_template(parameter_path, item.get('value', ''))
                    normalized_item['value'] = custom_value
                if variable_type == 'time':
                    time_format = str(item.get('time_format', 'date')).strip() or 'date'
                    if time_format not in TIME_PARAMETER_FORMATS:
                        raise serializers.ValidationError(f'参数 {parameter_path} 的时间格式无效')
                    try:
                        time_offset = int(item.get('time_offset') or 0)
                    except (TypeError, ValueError) as exc:
                        raise serializers.ValidationError(f'参数 {parameter_path} 的加减天数必须是整数') from exc
                    normalized_item.update({'time_format': time_format, 'time_offset': time_offset})
            paths.add(parameter_path)
            normalized.append(normalized_item)
        return normalized

    def validate(self, attrs):
        attrs = super().validate(attrs)
        path = attrs.get('path', self.instance.path if self.instance else '')
        request_parameter_mode = attrs.get('request_parameter_mode', self.instance.request_parameter_mode if self.instance else 'template')
        if request_parameter_mode == 'full':
            full_parameterizations = attrs.get('full_parameterizations', self.instance.full_parameterizations if self.instance else [])
            if not full_parameterizations:
                raise serializers.ValidationError({'full_parameterizations': '请至少配置一条全参数化参数'})
            attrs['request_params'] = {}
            attrs['parameterizations'] = []
            request_params = {}
        else:
            full_parameterizations = []
            attrs['full_parameterizations'] = []
            request_params = attrs.get(
                'request_params', self.instance.request_params if self.instance else {}
            )
        path = path.strip()
        attrs['path'] = path

        candidates = ApiInterface.objects.filter(path=path).only('id', 'request_params', 'request_parameter_mode', 'full_parameterizations')
        if self.instance:
            candidates = candidates.exclude(pk=self.instance.pk)
        if any(
            item.request_parameter_mode == request_parameter_mode
            and item.request_params == request_params
            and normalize_full_parameterizations_for_compare(item.full_parameterizations) == full_parameterizations
            for item in candidates
        ):
            raise serializers.ValidationError('相同 URL 和请求参数的接口已存在，不允许重复加入')
        reference_enabled = attrs.get('reference_enabled', self.instance.reference_enabled if self.instance else False)
        reference_interface = attrs.get('reference_interface', self.instance.reference_interface if self.instance else None)
        extracts = attrs.get('response_extracts', self.instance.response_extracts if self.instance else [])
        if reference_enabled and not reference_interface:
            raise serializers.ValidationError({'reference_interface': '启用关联标记后请选择关联接口'})
        if reference_interface and self.instance and reference_interface.pk == self.instance.pk:
            raise serializers.ValidationError({'reference_interface': '不能关联接口自身'})
        if reference_enabled and not extracts:
            raise serializers.ValidationError({'response_extracts': '请至少配置一条响应提取规则'})
        if not reference_enabled:
            attrs['reference_interface'] = None
            attrs['response_extracts'] = []
        module_name = attrs.get('module_name', self.instance.module_name if self.instance else '')
        headers = dict(attrs.get('headers', self.instance.headers if self.instance else {}) or {})
        for key in list(headers):
            if key.lower() in {'authorization', 'x-token', 'x-access-token'}:
                headers.pop(key)
        headers['x-token' if module_name == '后台' else 'authorization'] = ''
        attrs['headers'] = headers
        return attrs

    def validate_module_name(self, value):
        if value not in BUSINESS_MODULE_NAMES:
            raise serializers.ValidationError('请选择有效的业务模块')
        return value

    def validate_api_type(self, value):
        return '系统录入'

    def validate_assertions(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('接口断言必须是 JSON 对象')
        status_code = value.get('status_code')
        if status_code is not None and not isinstance(status_code, (int, list)):
            raise serializers.ValidationError('status_code 必须是整数或整数数组')
        timeout_seconds = value.get('timeout_seconds')
        if timeout_seconds is not None and (not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or timeout_seconds <= 0):
            raise serializers.ValidationError('timeout_seconds 必须是大于 0 的数字')
        return value

    def validate_response_extracts(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('响应提取规则必须是数组')
        normalized = []
        names = set()
        for item in value:
            if not isinstance(item, dict):
                raise serializers.ValidationError('每条响应提取规则必须是对象')
            name = str(item.get('name', '')).strip()
            path = str(item.get('path', '')).strip()
            if not name or not path:
                raise serializers.ValidationError('响应提取规则必须包含变量名和 JSON 路径')
            if name in names:
                raise serializers.ValidationError(f'响应提取变量名重复：{name}')
            names.add(name)
            normalized.append({'name': name, 'path': path})
        return normalized


class MonitorApiConfigSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source='created_by.display_name', read_only=True)
    source_interface_name = serializers.CharField(source='source_interface.name', read_only=True)

    class Meta:
        model = MonitorApiConfig
        fields = ['id', 'source_interface', 'source_interface_ids', 'source_interface_name', 'name', 'method', 'path', 'module_name', 'api_type', 'description', 'headers', 'request_params', 'assertions', 'enabled', 'created_by', 'created_by_name', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_by', 'created_by_name', 'source_interface_name', 'created_at', 'updated_at']
        extra_kwargs = {'module_name': {'required': False, 'allow_blank': True}}

    def validate_headers(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Headers 必须是 JSON 对象')
        return value

    def validate_request_params(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('请求参数必须是 JSON 对象')
        return value

    def validate_module_name(self, value):
        value = (value or '').strip()
        if not value:
            return ''
        return ApiInterfaceSerializer().validate_module_name(value)

    def validate_assertions(self, value):
        return ApiInterfaceSerializer().validate_assertions(value)

    def validate_api_type(self, value):
        return (value or '默认').strip() or '默认'

    def validate_source_interface_ids(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('来源接口ID必须是数组')
        normalized = []
        for item in value:
            if isinstance(item, bool):
                raise serializers.ValidationError('来源接口ID必须是整数')
            try:
                source_id = int(item)
            except (TypeError, ValueError) as exc:
                raise serializers.ValidationError('来源接口ID必须是整数') from exc
            if source_id not in normalized:
                normalized.append(source_id)
        if normalized and ApiInterface.objects.filter(id__in=normalized).count() != len(normalized):
            raise serializers.ValidationError('选择的接口不存在')
        return normalized

    def validate(self, attrs):
        attrs = super().validate(attrs)
        source_interface = attrs.get('source_interface', self.instance.source_interface if self.instance else None)
        source_interface_ids = attrs.get('source_interface_ids', self.instance.source_interface_ids if self.instance else [])
        if source_interface or source_interface_ids:
            attrs['api_type'] = '系统录入'
        return attrs


class AutomationTaskResultSerializer(serializers.ModelSerializer):
    status_name = serializers.CharField(source='get_status_display', read_only=True)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['path'] = unquote(data.get('path') or '')
        return data

    class Meta:
        model = AutomationTaskResult
        fields = ['id', 'execution_no', 'source_interface_id', 'interface_name', 'method', 'path', 'headers', 'request_params', 'assertions', 'status', 'status_name', 'duration_ms', 'response_message', 'response_log', 'executed_at']
        read_only_fields = fields


class AutomationTaskSerializer(serializers.ModelSerializer):
    module_ids = serializers.PrimaryKeyRelatedField(source='modules', many=True, queryset=AutomationModule.objects.all(), write_only=True, required=False)
    interface_ids = serializers.PrimaryKeyRelatedField(source='interfaces', many=True, queryset=ApiInterface.objects.filter(can_execute_in_task=True), required=False)
    app = serializers.SerializerMethodField()
    app_name = serializers.SerializerMethodField()
    module_name = serializers.SerializerMethodField()
    module_names = serializers.SerializerMethodField()
    environment_name = serializers.CharField(source='environment.name', read_only=True)
    owner_name = serializers.CharField(source='owner.display_name', read_only=True)
    task_type_name = serializers.CharField(source='get_task_type_display', read_only=True)
    status_name = serializers.CharField(source='get_status_display', read_only=True)
    execution_details = AutomationTaskResultSerializer(many=True, read_only=True)
    interface_count = serializers.SerializerMethodField()
    failure_count = serializers.SerializerMethodField()

    def get_modules(self, obj):
        return list(obj.modules.all())

    def get_module_names(self, obj):
        names = list(obj.modules.values_list('name', flat=True))
        if not names and obj.module_id:
            names = [obj.module.name]
        return names

    def get_app(self, obj):
        module = next(iter(self.get_modules(obj)), None)
        module = module or obj.module
        return module.app if module else ''

    def get_app_name(self, obj):
        module = next(iter(self.get_modules(obj)), None)
        module = module or obj.module
        return module.get_app_display() if module else ''

    def get_module_name(self, obj):
        return '、'.join(self.get_module_names(obj))

    def get_latest_execution_details(self, obj):
        details = list(obj.execution_details.all())
        if not details:
            return []
        latest_execution_no = max(item.execution_no for item in details)
        return [item for item in details if item.execution_no == latest_execution_no]

    def get_interface_count(self, obj):
        # The task scope is known when it is created; execution details are written asynchronously.
        if obj.task_type == 'scenario':
            return obj.interfaces.filter(can_execute_in_task=True).count()
        module_names = self.get_module_names(obj)
        return ApiInterface.objects.filter(module_name__in=module_names, can_execute_in_task=True).count()

    def get_failure_count(self, obj):
        if obj.status not in {'passed', 'failed'}:
            return 0
        return sum(1 for item in self.get_latest_execution_details(obj) if item.status == 'failed')

    class Meta:
        model = AutomationTask
        fields = ['id', 'name', 'module', 'module_ids', 'interface_ids', 'module_names', 'app', 'app_name', 'module_name', 'task_type', 'task_type_name', 'environment', 'environment_name', 'status', 'status_name', 'schedule', 'owner', 'owner_name', 'notification_status', 'notification_message', 'notified_at', 'interface_count', 'failure_count', 'execution_details', 'created_at', 'updated_at']
        read_only_fields = ['id', 'module_names', 'app', 'app_name', 'module_name', 'environment_name', 'owner_name', 'task_type_name', 'status_name', 'notification_status', 'notification_message', 'notified_at', 'interface_count', 'failure_count', 'execution_details', 'created_at', 'updated_at']

    def validate(self, attrs):
        attrs = super().validate(attrs)
        task_type = attrs.get('task_type', self.instance.task_type if self.instance else '')
        interfaces = attrs.get('interfaces')
        if task_type == 'scenario':
            if interfaces is None:
                interfaces = list(self.instance.interfaces.all()) if self.instance else []
            if not interfaces:
                raise serializers.ValidationError({'interface_ids': '请选择至少一个可执行接口'})
            invalid_interfaces = [
                item.name
                for item in interfaces
                if item.request_parameter_mode != 'full' or not item.full_parameterizations
            ]
            if invalid_interfaces:
                names = '、'.join(invalid_interfaces[:3])
                suffix = '等接口' if len(invalid_interfaces) > 3 else ''
                raise serializers.ValidationError({
                    'interface_ids': f'场景测试只能选择已配置全参数化参数的接口：{names}{suffix}'
                })
            module_names = {item.module_name for item in interfaces}
            interface_apps = {'backend' if name == '后台' else 'frontend' for name in module_names}
            if len(interface_apps) != 1:
                raise serializers.ValidationError({'interface_ids': '场景测试接口必须归属同一所属端'})
            interface_app = next(iter(interface_apps))
            modules = list(AutomationModule.objects.filter(app=interface_app, name__in=module_names))
            if len({item.name for item in modules}) != len(module_names):
                raise serializers.ValidationError({'interface_ids': '场景测试接口的业务模块不存在'})
            attrs['_interfaces'] = interfaces
            attrs['_modules'] = modules
            return attrs
        modules = attrs.get('modules')
        if self.instance:
            if modules is None:
                modules = list(self.instance.modules.all()) or ([self.instance.module] if self.instance.module else [])
        else:
            modules = modules or ([attrs.get('module')] if attrs.get('module') else [])
        if not modules:
            raise serializers.ValidationError({'module_ids': '请选择至少一个业务模块'})
        attrs['_modules'] = modules
        return attrs

    def create(self, validated_data):
        modules = validated_data.pop('_modules', validated_data.pop('modules', []))
        interfaces = validated_data.pop('_interfaces', validated_data.pop('interfaces', []))
        validated_data.pop('modules', None)
        validated_data.pop('interfaces', None)
        validated_data.pop('module', None)
        task = AutomationTask.objects.create(module=modules[0], **validated_data)
        task.modules.set(modules)
        task.interfaces.set(interfaces)
        return task

    def update(self, instance, validated_data):
        modules = validated_data.pop('_modules', None)
        interfaces = validated_data.pop('_interfaces', None)
        validated_data.pop('modules', None)
        validated_data.pop('interfaces', None)
        task = super().update(instance, validated_data)
        if modules is not None:
            task.module = modules[0]
            task.save(update_fields=['module', 'updated_at'])
            task.modules.set(modules)
        if interfaces is not None:
            task.interfaces.set(interfaces)
        return task


class MonitorExecutionDetailSerializer(serializers.ModelSerializer):
    status_name = serializers.CharField(source='get_status_display', read_only=True)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['path'] = unquote(data.get('path') or '')
        data['url'] = unquote(data.get('url') or '')
        return data

    class Meta:
        model = MonitorExecutionDetail
        fields = ['id', 'source_api_config_id', 'source_interface_id', 'interface_name', 'method', 'path', 'url', 'module_name', 'headers', 'request_params', 'assertions', 'status', 'status_name', 'duration_ms', 'response_message', 'executed_at', 'created_at']
        read_only_fields = fields


class MonitorExecutionSerializer(serializers.ModelSerializer):
    status_name = serializers.CharField(source='get_status_display', read_only=True)
    task_name = serializers.CharField(source='task.name', read_only=True)
    environment_name = serializers.CharField(source='task.environment.name', read_only=True)
    details = MonitorExecutionDetailSerializer(many=True, read_only=True)

    class Meta:
        model = MonitorExecution
        fields = ['id', 'task', 'task_name', 'environment_name', 'execution_no', 'status', 'status_name', 'interface_total', 'failure_count', 'average_duration_ms', 'message', 'started_at', 'finished_at', 'details']
        read_only_fields = fields


class MonitorTaskSerializer(serializers.ModelSerializer):
    environment_name = serializers.CharField(source='environment.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.display_name', read_only=True)
    status_name = serializers.CharField(source='get_status_display', read_only=True)
    interval_unit_name = serializers.CharField(source='get_interval_unit_display', read_only=True)
    api_config_ids = serializers.PrimaryKeyRelatedField(source='api_configs', many=True, queryset=MonitorApiConfig.objects.all(), required=False)
    automation_interface_ids = serializers.PrimaryKeyRelatedField(source='automation_interfaces', many=True, queryset=ApiInterface.objects.filter(can_execute_in_task=True), required=False)
    api_count = serializers.SerializerMethodField()
    failure_count = serializers.SerializerMethodField()
    latest_execution = serializers.SerializerMethodField()

    class Meta:
        model = MonitorTask
        fields = ['id', 'name', 'module_name', 'api_type', 'environment', 'environment_name', 'api_config_ids', 'automation_interface_ids', 'api_count', 'interval_value', 'interval_unit', 'interval_unit_name', 'enabled', 'status', 'status_name', 'failure_count', 'latest_execution', 'notification', 'last_run_time', 'next_run_time', 'created_by', 'created_by_name', 'created_at', 'updated_at']
        read_only_fields = ['id', 'environment_name', 'api_count', 'status', 'status_name', 'failure_count', 'latest_execution', 'last_run_time', 'next_run_time', 'created_by', 'created_by_name', 'created_at', 'updated_at']

    def get_api_count(self, obj):
        monitor_total = sum(len(item.source_interface_ids or [item.source_interface_id] if item.source_interface_id else []) for item in obj.api_configs.all())
        return monitor_total + obj.automation_interfaces.count()

    def get_failure_count(self, obj):
        latest = obj.executions.order_by('-started_at').first()
        return latest.failure_count if latest else 0

    def get_latest_execution(self, obj):
        latest = obj.executions.order_by('-started_at').first()
        return MonitorExecutionSerializer(latest).data if latest else None

    def _resolve_interfaces(self, api_type):
        api_type = (api_type or '').strip()
        monitor_interfaces = list(MonitorApiConfig.objects.filter(api_type=api_type, enabled=True)) if api_type else []
        automation_interfaces = list(ApiInterface.objects.filter(api_type=api_type, can_execute_in_task=True)) if api_type else []
        return monitor_interfaces, automation_interfaces

    def validate_interval_value(self, value):
        if value <= 0:
            raise serializers.ValidationError('执行间隔必须大于 0')
        return value

    def validate(self, attrs):
        api_type = attrs.get('api_type', self.instance.api_type if self.instance else '')
        api_configs = attrs.get('api_configs')
        automation_interfaces = attrs.get('automation_interfaces')
        if api_configs is None and automation_interfaces is None:
            api_configs, automation_interfaces = self._resolve_interfaces(api_type)
            attrs['api_configs'] = api_configs
            attrs['automation_interfaces'] = automation_interfaces
        if not api_configs and not automation_interfaces:
            raise serializers.ValidationError({'api_type': '该接口类型下暂无可执行接口'})
        return attrs


class MonitorAlarmSerializer(serializers.ModelSerializer):
    task_name = serializers.CharField(source='task.name', read_only=True)
    interface_name = serializers.CharField(source='detail.interface_name', read_only=True)
    status_name = serializers.CharField(source='get_status_display', read_only=True)
    level_name = serializers.CharField(source='get_level_display', read_only=True)
    handled_by_name = serializers.CharField(source='handled_by.display_name', read_only=True)

    class Meta:
        model = MonitorAlarm
        fields = ['id', 'task', 'task_name', 'execution', 'detail', 'interface_name', 'level', 'level_name', 'status', 'status_name', 'message', 'handled_by', 'handled_by_name', 'handled_at', 'created_at', 'updated_at']
        read_only_fields = ['id', 'task', 'task_name', 'execution', 'detail', 'interface_name', 'level', 'level_name', 'handled_by', 'handled_by_name', 'handled_at', 'created_at', 'updated_at']
