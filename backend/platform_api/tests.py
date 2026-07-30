import json
from unittest.mock import patch

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import ApiInterface, AutomationModule, AutomationTask, AutomationTaskResult, Environment, MonitorAlarm, MonitorApiConfig, MonitorExecution, MonitorExecutionDetail, MonitorTask, Role, User
from .executor import api_request_executor
from .services import build_parameter_variables, build_request_url, execute_task, replace_parameter_variables


class FakeHttpResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return b'{"ok": true, "data": {"access": "test-token"}}'


class JsonFakeHttpResponse(FakeHttpResponse):
    def __init__(self, body):
        self.body = body

    def read(self, size=-1):
        return json.dumps(self.body).encode('utf-8')


class PlatformApiTests(APITestCase):
    def setUp(self):
        self.admin_role = Role.objects.create(
            name='系统管理员', code='admin', is_system=True, permissions=[]
        )
        self.tester_role = Role.objects.create(
            name='测试工程师', code='tester', permissions=['environment.view']
        )
        self.admin = User.objects.create_superuser(
            username='admin', password='Aibet@123456', name='管理员',
            email='admin@example.com', role=self.admin_role,
        )
        self.client.force_authenticate(self.admin)

    def test_login_returns_tokens_and_user(self):
        self.client.force_authenticate(None)
        response = self.client.post('/api/auth/login/', {
            'username': 'admin', 'password': 'Aibet@123456'
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data['data'])
        self.assertEqual(response.data['data']['user']['role'], 'admin')

    def test_dashboard_returns_database_statistics(self):
        ApiInterface.objects.create(
            name='统计接口', method='GET', path='/api/stats/', module_name='活动',
            headers={}, request_params={}, assertions={}, created_by=self.admin,
        )
        response = self.client.get('/api/dashboard/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['data']['interfaces']['total'], 1)
        self.assertEqual(response.data['data']['interfaces']['by_module'][0]['module_name'], '活动')
        self.assertEqual(response.data['data']['execution']['task_total'], 0)
        self.assertEqual(len(response.data['data']['trend']), 7)

    @patch('platform_api.executor.perf_counter', side_effect=[0, 3.1])
    @patch('platform_api.executor.urlopen', return_value=FakeHttpResponse())
    def test_executor_marks_slow_response_as_failed(self, mocked_urlopen, mocked_clock):
        outcome = api_request_executor.execute(
            url='https://example.com/api/test', method='GET', headers={}, request_params={},
            assertions={'status_code': 200, 'timeout_seconds': 3},
        )
        self.assertEqual(outcome.status, 'failed')
        self.assertEqual(outcome.duration_ms, 3100)
        self.assertIn('耗时断言失败', outcome.message)

    def test_executor_extracts_nested_login_authorization_token(self):
        token = api_request_executor.extract_access_token(
            '{"code": 0, "data": {"token": {"authorization": "nested-token"}}}'
        )
        self.assertEqual(token, 'nested-token')

    def test_executor_expands_imported_query_and_body_parameters(self):
        self.assertEqual(
            build_request_url('https://example.com', '/api/users/', 'GET', {'query': {'page': 1, 'name': 'admin'}}),
            'https://example.com/api/users/?page=1&name=admin',
        )
        self.assertEqual(
            api_request_executor.get_request_params('POST', {'body': {'username': 'admin'}}),
            {'username': 'admin'},
        )

    def test_parameterized_request_values_are_generated_and_replaced(self):
        variables = build_parameter_variables([
            {'name': 'personName', 'type': 'name'},
            {'name': 'mobile', 'type': 'phone'},
            {'name': 'email', 'type': 'custom', 'value': 'fixed@example.com'},
        ])
        rendered = replace_parameter_variables(
            {'body': {'name': '{{personName}}', 'phone': '{{mobile}}', 'note': 'mail={{email}}'}},
            variables,
        )
        self.assertEqual(rendered['body']['name'], variables['personName'])
        self.assertRegex(rendered['body']['phone'], r'^1[3-9]\d{9}$')
        self.assertEqual(rendered['body']['note'], 'mail=fixed@example.com')
        legacy = replace_parameter_variables({'phone': '${mobile}'}, variables)
        self.assertRegex(legacy['phone'], r'^1[3-9]\d{9}$')

    @patch('platform_api.executor.urlopen', return_value=FakeHttpResponse())
    def test_frontend_request_uses_raw_authorization_token(self, mocked_urlopen):
        api_request_executor.execute(
            url='https://example.com/api/test', method='GET', headers={'Authorization': 'expired-token'}, request_params={},
            access_token='frontend-token', access_token_prefix='',
        )
        self.assertEqual(mocked_urlopen.call_args.args[0].get_header('Authorization'), 'frontend-token')

    def test_user_create_filter_update_and_reset_password(self):
        response = self.client.post('/api/users/', {
            'username': 'tester01', 'name': '测试一号',
            'email': 'tester01@example.com', 'password': 'SafePass@123',
            'role': 'tester',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user_id = response.data['data']['id']

        response = self.client.get('/api/users/?keyword=测试一号&role=tester')
        self.assertEqual(response.data['data']['total'], 1)

        response = self.client.patch(f'/api/users/{user_id}/', {
            'name': '测试二号', 'is_active': False
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['data']['is_active'])

        response = self.client.post(f'/api/users/{user_id}/reset-password/', {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['data']['temporary_password'].startswith('Aibet@'))

    def test_duplicate_username_is_rejected(self):
        response = self.client.post('/api/users/', {
            'username': 'admin', 'name': '重复账号', 'email': 'other@example.com',
            'password': 'SafePass@123', 'role': 'tester',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_user_can_be_created_without_email(self):
        response = self.client.post('/api/users/', {
            'username': 'tester_without_email', 'name': '无邮箱用户',
            'password': 'SafePass@123', 'role': 'tester',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['data']['email'], '')

    def test_current_admin_cannot_be_deleted_or_demoted(self):
        response = self.client.delete(f'/api/users/{self.admin.id}/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response = self.client.patch(f'/api/users/{self.admin.id}/', {'role': 'tester'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_role_permissions_and_delete_protection(self):
        response = self.client.post('/api/roles/', {
            'name': '发布观察员', 'code': 'release_viewer', 'description': '查看发布',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        role_id = response.data['data']['id']

        response = self.client.post(f'/api/roles/{role_id}/permissions/', {
            'permissions': ['home.view', 'automation.view', 'home.view']
        }, format='json')
        self.assertEqual(response.data['data']['permissions'], ['home.view', 'automation.view'])

        user = User.objects.create_user(
            username='observer', password='SafePass@123', name='观察员',
            email='observer@example.com', role_id=role_id,
        )
        response = self.client.delete(f'/api/roles/{role_id}/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        user.delete()
        response = self.client.delete(f'/api/roles/{role_id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_system_role_cannot_be_deleted_or_recoded(self):
        response = self.client.delete(f'/api/roles/{self.admin_role.id}/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response = self.client.patch(
            f'/api/roles/{self.admin_role.id}/', {'code': 'other'}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_environment_default_copy_and_delete_rules(self):
        response = self.client.post('/api/environments/', {
            'name': '测试环境', 'description': '测试',
            'base_url': 'https://api-test.example.com',
            'variables': [{'key': 'TOKEN', 'value': 'demo'}], 'is_default': True,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        first_id = response.data['data']['id']

        response = self.client.post('/api/environments/', {
            'name': '预发布环境', 'base_url': 'https://api-stage.example.com',
            'variables': [], 'is_default': True,
        }, format='json')
        second_id = response.data['data']['id']
        self.assertFalse(Environment.objects.get(pk=first_id).is_default)

        response = self.client.post(f'/api/environments/{second_id}/copy/', {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(response.data['data']['is_default'])

        response = self.client.delete(f'/api/environments/{second_id}/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response = self.client.post(f'/api/environments/{first_id}/default/', {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response = self.client.delete(f'/api/environments/{second_id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_role_permission_blocks_unauthorized_write(self):
        viewer = User.objects.create_user(
            username='viewer', password='SafePass@123', name='只读用户',
            email='viewer@example.com', role=self.tester_role,
        )
        self.client.force_authenticate(viewer)
        response = self.client.get('/api/environments/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response = self.client.post('/api/environments/', {
            'name': '无权创建', 'base_url': 'https://example.com', 'variables': []
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_interface_assets_are_persisted_and_filterable(self):
        response = self.client.post('/api/interfaces/', {
            'name': '订单详情', 'method': 'GET', 'path': '/api/orders/1/',
            'module_name': '个人中心', 'description': '查询订单详情',
            'headers': {'Content-Type': 'application/json; charset=utf-8', 'X-Tenant': 'demo'},
            'request_params': {'order_id': 1},
            'api_type': '核心链路',
            'can_execute_in_task': False,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        interface_id = response.data['data']['id']
        interface = ApiInterface.objects.get(pk=interface_id)
        self.assertEqual(interface.created_by, self.admin)
        self.assertEqual(interface.headers['Content-Type'], 'application/json; charset=utf-8')
        self.assertEqual(interface.request_params, {'order_id': 1})
        self.assertEqual(interface.api_type, '系统录入')
        self.assertFalse(interface.can_execute_in_task)
        response = self.client.get('/api/interfaces/?keyword=订单&method=GET')
        self.assertEqual(response.data['data']['total'], 1)
        response = self.client.get('/api/interfaces/?can_execute_in_task=false&api_type=系统录入')
        self.assertEqual(response.data['data']['total'], 1)
        response = self.client.patch(f'/api/interfaces/{interface_id}/', {'description': '已更新'}, format='json')
        self.assertEqual(response.data['data']['description'], '已更新')

        response = self.client.post('/api/interfaces/', {
            'name': '无效接口', 'method': 'POST', 'path': '/api/invalid/',
            'module_name': '个人中心', 'headers': ['invalid'], 'request_params': [],
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.post('/api/interfaces/', {
            'name': '空参数接口', 'method': 'POST', 'path': '/api/empty-params/',
            'module_name': '赛事', 'headers': {}, 'request_params': {},
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['data']['request_params'], {})

    def test_interface_rejects_duplicate_url_and_params(self):
        payload = {
            'name': '查询赛事', 'method': 'GET', 'path': '/api/events/',
            'module_name': '赛事', 'headers': {},
            'request_params': {'page': 1, 'filters': {'status': 'active', 'type': 'league'}},
        }
        response = self.client.post('/api/interfaces/', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        duplicate = {
            **payload,
            'name': '重复赛事接口',
            'method': 'POST',
            'path': '  /api/events/  ',
            'request_params': {'filters': {'type': 'league', 'status': 'active'}, 'page': 1},
        }
        response = self.client.post('/api/interfaces/', duplicate, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('相同 URL 和请求参数', response.data['message'])

        different_params = {
            **payload,
            'name': '赛事第二页',
            'method': 'POST',
            'request_params': {'page': 2, 'filters': {'status': 'active', 'type': 'league'}},
        }
        response = self.client.post('/api/interfaces/', different_params, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        different_params_id = response.data['data']['id']

        response = self.client.patch(
            f'/api/interfaces/{different_params_id}/',
            {'request_params': payload['request_params']}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('platform_api.executor.urlopen', return_value=FakeHttpResponse())
    def test_automation_modules_tasks_and_run_actions(self, mocked_urlopen):
        module = AutomationModule.objects.get(app='frontend', name='个人中心')
        environment = Environment.objects.create(
            name='测试环境', base_url='https://test.example.com', login_url='https://test.example.com/api/auth/login/',
            variables=[{'key': 'identifier', 'value': '用户名'}, {'key': 'secret', 'value': '密码'}],
        )
        interface = ApiInterface.objects.create(
            name='个人信息接口', method='POST', path='/api/profile/', module_name='个人中心',
            headers={'Content-Type': 'application/json; charset=utf-8'}, request_params={'username': 'demo'},
            assertions={'status_code': 200, 'body_contains': 'ok'}, created_by=self.admin,
        )
        response = self.client.post('/api/automation/tasks/', {
            'name': '登录回归', 'module': module.id, 'task_type': 'ui',
            'environment': environment.id, 'owner': self.admin.id,
            'schedule': '手动执行',
            'login_password': 'Aibet@123456',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        task_id = response.data['data']['id']
        self.assertEqual(response.data['data']['module_name'], '个人中心')
        self.assertEqual(response.data['data']['status'], 'pending')
        self.assertEqual(response.data['data']['interface_count'], 1)
        self.assertEqual(mocked_urlopen.call_count, 0)
        response = self.client.post(f'/api/automation/tasks/{task_id}/run/', {'login_password': 'Aibet@123456'}, format='json')
        self.assertEqual(response.data['data']['status'], 'passed')
        self.assertEqual(len(response.data['data']['execution_details']), 2)
        self.assertEqual(response.data['data']['execution_details'][0]['interface_name'], '系统登录')
        self.assertEqual(response.data['data']['execution_details'][0]['execution_no'], 1)
        self.assertEqual(response.data['data']['execution_details'][1]['execution_no'], 1)
        self.assertEqual(mocked_urlopen.call_count, 2)
        self.assertEqual(
            json.loads(mocked_urlopen.call_args_list[0].args[0].data.decode('utf-8')),
            {'identifier': 'admin@example.com', 'secret': 'Aibet@123456'},
        )
        self.assertEqual(response.data['data']['execution_details'][0]['request_params'], {'identifier': 'admin@example.com'})
        self.assertEqual(mocked_urlopen.call_args.kwargs['timeout'], 3)
        self.assertEqual(AutomationTask.objects.count(), 1)
        detail = AutomationTaskResult.objects.get(task_id=task_id, source_interface_id=interface.id)
        self.assertEqual(detail.source_interface_id, interface.id)
        self.assertEqual(detail.interface_name, interface.name)
        self.assertEqual(detail.headers, interface.headers)
        self.assertEqual(detail.assertions, interface.assertions)
        self.assertEqual(detail.path, 'https://test.example.com/api/profile/')
        response = self.client.patch(f'/api/interfaces/{interface.id}/', {
            'name': '最新个人信息接口', 'path': '/api/profile/latest/',
            'headers': {'X-Version': 'latest'}, 'request_params': {'username': 'latest'},
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response = self.client.post(f'/api/automation/task-results/{detail.id}/retry/', {'login_password': 'Aibet@123456'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['data']['status'], 'passed')
        self.assertEqual(response.data['data']['execution_no'], 2)
        self.assertEqual(response.data['data']['interface_name'], '最新个人信息接口')
        self.assertEqual(response.data['data']['path'], 'https://test.example.com/api/profile/latest/')
        self.assertEqual(response.data['data']['headers'], {'X-Version': 'latest', 'authorization': ''})
        self.assertEqual(AutomationTaskResult.objects.filter(task_id=task_id).count(), 4)
        response = self.client.delete(f'/api/interfaces/{interface.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(ApiInterface.objects.filter(pk=interface.id).exists())
        self.assertTrue(AutomationTaskResult.objects.filter(task_id=task_id).exists())
        response = self.client.post(f'/api/automation/task-results/{detail.id}/retry/', {'login_password': 'Aibet@123456'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(AutomationTaskResult.objects.filter(task_id=task_id).count(), 4)
        response = self.client.delete(f'/api/automation/tasks/{task_id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(AutomationTask.objects.filter(pk=task_id).exists())
        self.assertFalse(AutomationTaskResult.objects.filter(task_id=task_id).exists())

    @patch('platform_api.executor.urlopen', return_value=FakeHttpResponse())
    def test_backend_task_login_uses_configured_parameter_names(self, mocked_urlopen):
        module, _ = AutomationModule.objects.get_or_create(app='backend', name='后台', defaults={'sort_order': 1})
        environment = Environment.objects.create(
            name='后台环境', base_url='https://admin.example.com', login_url='https://admin.example.com/auth/login',
            variables=[{'key': 'userName', 'value': '用户名'}, {'key': 'password', 'value': '密码'}],
        )
        ApiInterface.objects.create(
            name='后台用户接口', method='GET', path='/api/users/', module_name='后台',
            headers={}, request_params={}, assertions={'status_code': 200}, created_by=self.admin,
        )
        task = AutomationTask.objects.create(
            name='后台登录回归', task_type='api', environment=environment, owner=self.admin,
        )
        task.modules.add(module)

        execute_task(task, self.admin, 'Aibet@123456')

        login_request = mocked_urlopen.call_args_list[0].args[0]
        login_body = login_request.data.decode('utf-8')
        self.assertIn('multipart/form-data; boundary=', login_request.get_header('Content-type'))
        self.assertIn('name="userName"\r\n\r\nadmin', login_body)
        self.assertIn('name="password"\r\n\r\nAibet@123456', login_body)
        login_result = AutomationTaskResult.objects.get(task=task, interface_name='系统登录')
        self.assertEqual(login_result.request_params, {'userName': 'admin'})
        api_request = mocked_urlopen.call_args_list[1].args[0]
        self.assertEqual(api_request.get_header('X-token'), 'test-token')
        self.assertIsNone(api_request.get_header('Authorization'))

    @patch('platform_api.executor.urlopen', side_effect=[
        JsonFakeHttpResponse({'data': {'access': 'test-token'}}),
        JsonFakeHttpResponse({'data': {'forceLogout': {'minutes': 15}}}),
        JsonFakeHttpResponse({'ok': True}),
    ])
    def test_task_resolves_variables_from_successful_dependency_response(self, mocked_urlopen):
        module, _ = AutomationModule.objects.get_or_create(app='backend', name='后台', defaults={'sort_order': 1})
        environment = Environment.objects.create(
            name='后台环境', base_url='https://admin.example.com', login_url='https://admin.example.com/auth/login',
            variables=[{'key': 'userName', 'value': '用户名'}, {'key': 'password', 'value': '密码'}],
        )
        dependency = ApiInterface.objects.create(
            name='获取设置', method='GET', path='/api/v2/sys/getSetting', module_name='后台',
            headers={}, request_params={}, assertions={'status_code': 200}, created_by=self.admin,
        )
        target = ApiInterface.objects.create(
            name='获取游戏配置', method='GET', path='/api/v2/gameOffering/get', module_name='后台',
            headers={}, request_params={'query': {'tesrh': '${tesrh}'}}, assertions={'status_code': 200},
            reference_enabled=True, reference_interface=dependency,
            response_extracts=[{'name': 'tesrh', 'path': 'data.forceLogout.minutes'}], created_by=self.admin,
        )
        task = AutomationTask.objects.create(
            name='关联响应变量回归', task_type='api', environment=environment, owner=self.admin,
        )
        task.modules.add(module)

        execute_task(task, self.admin, 'Aibet@123456')

        target_result = AutomationTaskResult.objects.get(task=task, source_interface_id=target.id)
        self.assertEqual(target_result.status, 'passed', target_result.response_message)
        self.assertEqual(target_result.request_params, {'tesrh': 15})
        self.assertIn('tesrh=15', target_result.path)
        dependency_result = AutomationTaskResult.objects.get(task=task, source_interface_id=dependency.id)
        self.assertIn('forceLogout', dependency_result.response_log)
        self.assertEqual(mocked_urlopen.call_count, 3)

    @patch('platform_api.executor.urlopen', return_value=FakeHttpResponse())
    def test_monitor_center_configs_tasks_alarms_and_retry(self, mocked_urlopen):
        environment = Environment.objects.create(name='监控环境', base_url='https://monitor.example.com')
        interface = ApiInterface.objects.create(
            name='VIP 等级', method='GET', path='/api/v1/vip/levels', module_name='个人中心',
            headers={'Content-Type': 'application/json; charset=utf-8'}, request_params={},
            assertions={'status_code': 200, 'body_contains': 'missing', 'timeout_seconds': 3},
            api_type='核心链路', can_execute_in_task=False, created_by=self.admin,
        )
        failed_interface = ApiInterface.objects.create(
            name='VIP 权益', method='GET', path='/api/v1/vip/benefits', module_name='个人中心',
            headers={'Content-Type': 'application/json; charset=utf-8'}, request_params={},
            assertions={'status_code': 200, 'body_contains': 'missing', 'timeout_seconds': 3},
            api_type='核心链路', can_execute_in_task=False, created_by=self.admin,
        )
        response = self.client.post('/api/monitor/interfaces/', {'source_interface_ids': [interface.id, failed_interface.id]}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        config_id = response.data['data']['id']
        self.assertEqual(response.data['data']['source_interface_ids'], [interface.id, failed_interface.id])
        self.assertEqual(response.data['data']['name'], 'VIP 等级')
        self.assertEqual(response.data['data']['api_type'], '系统录入')
        self.assertEqual(response.data['data']['assertions']['timeout_seconds'], 3)
        response = self.client.post('/api/monitor/tasks/', {
            'name': '禁用自动化接口任务', 'module_name': '个人中心', 'api_type': '核心链路',
            'environment': environment.id, 'automation_interface_ids': [interface.id],
            'interval_value': 1, 'interval_unit': 'minute', 'enabled': True,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        interface.can_execute_in_task = True
        interface.assertions = {'status_code': 200, 'timeout_seconds': 3}
        interface.save(update_fields=['can_execute_in_task', 'assertions'])

        response = self.client.post('/api/monitor/tasks/', {
            'name': 'VIP 监控', 'module_name': '个人中心', 'api_type': '核心链路',
            'environment': environment.id, 'api_config_ids': [config_id],
            'automation_interface_ids': [interface.id], 'interval_value': 1,
            'interval_unit': 'minute', 'enabled': True,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        task_id = response.data['data']['id']
        self.assertEqual(response.data['data']['api_config_ids'], [config_id])
        self.assertEqual(response.data['data']['automation_interface_ids'], [interface.id])
        self.assertEqual(response.data['data']['api_count'], 3)
        self.assertIsNotNone(response.data['data']['next_run_time'])

        response = self.client.post(f'/api/monitor/tasks/{task_id}/run/', {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['data']['status'], 'failed')
        self.assertEqual(response.data['data']['interface_total'], 3)
        self.assertEqual(response.data['data']['failure_count'], 1)
        detail = MonitorExecutionDetail.objects.get(execution_id=response.data['data']['id'], source_api_config_id=config_id, source_interface_id=failed_interface.id)
        automation_detail = MonitorExecutionDetail.objects.get(execution_id=response.data['data']['id'], source_api_config_id=None, source_interface_id=interface.id)
        self.assertEqual(detail.url, 'https://monitor.example.com/api/v1/vip/benefits')
        self.assertEqual(automation_detail.url, 'https://monitor.example.com/api/v1/vip/levels')
        self.assertEqual(MonitorAlarm.objects.filter(task_id=task_id, status='open').count(), 1)

        failed_interface.path = '/api/v1/vip/benefits/latest'
        failed_interface.assertions = {'status_code': 200, 'timeout_seconds': 3}
        failed_interface.save(update_fields=['path', 'assertions'])
        response = self.client.post(f'/api/monitor/execution-details/{detail.id}/retry/', {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['data']['status'], 'passed')
        self.assertEqual(response.data['data']['url'], 'https://monitor.example.com/api/v1/vip/benefits/latest')

        response = self.client.get(f'/api/monitor/tasks/{task_id}/history/')
        self.assertEqual(response.data['data']['total'], 2)
        alarm_id = MonitorAlarm.objects.filter(task_id=task_id).first().id
        response = self.client.patch(f'/api/monitor/alarms/{alarm_id}/', {'status': 'handled'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['data']['status'], 'handled')
        response = self.client.delete(f'/api/monitor/interfaces/{config_id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(MonitorApiConfig.objects.filter(pk=config_id).exists())
        self.assertTrue(MonitorExecutionDetail.objects.filter(pk=detail.id).exists())

    def test_business_models_have_chinese_table_comments(self):
        models = [Role, User, Environment, AutomationModule, ApiInterface, AutomationTask, AutomationTaskResult, MonitorApiConfig, MonitorTask, MonitorExecution, MonitorExecutionDetail, MonitorAlarm]
        for model in models:
            self.assertTrue(model._meta.db_table.startswith('aibet_'))
            self.assertTrue(model._meta.db_table_comment)
