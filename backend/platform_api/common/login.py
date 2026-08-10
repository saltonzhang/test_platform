import base64
import json

from ..executor import api_request_executor
from ..models import UserEnvironmentAccount


def get_user_environment_account(user, environment):
    """Return the target-system account configured for a platform user/environment."""
    if not user or not environment:
        return ''
    return (
        UserEnvironmentAccount.objects.filter(user=user, environment=environment)
        .values_list('account', flat=True)
        .first()
        or ''
    ).strip()


def get_login_parameter_names(environment):
    account_labels = {'账号', '用户名', '用户账号', '登录账号', '登录用户名', '账户', 'account', 'username'}
    password_labels = {'密码', '登录密码', 'password'}
    account_name = 'username'
    password_name = 'password'
    for variable in environment.variables or []:
        if not isinstance(variable, dict):
            continue
        name = str(variable.get('key', '')).strip()
        label = str(variable.get('value', '')).strip().lower()
        if not name:
            continue
        if label in account_labels:
            account_name = name
        elif label in password_labels:
            password_name = name
    if account_name == password_name:
        raise ValueError('环境配置中的登录账号参数名和密码参数名不能相同')
    return account_name, password_name


def target_login_failure_message(message):
    detail = str(message or '').strip()
    suffix = f' 原始信息：{detail}' if detail else ''
    return f'目标系统登录失败，请检查目标系统登录账号和密码。{suffix}'


def build_login_headers(login_encoding):
    return {'Content-Type': 'multipart/form-data'} if login_encoding == 'multipart' else {'Content-Type': 'application/json; charset=utf-8'}


def execute_platform_login(
    *,
    login_url,
    account,
    password,
    account_parameter,
    password_parameter,
    login_encoding='json',
    login_timeout_seconds=10,
):
    return api_request_executor.execute(
        url=login_url,
        method='POST',
        headers=build_login_headers(login_encoding),
        request_params={account_parameter: account, password_parameter: password},
        assertions={'status_code': 200, 'timeout_seconds': login_timeout_seconds},
        login_url=login_url,
        request_encoding=login_encoding,
    )


def extract_token_user_id(token):
    try:
        payload = token.split('.')[1] + '=='
        data = json.loads(base64.urlsafe_b64decode(payload).decode('utf-8'))
        return str(data.get('ID') or data.get('id') or data.get('userId') or '')
    except (IndexError, TypeError, ValueError, UnicodeDecodeError):
        return ''
