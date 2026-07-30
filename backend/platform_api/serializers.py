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
    'data_factory.account_balance',
    'data_factory.order_result_push',
}


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
        if obj.tool_name == '订单结果推送':
            content = {'事件 ID': obj.email, '市场 ID': obj.adjustment_id, '消息 Key': obj.member_id, '执行结果': obj.get_status_display()}
            if obj.message:
                content['信息'] = obj.message
            return content
        content = {
            '会员邮箱': obj.email,
            '金额': str(obj.amount),
            '执行结果': obj.get_status_display(),
        }
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
        fields = ['id', 'name', 'method', 'path', 'module_name', 'api_type', 'description', 'headers', 'request_params', 'parameterizations', 'assertions', 'reference_enabled', 'reference_interface', 'reference_interface_name', 'response_extracts', 'can_execute_in_task', 'created_by', 'created_by_name', 'created_at', 'updated_at']
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
        allowed_types = {'name', 'time', 'location', 'phone', 'id_card', 'email', 'custom'}
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
            if kind not in allowed_types:
                raise serializers.ValidationError(f'不支持的参数化类型：{kind}')
            if kind == 'custom' and not str(item.get('value', '')).strip():
                raise serializers.ValidationError(f'自定义参数 {name} 必须填写值')
            names.add(name)
            normalized.append({'name': name, 'type': kind, **({'value': item.get('value', '')} if kind == 'custom' else {})})
        return normalized

    def validate(self, attrs):
        attrs = super().validate(attrs)
        path = attrs.get('path', self.instance.path if self.instance else '')
        request_params = attrs.get(
            'request_params', self.instance.request_params if self.instance else {}
        )
        path = path.strip()
        attrs['path'] = path

        candidates = ApiInterface.objects.filter(path=path).only('id', 'request_params')
        if self.instance:
            candidates = candidates.exclude(pk=self.instance.pk)
        if any(item.request_params == request_params for item in candidates):
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
        module_names = self.get_module_names(obj)
        return ApiInterface.objects.filter(module_name__in=module_names, can_execute_in_task=True).count()

    def get_failure_count(self, obj):
        if obj.status not in {'passed', 'failed'}:
            return 0
        return sum(1 for item in self.get_latest_execution_details(obj) if item.status == 'failed')

    class Meta:
        model = AutomationTask
        fields = ['id', 'name', 'module', 'module_ids', 'module_names', 'app', 'app_name', 'module_name', 'task_type', 'task_type_name', 'environment', 'environment_name', 'status', 'status_name', 'schedule', 'owner', 'owner_name', 'notification_status', 'notification_message', 'notified_at', 'interface_count', 'failure_count', 'execution_details', 'created_at', 'updated_at']
        read_only_fields = ['id', 'module_names', 'app', 'app_name', 'module_name', 'environment_name', 'owner_name', 'task_type_name', 'status_name', 'notification_status', 'notification_message', 'notified_at', 'interface_count', 'failure_count', 'execution_details', 'created_at', 'updated_at']

    def validate(self, attrs):
        attrs = super().validate(attrs)
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
        validated_data.pop('modules', None)
        validated_data.pop('module', None)
        task = AutomationTask.objects.create(module=modules[0], **validated_data)
        task.modules.set(modules)
        return task

    def update(self, instance, validated_data):
        modules = validated_data.pop('_modules', None)
        validated_data.pop('modules', None)
        task = super().update(instance, validated_data)
        if modules is not None:
            task.module = modules[0]
            task.save(update_fields=['module', 'updated_at'])
            task.modules.set(modules)
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
