import os
import json
import io
import zipfile
from datetime import datetime
from decimal import Decimal
from unittest.mock import Mock, patch
from types import SimpleNamespace

from django.urls import reverse
from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from django.core.files.uploadedfile import SimpleUploadedFile

from .models import ApiInterface, AutomationModule, AutomationTask, AutomationTaskResult, DataFactoryExecution, Environment, EnvironmentPackage, MonitorAlarm, MonitorApiConfig, MonitorExecution, MonitorExecutionDetail, MonitorTask, Role, User, UserEnvironmentAccount
from .executor import api_request_executor
from .interface_import import parse_fetch_text
from .testcase.services import parse_xmind_package
from .serializers import AutomationTaskSerializer, DataFactoryExecutionSerializer
from .services import AUTOMATION_PLATFORM_URL, build_full_parameter_scenarios, build_parameter_variables, build_request_url, execute_task, replace_parameter_variables, replace_response_variables, resolve_full_custom_value, send_feishu_monitor_alarm, send_feishu_task_result


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


class TestCasePackageImportTests(SimpleTestCase):
    def test_parses_xmind_content_json_into_tree(self):
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, 'w') as archive:
            archive.writestr('content.json', json.dumps([{
                'rootTopic': {
                    'title': '登录用例包',
                    'markers': [{'markerId': 'priority-1'}],
                    'children': {'attached': [{'title': '登录成功', 'children': {'attached': [{'title': '校验首页'}]}}]},
                },
            }]))
        name, content = parse_xmind_package(SimpleUploadedFile('login.xmind', payload.getvalue()))
        self.assertEqual(name, '登录用例包')
        self.assertEqual(content['tag'], ['待定'])
        self.assertEqual(content['children'][0]['title'], '登录成功')
        self.assertEqual(content['children'][0]['children'][0]['title'], '校验首页')


class DatabaseConfigTests(SimpleTestCase):
    def test_legacy_database_config_is_used_without_profile(self):
        from platform_api.common.database import get_database_config

        with patch.dict(os.environ, {
            'DATA_FACTORY_DB_PROFILE': '',
            'DATA_FACTORY_DB_HOST': 'legacy-host',
            'DATA_FACTORY_DB_PORT': '3306',
            'DATA_FACTORY_DB_USER': 'legacy-user',
            'DATA_FACTORY_DB_PASSWORD': 'legacy-pass',
            'DATA_FACTORY_DB_NAME': 'legacy_db',
            'DATA_FACTORY_DB_CHARSET': 'utf8mb4',
            'DATA_FACTORY_DB_CONNECT_TIMEOUT': '11',
            'DATA_FACTORY_DB_READ_TIMEOUT': '22',
            'DATA_FACTORY_DB_WRITE_TIMEOUT': '33',
        }, clear=False):
            config = get_database_config()

        self.assertEqual(config['host'], 'legacy-host')
        self.assertEqual(config['port'], 3306)
        self.assertEqual(config['user'], 'legacy-user')
        self.assertEqual(config['password'], 'legacy-pass')
        self.assertEqual(config['database'], 'legacy_db')
        self.assertEqual(config['charset'], 'utf8mb4')
        self.assertEqual(config['connect_timeout'], 11)
        self.assertEqual(config['read_timeout'], 22)
        self.assertEqual(config['write_timeout'], 33)
        self.assertEqual(config['cursorclass'].__name__, 'DictCursor')

    def test_profile_database_config_is_selected_from_env(self):
        from platform_api.common.database import get_database_config

        with patch.dict(os.environ, {
            'DATA_FACTORY_DB_PROFILE': 'report',
            'DATA_FACTORY_DB_REPORT_HOST': 'report-host',
            'DATA_FACTORY_DB_REPORT_PORT': '3307',
            'DATA_FACTORY_DB_REPORT_USER': 'report-user',
            'DATA_FACTORY_DB_REPORT_PASSWORD': 'report-pass',
            'DATA_FACTORY_DB_REPORT_NAME': 'report_db',
            'DATA_FACTORY_DB_REPORT_CONNECT_TIMEOUT': '7',
        }, clear=False):
            config = get_database_config()

        self.assertEqual(config['host'], 'report-host')
        self.assertEqual(config['port'], 3307)
        self.assertEqual(config['user'], 'report-user')
        self.assertEqual(config['password'], 'report-pass')
        self.assertEqual(config['database'], 'report_db')
        self.assertEqual(config['connect_timeout'], 7)

    def test_explicit_profile_argument_overrides_environment_profile(self):
        from platform_api.common.database import get_database_config

        with patch.dict(os.environ, {
            'DATA_FACTORY_DB_PROFILE': 'report',
            'DATA_FACTORY_DB_REPORT_HOST': 'report-host',
            'DATA_FACTORY_DB_REPORT_PORT': '3307',
            'DATA_FACTORY_DB_REPORT_USER': 'report-user',
            'DATA_FACTORY_DB_REPORT_PASSWORD': 'report-pass',
            'DATA_FACTORY_DB_REPORT_NAME': 'report_db',
            'DATA_FACTORY_DB_AUDIT_HOST': 'audit-host',
            'DATA_FACTORY_DB_AUDIT_PORT': '3308',
            'DATA_FACTORY_DB_AUDIT_USER': 'audit-user',
            'DATA_FACTORY_DB_AUDIT_PASSWORD': 'audit-pass',
            'DATA_FACTORY_DB_AUDIT_NAME': 'audit_db',
        }, clear=False):
            config = get_database_config(profile='audit')

        self.assertEqual(config['host'], 'audit-host')
        self.assertEqual(config['port'], 3308)
        self.assertEqual(config['user'], 'audit-user')
        self.assertEqual(config['password'], 'audit-pass')
        self.assertEqual(config['database'], 'audit_db')

    def test_missing_profile_fields_raise_clear_error(self):
        from platform_api.common.database import get_database_config

        with patch.dict(os.environ, {
            'DATA_FACTORY_DB_PROFILE': 'broken',
            'DATA_FACTORY_DB_BROKEN_HOST': 'broken-host',
        }, clear=False):
            with self.assertRaises(RuntimeError) as ctx:
                get_database_config()

        self.assertIn('DATA_FACTORY_DB_BROKEN_PORT', str(ctx.exception))
        self.assertIn('profile=broken', str(ctx.exception))

    @patch('platform_api.common.database.pymysql.connect')
    def test_get_db_connection_uses_explicit_profile(self, mocked_connect):
        from platform_api.common.database import get_db_connection

        mocked_connect.return_value = object()
        with patch.dict(os.environ, {
            'DATA_FACTORY_DB_PROFILE': 'report',
            'DATA_FACTORY_DB_REPORT_HOST': 'report-host',
            'DATA_FACTORY_DB_REPORT_PORT': '3307',
            'DATA_FACTORY_DB_REPORT_USER': 'report-user',
            'DATA_FACTORY_DB_REPORT_PASSWORD': 'report-pass',
            'DATA_FACTORY_DB_REPORT_NAME': 'report_db',
            'DATA_FACTORY_DB_AUDIT_HOST': 'audit-host',
            'DATA_FACTORY_DB_AUDIT_PORT': '3308',
            'DATA_FACTORY_DB_AUDIT_USER': 'audit-user',
            'DATA_FACTORY_DB_AUDIT_PASSWORD': 'audit-pass',
            'DATA_FACTORY_DB_AUDIT_NAME': 'audit_db',
        }, clear=False):
            get_db_connection(profile='audit')

        mocked_connect.assert_called_once()
        self.assertEqual(mocked_connect.call_args.kwargs['host'], 'audit-host')
        self.assertEqual(mocked_connect.call_args.kwargs['port'], 3308)
        self.assertEqual(mocked_connect.call_args.kwargs['database'], 'audit_db')


class DataFactoryCredentialTests(SimpleTestCase):
    @override_settings(
        DATA_FACTORY_FRONTEND_ACCOUNT='frontend-account',
        DATA_FACTORY_FRONTEND_PASSWORD='frontend-password',
        DATA_FACTORY_BACKEND_ACCOUNT='backend-account',
        DATA_FACTORY_BACKEND_PASSWORD='backend-password',
    )
    def test_data_factory_credentials_are_selected_by_environment_type(self):
        from platform_api.data_factory.account_balance import get_data_factory_credentials

        self.assertEqual(get_data_factory_credentials('frontend'), ('frontend-account', 'frontend-password'))
        self.assertEqual(get_data_factory_credentials('backend'), ('backend-account', 'backend-password'))


class DataFactoryMemberQueryTests(SimpleTestCase):
    @patch('platform_api.data_factory.member_query.query_one', return_value={
        'id': 407361968781922304,
        'uuid': '21181393-7bc4-4eb1-b4f1-80eae482fcbe',
        'id_number': '31751198243',
        'email': 'colin7672@proton.me',
        'nickname': 'User442106',
    })
    def test_member_query_maps_fields_without_password(self, mocked_query_one):
        from platform_api.data_factory.member_query import query_member_by_email

        result = query_member_by_email(' Colin7672@Proton.me ', environment_name='helix')

        mocked_query_one.assert_called_once_with(
            'SELECT id, uuid, id_number, email, nickname FROM member WHERE email = %s OR nickname = %s LIMIT 1',
            ('colin7672@proton.me', 'Colin7672@Proton.me'),
        )
        self.assertEqual(result, {
            'environment_name': 'helix',
            'email': 'colin7672@proton.me',
            'uid': '21181393-7bc4-4eb1-b4f1-80eae482fcbe',
            'cpf': '31751198243',
            'member_id': '407361968781922304',
            'nickname': 'User442106',
        })
        self.assertNotIn('password', result)


class DataFactoryMemberStatusActivateTests(SimpleTestCase):
    @patch('platform_api.data_factory.member_status_activate.DatabaseClient')
    def test_member_status_activate_updates_last_active_time_with_parameterized_sql(self, mocked_database_client):
        from platform_api.data_factory.member_status_activate import activate_member_status

        mocked_db = mocked_database_client.return_value.__enter__.return_value
        mocked_db.query_one.return_value = {'id': 402349924005449728}
        mocked_db.execute_write.return_value = 1

        result = activate_member_status('Member@Example.com', environment_name='helix')

        mocked_db.execute_write.assert_called_once()
        sql, params = mocked_db.execute_write.call_args.args
        self.assertIn('UPDATE member_extra', sql)
        self.assertIn('SELECT id FROM member WHERE email = %s', sql)
        self.assertEqual(params, ('member@example.com',))
        self.assertIn('SET last_active_time = NOW()', sql)
        self.assertEqual(result, {
            'environment_name': 'helix',
            'member_id': '402349924005449728',
            'affected_rows': 1,
            'status': 'passed',
            'message': '用户状态已激活，影响行数 1',
        })


class DataFactoryAccountAddKycTests(SimpleTestCase):
    @patch('platform_api.data_factory.account_add.requests.post')
    @patch('platform_api.data_factory.account_add.query_one', side_effect=RuntimeError('missing db config'))
    def test_data_factory_account_add_member_lookup_error_stops_registration(self, mocked_query_one, mocked_post):
        from platform_api.data_factory.account_add import DataFactoryError, _run_single_account

        frontend_environment = SimpleNamespace(
            name='账户添加前台查询异常',
            base_url='https://api-test.helix.city',
        )
        backend_environment = SimpleNamespace(
            name='账户添加后台查询异常',
            base_url='https://mgt-api-test.helix.city',
            login_url='https://mgt-api-test.helix.city/api/v2/login',
            id=99,
        )
        with self.assertRaisesMessage(DataFactoryError, '查询账号是否存在时出错'):
            _run_single_account(
                frontend_environment,
                backend_environment,
                email='colin7672@proton.me',
                amount=Decimal('7'),
            )

        mocked_query_one.assert_called_once_with(
            'SELECT id FROM member WHERE email = %s LIMIT 1',
            ('colin7672@proton.me',),
        )
        mocked_post.assert_not_called()

    @patch('platform_api.data_factory.account_add.DatabaseClient')
    def test_data_factory_account_add_marks_kyc_passed_via_database_update(self, mocked_database_client):
        from platform_api.data_factory.account_add import mark_kyc_passed

        mocked_db = mocked_database_client.return_value.__enter__.return_value
        mocked_db.execute_write.return_value = 1

        affected_rows = mark_kyc_passed('404211509485375488')

        self.assertEqual(affected_rows, 1)
        mocked_db.execute_write.assert_called_once()
        sql, params = mocked_db.execute_write.call_args.args
        self.assertIn('UPDATE member_extra', sql)
        self.assertIn('SET kyc_status = 2, kyc_passed = 1, kyc_level = 2', sql)
        self.assertEqual(params, ('404211509485375488',))

    @patch('platform_api.data_factory.account_add.time.sleep', return_value=None)
    @patch('platform_api.data_factory.account_add.mark_kyc_passed', return_value=1)
    @patch('platform_api.data_factory.account_add.query_kyc_info_from_db', return_value=(
        '404211509485375488', 'uuid-1', None, None,
    ))
    @patch('platform_api.data_factory.account_add.get_kyc_url')
    @patch('platform_api.data_factory.account_add.extract_token_str', return_value='test-token')
    @patch('platform_api.data_factory.account_add.get_brazil_id', return_value='123.456.789-09')
    @patch('platform_api.data_factory.account_add.check_member_exists', return_value=None)
    @patch('platform_api.data_factory.account_add.requests.post')
    def test_data_factory_account_add_uses_database_update_after_registration(
        self,
        mocked_post,
        mocked_check_member_exists,
        mocked_get_brazil_id,
        mocked_extract_token_str,
        mocked_get_kyc_url,
        mocked_query_kyc_info_from_db,
        mocked_mark_kyc_passed,
        mocked_sleep,
    ):
        from platform_api.data_factory.account_add import _run_single_account

        response = Mock()
        response.status_code = 200
        response.text = '{"code": 0}'
        response.headers = {}
        response.json.return_value = {'code': 0}
        mocked_post.return_value = response

        frontend_environment = SimpleNamespace(
            name='账户添加前台数据库更新',
            base_url='https://api-test.helix.city',
        )
        backend_environment = SimpleNamespace(
            name='账户添加后台数据库更新',
            base_url='https://mgt-api-test.helix.city',
            login_url='https://mgt-api-test.helix.city/api/v2/login',
            id=99,
        )
        result = _run_single_account(
            frontend_environment,
            backend_environment,
            email='colin7672@proton.me',
            amount=Decimal('0'),
        )

        mocked_mark_kyc_passed.assert_called_once_with('404211509485375488')
        mocked_get_kyc_url.assert_called_once_with(frontend_environment, 'test-token')
        self.assertEqual(result['member_id'], '404211509485375488')
        self.assertEqual(result['status'], 'registered')

class OrderResultRollbackTests(SimpleTestCase):
    def mocked_success_outcome(self):
        return type('Outcome', (), {
            'status': 'passed',
            'message': 'HTTP 200 · 断言通过',
            'response_log': '{"ok":true}',
        })()

    @patch('platform_api.data_factory.order_result_push.api_request_executor.execute')
    def test_rollback_bet_settlement_posts_content_payload(self, mocked_execute):
        from platform_api.data_factory.order_result_push import ROLLBACK_BET_SETTLEMENT_URL, rollback_bet_settlement

        mocked_execute.return_value = self.mocked_success_outcome()

        result = rollback_bet_settlement(
            product='3',
            event_id='sr:match:66886848',
            market_id='18',
            specifiers='total=1.5',
            timestamp=1784601930281,
        )

        mocked_execute.assert_called_once()
        self.assertEqual(mocked_execute.call_args.kwargs['url'], ROLLBACK_BET_SETTLEMENT_URL)
        self.assertEqual(mocked_execute.call_args.kwargs['method'], 'POST')
        payload = mocked_execute.call_args.kwargs['request_params']
        self.assertEqual(payload['partition'], 0)
        self.assertEqual(payload['key'], 'sr:match:66886848')
        self.assertEqual(payload['keySerde'], 'String')
        self.assertEqual(payload['valueSerde'], 'String')
        self.assertNotIn('value', payload)
        self.assertIn('<rollback_bet_settlement product="3" event_id="sr:match:66886848" timestamp="1784601930281">', payload['content'])
        self.assertIn('<market id="18" specifiers="total=1.5"/>', payload['content'])
        self.assertEqual(result['event_id'], 'sr:match:66886848')
        self.assertEqual(result['payload'], payload)


class FeishuAutomationNotificationTests(SimpleTestCase):
    @override_settings(FEISHU_BOT_WEBHOOK_URL='https://example.test/feishu-hook', FEISHU_BOT_SSL_VERIFY=True)
    @patch('platform_api.services.urlopen')
    def test_notification_contains_platform_url_and_action_button(self, mocked_urlopen):
        mocked_urlopen.return_value = JsonFakeHttpResponse({'code': 0})
        task = SimpleNamespace(
            name='下单回归',
            status='passed',
            environment=SimpleNamespace(name='测试环境'),
            owner=SimpleNamespace(name='测试人员', username='tester'),
        )
        result = SimpleNamespace(status='passed', interface_name='创建订单')

        notification_status, notification_message = send_feishu_task_result(task, [result])

        self.assertEqual(notification_status, 'sent')
        self.assertEqual(notification_message, '飞书通知发送成功')
        request = mocked_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode('utf-8'))
        self.assertEqual(payload['msg_type'], 'interactive')
        elements = payload['card']['elements']
        content = elements[0]['text']['content']
        self.assertIn('执行时间：', content)
        self.assertIn('执行人：测试人员', content)
        self.assertNotIn('平台地址：', content)
        action = elements[1]['actions'][0]
        self.assertEqual(action['text']['content'], '去平台')
        self.assertEqual(action['url'], AUTOMATION_PLATFORM_URL)
        self.assertEqual(action['width'], 'fill')

    @override_settings(FEISHU_BOT_WEBHOOK_URL='https://example.test/feishu-hook', FEISHU_BOT_SSL_VERIFY=True)
    @patch('platform_api.services.urlopen')
    def test_monitor_alarm_notification_uses_dedicated_template(self, mocked_urlopen):
        mocked_urlopen.return_value = JsonFakeHttpResponse({'code': 0})
        finished_at = timezone.make_aware(datetime(2026, 8, 5, 20, 30))
        task = SimpleNamespace(name='VIP 监控任务', api_type='VIP 权益')
        execution = SimpleNamespace(
            task=task,
            finished_at=finished_at,
            interface_total=3,
            failure_count=1,
        )
        details = [
            SimpleNamespace(status='passed', interface_name='VIP 等级'),
            SimpleNamespace(status='failed', interface_name='VIP 权益'),
        ]

        notification_status, notification_message = send_feishu_monitor_alarm(execution, details)

        self.assertEqual(notification_status, 'sent')
        self.assertEqual(notification_message, '监控任务告警通知发送成功')
        request = mocked_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode('utf-8'))
        self.assertEqual(payload['card']['header']['title']['content'], '监控任务告警提示')
        content = payload['card']['elements'][0]['text']['content']
        self.assertIn('任务名称：VIP 监控任务', content)
        self.assertIn('任务接口名称：VIP 权益', content)
        self.assertIn('触发时间：2026-08-05 20:30:00', content)
        self.assertIn('接口数量：3', content)
        self.assertIn('异常接口数量：1', content)
        action = payload['card']['elements'][1]['actions'][0]
        self.assertEqual(action['text']['content'], '去平台')
        self.assertEqual(action['url'], AUTOMATION_PLATFORM_URL)


class OrderResultCancelTests(SimpleTestCase):
    def mocked_success_outcome(self):
        return type('Outcome', (), {
            'status': 'passed',
            'message': 'HTTP 200 · 断言通过',
            'response_log': '{"ok":true}',
        })()

    @patch('platform_api.data_factory.order_result_push.api_request_executor.execute')
    def test_bet_cancel_posts_content_payload(self, mocked_execute):
        from platform_api.data_factory.order_result_push import BET_CANCEL_URL, bet_cancel

        mocked_execute.return_value = self.mocked_success_outcome()

        result = bet_cancel(
            product='3',
            event_id='sr:match:66886868',
            market_id='1',
            specifiers='',
            start_time='',
            end_time='',
            timestamp=1784601930281,
        )

        mocked_execute.assert_called_once()
        self.assertEqual(mocked_execute.call_args.kwargs['url'], BET_CANCEL_URL)
        self.assertEqual(mocked_execute.call_args.kwargs['method'], 'POST')
        payload = mocked_execute.call_args.kwargs['request_params']
        self.assertEqual(payload['partition'], 0)
        self.assertEqual(payload['key'], 'sr:match:66886868')
        self.assertEqual(payload['keySerde'], 'String')
        self.assertEqual(payload['valueSerde'], 'String')
        self.assertNotIn('value', payload)
        self.assertIn(
            '<bet_cancel start_time="" end_time="" product="3" event_id="sr:match:66886868" timestamp="1784601930281">',
            payload['content'],
        )
        self.assertIn('<market void_reason="4" id="1" specifiers=""/>', payload['content'])
        self.assertEqual(result['event_id'], 'sr:match:66886868')
        self.assertEqual(result['payload'], payload)

    @patch('platform_api.data_factory.order_result_push.api_request_executor.execute')
    def test_rollback_bet_cancel_posts_content_payload(self, mocked_execute):
        from platform_api.data_factory.order_result_push import ROLLBACK_BET_CANCEL_URL, rollback_bet_cancel

        mocked_execute.return_value = self.mocked_success_outcome()

        result = rollback_bet_cancel(
            product='3',
            event_id='sr:match:66886868',
            market_id='1',
            specifiers='',
            start_time='',
            end_time='',
            timestamp=1784602930291,
        )

        mocked_execute.assert_called_once()
        self.assertEqual(mocked_execute.call_args.kwargs['url'], ROLLBACK_BET_CANCEL_URL)
        self.assertEqual(mocked_execute.call_args.kwargs['method'], 'POST')
        payload = mocked_execute.call_args.kwargs['request_params']
        self.assertEqual(payload['partition'], 0)
        self.assertEqual(payload['key'], 'sr:match:66886868')
        self.assertEqual(payload['keySerde'], 'String')
        self.assertEqual(payload['valueSerde'], 'String')
        self.assertNotIn('value', payload)
        self.assertIn(
            '<rollback_bet_cancel start_time="" end_time="" product="3" event_id="sr:match:66886868" timestamp="1784602930291">',
            payload['content'],
        )
        self.assertIn('<market id="1" specifiers=""/>', payload['content'])
        self.assertEqual(result['event_id'], 'sr:match:66886868')
        self.assertEqual(result['payload'], payload)


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

    def set_environment_account(self, environment, account='target-system-account'):
        return UserEnvironmentAccount.objects.update_or_create(
            user=self.admin, environment=environment, defaults={'account': account},
        )

    def test_login_returns_tokens_and_user(self):
        self.client.force_authenticate(None)
        response = self.client.post('/api/auth/login/', {
            'username': 'admin', 'password': 'Aibet@123456'
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data['data'])
        self.assertEqual(response.data['data']['user']['role'], 'admin')

    @override_settings(LARK_APP_ID='cli_test', LARK_APP_SECRET='secret', LARK_FRONTEND_URL='http://frontend.test', LARK_DEFAULT_ROLE_CODE='tester')
    def test_lark_callback_provisions_user_and_returns_platform_tokens(self):
        self.client.force_authenticate(None)
        session = self.client.session
        session['lark_oauth_state'] = 'valid-state'
        session.save()
        with patch('platform_api.views.lark_request', side_effect=[
            {'app_access_token': 'app-access-token'},
            {'access_token': 'lark-access-token'},
            {'union_id': 'union-new-user', 'open_id': 'open-new-user', 'name': 'Lark Tester', 'email': 'lark@example.com'},
        ]):
            response = self.client.get('/api/auth/lark/callback/?code=auth-code&state=valid-state')
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertTrue(response['Location'].startswith('http://frontend.test/login#access='))
        user = User.objects.get(lark_union_id='union-new-user')
        self.assertEqual(user.role, self.tester_role)
        self.assertEqual(user.created_via, 'lark_sso')

        # The same browser session should bypass the Lark authorization page next time.
        response = self.client.get('/api/auth/lark/login/')
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertTrue(response['Location'].startswith('http://frontend.test/login#access='))

    def test_lark_provision_binds_existing_manual_user_by_email(self):
        from .views import provision_lark_user
        manual = User.objects.create_user(username='manual-user', password='password123', name='原姓名', email='manual@example.com', role=self.tester_role)
        user = provision_lark_user({'union_id': 'union-manual-user', 'open_id': 'open-manual-user', 'name': 'Lark 姓名', 'email': 'manual@example.com'})
        self.assertEqual(user.id, manual.id)
        self.assertEqual(user.lark_union_id, 'union-manual-user')
        self.assertEqual(user.name, 'Lark 姓名')

    def test_lark_callback_rejects_invalid_state(self):
        self.client.force_authenticate(None)
        response = self.client.get('/api/auth/lark/callback/?code=auth-code&state=invalid-state')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

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

    def test_dashboard_requires_home_view_permission(self):
        user = User.objects.create_user(
            username='no-home-user', password='SafePass@123', name='无首页权限用户',
            role=self.tester_role,
        )
        self.client.force_authenticate(user)
        response = self.client.get('/api/dashboard/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

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

    def test_response_variable_replacement_supports_array_object_paths(self):
        variables = {'lobbies': [{'id': 123, 'name': 'main'}]}
        self.assertEqual(
            replace_response_variables({'lobby_id': '${lobbies[0].id}'}, variables),
            {'lobby_id': 123},
        )
        self.assertEqual(
            replace_response_variables({'label': 'lobby=${lobbies[0].name}'}, variables),
            {'label': 'lobby=main'},
        )

    def test_parameterized_request_values_are_generated_and_replaced(self):
        with patch('platform_api.services.timezone.now', return_value=datetime(2026, 8, 4, 10, 30, tzinfo=timezone.get_current_timezone())):
            variables = build_parameter_variables([
                {'name': 'personName', 'type': 'name'},
                {'name': 'mobile', 'type': 'phone'},
                {'name': 'email', 'type': 'custom', 'value': 'fixed@example.com'},
                {'name': 'bizDate', 'type': 'time', 'time_format': 'date', 'time_offset': 3},
                {'name': 'bizMonth', 'type': 'time', 'time_format': 'year_month', 'time_offset': -35},
            ])
        rendered = replace_parameter_variables(
            {'body': {'name': '{{personName}}', 'phone': '{{mobile}}', 'note': 'mail={{email}}', 'date': '{{bizDate}}', 'month': '{{bizMonth}}'}},
            variables,
        )
        self.assertEqual(rendered['body']['name'], variables['personName'])
        self.assertRegex(rendered['body']['phone'], r'^1[3-9]\d{9}$')
        self.assertEqual(rendered['body']['note'], 'mail=fixed@example.com')
        self.assertEqual(rendered['body']['date'], '2026-08-07')
        self.assertEqual(rendered['body']['month'], '2026-06')
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

    def test_get_brazil_id_returns_valid_cpf_format(self):
        from platform_api.data_factory.account_add import get_brazil_id

        def check_digit(values, start_weight):
            total = sum(value * weight for value, weight in zip(values, range(start_weight, 1, -1)))
            remainder = (total * 10) % 11
            return 0 if remainder == 10 else remainder

        cpf = get_brazil_id()
        self.assertRegex(cpf, r'^\d{3}\.\d{3}\.\d{3}-\d{2}$')
        digits = [int(ch) for ch in cpf if ch.isdigit()]
        self.assertEqual(len(digits), 11)
        self.assertNotEqual(len(set(digits[:9])), 1)
        self.assertEqual(digits[9], check_digit(digits[:9], 10))
        self.assertEqual(digits[10], check_digit(digits[:10], 11))

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
        self.assertNotIn('platform_account', response.data['data'])

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

    def test_current_user_environment_accounts_are_isolated_and_can_be_saved(self):
        default_package = EnvironmentPackage.objects.create(name='默认账号环境包')
        secondary_package = EnvironmentPackage.objects.create(name='备用账号环境包')
        default_environment = Environment.objects.create(
            name='默认账号环境', base_url='https://default.example.com', is_default=True, package=default_package,
        )
        secondary_environment = Environment.objects.create(
            name='备用账号环境', base_url='https://secondary.example.com', package=secondary_package,
        )
        other_user = User.objects.create_user(
            username='other-user', password='SafePass@123', name='其他用户', role=self.tester_role,
        )
        UserEnvironmentAccount.objects.create(
            user=other_user, environment=default_environment, account='other-account',
        )

        response = self.client.get('/api/me/environment-accounts/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['data'], {
            'accounts': [],
            'environment_packages': [
                {'id': secondary_package.id, 'name': '备用账号环境包', 'environments': [
                    {'id': secondary_environment.id, 'name': '备用账号环境'},
                ]},
                {'id': default_package.id, 'name': '默认账号环境包', 'environments': [
                    {'id': default_environment.id, 'name': '默认账号环境'},
                ]},
            ],
        })

        response = self.client.put('/api/me/environment-accounts/', {
            'accounts': [
                {'environment_id': default_environment.id, 'account': 'default-account'},
                {'environment_id': secondary_environment.id, 'account': 'secondary-account'},
            ],
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            UserEnvironmentAccount.objects.get(user=self.admin, environment=default_environment).account,
            'default-account',
        )
        self.assertEqual(
            UserEnvironmentAccount.objects.get(user=self.admin, environment=secondary_environment).account,
            'secondary-account',
        )
        self.assertEqual(
            UserEnvironmentAccount.objects.get(user=other_user, environment=default_environment).account,
            'other-account',
        )
        self.assertEqual(response.data['data']['accounts'], [
            {'environment_id': default_environment.id, 'environment_name': '默认账号环境', 'environment_package_id': default_package.id, 'environment_package_name': '默认账号环境包', 'account': 'default-account'},
            {'environment_id': secondary_environment.id, 'environment_name': '备用账号环境', 'environment_package_id': secondary_package.id, 'environment_package_name': '备用账号环境包', 'account': 'secondary-account'},
        ])

    def test_user_can_be_created_without_email(self):
        response = self.client.post('/api/users/', {
            'username': 'tester_without_email', 'name': '无邮箱用户',
            'password': 'SafePass@123', 'role': 'tester',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['data']['email'], '')

    def test_user_status_requires_and_uses_dedicated_permission(self):
        status_role = Role.objects.create(name='状态管理员', code='status_manager', permissions=['users.status'])
        operator = User.objects.create_user(username='status-operator', password='SafePass@123', name='状态管理员', role=status_role)
        target = User.objects.create_user(username='status-target', password='SafePass@123', name='待停用用户', role=self.tester_role)
        self.client.force_authenticate(operator)
        response = self.client.post(f'/api/users/{target.id}/toggle-status/', {'is_active': False}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['data']['is_active'])

    def test_data_factory_order_operations_require_separate_permissions(self):
        role = Role.objects.create(name='订单操作员', code='order_operator', permissions=[])
        operator = User.objects.create_user(username='order-operator', password='SafePass@123', name='订单操作员', role=role)
        self.client.force_authenticate(operator)
        operations = [
            ('data_factory.order_result_push', '/api/data-factory/order-result-push/'),
            ('data_factory.rollback_settlement', '/api/data-factory/rollback-settlement/'),
            ('data_factory.bet_cancel', '/api/data-factory/bet-cancel/'),
            ('data_factory.rollback_bet_cancel', '/api/data-factory/rollback-bet-cancel/'),
        ]
        for permission, path in operations:
            with self.subTest(permission=permission):
                role.permissions = [permission]
                role.save(update_fields=['permissions'])
                allowed_response = self.client.post(path, {}, format='json')
                self.assertEqual(allowed_response.status_code, status.HTTP_400_BAD_REQUEST)
                role.permissions = []
                role.save(update_fields=['permissions'])
                denied_response = self.client.post(path, {}, format='json')
                self.assertEqual(denied_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_data_factory_member_query_requires_dedicated_permission(self):
        role = Role.objects.create(name='会员查询员', code='member_query_operator', permissions=[])
        operator = User.objects.create_user(username='member-query-operator', password='SafePass@123', name='会员查询员', role=role)
        self.client.force_authenticate(operator)

        denied_response = self.client.post('/api/data-factory/member-query/', {}, format='json')
        self.assertEqual(denied_response.status_code, status.HTTP_403_FORBIDDEN)

        role.permissions = ['data_factory.member_query']
        role.save(update_fields=['permissions'])
        allowed_response = self.client.post('/api/data-factory/member-query/', {}, format='json')
        self.assertEqual(allowed_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_data_factory_member_status_activate_requires_dedicated_permission(self):
        role = Role.objects.create(name='用户状态管理员', code='member_status_operator', permissions=[])
        operator = User.objects.create_user(username='member-status-operator', password='SafePass@123', name='用户状态管理员', role=role)
        self.client.force_authenticate(operator)

        denied_response = self.client.post('/api/data-factory/member-status-activate/', {}, format='json')
        self.assertEqual(denied_response.status_code, status.HTTP_403_FORBIDDEN)

        role.permissions = ['data_factory.member_status_activate']
        role.save(update_fields=['permissions'])
        allowed_response = self.client.post('/api/data-factory/member-status-activate/', {}, format='json')
        self.assertEqual(allowed_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_data_factory_environment_list_uses_tool_permission_and_hides_variables(self):
        Environment.objects.create(
            name='工具环境', base_url='https://tool.example.com', login_url='https://tool.example.com/login',
            variables=[{'key': 'SECRET_TOKEN', 'value': 'secret-value'}],
        )
        role = Role.objects.create(name='数据工具员', code='data_tool_operator', permissions=['data_factory.member_status_activate'])
        operator = User.objects.create_user(username='data-tool-operator', password='SafePass@123', name='数据工具员', role=role)
        self.client.force_authenticate(operator)
        response = self.client.get('/api/data-factory/environments/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['data'][0]['variables'], [])
        self.assertNotIn('secret-value', str(response.data))

    @patch('platform_api.views.query_member_by_email', return_value={
        'environment_name': 'helix',
        'email': 'colin7672@proton.me',
        'uid': '21181393-7bc4-4eb1-b4f1-80eae482fcbe',
        'cpf': '31751198243',
        'member_id': '407361968781922304',
        'nickname': 'User442106',
    })
    def test_data_factory_member_query_returns_selected_environment_and_sanitized_fields(self, mocked_query_member):
        package = EnvironmentPackage.objects.create(name='用户查询环境包')
        environment = Environment.objects.create(
            name='查询后台环境', base_url='https://tool.example.com', login_url='https://tool.example.com/login', package=package,
        )

        response = self.client.post('/api/data-factory/member-query/', {
            'environment_package': package.id,
            'keyword': 'Colin7672@Proton.me',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mocked_query_member.assert_called_once_with('Colin7672@Proton.me', environment_name='查询后台环境')
        self.assertEqual(response.data['data']['member_id'], '407361968781922304')
        self.assertEqual(response.data['data']['uid'], '21181393-7bc4-4eb1-b4f1-80eae482fcbe')
        self.assertNotIn('password', str(response.data).lower())
        execution = DataFactoryExecution.objects.get(tool_name='查询用户信息', email='Colin7672@Proton.me')
        self.assertEqual(execution.environment, environment)
        self.assertEqual(execution.member_id, '407361968781922304')

    @patch('platform_api.views.activate_member_status', return_value={
        'environment_name': 'helix',
        'member_id': '402349924005449728',
        'affected_rows': 1,
        'status': 'passed',
        'message': '用户状态已激活，影响行数 1',
    })
    def test_data_factory_member_status_activate_returns_selected_environment_and_records_execution(self, mocked_activate_member_status):
        package = EnvironmentPackage.objects.create(name='状态激活环境包')
        environment = Environment.objects.create(
            name='状态激活后台环境', base_url='https://tool.example.com', login_url='https://tool.example.com/login', package=package,
        )

        response = self.client.post('/api/data-factory/member-status-activate/', {
            'environment_package': package.id,
            'email': 'member@example.com',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mocked_activate_member_status.assert_called_once_with('member@example.com', environment_name='状态激活后台环境')
        self.assertEqual(response.data['data']['member_id'], '402349924005449728')
        self.assertEqual(response.data['data']['affected_rows'], 1)
        self.assertNotIn('password', str(response.data).lower())
        execution = DataFactoryExecution.objects.get(tool_name='用户状态激活', email='member@example.com')
        self.assertEqual(execution.environment, environment)
        self.assertEqual(execution.message, '用户状态已激活，影响行数 1')

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
            'permissions': ['home.view', 'automation.view', 'data_factory.account_add', 'data_factory.member_query', 'data_factory.member_status_activate', 'home.view']
        }, format='json')
        self.assertEqual(response.data['data']['permissions'], ['home.view', 'automation.view', 'data_factory.account_add', 'data_factory.member_query', 'data_factory.member_status_activate'])

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
        self.set_environment_account(environment, 'frontend-account')
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
            {'identifier': 'frontend-account', 'secret': target_password},
        )
        self.assertEqual(response.data['data']['execution_details'][0]['request_params'], {'identifier': 'frontend-account'})
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
        self.set_environment_account(environment)

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

    @override_settings(DATA_FACTORY_BACKEND_ACCOUNT='factory-account', DATA_FACTORY_BACKEND_PASSWORD='factory-password')
    @patch('platform_api.views.execute_account_balance', return_value={
        'member_id': 'member-1', 'adjustment_id': 'adjustment-1',
    })
    def test_data_factory_uses_configured_platform_credentials(self, mocked_execute):
        package = EnvironmentPackage.objects.create(name='余额工具环境包')
        environment = Environment.objects.create(
            name='后台工具环境', base_url='https://admin.example.com',
            login_url='https://admin.example.com/auth/login', package=package,
        )
        response = self.client.post('/api/data-factory/account-balance/', {
            'environment_package': package.id,
            'email': 'member@example.com',
            'amount': 10,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mocked_execute.assert_called_once_with(
            environment.id, 'member@example.com', Decimal('10'),
        )

    @patch('platform_api.views.execute_account_balance', side_effect=ValueError('boom'))
    def test_data_factory_account_balance_unexpected_error_returns_400(self, mocked_execute):
        package = EnvironmentPackage.objects.create(name='余额工具异常环境包')
        environment = Environment.objects.create(
            name='后台工具环境异常', base_url='https://admin.example.com',
            login_url='https://admin.example.com/auth/login', package=package,
        )
        response = self.client.post('/api/data-factory/account-balance/', {
            'environment_package': package.id,
            'email': 'member@example.com',
            'amount': 10,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('boom', str(response.data))
        mocked_execute.assert_called_once()

    def test_data_factory_account_balance_requires_backend_environment_in_package(self):
        package = EnvironmentPackage.objects.create(name='仅前台环境包')
        Environment.objects.create(name='仅前台环境', base_url='https://web.example.com', package=package)
        response = self.client.post('/api/data-factory/account-balance/', {
            'environment_package': package.id,
            'email': 'member@example.com',
            'amount': 10,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('未配置后台环境', str(response.data))

    @patch('platform_api.views.bet_cancel', return_value={
        'event_id': 'sr:match:66886868',
        'key': 'sr:match:66886868',
        'timestamp': 1784601930281,
        'status_code': 200,
        'message': 'HTTP 200 · 断言通过',
        'response': '{"ok":true}',
        'payload': {
            'partition': 0,
            'key': 'sr:match:66886868',
            'content': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n<bet_cancel start_time="" end_time="" product="3" event_id="sr:match:66886868" timestamp="1784601930281"><market void_reason="4" id="1" specifiers="goalnr=2"/>\r\n</bet_cancel>',
            'keySerde': 'String',
            'valueSerde': 'String',
        },
    })
    def test_data_factory_bet_cancel_uses_optional_fields(self, mocked_execute):
        environment = Environment.objects.create(
            name='取消测试环境', base_url='https://admin.example.com',
            login_url='https://admin.example.com/auth/login',
        )
        response = self.client.post('/api/data-factory/bet-cancel/', {
            'product': 3,
            'event_id': 'sr:match:66886868',
            'market_id': 1,
            'specifiers': 'goalnr=2',
            'start_time': '',
            'end_time': '',
            'timestamp': 1784601930281,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mocked_execute.assert_called_once_with(
            product='3',
            event_id='sr:match:66886868',
            market_id='1',
            specifiers='goalnr=2',
            start_time='',
            end_time='',
            timestamp=1784601930281,
        )
        execution = DataFactoryExecution.objects.get(tool_name='取消', email='sr:match:66886868')
        self.assertEqual(execution.status, 'passed')
        self.assertIn('product=3', execution.message)
        self.assertIn('specifiers=goalnr=2', execution.message)

    @patch('platform_api.views.rollback_bet_cancel', return_value={
        'event_id': 'sr:match:66886868',
        'key': 'sr:match:66886868',
        'timestamp': 1784602930291,
        'status_code': 200,
        'message': 'HTTP 200 · 断言通过',
        'response': '{"ok":true}',
        'payload': {
            'partition': 0,
            'key': 'sr:match:66886868',
            'content': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n<rollback_bet_cancel start_time="" end_time="" product="3" event_id="sr:match:66886868" timestamp="1784602930291"><market id="1" specifiers="goalnr=2"/>\r\n</rollback_bet_cancel>',
            'keySerde': 'String',
            'valueSerde': 'String',
        },
    })
    def test_data_factory_rollback_bet_cancel_uses_optional_fields(self, mocked_execute):
        Environment.objects.create(
            name='回滚取消测试环境', base_url='https://admin.example.com',
            login_url='https://admin.example.com/auth/login',
        )
        response = self.client.post('/api/data-factory/rollback-bet-cancel/', {
            'product': 3,
            'event_id': 'sr:match:66886868',
            'market_id': 1,
            'specifiers': 'goalnr=2',
            'start_time': '',
            'end_time': '',
            'timestamp': 1784602930291,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mocked_execute.assert_called_once_with(
            product='3',
            event_id='sr:match:66886868',
            market_id='1',
            specifiers='goalnr=2',
            start_time='',
            end_time='',
            timestamp=1784602930291,
        )
        execution = DataFactoryExecution.objects.get(tool_name='回滚取消', email='sr:match:66886868')
        self.assertEqual(execution.status, 'passed')
        self.assertIn('product=3', execution.message)
        self.assertIn('specifiers=goalnr=2', execution.message)

    @patch('platform_api.data_factory.account_balance.execute_platform_login')
    def test_data_factory_account_balance_uses_login_encoding_keyword(self, mocked_login):
        environment = Environment.objects.create(
            name='后台工具环境登录参数', base_url='https://admin.example.com',
            login_url='https://admin.example.com/auth/login',
        )
        mocked_login.return_value = type('LoginResult', (), {'access_token': '', 'message': ''})()
        from platform_api.data_factory.account_balance import DataFactoryError, execute_account_balance
        with self.assertRaises(DataFactoryError):
            with override_settings(DATA_FACTORY_BACKEND_ACCOUNT='factory-account', DATA_FACTORY_BACKEND_PASSWORD='factory-password'):
                execute_account_balance(environment.id, 'member@example.com', Decimal('10'))
        mocked_login.assert_called_once()
        self.assertEqual(mocked_login.call_args.kwargs['account'], 'factory-account')
        self.assertEqual(mocked_login.call_args.kwargs['password'], 'factory-password')
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
        package = EnvironmentPackage.objects.create(name='账户添加环境包')
        frontend_environment = Environment.objects.create(
            name='账户添加前台环境', base_url='https://api-test.helix.city',
            login_url='', package=package,
        )
        backend_environment = Environment.objects.create(
            name='账户添加后台环境', base_url='https://mgt-api-test.helix.city',
            login_url='https://mgt-api-test.helix.city/api/v2/login',
            variables=[{'key': 'userName', 'value': '用户名'}, {'key': 'password', 'value': '密码'}],
            package=package,
        )
        response = self.client.post('/api/data-factory/account-add/', {
            'environment_package': package.id,
            'email': '',
            'amount': 10,
            'quantity': 3,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data['data']['status'], 'running')
        mocked_on_commit.assert_called_once()
        mocked_execute.assert_called_once_with(
            frontend_environment.id, backend_environment.id, '', Decimal('10'), 3,
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
        self.set_environment_account(environment)

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
        self.set_environment_account(environment, 'target-backend-account')

        execute_task(task, self.admin, 'Aibet@123456')

        login_request = mocked_urlopen.call_args_list[0].args[0]
        login_body = login_request.data.decode('utf-8')
        self.assertIn('multipart/form-data; boundary=', login_request.get_header('Content-type'))
        self.assertIn('name="userName"\r\n\r\ntarget-backend-account', login_body)
        self.assertIn('name="password"\r\n\r\nAibet@123456', login_body)
        login_result = AutomationTaskResult.objects.get(task=task, interface_name='系统登录')
        self.assertEqual(login_result.request_params, {'userName': 'target-backend-account'})
        api_request = mocked_urlopen.call_args_list[1].args[0]
        self.assertEqual(api_request.get_header('X-token'), 'test-token')
        self.assertIsNone(api_request.get_header('Authorization'))

    def test_task_requires_environment_account(self):
        module, _ = AutomationModule.objects.get_or_create(app='backend', name='后台', defaults={'sort_order': 1})
        environment = Environment.objects.create(
            name='缺少平台账号后台环境', base_url='https://admin.example.com',
            login_url='https://admin.example.com/auth/login',
        )
        task = AutomationTask.objects.create(
            name='后台账号校验', task_type='api', environment=environment, owner=self.admin,
        )
        task.modules.add(module)

        results = execute_task(task, self.admin, 'Aibet@123456')

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, 'failed')
        self.assertIn('当前用户未配置环境“缺少平台账号后台环境”的目标系统账号', results[0].response_message)

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
        self.set_environment_account(environment)

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
        self.set_environment_account(environment)

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
        self.set_environment_account(environment)

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
        self.set_environment_account(environment)

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
        self.set_environment_account(environment)

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
        environment = Environment.objects.create(
            name='监控环境', base_url='https://monitor.example.com',
            login_url='https://monitor.example.com/api/auth/login/',
        )
        self.set_environment_account(environment)
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
            'name': '按接口名称创建任务', 'module_name': '个人中心', 'api_type': 'VIP 等级',
            'environment': environment.id, 'interval_value': 1,
            'interval_unit': 'minute', 'enabled': True,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['data']['api_config_ids'], [config_id])
        self.assertEqual(response.data['data']['automation_interface_ids'], [interface.id])

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

        response = self.client.post(
            f'/api/monitor/tasks/{task_id}/run/',
            {'login_password': 'target-login-pass'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['data']['status'], 'failed')
        self.assertEqual(response.data['data']['interface_total'], 4)
        self.assertEqual(response.data['data']['failure_count'], 1)
        self.assertEqual(response.data['data']['details'][0]['interface_name'], '系统登录')
        detail = MonitorExecutionDetail.objects.get(execution_id=response.data['data']['id'], source_api_config_id=config_id, source_interface_id=failed_interface.id)
        automation_detail = MonitorExecutionDetail.objects.get(execution_id=response.data['data']['id'], source_api_config_id=None, source_interface_id=interface.id)
        self.assertEqual(detail.url, 'https://monitor.example.com/api/v1/vip/benefits')
        self.assertEqual(automation_detail.url, 'https://monitor.example.com/api/v1/vip/levels')
        self.assertEqual(MonitorAlarm.objects.filter(task_id=task_id, status='open').count(), 1)

        failed_interface.path = '/api/v1/vip/benefits/latest'
        failed_interface.assertions = {'status_code': 200, 'timeout_seconds': 3}
        failed_interface.save(update_fields=['path', 'assertions'])
        response = self.client.post(
            f'/api/monitor/execution-details/{detail.id}/retry/',
            {'login_password': 'target-login-pass'}, format='json',
        )
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

    def test_monitor_task_uses_matching_environment_from_selected_package(self):
        package = EnvironmentPackage.objects.create(name='监控任务环境包')
        frontend_environment = Environment.objects.create(
            name='监控前台环境', base_url='https://monitor-frontend.example.com', package=package,
        )
        backend_environment = Environment.objects.create(
            name='监控后台环境', base_url='https://monitor-backend.example.com', package=package,
        )
        frontend_interface = ApiInterface.objects.create(
            name='前台监控接口', method='GET', path='/api/frontend/health', module_name='个人中心',
            headers={}, request_params={}, assertions={}, can_execute_in_task=True, created_by=self.admin,
        )
        backend_interface = ApiInterface.objects.create(
            name='后台监控接口', method='GET', path='/api/backend/health', module_name='后台',
            headers={}, request_params={}, assertions={}, can_execute_in_task=True, created_by=self.admin,
        )

        frontend_response = self.client.post('/api/monitor/tasks/', {
            'name': '前台环境包监控任务', 'api_type': frontend_interface.name,
            'environment_package': package.id, 'interval_value': 1,
            'interval_unit': 'minute', 'enabled': True,
        }, format='json')
        self.assertEqual(frontend_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(frontend_response.data['data']['environment'], frontend_environment.id)

        backend_response = self.client.post('/api/monitor/tasks/', {
            'name': '后台环境包监控任务', 'api_type': backend_interface.name,
            'environment_package': package.id, 'interval_value': 1,
            'interval_unit': 'minute', 'enabled': True,
        }, format='json')
        self.assertEqual(backend_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(backend_response.data['data']['environment'], backend_environment.id)

    def test_monitor_task_rejects_package_when_source_interfaces_span_apps(self):
        package = EnvironmentPackage.objects.create(name='跨端监控任务环境包')
        Environment.objects.create(
            name='跨端监控前台环境', base_url='https://cross-frontend.example.com', package=package,
        )
        Environment.objects.create(
            name='跨端监控后台环境', base_url='https://cross-backend.example.com', package=package,
        )
        frontend_interface = ApiInterface.objects.create(
            name='跨端前台来源接口', method='GET', path='/api/frontend/health', module_name='个人中心',
            headers={}, request_params={}, assertions={}, created_by=self.admin,
        )
        backend_interface = ApiInterface.objects.create(
            name='跨端后台来源接口', method='GET', path='/api/backend/health', module_name='后台',
            headers={}, request_params={}, assertions={}, created_by=self.admin,
        )
        MonitorApiConfig.objects.create(
            name='跨端监控接口', method='GET', path='/api/health', module_name='',
            source_interface=frontend_interface,
            source_interface_ids=[frontend_interface.id, backend_interface.id],
            headers={}, request_params={}, assertions={}, created_by=self.admin,
        )

        response = self.client.post('/api/monitor/tasks/', {
            'name': '跨端环境包监控任务', 'api_type': '跨端监控接口',
            'environment_package': package.id, 'interval_value': 1,
            'interval_unit': 'minute', 'enabled': True,
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['message'], '监控接口必须归属同一所属端')

    def test_business_models_have_chinese_table_comments(self):
        models = [Role, User, Environment, AutomationModule, ApiInterface, AutomationTask, AutomationTaskResult, MonitorApiConfig, MonitorTask, MonitorExecution, MonitorExecutionDetail, MonitorAlarm]
        for model in models:
            self.assertTrue(model._meta.db_table.startswith('aibet_'))
            self.assertTrue(model._meta.db_table_comment)
