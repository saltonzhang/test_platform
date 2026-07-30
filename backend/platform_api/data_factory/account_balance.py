import base64
import json
from datetime import timedelta
from urllib.parse import urlencode, urljoin

from django.utils import timezone

from ..executor import api_request_executor
from ..models import Environment
from ..services import get_login_parameter_names, target_login_failure_message


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


def _token_user_id(token):
    try:
        payload = token.split('.')[1] + '=='
        data = json.loads(base64.urlsafe_b64decode(payload).decode('utf-8'))
        return str(data.get('ID') or data.get('id') or data.get('userId') or '')
    except (IndexError, TypeError, ValueError, UnicodeDecodeError):
        return ''


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


def execute_account_balance(operator, password, environment_id, email, amount):
    environment = Environment.objects.filter(pk=environment_id).first()
    if not environment or not environment.login_url:
        raise DataFactoryError('请选择已配置后台登录地址的运行环境')
    if not operator.username:
        raise DataFactoryError('当前用户未配置后台账号')
    account_key, password_key = get_login_parameter_names(environment)
    login = api_request_executor.execute(
        url=environment.login_url,
        method='POST',
        headers={'Content-Type': 'multipart/form-data'},
        request_params={account_key: operator.username, password_key: password},
        assertions={'status_code': 200, 'timeout_seconds': 10},
        login_url=environment.login_url,
        request_encoding='multipart',
    )
    if not login.access_token:
        raise DataFactoryError(target_login_failure_message(login.message))

    headers = {'Accept': 'application/json, text/plain, */*', 'X-Token': '', 'Content-Type': 'application/json'}
    user_id = _token_user_id(login.access_token)
    if user_id:
        headers['X-User-Id'] = user_id

    def call(path, method='GET', params=None, query=None):
        outcome = api_request_executor.execute(
            url=_url(environment, path, query), method=method, headers=headers,
            request_params=params or {}, assertions={'status_code': 200, 'timeout_seconds': 15},
            access_token=login.access_token,
        )
        return _read_json(outcome)

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
