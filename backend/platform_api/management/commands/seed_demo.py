from django.core.management.base import BaseCommand

from platform_api.constants import BUSINESS_MODULE_NAMES
from platform_api.models import ApiInterface, AutomationModule, AutomationTask, AutomationTaskResult, Environment, MonitorApiConfig, MonitorTask, Role, User


class Command(BaseCommand):
    help = '创建 AIBET Auto 演示角色、管理员和环境'

    def handle(self, *args, **options):
        all_permissions = ['home.view','data_factory.view','data_factory.account_add','data_factory.account_balance','data_factory.member_status_activate','data_factory.member_query','data_factory.order_result_push','data_factory.rollback_settlement','data_factory.bet_cancel','data_factory.rollback_bet_cancel','automation.view','automation.create','automation.run','automation.edit','automation.delete','automation.scene_package.view','automation.scene_package.manage','monitor.api.view','monitor.api.manage','monitor.task.view','monitor.task.manage','monitor.task.run','monitor.alarm.view','monitor.alarm.handle','environment.view','environment.manage','users.view','users.manage','users.status','users.delete','roles.view','roles.manage','roles.grant','roles.delete']
        admin_role, _ = Role.objects.update_or_create(code='admin', defaults={'name':'系统管理员','description':'拥有平台全部管理权限','permissions':all_permissions,'is_system':True})
        for code, name, permissions in [
            ('test_lead','测试负责人',['home.view','automation.view','automation.create','automation.run','automation.edit','automation.delete','automation.scene_package.view','automation.scene_package.manage','monitor.api.view','monitor.api.manage','monitor.task.view','monitor.task.manage','monitor.task.run','monitor.alarm.view','monitor.alarm.handle','environment.view','environment.manage','users.view']),
            ('tester','测试工程师',['home.view','automation.view','automation.create','automation.run','automation.edit','automation.scene_package.view','monitor.api.view','monitor.task.view','monitor.task.run','monitor.alarm.view','environment.view']),
            ('viewer','只读成员',['home.view','automation.view','automation.scene_package.view','monitor.api.view','monitor.task.view','monitor.alarm.view','environment.view']),
        ]:
            Role.objects.update_or_create(code=code, defaults={'name':name,'permissions':permissions,'description':name})
        admin, created = User.objects.get_or_create(username='admin', defaults={'name':'林工程师','email':'admin@aibet.local','role':admin_role,'is_staff':True,'is_superuser':True})
        if created:
            admin.set_password('Aibet@123456')
            admin.save()
        Environment.objects.get_or_create(name='测试环境', defaults={'description':'日常开发联调与功能验证','base_url':'https://api-test.aibet.cn','variables':[],'is_default':True})
        Environment.objects.get_or_create(name='预发布环境', defaults={'description':'版本发布前的完整回归验证','base_url':'https://api-stage.aibet.cn','variables':[]})
        Environment.objects.get_or_create(name='生产环境', defaults={'description':'线上服务可用性巡检','base_url':'https://api.aibet.cn','variables':[]})
        tester_role = Role.objects.get(code='tester')
        demo_users = {}
        for username, name in [('zhoumin', '周敏'), ('chenyuan', '陈远'), ('fangxiao', '方晓')]:
            user, created = User.objects.get_or_create(username=username, defaults={'name':name,'email':'','role':tester_role})
            if created:
                user.set_unusable_password()
                user.save(update_fields=['password'])
            demo_users[name] = user
        demo_users['林工程师'] = admin

        module_map = {}
        for app, names in {
            'frontend': BUSINESS_MODULE_NAMES,
            'backend': BUSINESS_MODULE_NAMES,
        }.items():
            for index, name in enumerate(names):
                module, _ = AutomationModule.objects.update_or_create(app=app, name=name, defaults={'sort_order':index})
                module_map[(app, name)] = module

        for name, method, path, module_name, api_type in [
            ('用户登录', 'POST', '/api/auth/login/', '个人中心', '登录'),
            ('获取当前用户', 'GET', '/api/auth/me/', '个人中心', '核心链路'),
            ('用户列表', 'GET', '/api/users/', '个人中心', '业务巡检'),
            ('新增测试环境', 'POST', '/api/environments/', '活动', '回归'),
        ]:
            ApiInterface.objects.update_or_create(method=method, path=path, defaults={'name':name,'module_name':module_name,'api_type':api_type,'headers':{'Content-Type':'application/json; charset=utf-8'},'can_execute_in_task':True,'created_by':admin})
        for interface in ApiInterface.objects.all():
            MonitorApiConfig.objects.update_or_create(
                name=f'{interface.name}监控',
                path=interface.path,
                    defaults={'source_interface':interface,'method':interface.method,'module_name':interface.module_name,'api_type':interface.api_type,'description':interface.description,'headers':interface.headers,'request_params':interface.request_params,'assertions':interface.assertions or {'status_code':200,'timeout_seconds':3,'json_path':'code','expected_value':0},'enabled':True,'created_by':admin},
            )

        task_rows = [
            ('登录与权限回归','frontend','个人中心','ui','测试环境','passed','每天 09:00','周敏'),
            ('个人资料编辑流程','frontend','个人中心','scenario','预发布环境','pending','手动执行','林工程师'),
            ('商家后台冒烟测试','frontend','赛事','ui','测试环境','failed','代码提交后','陈远'),
            ('核心交易链路回归','frontend','活动','scenario','预发布环境','running','手动执行','林工程师'),
            ('用户服务 API 回归','backend','个人中心','api','测试环境','passed','每天 09:00','周敏'),
            ('订单状态流转校验','backend','赛事','api','预发布环境','pending','代码提交后','陈远'),
            ('支付接口稳定性巡检','backend','游戏','api','生产环境','running','每 30 分钟','方晓'),
        ]
        for name, app, module_name, task_type, environment_name, task_status, schedule, owner_name in task_rows:
            module = module_map[(app, module_name)]
            task, _ = AutomationTask.objects.update_or_create(name=name, defaults={'module':module,'task_type':task_type,'environment':Environment.objects.get(name=environment_name),'status':task_status,'schedule':schedule,'owner':demo_users[owner_name]})
            task.modules.set([module])
            for index, interface in enumerate(ApiInterface.objects.filter(module_name=module_name)):
                detail_status = 'failed' if task_status == 'failed' and index == 0 else task_status
                AutomationTaskResult.objects.update_or_create(
                    task=task,
                    execution_no=1,
                    source_interface_id=interface.id,
                    defaults={'interface_name':interface.name,'method':interface.method,'path':interface.path,'headers':interface.headers,'request_params':interface.request_params,'status':detail_status,'duration_ms':120 + index * 87,'response_message':'断言通过' if detail_status == 'passed' else ''},
                )
        monitor_task, _ = MonitorTask.objects.update_or_create(
            name='核心接口可用性监控',
            defaults={'module_name':'个人中心','api_type':'核心链路','environment':Environment.objects.get(name='测试环境'),'interval_value':5,'interval_unit':'minute','enabled':True,'created_by':admin},
        )
        monitor_task.api_configs.set(MonitorApiConfig.objects.filter(module_name='个人中心', enabled=True))
        monitor_task.automation_interfaces.set(ApiInterface.objects.filter(module_name='个人中心', can_execute_in_task=True))
        self.stdout.write(self.style.SUCCESS('演示数据初始化完成，管理员：admin / Aibet@123456'))
