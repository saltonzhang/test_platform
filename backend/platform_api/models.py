from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.Model):
    name = models.CharField('角色名称', max_length=50)
    code = models.CharField('角色编码', max_length=50, unique=True)
    description = models.TextField('描述', blank=True, default='')
    permissions = models.JSONField('权限配置', default=list, blank=True)
    is_system = models.BooleanField('系统角色', default=False)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'aibet_role'
        db_table_comment = '角色信息表'
        verbose_name = '角色'
        verbose_name_plural = '角色'
        ordering = ['created_at', 'id']

    def __str__(self):
        return f'{self.name} ({self.code})'


class User(AbstractUser):
    name = models.CharField('姓名', max_length=50)
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name='users', verbose_name='角色')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    @property
    def display_name(self):
        return self.name or self.username

    class Meta:
        db_table = 'aibet_user'
        db_table_comment = '用户信息表'
        verbose_name = '用户'
        verbose_name_plural = '用户'


class Environment(models.Model):
    name = models.CharField('环境名称', max_length=100, unique=True)
    description = models.TextField('描述', blank=True, default='')
    base_url = models.URLField('服务地址', max_length=500)
    login_url = models.URLField('登录地址', max_length=500, blank=True, default='')
    variables = models.JSONField('环境变量', default=list, blank=True)
    is_default = models.BooleanField('默认环境', default=False)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'aibet_environment'
        db_table_comment = '自动化运行环境配置表'
        verbose_name = '运行环境'
        verbose_name_plural = '运行环境'
        ordering = ['-is_default', 'created_at', 'id']

    def __str__(self):
        return self.name


class DataFactoryExecution(models.Model):
    STATUS_CHOICES = [('running', '执行中'), ('passed', '已完成'), ('failed', '执行失败')]

    tool_name = models.CharField('工具名称', max_length=100)
    operator = models.ForeignKey(User, on_delete=models.PROTECT, related_name='data_factory_executions', verbose_name='操作人')
    environment = models.ForeignKey(Environment, on_delete=models.SET_NULL, null=True, related_name='data_factory_executions', verbose_name='运行环境')
    email = models.EmailField('会员邮箱')
    amount = models.DecimalField('金额', max_digits=14, decimal_places=2)
    member_id = models.CharField('会员ID', max_length=100, blank=True, default='')
    adjustment_id = models.CharField('审批单据ID', max_length=100, blank=True, default='')
    status = models.CharField('执行状态', max_length=20, choices=STATUS_CHOICES, default='running')
    message = models.TextField('执行信息', blank=True, default='')
    executed_at = models.DateTimeField('执行时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'aibet_data_factory_execution'
        db_table_comment = '数据工厂执行记录表'
        verbose_name = '数据工厂执行记录'
        verbose_name_plural = '数据工厂执行记录'
        ordering = ['-executed_at', '-id']


class AutomationModule(models.Model):
    APP_CHOICES = [('frontend', '前端'), ('backend', '后台')]

    app = models.CharField('所属端', max_length=20, choices=APP_CHOICES)
    name = models.CharField('模块名称', max_length=100)
    sort_order = models.PositiveIntegerField('排序', default=0)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'aibet_automation_module'
        db_table_comment = '自动化业务模块表'
        verbose_name = '自动化模块'
        verbose_name_plural = '自动化模块'
        ordering = ['app', 'sort_order', 'id']
        constraints = [models.UniqueConstraint(fields=['app', 'name'], name='uniq_automation_app_module')]

    def __str__(self):
        return f'{self.get_app_display()} - {self.name}'


class ApiInterface(models.Model):
    METHOD_CHOICES = [(item, item) for item in ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']]

    name = models.CharField('接口名称', max_length=200)
    method = models.CharField('请求方法', max_length=10, choices=METHOD_CHOICES)
    path = models.CharField('请求路径', max_length=500)
    module_name = models.CharField('所属模块', max_length=100)
    api_type = models.CharField('接口类型', max_length=100, default='默认', blank=True)
    description = models.TextField('接口描述', blank=True, default='')
    headers = models.JSONField('请求头', default=dict, blank=True)
    request_params = models.JSONField('请求参数', default=dict, blank=True)
    parameterizations = models.JSONField('参数化配置', default=list, blank=True)
    assertions = models.JSONField('接口断言', default=dict, blank=True)
    reference_enabled = models.BooleanField('启用关联标记', default=False)
    reference_interface = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='referenced_by_interfaces', verbose_name='关联接口')
    response_extracts = models.JSONField('关联响应提取规则', default=list, blank=True)
    can_execute_in_task = models.BooleanField('可被任务执行', default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_interfaces', verbose_name='创建人')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'aibet_api_interface'
        db_table_comment = '自动化接口资产表'
        verbose_name = '接口资产'
        verbose_name_plural = '接口资产'
        ordering = ['-updated_at', 'id']

    def __str__(self):
        return f'{self.method} {self.path}'


class AutomationTask(models.Model):
    TYPE_CHOICES = [('api', '接口测试'), ('ui', 'UI 测试'), ('scenario', '场景测试')]
    STATUS_CHOICES = [('pending', '待执行'), ('running', '执行中'), ('passed', '已通过'), ('failed', '失败')]
    NOTIFICATION_STATUS_CHOICES = [('pending', '待发送'), ('sent', '发送成功'), ('failed', '发送失败'), ('disabled', '未配置')]

    name = models.CharField('任务名称', max_length=200)
    # 保留旧字段兼容历史任务；新任务使用 modules 关联多个业务模块。
    module = models.ForeignKey(AutomationModule, on_delete=models.PROTECT, null=True, blank=True, related_name='legacy_tasks', verbose_name='默认业务模块')
    modules = models.ManyToManyField(AutomationModule, related_name='tasks', blank=True, verbose_name='业务模块')
    task_type = models.CharField('测试类型', max_length=20, choices=TYPE_CHOICES)
    environment = models.ForeignKey(Environment, on_delete=models.PROTECT, related_name='automation_tasks', verbose_name='运行环境')
    status = models.CharField('任务状态', max_length=20, choices=STATUS_CHOICES, default='pending')
    schedule = models.CharField('执行策略', max_length=100, default='手动执行')
    owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name='automation_tasks', verbose_name='负责人')
    notification_status = models.CharField('飞书通知状态', max_length=20, choices=NOTIFICATION_STATUS_CHOICES, default='pending')
    notification_message = models.TextField('飞书通知信息', blank=True, default='')
    notified_at = models.DateTimeField('飞书通知时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'aibet_automation_task'
        db_table_comment = '自动化执行任务表'
        verbose_name = '自动化任务'
        verbose_name_plural = '自动化任务'
        ordering = ['-updated_at', 'id']

    def __str__(self):
        return self.name


class AutomationTaskResult(models.Model):
    STATUS_CHOICES = [('pending', '待执行'), ('running', '执行中'), ('passed', '已通过'), ('failed', '失败')]

    task = models.ForeignKey(AutomationTask, on_delete=models.CASCADE, related_name='execution_details', verbose_name='自动化任务')
    execution_no = models.PositiveIntegerField('执行批次', default=1)
    source_interface_id = models.PositiveBigIntegerField('来源接口ID', null=True, blank=True)
    interface_name = models.CharField('接口名称快照', max_length=200, default='')
    method = models.CharField('请求方法快照', max_length=10, default='')
    path = models.CharField('请求路径快照', max_length=500, default='')
    headers = models.JSONField('请求头快照', default=dict, blank=True)
    request_params = models.JSONField('请求参数快照', default=dict, blank=True)
    assertions = models.JSONField('接口断言快照', default=dict, blank=True)
    status = models.CharField('执行结果', max_length=20, choices=STATUS_CHOICES, default='pending')
    duration_ms = models.PositiveIntegerField('耗时（毫秒）', null=True, blank=True)
    response_message = models.TextField('执行信息', blank=True, default='')
    response_log = models.TextField('失败响应日志', blank=True, default='')
    executed_at = models.DateTimeField('执行时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'aibet_automation_task_result'
        db_table_comment = '自动化任务接口执行明细表'
        verbose_name = '任务执行明细'
        verbose_name_plural = '任务执行明细'
        ordering = ['id']

    def __str__(self):
        return f'{self.task.name} - {self.interface_name}'


class MonitorApiConfig(models.Model):
    METHOD_CHOICES = ApiInterface.METHOD_CHOICES

    source_interface = models.ForeignKey(ApiInterface, on_delete=models.SET_NULL, null=True, blank=True, related_name='monitor_configs', verbose_name='来源接口')
    source_interface_ids = models.JSONField('来源接口ID列表', default=list, blank=True)
    name = models.CharField('接口名称', max_length=200)
    method = models.CharField('请求方法', max_length=10, choices=METHOD_CHOICES)
    path = models.CharField('请求路径', max_length=500)
    module_name = models.CharField('所属模块', max_length=100)
    api_type = models.CharField('接口类型', max_length=100, default='默认', blank=True)
    description = models.TextField('接口描述', blank=True, default='')
    headers = models.JSONField('请求头', default=dict, blank=True)
    request_params = models.JSONField('请求参数', default=dict, blank=True)
    assertions = models.JSONField('接口断言', default=dict, blank=True)
    enabled = models.BooleanField('启用状态', default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_monitor_configs', verbose_name='创建人')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'aibet_monitor_api_config'
        db_table_comment = '监控中心接口配置表'
        verbose_name = '监控接口配置'
        verbose_name_plural = '监控接口配置'
        ordering = ['-updated_at', 'id']

    def __str__(self):
        return f'{self.method} {self.path}'


class MonitorTask(models.Model):
    UNIT_CHOICES = [('minute', '分钟'), ('hour', '小时'), ('day', '天')]
    STATUS_CHOICES = [('pending', '待执行'), ('running', '执行中'), ('passed', '已通过'), ('failed', '失败')]

    name = models.CharField('任务名称', max_length=200)
    module_name = models.CharField('任务模块', max_length=100, blank=True, default='')
    api_type = models.CharField('接口类型', max_length=100, blank=True, default='')
    environment = models.ForeignKey(Environment, on_delete=models.PROTECT, related_name='monitor_tasks', verbose_name='监控环境')
    api_configs = models.ManyToManyField(MonitorApiConfig, blank=True, related_name='monitor_tasks', verbose_name='监控接口')
    automation_interfaces = models.ManyToManyField(ApiInterface, blank=True, related_name='monitor_tasks', verbose_name='自动化接口')
    interval_value = models.PositiveIntegerField('执行间隔', default=1)
    interval_unit = models.CharField('间隔单位', max_length=20, choices=UNIT_CHOICES, default='minute')
    enabled = models.BooleanField('启用状态', default=True)
    status = models.CharField('最近执行状态', max_length=20, choices=STATUS_CHOICES, default='pending')
    notification = models.JSONField('通知配置', default=dict, blank=True)
    last_run_time = models.DateTimeField('最近执行时间', null=True, blank=True)
    next_run_time = models.DateTimeField('下次执行时间', null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_monitor_tasks', verbose_name='创建人')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'aibet_monitor_task'
        db_table_comment = '监控中心定时任务表'
        verbose_name = '监控任务'
        verbose_name_plural = '监控任务'
        ordering = ['-updated_at', 'id']

    def __str__(self):
        return self.name


class MonitorExecution(models.Model):
    STATUS_CHOICES = [('running', '执行中'), ('passed', '已通过'), ('failed', '失败')]

    task = models.ForeignKey(MonitorTask, on_delete=models.CASCADE, related_name='executions', verbose_name='监控任务')
    execution_no = models.PositiveIntegerField('执行批次', default=1)
    status = models.CharField('执行结果', max_length=20, choices=STATUS_CHOICES, default='running')
    interface_total = models.PositiveIntegerField('接口总数', default=0)
    failure_count = models.PositiveIntegerField('失败数量', default=0)
    average_duration_ms = models.PositiveIntegerField('平均耗时（毫秒）', default=0)
    message = models.TextField('执行信息', blank=True, default='')
    started_at = models.DateTimeField('开始时间', auto_now_add=True)
    finished_at = models.DateTimeField('结束时间', null=True, blank=True)

    class Meta:
        db_table = 'aibet_monitor_execution'
        db_table_comment = '监控中心任务执行记录表'
        verbose_name = '监控执行记录'
        verbose_name_plural = '监控执行记录'
        ordering = ['-started_at', 'id']

    def __str__(self):
        return f'{self.task.name} #{self.execution_no}'


class MonitorExecutionDetail(models.Model):
    STATUS_CHOICES = [('running', '执行中'), ('passed', '已通过'), ('failed', '失败')]

    execution = models.ForeignKey(MonitorExecution, on_delete=models.CASCADE, related_name='details', verbose_name='监控执行记录')
    source_api_config_id = models.PositiveBigIntegerField('来源监控接口ID', null=True, blank=True)
    source_interface_id = models.PositiveBigIntegerField('来源自动化接口ID', null=True, blank=True)
    interface_name = models.CharField('接口名称快照', max_length=200, default='')
    method = models.CharField('请求方法快照', max_length=10, default='')
    path = models.CharField('请求路径快照', max_length=500, default='')
    url = models.CharField('完整请求地址快照', max_length=800, default='')
    module_name = models.CharField('所属模块快照', max_length=100, default='')
    headers = models.JSONField('请求头快照', default=dict, blank=True)
    request_params = models.JSONField('请求参数快照', default=dict, blank=True)
    assertions = models.JSONField('接口断言快照', default=dict, blank=True)
    status = models.CharField('执行结果', max_length=20, choices=STATUS_CHOICES, default='running')
    duration_ms = models.PositiveIntegerField('耗时（毫秒）', null=True, blank=True)
    response_message = models.TextField('执行信息', blank=True, default='')
    executed_at = models.DateTimeField('执行时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'aibet_monitor_execution_detail'
        db_table_comment = '监控中心接口执行明细表'
        verbose_name = '监控执行明细'
        verbose_name_plural = '监控执行明细'
        ordering = ['id']

    def __str__(self):
        return f'{self.execution.task.name} - {self.interface_name}'


class MonitorAlarm(models.Model):
    STATUS_CHOICES = [('open', '未处理'), ('handled', '已处理')]
    LEVEL_CHOICES = [('warning', '警告'), ('error', '错误')]

    task = models.ForeignKey(MonitorTask, on_delete=models.CASCADE, related_name='alarms', verbose_name='监控任务')
    execution = models.ForeignKey(MonitorExecution, on_delete=models.CASCADE, related_name='alarms', verbose_name='执行记录')
    detail = models.ForeignKey(MonitorExecutionDetail, on_delete=models.SET_NULL, null=True, blank=True, related_name='alarms', verbose_name='执行明细')
    level = models.CharField('报警级别', max_length=20, choices=LEVEL_CHOICES, default='error')
    status = models.CharField('处理状态', max_length=20, choices=STATUS_CHOICES, default='open')
    message = models.TextField('报警内容')
    handled_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='handled_monitor_alarms', verbose_name='处理人')
    handled_at = models.DateTimeField('处理时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'aibet_monitor_alarm'
        db_table_comment = '监控中心报警记录表'
        verbose_name = '监控报警记录'
        verbose_name_plural = '监控报警记录'
        ordering = ['-created_at', 'id']

    def __str__(self):
        return f'{self.task.name} - {self.get_status_display()}'
