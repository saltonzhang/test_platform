import json
from decimal import Decimal
from unittest.mock import patch

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import ApiInterface, AutomationModule, AutomationTask, AutomationTaskResult, DataFactoryExecution, Environment, MonitorAlarm, MonitorApiConfig, MonitorExecution, MonitorExecutionDetail, MonitorTask, Role, User
from .executor import api_request_executor
from .interface_import import parse_fetch_text
from .serializers import AutomationTaskSerializer, DataFactoryExecutionSerializer
from .services import build_full_parameter_scenarios, build_parameter_variables, build_request_url, execute_task, replace_parameter_variables, resolve_full_custom_value


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
        self.assertEqual(
            api_request_executor.extract_access_token('{"code": 0, "data": {"x-token": "backend-token"}}'),
            'backend-token',
        )

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

    def test_full_custom_value_auto_detects_json_and_plain_text(self):
        self.assertEqual(resolve_full_custom_value({'path': 'body.count', 'value': '123'}, {}), 123)
        self.assertEqual(resolve_full_custom_value({'path': 'body.note', 'value': 'plain-text'}, {}), 'plain-text')
        self.assertEqual(
            resolve_full_custom_value({'path': 'body.values', 'value': '[${retrh},${retrh}]'}, {'retrh': 15}),
            [15, 15],
        )
        self.assertEqual(
            resolve_full_custom_value({'path': 'body.label', 'value': 'prefix-${name}'}, {'name': 'alice'}),
            'prefix-alice',
        )

    def test_full_custom_value_selects_one_multiple_range_and_all_array_items(self):
        variables = {'bit': [{'uid': 1}, {'uid': 2}, {'uid': 3}]}
        self.assertEqual(
            resolve_full_custom_value({'path': 'body.uid', 'value': '${bit[0].uid}'}, variables),
            1,
        )
        self.assertEqual(
            resolve_full_custom_value({'path': 'body.uid', 'value': '${bit[0,2].uid}'}, variables),
            [1, 3],
        )
        self.assertEqual(
            resolve_full_custom_value({'path': 'body.uid', 'value': '${bit[0:2].uid}'}, variables),
            [1, 2],
        )
        self.assertEqual(
            resolve_full_custom_value({'path': 'body.uid', 'value': '${bit[*].uid}'}, variables),
            [1, 2, 3],
        )

        interface = ApiInterface(
            method='POST', request_parameter_mode='full',
            full_parameterizations=[
                {
                    'path': 'body.uid', 'value_mode': 'variable', 'variable_type': 'custom',
                    'value': '${bit[0,2].uid}',
                },
                {'path': 'body.enabled', 'value_mode': 'fixed', 'values': [True, False]},
            ],
        )
        self.assertEqual(
            build_full_parameter_scenarios(interface, response_variables=variables),
            [
                {'uid': 1, 'enabled': True},
                {'uid': 1, 'enabled': False},
                {'uid': 3, 'enabled': True},
                {'uid': 3, 'enabled': False},
            ],
        )
        interface.full_parameterizations[0]['value'] = '${bit[*].uid}'
        with self.assertRaisesMessage(ValueError, '关联接口返回列表为空'):
            build_full_parameter_scenarios(interface, response_variables={'bit': []})

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

    def test_interface_request_parameter_modes_are_persisted_and_validated(self):
        template_response = self.client.post('/api/interfaces/', {
            'name': '模板参数接口', 'method': 'POST', 'path': '/api/parameter-mode/template/',
            'module_name': '个人中心', 'headers': {}, 'request_params': {'body': {'name': '{{personName}}'}},
            'parameterizations': [{'name': 'personName', 'type': 'name'}],
        }, format='json')
        self.assertEqual(template_response.status_code, status.HTTP_201_CREATED)
        template = template_response.data['data']
        self.assertEqual(template['request_parameter_mode'], 'template')
        self.assertEqual(template['full_parameterizations'], [])
        self.assertEqual(template['parameterizations'], [{'name': 'personName', 'type': 'name'}])

        full_config = [
            {'path': 'query.page', 'value_mode': 'fixed', 'values': [1, 2, 3]},
            {'path': 'body.user.enabled', 'value_mode': 'fixed', 'values': [True, False]},
            {'path': 'body.user.name', 'value_mode': 'variable', 'variable_type': 'name'},
            {'path': 'body.mobile', 'value_mode': 'variable', 'variable_type': 'custom', 'value': '13800138000'},
            {'path': 'body.values', 'value_mode': 'variable', 'variable_type': 'custom', 'custom_value_type': 'array', 'value': '[${retrh},${retrh}]'},
        ]
        expected_full_config = [
            *full_config[:3],
            {'path': 'body.mobile', 'value_mode': 'variable', 'variable_type': 'custom', 'value': '13800138000'},
            {'path': 'body.values', 'value_mode': 'variable', 'variable_type': 'custom', 'value': '[${retrh},${retrh}]'},
        ]
        full_response = self.client.post('/api/interfaces/', {
            'name': '全参数化接口', 'method': 'POST', 'path': '/api/parameter-mode/full/',
            'module_name': '个人中心', 'headers': {}, 'request_parameter_mode': 'full',
            'request_params': {'legacy': 'ignored'}, 'parameterizations': [{'name': 'ignored', 'type': 'name'}],
            'full_parameterizations': full_config,
        }, format='json')
        self.assertEqual(full_response.status_code, status.HTTP_201_CREATED)
        full = full_response.data['data']
        self.assertEqual(full['request_parameter_mode'], 'full')
        self.assertEqual(full['request_params'], {})
        self.assertEqual(full['parameterizations'], [])
        self.assertEqual(full['full_parameterizations'], expected_full_config)

        distinct_response = self.client.post('/api/interfaces/', {
            'name': '全参数化接口二', 'method': 'POST', 'path': '/api/parameter-mode/full/',
            'module_name': '个人中心', 'headers': {}, 'request_parameter_mode': 'full',
            'full_parameterizations': [{'path': 'query.page', 'value_mode': 'fixed', 'values': [4]}],
        }, format='json')
        self.assertEqual(distinct_response.status_code, status.HTTP_201_CREATED)

        update_response = self.client.patch(f"/api/interfaces/{full['id']}/", {
            'request_parameter_mode': 'template', 'request_params': {'body': {'fixed': 'value'}},
            'parameterizations': [],
        }, format='json')
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        self.assertEqual(update_response.data['data']['full_parameterizations'], [])

        invalid_payload = {
            'name': '无效全参数化接口', 'method': 'POST', 'path': '/api/parameter-mode/invalid/',
            'module_name': '个人中心', 'headers': {}, 'request_parameter_mode': 'full',
        }
        for config in (
            [],
            [{'path': 'page', 'value_mode': 'fixed', 'values': [1]}],
            [{'path': 'query.page', 'value_mode': 'fixed', 'values': [1]}, {'path': 'query.page', 'value_mode': 'fixed', 'values': [2]}],
            [{'path': 'query.page', 'value_mode': 'fixed', 'values': []}],
            [{'path': 'query.page', 'value_mode': 'variable', 'variable_type': 'unknown'}],
            [{'path': 'query.page', 'value_mode': 'variable', 'variable_type': 'custom'}],
            [{'path': 'query.page', 'value_mode': 'variable', 'variable_type': 'custom', 'value': '   '}],
            [{'path': 'query.page', 'value_mode': 'variable', 'variable_type': 'custom', 'value': '${bit[foo].uid}'}],
        ):
            response = self.client.post('/api/interfaces/', {**invalid_payload, 'full_parameterizations': config}, format='json')
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_batch_import_fetch_text_parses_and_skips_duplicates(self):
        text = '''fetch("https://api-test.helix.city/api/v1/member/getUnreadCount?scope=all", {
  "headers": {
    "authorization": "sensitive-token",
    "accept": "application/json, text/plain, */*"
  },
  "method": "GET",
  "body": null
});
fetch("https://api-test.helix.city/api/v1/member/getUnreadCount?scope=all", {
  "headers": {"authorization": "another-token"},
  "method": "GET"
});'''
        parsed = parse_fetch_text(text)
        self.assertEqual(parsed[0]['module_name'], '个人中心')
        self.assertEqual(parsed[0]['request_params'], {'query': {'scope': 'all'}})
        response = self.client.post('/api/interfaces/batch-import/', {'text': text}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['data']['imported']), 1)
        self.assertEqual(len(response.data['data']['skipped']), 1)
        interface = ApiInterface.objects.get(path='/api/v1/member/getUnreadCount')
        self.assertEqual(interface.headers['authorization'], '')
        self.assertNotIn('sensitive-token', str(interface.headers))

    @patch('platform_api.executor.urlopen', return_value=FakeHttpResponse())
    def test_automation_modules_tasks_and_run_actions(self, mocked_urlopen):
        target_password = 'target-login-pass'
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
            'login_password': target_password,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        task_id = response.data['data']['id']
        self.assertEqual(response.data['data']['module_name'], '个人中心')
        self.assertEqual(response.data['data']['status'], 'pending')
        self.assertEqual(response.data['data']['interface_count'], 1)
        self.assertEqual(mocked_urlopen.call_count, 0)
        response = self.client.post(f'/api/automation/tasks/{task_id}/run/', {'login_password': target_password}, format='json')
        self.assertEqual(response.data['data']['status'], 'passed')
        self.assertEqual(len(response.data['data']['execution_details']), 2)
        self.assertEqual(response.data['data']['execution_details'][0]['interface_name'], '系统登录')
        self.assertEqual(response.data['data']['execution_details'][0]['execution_no'], 1)
        self.assertEqual(response.data['data']['execution_details'][1]['execution_no'], 1)
        self.assertEqual(mocked_urlopen.call_count, 2)
        self.assertEqual(
            json.loads(mocked_urlopen.call_args_list[0].args[0].data.decode('utf-8')),
            {'identifier': 'admin@example.com', 'secret': target_password},
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
        response = self.client.post(f'/api/automation/task-results/{detail.id}/retry/', {'login_password': target_password}, format='json')
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
        response = self.client.post(f'/api/automation/task-results/{detail.id}/retry/', {'login_password': target_password}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(AutomationTaskResult.objects.filter(task_id=task_id).count(), 4)
        response = self.client.delete(f'/api/automation/tasks/{task_id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(AutomationTask.objects.filter(pk=task_id).exists())
        self.assertFalse(AutomationTaskResult.objects.filter(task_id=task_id).exists())

    @patch('platform_api.executor.urlopen', return_value=FakeHttpResponse())
    def test_scenario_task_executes_full_parameter_cartesian_product(self, mocked_urlopen):
        target_password = 'target-login-pass'
        module = AutomationModule.objects.get(app='frontend', name='个人中心')
        environment = Environment.objects.create(
            name='场景测试环境',
            base_url='https://scenario.example.com',
            login_url='https://scenario.example.com/api/auth/login/',
        )
        template_interface = ApiInterface.objects.create(
            name='模板接口', method='POST', path='/api/template/', module_name='个人中心',
            headers={}, request_params={'body': {'name': 'fixed'}}, created_by=self.admin,
        )
        invalid_task = self.client.post('/api/automation/tasks/', {
            'name': '无效场景任务', 'interface_ids': [template_interface.id], 'task_type': 'scenario',
            'environment': environment.id, 'owner': self.admin.id, 'login_password': target_password,
        }, format='json')
        self.assertEqual(invalid_task.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('全参数化', invalid_task.data['message'])

        interface = ApiInterface.objects.create(
            name='用户组合场景', method='POST', path='/api/scenario/users/', module_name='个人中心',
            headers={'Content-Type': 'application/json; charset=utf-8'},
            request_parameter_mode='full',
            full_parameterizations=[
                {'path': 'body.name', 'value_mode': 'fixed', 'values': [111, 222]},
                {'path': 'body.gender', 'value_mode': 'fixed', 'values': ['nv', 'nan']},
                {'path': 'body.operator', 'value_mode': 'variable', 'variable_type': 'name'},
                {'path': 'body.count', 'value_mode': 'variable', 'variable_type': 'custom', 'value': '123'},
                {'path': 'body.note', 'value_mode': 'variable', 'variable_type': 'custom', 'value': 'plain-text'},
            ],
            assertions={'status_code': 200}, created_by=self.admin,
        )
        scenario_serializer = AutomationTaskSerializer(data={
            'name': '场景模块归属校验', 'interface_ids': [interface.id], 'task_type': 'scenario',
            'environment': environment.id, 'owner': self.admin.id,
        })
        self.assertTrue(scenario_serializer.is_valid(), scenario_serializer.errors)
        serialized_task = scenario_serializer.save()
        self.assertEqual(
            list(serialized_task.modules.values_list('app', 'name')),
            [('frontend', '个人中心')],
        )
        serialized_task.delete()

        task = AutomationTask.objects.create(
            name='全参数组合场景', module=module, task_type='scenario',
            environment=environment, owner=self.admin,
        )
        task.modules.add(module)
        task.interfaces.add(interface)

        generated_names = ['场景用户1', '场景用户2', '场景用户3', '场景用户4']
        with patch('platform_api.services.generate_parameter_value', side_effect=generated_names) as mocked_generate:
            results = execute_task(task, self.admin, target_password)

        self.assertEqual(mocked_generate.call_count, 4)
        self.assertEqual(mocked_urlopen.call_count, 5)
        self.assertEqual(len(results), 5)
        details = list(AutomationTaskResult.objects.filter(
            task=task, source_interface_id=interface.id, execution_no=1,
        ).order_by('id'))
        expected_params = [
            {'name': 111, 'gender': 'nv', 'operator': '场景用户1', 'count': 123, 'note': 'plain-text'},
            {'name': 111, 'gender': 'nan', 'operator': '场景用户2', 'count': 123, 'note': 'plain-text'},
            {'name': 222, 'gender': 'nv', 'operator': '场景用户3', 'count': 123, 'note': 'plain-text'},
            {'name': 222, 'gender': 'nan', 'operator': '场景用户4', 'count': 123, 'note': 'plain-text'},
        ]
        self.assertEqual([item.request_params for item in details], expected_params)
        self.assertTrue(all(item.status == 'passed' for item in details))
        self.assertEqual([
            json.loads(call.args[0].data.decode('utf-8'))
            for call in mocked_urlopen.call_args_list[1:]
        ], expected_params)

        mocked_urlopen.reset_mock()
        retry_response = self.client.post(
            f'/api/automation/task-results/{details[2].id}/retry/',
            {'login_password': target_password}, format='json',
        )
        self.assertEqual(retry_response.status_code, status.HTTP_200_OK)
        self.assertEqual(retry_response.data['data']['request_params'], expected_params[2])
        self.assertEqual(mocked_urlopen.call_count, 2)

    @patch('platform_api.views.execute_account_balance', return_value={
        'member_id': 'member-1', 'adjustment_id': 'adjustment-1',
    })
    def test_data_factory_uses_target_system_password(self, mocked_execute):
        environment = Environment.objects.create(
            name='后台工具环境', base_url='https://admin.example.com',
            login_url='https://admin.example.com/auth/login',
        )
        target_password = 'target-login-pass'
        response = self.client.post('/api/data-factory/account-balance/', {
            'environment': environment.id,
            'email': 'member@example.com',
            'amount': 10,
            'login_password': target_password,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mocked_execute.assert_called_once_with(
            self.admin, target_password, environment.id, 'member@example.com', Decimal('10'),
        )

    @patch('platform_api.views.execute_account_balance', side_effect=ValueError('boom'))
    def test_data_factory_account_balance_unexpected_error_returns_400(self, mocked_execute):
        environment = Environment.objects.create(
            name='后台工具环境异常', base_url='https://admin.example.com',
            login_url='https://admin.example.com/auth/login',
        )
        response = self.client.post('/api/data-factory/account-balance/', {
            'environment': environment.id,
            'email': 'member@example.com',
            'amount': 10,
            'login_password': 'target-login-pass',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('boom', str(response.data))
        mocked_execute.assert_called_once()

    @patch('platform_api.data_factory.account_balance.execute_platform_login')
    def test_data_factory_account_balance_uses_login_encoding_keyword(self, mocked_login):
        environment = Environment.objects.create(
            name='后台工具环境登录参数', base_url='https://admin.example.com',
            login_url='https://admin.example.com/auth/login',
        )
        mocked_login.return_value = type('LoginResult', (), {'access_token': '', 'message': ''})()
        from platform_api.data_factory.account_balance import DataFactoryError, execute_account_balance
        with self.assertRaises(DataFactoryError):
            execute_account_balance(self.admin, 'target-login-pass', environment.id, 'member@example.com', Decimal('10'))
        mocked_login.assert_called_once()
        self.assertEqual(mocked_login.call_args.kwargs.get('login_encoding'), 'multipart')
        self.assertNotIn('request_encoding', mocked_login.call_args.kwargs)

    @patch('platform_api.views.close_old_connections')
    @patch('platform_api.views.transaction.on_commit', side_effect=lambda callback: callback())
    @patch('platform_api.views.threading.Thread')
    @patch('platform_api.views.execute_account_add', return_value={
        'environment_name': '账户添加环境',
        'email': 'test3@test.com',
        'emails': ['test1@test.com', 'test2@test.com', 'test3@test.com'],
        'amount': '10',
        'quantity': 3,
        'status': 'executed',
    })
    def test_data_factory_account_add_runs_asynchronously(self, mocked_execute, mocked_thread, mocked_on_commit, mocked_close_connections):
        mocked_thread.return_value.start.side_effect = lambda: mocked_thread.call_args.kwargs['target']()
        frontend_environment = Environment.objects.create(
            name='账户添加前台环境', base_url='https://api-test.helix.city',
            login_url='',
        )
        backend_environment = Environment.objects.create(
            name='账户添加后台环境', base_url='https://mgt-api-test.helix.city',
            login_url='https://mgt-api-test.helix.city/api/v2/login',
            variables=[{'key': 'userName', 'value': '用户名'}, {'key': 'password', 'value': '密码'}],
        )
        target_password = 'target-login-pass'
        response = self.client.post('/api/data-factory/account-add/', {
            'frontend_environment': frontend_environment.id,
            'backend_environment': backend_environment.id,
            'email': '',
            'amount': 10,
            'quantity': 3,
            'login_password': target_password,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data['data']['status'], 'running')
        mocked_on_commit.assert_called_once()
        mocked_execute.assert_called_once_with(
            self.admin, target_password, frontend_environment.id, backend_environment.id, '', Decimal('10'), 3,
        )
        execution = DataFactoryExecution.objects.get(pk=response.data['data']['execution_id'])
        self.assertEqual(execution.status, 'passed')
        self.assertEqual(execution.generated_emails, ['test1@test.com', 'test2@test.com', 'test3@test.com'])
        self.assertEqual(execution.email, 'test1@test.com')
        self.assertEqual(
            DataFactoryExecutionSerializer(execution).data['execution_content']['生成邮箱'],
            'test1@test.com、test2@test.com、test3@test.com',
        )

    @patch('platform_api.executor.urlopen', return_value=JsonFakeHttpResponse({
        'code': 5012, 'msg': 'not logged in or illegal access', 'data': None,
    }))
    def test_task_login_failure_returns_clear_message(self, mocked_urlopen):
        module = AutomationModule.objects.get(app='frontend', name='个人中心')
        environment = Environment.objects.create(
            name='登录失败环境', base_url='https://test.example.com',
            login_url='https://test.example.com/api/auth/login/',
        )
        task = AutomationTask.objects.create(
            name='登录失败提示', task_type='api', environment=environment, owner=self.admin,
        )
        task.modules.add(module)

        response = self.client.post(
            f'/api/automation/tasks/{task.id}/run/',
            {'login_password': 'target-login-pass'}, format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('目标系统登录失败', response.data['message'], response.data)
        self.assertIn('登录账号和密码', response.data['message'])

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

    @patch('platform_api.executor.urlopen', side_effect=[
        JsonFakeHttpResponse({'data': {'access': 'test-token'}}),
        JsonFakeHttpResponse({'data': {'forceLogout': {'minutes': 15}}}),
        JsonFakeHttpResponse({'ok': True}),
    ])
    def test_full_parameter_custom_array_uses_dependency_response_variables(self, mocked_urlopen):
        module, _ = AutomationModule.objects.get_or_create(app='backend', name='后台', defaults={'sort_order': 1})
        environment = Environment.objects.create(
            name='后台全参数变量环境',
            base_url='https://admin-full.example.com',
            login_url='https://admin-full.example.com/auth/login',
            variables=[{'key': 'userName', 'value': '用户名'}, {'key': 'password', 'value': '密码'}],
        )
        dependency = ApiInterface.objects.create(
            name='获取全参数变量', method='GET', path='/api/v2/sys/getSetting', module_name='后台',
            headers={}, request_params={}, assertions={'status_code': 200}, created_by=self.admin,
        )
        target = ApiInterface.objects.create(
            name='全参数数组接口', method='POST', path='/api/v2/gameOffering/set', module_name='后台',
            headers={'Content-Type': 'application/json; charset=utf-8'},
            request_parameter_mode='full',
            full_parameterizations=[
                {
                    'path': 'body.retches', 'value_mode': 'variable', 'variable_type': 'custom',
                    'value': '[${retrh},${retrh}]',
                },
            ],
            assertions={'status_code': 200},
            reference_enabled=True,
            reference_interface=dependency,
            response_extracts=[{'name': 'retrh', 'path': 'data.forceLogout.minutes'}],
            created_by=self.admin,
        )
        task = AutomationTask.objects.create(
            name='全参数关联变量回归', task_type='api', environment=environment, owner=self.admin,
        )
        task.modules.add(module)

        execute_task(task, self.admin, 'Aibet@123456')

        target_result = AutomationTaskResult.objects.get(task=task, source_interface_id=target.id)
        self.assertEqual(target_result.status, 'passed', target_result.response_message)
        self.assertEqual(target_result.request_params, {'retches': [15, 15]})
        self.assertEqual(
            json.loads(mocked_urlopen.call_args_list[2].args[0].data.decode('utf-8')),
            {'retches': [15, 15]},
        )

    @patch('platform_api.executor.urlopen', side_effect=[
        JsonFakeHttpResponse({'data': {'access': 'test-token'}}),
        JsonFakeHttpResponse({'data': {'bit': [{'uid': 1}, {'uid': 2}, {'uid': 3}]}}),
        JsonFakeHttpResponse({'ok': True}),
        JsonFakeHttpResponse({'ok': True}),
        JsonFakeHttpResponse({'ok': True}),
    ])
    def test_scenario_expands_selected_dependency_array_values(self, mocked_urlopen):
        module, _ = AutomationModule.objects.get_or_create(app='backend', name='后台', defaults={'sort_order': 1})
        environment = Environment.objects.create(
            name='后台数组遍历环境', base_url='https://admin-array.example.com',
            login_url='https://admin-array.example.com/auth/login',
            variables=[{'key': 'userName', 'value': '用户名'}, {'key': 'password', 'value': '密码'}],
        )
        dependency = ApiInterface.objects.create(
            name='获取 UID 列表', method='GET', path='/api/users', module_name='后台',
            headers={}, request_params={}, assertions={'status_code': 200}, created_by=self.admin,
        )
        target = ApiInterface.objects.create(
            name='逐个处理 UID', method='POST', path='/api/users/process', module_name='后台',
            headers={'Content-Type': 'application/json; charset=utf-8'}, request_parameter_mode='full',
            full_parameterizations=[{
                'path': 'body.uid', 'value_mode': 'variable', 'variable_type': 'custom',
                'value': '${bit[*].uid}',
            }],
            assertions={'status_code': 200}, reference_enabled=True, reference_interface=dependency,
            response_extracts=[{'name': 'bit', 'path': 'data.bit'}], created_by=self.admin,
        )
        task = AutomationTask.objects.create(
            name='关联 UID 遍历场景', task_type='scenario', environment=environment, owner=self.admin,
        )
        task.modules.add(module)
        task.interfaces.add(target)

        execute_task(task, self.admin, 'Aibet@123456')

        details = list(AutomationTaskResult.objects.filter(
            task=task, source_interface_id=target.id,
        ).order_by('id'))
        self.assertEqual([item.request_params for item in details], [{'uid': 1}, {'uid': 2}, {'uid': 3}])
        self.assertTrue(all(item.status == 'passed' for item in details))
        self.assertEqual(mocked_urlopen.call_count, 5)

    @patch('platform_api.executor.urlopen', side_effect=[
        JsonFakeHttpResponse({'data': {'access': 'test-token'}}),
        JsonFakeHttpResponse({'data': {'bit': []}}),
    ])
    def test_scenario_records_empty_dependency_array_as_failure(self, mocked_urlopen):
        module, _ = AutomationModule.objects.get_or_create(app='backend', name='后台', defaults={'sort_order': 1})
        environment = Environment.objects.create(
            name='后台空数组环境', base_url='https://admin-empty-array.example.com',
            login_url='https://admin-empty-array.example.com/auth/login',
            variables=[{'key': 'userName', 'value': '用户名'}, {'key': 'password', 'value': '密码'}],
        )
        dependency = ApiInterface.objects.create(
            name='获取空 UID 列表', method='GET', path='/api/empty-users', module_name='后台',
            headers={}, request_params={}, assertions={'status_code': 200}, created_by=self.admin,
        )
        target = ApiInterface.objects.create(
            name='处理空 UID 列表', method='POST', path='/api/empty-users/process', module_name='后台',
            headers={}, request_parameter_mode='full', full_parameterizations=[{
                'path': 'body.uid', 'value_mode': 'variable', 'variable_type': 'custom',
                'value': '${bit[*].uid}',
            }], assertions={'status_code': 200}, reference_enabled=True, reference_interface=dependency,
            response_extracts=[{'name': 'bit', 'path': 'data.bit'}], created_by=self.admin,
        )
        task = AutomationTask.objects.create(
            name='关联 UID 空列表场景', task_type='scenario', environment=environment, owner=self.admin,
        )
        task.modules.add(module)
        task.interfaces.add(target)

        execute_task(task, self.admin, 'Aibet@123456')

        target_result = AutomationTaskResult.objects.get(task=task, source_interface_id=target.id)
        self.assertEqual(target_result.status, 'failed')
        self.assertEqual(target_result.request_params, {})
        self.assertIn('关联接口返回列表为空', target_result.response_message)
        self.assertEqual(mocked_urlopen.call_count, 2)

    @patch('platform_api.executor.perf_counter', side_effect=[0, 0.1, 0, 4.1])
    @patch('platform_api.executor.urlopen', side_effect=[
        JsonFakeHttpResponse({'data': {'access': 'test-token'}}),
        JsonFakeHttpResponse({'data': {'pageInfo': {'totalCount': 15}}}),
    ])
    def test_full_parameter_dependency_failure_blocks_consumer_with_clear_message(self, mocked_urlopen, mocked_clock):
        module, _ = AutomationModule.objects.get_or_create(app='backend', name='后台', defaults={'sort_order': 1})
        environment = Environment.objects.create(
            name='后台全参数依赖失败环境',
            base_url='https://admin-full-failed.example.com',
            login_url='https://admin-full-failed.example.com/auth/login',
            variables=[{'key': 'userName', 'value': '用户名'}, {'key': 'password', 'value': '密码'}],
        )
        dependency = ApiInterface.objects.create(
            name='settledOrderHistory', method='GET', path='/sport/v1/casino/settledOrderHistory',
            module_name='后台', headers={}, request_params={'query': {'page': '1'}},
            assertions={'status_code': 200, 'timeout_seconds': 3}, created_by=self.admin,
        )
        target = ApiInterface.objects.create(
            name='GET inUseInfo', method='GET', path='/api/v1/mmm/wallet/inUseInfo',
            module_name='后台', headers={}, request_parameter_mode='full',
            full_parameterizations=[
                {'path': 'query.name', 'value_mode': 'fixed', 'values': [111, 222, 333]},
                {'path': 'query.lint', 'value_mode': 'fixed', 'values': ['aaa']},
                {
                    'path': 'query.retch', 'value_mode': 'variable', 'variable_type': 'custom',
                    'value': '[${retrh},${retrh}]',
                },
            ],
            assertions={'status_code': 200},
            reference_enabled=True,
            reference_interface=dependency,
            response_extracts=[{'name': 'retrh', 'path': 'data.pageInfo.totalCount'}],
            created_by=self.admin,
        )
        task = AutomationTask.objects.create(
            name='全参数依赖失败回归', task_type='scenario', environment=environment, owner=self.admin,
        )
        task.modules.add(module)
        task.interfaces.add(target)

        execute_task(task, self.admin, 'Aibet@123456')

        dependency_result = AutomationTaskResult.objects.get(task=task, source_interface_id=dependency.id)
        self.assertEqual(dependency_result.status, 'failed')
        self.assertIn('耗时断言失败', dependency_result.response_message)
        target_result = AutomationTaskResult.objects.get(task=task, source_interface_id=target.id)
        self.assertEqual(target_result.status, 'failed')
        self.assertEqual(target_result.request_params, {})
        self.assertIn('关联接口 settledOrderHistory 未通过', target_result.response_message)
        self.assertIn('retrh', target_result.response_message)
        self.assertEqual(mocked_urlopen.call_count, 2)

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
