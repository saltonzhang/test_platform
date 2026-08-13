import json
from datetime import timedelta
from urllib.parse import urlencode, urljoin

from django.utils import timezone
from django.conf import settings

from ..executor import api_request_executor
from ..models import Environment
from ..common.login import execute_platform_login, extract_token_user_id, get_login_parameter_names, target_login_failure_message


class DataFactoryError(Exception):
    pass


def _url(environment, path, query=None):
    url = urljoin(f'{environment.base_url.rstrip("/")}/', path.lstrip('/'))
    if query:
        url = f'{url}?{urlencode(query, doseq=True)}'
    return url


def _data(payload):
    if not isinstance(payload, dict) or payload.get('code', 0) != 0:
        message = payload.get('msg') if isinstance(payload, dict) else ''
        raise DataFactoryError(message or '后台接口返回业务失败')
    return payload.get('data', {})


def _read_json(outcome):
    if outcome.status != 'passed':
        raise DataFactoryError(outcome.message)
    try:
        return _data(json.loads(outcome.response_log or '{}'))
    except (TypeError, ValueError) as exc:
        raise DataFactoryError('后台接口返回内容不是有效 JSON') from exc


def _member_id(data):
    if isinstance(data, list):
        for item in data:
            value = _member_id(item)
            if value:
                return value
    if isinstance(data, dict):
        value = data.get('id') or data.get('memberId')
        if value is not None:
            return str(value)
        for key in ('member', 'user', 'record', 'list', 'records', 'items'):
            if isinstance(data.get(key), (dict, list)):
                value = _member_id(data[key])
                if value:
                    return value
    return ''


def _latest_adjustment_id(data, member_id):
    rows = data if isinstance(data, list) else next((data.get(key, []) for key in ('list', 'records', 'items') if isinstance(data.get(key), list)), []) if isinstance(data, dict) else []
    for row in rows:
        if isinstance(row, dict) and str(row.get('memberId', member_id)) == str(member_id) and row.get('id') is not None:
            return str(row['id'])
    return ''


def get_data_factory_credentials(environment_type):
    """Return the configured credentials for the platform role used by a tool."""
    credentials = {
        'frontend': (settings.DATA_FACTORY_FRONTEND_ACCOUNT, settings.DATA_FACTORY_FRONTEND_PASSWORD),
        'backend': (settings.DATA_FACTORY_BACKEND_ACCOUNT, settings.DATA_FACTORY_BACKEND_PASSWORD),
    }
    account, password = credentials.get(environment_type, ('', ''))
    if not account or not password:
        names = {
            'frontend': 'DATA_FACTORY_FRONTEND_ACCOUNT 和 DATA_FACTORY_FRONTEND_PASSWORD',
            'backend': 'DATA_FACTORY_BACKEND_ACCOUNT 和 DATA_FACTORY_BACKEND_PASSWORD',
        }
        raise DataFactoryError(f'请配置 {names.get(environment_type, "有效的数据工厂环境账号密码")}')
    return account, password


def execute_account_balance(environment_id, email, amount, *, database_profile=None):
    environment = Environment.objects.filter(pk=environment_id).first()
    if not environment or not environment.login_url:
        raise DataFactoryError('请选择已配置后台登录地址的运行环境')
    account, password = get_data_factory_credentials('backend')
    try:
        account_key, password_key = get_login_parameter_names(environment)
    except ValueError as exc:
        raise DataFactoryError(str(exc)) from exc
    try:
        login = execute_platform_login(
            login_url=environment.login_url,
            account=account,
            password=password,
            account_parameter=account_key,
            password_parameter=password_key,
            login_encoding='multipart',
            login_timeout_seconds=10,
        )
    except Exception as exc:
        raise DataFactoryError(f'后台登录请求异常：{exc}') from exc
    if not login.access_token:
        raise DataFactoryError(target_login_failure_message(login.message))

    headers = {'Accept': 'application/json, text/plain, */*', 'X-Token': '', 'Content-Type': 'application/json'}
    user_id = extract_token_user_id(login.access_token)
    if user_id:
        headers['X-User-Id'] = user_id

    def call(path, method='GET', params=None, query=None):
        outcome = api_request_executor.execute(
            url=_url(environment, path, query), method=method, headers=headers,
            request_params=params or {}, assertions={'status_code': 200, 'timeout_seconds': 15},
            access_token=login.access_token,
        )
        return _read_json(outcome)

    try:
        member = call('/api/v2/member/find', query={'user': email.split('@', 1)[0]})
        member_id = _member_id(member)
        if not member_id:
            raise DataFactoryError('未找到该邮箱对应的 memberId')

        call('/api/v2/fundAdjustment/create', 'POST', {
            'accountType': 0, 'amount': float(amount), 'currency': 'BRL', 'memberId': member_id,
            'type': 104, 'agent': '', 'accountCode': 'Cash1', 'remark': 'autotest',
        })
        now = timezone.localtime()
        query = {
            'page': 1, 'pageSize': 50, 'timezone': '+08:00', 'memberId': member_id,
            'type': '-999', 'account': '-999', 'status': '-999',
            'requestTimeStart': (now - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S.000Z'),
            'requestTimeEnd': (now + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S.000Z'),
        }
        adjustment_id = _latest_adjustment_id(call('/api/v2/fundAdjustment/list', query=query), member_id)
        if not adjustment_id:
            raise DataFactoryError('加款单已创建，但未查询到可审批的最新单据')
        call('/api/v2/fundAdjustment/audit', 'POST', {'id': adjustment_id, 'remark': 'autotest', 'status': 1})
        return {'environment_name': environment.name, 'email': email, 'member_id': member_id, 'amount': str(amount), 'adjustment_id': adjustment_id, 'status': 'approved'}
    except DataFactoryError:
        raise
    except Exception as exc:
        raise DataFactoryError(f'账户余额执行异常：{exc}') from exc
