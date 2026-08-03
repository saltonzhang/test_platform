import json
import re
import time
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlencode, urljoin, urlsplit

import requests
import urllib3
from django.utils import timezone

from ..common.database import DatabaseClient, query_one
from ..common.login import execute_platform_login, extract_token_user_id, get_login_parameter_names, target_login_failure_message
from ..executor import api_request_executor
from ..models import Environment
from .account_balance import DataFactoryError, execute_account_balance


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _url(base_url, path, query=None):
    url = urljoin(f'{str(base_url).rstrip("/")}/', str(path).lstrip('/'))
    if query:
        url = f'{url}?{urlencode(query, doseq=True)}'
    return url


def _root_url(url):
    parsed = urlsplit(str(url))
    return f'{parsed.scheme}://{parsed.netloc}' if parsed.scheme and parsed.netloc else str(url).rstrip('/')


def check_member_exists(email):
    if not email:
        return None
    try:
        row = query_one('SELECT id FROM member WHERE email = %s LIMIT 1', (email,))
        return row['id'] if row else None
    except Exception as exc:
        print(f'❌ 查询账号是否存在时出错: {exc}')
        return None


def query_kyc_info_from_db(email):
    try:
        with DatabaseClient() as db:
            member_row = db.query_one('SELECT id, uuid FROM member WHERE email = %s LIMIT 1', (email,))
            if not member_row:
                print(f'❌ 数据库 member 表未查到账号: {email}')
                return None, None, None, None

            member_id = member_row['id']
            uuid = member_row['uuid']
            #print(f'✅ 查找到用户 member_id: {member_id}, uuid: {uuid}')

            kyc_row = db.query_one(
                '''
                    SELECT serasa_validation_id, request_payload
                    FROM kyc_record
                    WHERE user_id = %s
                    ORDER BY id DESC LIMIT 1
                ''',
                (uuid,),
            )
        if not kyc_row:
            print(f'❌ 数据库 kyc_record 表未查到 user_id = {uuid} 的记录')
            return member_id, uuid, None, None

        serasa_validation_id = kyc_row['serasa_validation_id']
        request_payload_raw = kyc_row['request_payload']
        document_cpf = None
        if request_payload_raw:
            payload_data = json.loads(request_payload_raw) if isinstance(request_payload_raw, str) else request_payload_raw
            for item in payload_data.get('formFieldsRequest', []):
                if item.get('formField') == 'CPF':
                    document_cpf = item.get('value')
                    break

        return member_id, uuid, serasa_validation_id, document_cpf
    except Exception as exc:
        print(f'❌ 数据库查询出错: {exc}')
        return None, None, None, None


def get_brazil_id():
    url = 'https://www.shenfendaquan.com/Index/index/ba_xi_ren_shen_fen_sheng_cheng'
    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36'
        )
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        match = re.search(r'\d{3}\.\d{3}\.\d{3}-\d{2}', response.text)
        if match:
            return match.group(0)
        raise ValueError('未匹配到 CPF 格式')
    except Exception as exc:
        print(f'❌ 获取 CPF 失败: {exc}')
        return None


def extract_token_str(res_json, response_headers):
    token_candidate = ''
    if isinstance(res_json, dict):
        token_candidate = api_request_executor.extract_access_token(json.dumps(res_json, ensure_ascii=False))
    if not token_candidate:
        token_candidate = (
            response_headers.get('Authorization')
            or response_headers.get('authorization')
            or response_headers.get('X-Token')
            or response_headers.get('x-token')
            or response_headers.get('X-Access-Token')
            or response_headers.get('x-access-token')
            or ''
        )
    if not token_candidate:
        print('❌ 未提取到有效的字符串 Token')
        return ''
    return str(token_candidate)


def _response_message(res_json, fallback=''):
    if isinstance(res_json, dict):
        for key in ('msg', 'message', 'error', 'detail'):
            value = res_json.get(key)
            if value not in (None, ''):
                return str(value)
        data = res_json.get('data')
        if isinstance(data, dict):
            for key in ('msg', 'message', 'error', 'detail'):
                value = data.get(key)
                if value not in (None, ''):
                    return str(value)
    return str(fallback or '').strip()[:300]


def _login_registered_account(environment, email, password):
    login_url = getattr(environment, 'login_url', '') or _url(
        getattr(environment, 'base_url', ''), '/api/v1/auth/login',
    )
    if not login_url:
        return '', '前台环境未配置登录地址'
    try:
        account_parameter, password_parameter = get_login_parameter_names(environment)
        login = execute_platform_login(
            login_url=login_url,
            account=email,
            password=password,
            account_parameter=account_parameter,
            password_parameter=password_parameter,
            login_encoding='json',
            login_timeout_seconds=10,
        )
    except Exception as exc:
        return '', f'注册后登录请求异常：{exc}'
    if not login.access_token:
        return '', f'注册后登录失败：{_response_message({}, login.message)}'
    return str(login.access_token), ''


def extract_login_user_id(response_log, token):
    try:
        payload = json.loads(response_log or '{}')
        data = payload.get('data', payload)
        if isinstance(data, dict):
            user_id = data.get('userId') or data.get('id')
            if not user_id and isinstance(data.get('user'), dict):
                user_id = data['user'].get('id')
            if user_id:
                return str(user_id)
    except Exception:
        pass
    return extract_token_user_id(token)


def get_kyc_url(environment, token):
    print('\n================ [获取 KYC URL 认证接口] ================')
    kyc_api_url = _url(getattr(environment, 'base_url', ''), '/api/v1/member/getKycUrl')
    current_ts = int(time.time())

    headers = {
        'accept': 'application/json, text/plain, */*',
        'authorization': token,
        'origin': 'https://matchday.helix.city',
        'referer': 'https://matchday.helix.city/',
        'user-agent': (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36'
        ),
        'x-chan': '0',
        'x-device-id': '18b225ed-c2e0-4fa3-b821-966271680942',
        'x-lang': 'en',
        'x-nonce': '4wMqKl',
        'x-platform': 'WEB',
        'x-signature': 'c8ec480b3b970e5d1085f2d6727f088434224db6a0084c4f1d16b4d9319c1db4',
        'x-timestamp': str(current_ts),
        'x-trace': '{"gaid":"1895362410.1774335438"}',
        'x-ver': '0.2.277',
    }

    try:
        response = requests.get(kyc_api_url, headers=headers, timeout=10)
        print(f'KYC 请求 HTTP 状态码: {response.status_code}')
        print(f'KYC 响应数据: {response.text}')
    except Exception as exc:
        raise DataFactoryError(f'KYC 认证请求失败：{exc}') from exc

    try:
        kyc_json = response.json()
    except ValueError:
        kyc_json = None
    kyc_code = kyc_json.get('code') if isinstance(kyc_json, dict) else None
    kyc_failed = kyc_code not in (None, True, 0, '0', 200, '200', 201, '201')
    if not 200 <= response.status_code < 300 or kyc_failed:
        message = _response_message(kyc_json, f'HTTP {response.status_code}')
        raise DataFactoryError(f'KYC 认证失败：{message or f"HTTP {response.status_code}"}')


def trigger_face_verification_webhook(protocol, document, email):
    print('\n================ [调用 Webhook 完成人脸认证] ================')
    webhook_url = 'https://webhook-test.matchday.ink/tobapi/v1/kyc/serasaexperian'
    payload = {
        'protocol': protocol,
        'document': document,
        'status': 'CONCLUIDO',
        'result': 'SEM RISCO APARENTE',
        'alerts': ['FOTO DO CLIENTE'],
        'userInformation': {
            'fullName': 'Joao Jose Nascimento Dos Santos',
            'gender': 'M',
            'birthDate': '1990-01-01',
            'nationality': 'BRASILEIRO',
            'email': email,
            'phone': {'areaCode': '11', 'number': '999999999'},
        },
    }
    headers = {'Content-Type': 'application/json'}
    print(f'🚀 Webhook 请求参数:\n{json.dumps(payload, indent=2, ensure_ascii=False)}')
    try:
        response = requests.post(webhook_url, headers=headers, json=payload, timeout=10)
        print(f'✅ Webhook 响应状态码: {response.status_code}')
        print(f'✅ Webhook 响应内容: {response.text}')
    except Exception as exc:
        print(f'❌ Webhook 请求失败: {exc}')


"""
以下四个旧的后台加款方法已停用。
账户添加统一调用 account_balance.execute_account_balance，避免重复维护登录、
创建加款单、查询加款单和审批逻辑；保留原实现文本便于后续追溯。

def mgt_login(environment, username='test01', password='Admin123!'):
    print('\n================ [后台管理员登录] ================')
    login_url = getattr(environment, 'login_url', '')
    if not login_url:
        print('❌ 未配置后台登录地址')
        return None, None
    account_parameter, password_parameter = get_login_parameter_names(environment)
    try:
        login = execute_platform_login(
            login_url=login_url,
            account=username,
            password=password,
            account_parameter=account_parameter,
            password_parameter=password_parameter,
            login_encoding='multipart',
            login_timeout_seconds=10,
        )
        print(f'✅ 后台登录结果: {login.message}')
        if not login.access_token:
            print(f'❌ 后台登录失败: {target_login_failure_message(login.message)}')
            return None, None
        x_token = login.access_token
        x_user_id = extract_login_user_id(login.response_log, x_token) or '371'
        print(f'🔑 成功获取后台 x-token 与 x-user-id ({x_user_id})')
        return str(x_token), str(x_user_id)
    except Exception as exc:
        print(f'❌ 后台登录失败: {exc}')
        return None, None


def create_fund_adjustment(environment, x_token, x_user_id, member_id, amount):
    print('\n================ [后台创建手动充值单] ================')
    url = _url(_root_url(getattr(environment, 'login_url', '')), '/api/v2/fundAdjustment/create')
    headers = {
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en,zh-CN;q=0.9,zh;q=0.8,en-US;q=0.7',
        'Content-Type': 'application/json',
        'Origin': 'http://mgt.helix.city',
        'Referer': 'http://mgt.helix.city/',
        'User-Agent': (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36'
        ),
        'x-token': x_token,
        'x-user-id': str(x_user_id),
    }
    payload = {
        'accountType': 0,
        'amount': amount,
        'currency': 'BRL',
        'memberId': str(member_id),
        'type': 104,
        'agent': '',
        'accountCode': 'Cash2',
        'remark': '1',
    }
    print(f'🚀 充值请求 Body:\n{json.dumps(payload, indent=2, ensure_ascii=False)}')
    try:
        response = requests.post(url, headers=headers, json=payload, verify=False, timeout=10)
        print(f'✅ 创建充值单接口响应状态码: {response.status_code}')
        print(f'✅ 创建充值单响应结果: {response.text}')
        return True
    except Exception as exc:
        print(f'❌ 创建手动充值单失败: {exc}')
        return False


def get_fund_adjustment_id_from_list(environment, x_token, x_user_id, member_id):
    print('\n================ [从列表接口提取最新充值单 ID] ================')
    url = _url(_root_url(getattr(environment, 'login_url', '')), '/api/v2/fundAdjustment/list')
    headers = {
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en,zh-CN;q=0.9,zh;q=0.8,en-US;q=0.7',
        'Origin': 'http://mgt.helix.city',
        'Referer': 'http://mgt.helix.city/',
        'User-Agent': (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36'
        ),
        'x-token': x_token,
        'x-user-id': str(x_user_id),
    }
    params = {
        'page': 1,
        'pageSize': 50,
        'timezone': '+08:00',
        'memberId': str(member_id),
        'type': -999,
        'account': -999,
        'status': -999,
    }
    try:
        response = requests.get(url, headers=headers, params=params, verify=False, timeout=10)
        print(f'列表查询 HTTP 状态码: {response.status_code}')
        res_json = response.json()
        data_list = res_json.get('data', {}).get('list', [])
        if data_list:
            latest_id = data_list[0].get('id')
            print(f'🎯 成功匹配到充值单 ID (data.list[0].id): {latest_id}')
            return str(latest_id)
        print(f'❌ 列表中未找到 memberId = {member_id} 的充值订单')
        return None
    except Exception as exc:
        print(f'❌ 查询充值单列表失败: {exc}')
        return None


def audit_fund_adjustment(environment, x_token, x_user_id, adjustment_id):
    print('\n================ [后台审批通过充值单] ================')
    url = _url(_root_url(getattr(environment, 'login_url', '')), '/api/v2/fundAdjustment/audit')
    headers = {
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en,zh-CN;q=0.9,zh;q=0.8,en-US;q=0.7',
        'Content-Type': 'application/json',
        'Origin': 'http://mgt.helix.city',
        'Referer': 'http://mgt.helix.city/',
        'User-Agent': (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36'
        ),
        'x-token': x_token,
        'x-user-id': str(x_user_id),
    }
    payload = {'id': str(adjustment_id), 'remark': '1', 'status': 1}
    print(f'🚀 审批请求 Body:\n{json.dumps(payload, indent=2, ensure_ascii=False)}')
    try:
        response = requests.post(url, headers=headers, json=payload, verify=False, timeout=10)
        print(f'✅ 审批充值单状态码: {response.status_code}')
        print(f'✅ 审批充值单响应结果: {response.text}')
    except Exception as exc:
        print(f'❌ 审批充值单失败: {exc}')
"""


def _normalize_account_add_amount(amount):
    if amount in (None, ''):
        return Decimal('0')
    try:
        normalized = Decimal(str(amount))
    except Exception as exc:
        raise DataFactoryError('请输入有效金额') from exc
    if not normalized.is_finite() or normalized < 0 or normalized > Decimal('1000000'):
        raise DataFactoryError('金额不能小于 0 且不超过 1000000')
    return normalized


def _build_account_add_result(frontend_environment, backend_environment, email, balance_result=None, fallback_member_id=None, status='completed'):
    balance_result = balance_result or {}
    return {
        'environment_name': f'{frontend_environment.name} / {backend_environment.name}',
        'frontend_environment_name': frontend_environment.name,
        'backend_environment_name': backend_environment.name,
        'email': email,
        'member_id': str(balance_result.get('member_id') or fallback_member_id or ''),
        'adjustment_id': str(balance_result.get('adjustment_id') or ''),
        'status': balance_result.get('status') or status,
    }


def _run_single_account(frontend_environment, backend_environment, username='test01', password='Admin123!', email='', amount=5000, max_retries=10, operator=None):
    email_clean = str(email or '').strip().lower()
    amount_value = _normalize_account_add_amount(amount)
    base_url = getattr(frontend_environment, 'base_url', '')
    login_url = getattr(backend_environment, 'login_url', '')
    if not base_url:
        raise DataFactoryError('请选择已配置前台地址的运行环境')
    if not login_url:
        raise DataFactoryError('请选择已配置后台登录地址的运行环境')
    if not username or operator is None or not getattr(operator, 'username', ''):
        raise DataFactoryError('当前用户未配置后台账号')

    if email_clean:
        existing_member_id = check_member_exists(email_clean)
        if existing_member_id:
            print(f'\n================ [检测到账号 {email_clean} 已存在] ================')
            balance_result = None
            if amount_value > 0:
                print(f'🔍 Member ID: {existing_member_id}。直接跳过注册与 KYC 认证，调用账户余额工具充值...')
                balance_result = execute_account_balance(
                    operator, password, backend_environment.id, email_clean, amount_value,
                )
            else:
                print(f'🔍 Member ID: {existing_member_id}。未填写金额，跳过账户余额操作。')
            return _build_account_add_result(
                frontend_environment, backend_environment, email_clean, balance_result, existing_member_id,
                status='existing',
            )

    last_error = None
    for attempt in range(1, max_retries + 1):
        print(f'\n================ [第 {attempt}/{max_retries} 次尝试注册与认证] ================')
        try:
            id_number = get_brazil_id()
            if not id_number:
                raise DataFactoryError('未能生成有效 CPF')

            current_ts = int(time.time())
            email_identifier = email_clean if email_clean else f'test{current_ts}@test.com'
            print(f'生成的 CPF (idNumber): {id_number}')
            print(f'使用的账号邮箱 (email/identifier): {email_identifier}')

            register_url = _url(base_url, '/api/v1/auth/register')
            headers = {
                'accept': 'application/json, text/plain, */*',
                'content-type': 'application/json;charset=UTF-8',
                'origin': 'https://matchday.helix.city',
                'referer': 'https://matchday.helix.city/',
                'user-agent': (
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36'
                ),
                'x-chan': '0',
                'x-device-id': '18b225ed-c2e0-4fa3-b821-966271680942',
                'x-lang': 'en',
                'x-nonce': 'hEIT38',
                'x-platform': 'WEB',
                'x-signature': 'a90d5da3ccf4541e6df989becaae539eab7f4a92f70908ca8fe98faa5286ba41',
                'x-timestamp': str(current_ts),
                'x-trace': '{"gaid":"1895362410.1774335438"}',
                'x-ver': '0.2.277',
            }
            payload = {
                'password': 'Test1234!',
                'country': 'BRA',
                'birthday': '',
                'email': email_identifier,
                'identifier': email_identifier,
                'lang': 'en',
                'idNumber': id_number,
                'surName': '',
                'telPhone': '',
                'telAreaCode': '55',
                'invitationCode': '',
                'sourceUrl': 'https://matchday.helix.city/en',
                'referralCode': '',
            }

            response = requests.post(register_url, headers=headers, json=payload, timeout=10)
            res_text = response.text
            try:
                res_json = response.json()
                msg = str(res_json.get('msg', '')).lower()
            except Exception:
                res_json = None
                msg = res_text.lower()

            if 'cpf number existed' in msg or 'cpf number existed' in res_text.lower():
                print(f'⚠️ CPF ({id_number}) 已存在，重新获取并发起注册...')
                last_error = DataFactoryError(f'CPF ({id_number}) 已存在，无法注册新账号')
                time.sleep(1)
                continue

            response_message = _response_message(res_json, res_text)
            response_code = res_json.get('code') if isinstance(res_json, dict) else None
            business_failed = response_code not in (None, True, 0, '0', 200, '200', 201, '201')
            if not 200 <= response.status_code < 300 or business_failed:
                failure_message = response_message or f'HTTP {response.status_code}'
                print(f'❌ 账号注册失败：{failure_message}')
                last_error = DataFactoryError(f'账号注册失败：{failure_message}')
                time.sleep(1)
                continue

            print(f'✅ 账号注册成功！HTTP 状态码: {response.status_code}')
            user_token = extract_token_str(res_json, response.headers)
            if not user_token:
                user_token, login_error = _login_registered_account(
                    frontend_environment, email_identifier, payload['password'],
                )
                if not user_token:
                    error_message = login_error or '注册响应未返回有效 Token'
                    print(f'❌ 注册后认证失败：{error_message}')
                    last_error = DataFactoryError(error_message)
                time.sleep(1)
                if not user_token:
                    continue

            get_kyc_url(frontend_environment, user_token)
            print('\n⏳ 正在等待数据库写入 KYC 记录 (延时 2 秒)...')
            time.sleep(2)

            member_id, uuid, protocol, document = query_kyc_info_from_db(email_identifier)
            if not member_id:
                raise DataFactoryError('未能从数据库中找到 member_id')
            if protocol and document:
                print(
                    f'🎯 查库解析成功!\n -> member_id: {member_id}\n -> user_id (uuid): {uuid}\n'
                    f' -> protocol (serasa_validation_id): {protocol}\n -> document (CPF): {document}'
                )
                trigger_face_verification_webhook(protocol, document, email_identifier)
                balance_result = None
                if amount_value > 0:
                    balance_result = execute_account_balance(
                        operator, password, backend_environment.id, email_identifier, amount_value,
                    )
                else:
                    print('未填写金额，跳过账户余额操作。')
                return _build_account_add_result(
                    frontend_environment, backend_environment, email_identifier, balance_result, member_id,
                    status='registered',
                )

            raise DataFactoryError('未能从数据库中成功提取 KYC 变量')
        except DataFactoryError as exc:
            last_error = exc
            print(f'❌ 运行过程中发生错误: {exc}')
            time.sleep(1)

    if last_error:
        raise last_error
    raise DataFactoryError('注册与认证流程执行失败')


def run_full_automation(frontend_environment, backend_environment, username='test01', password='Admin123!', email='', amount=5000, max_retries=10, operator=None, quantity=1):
    """按数量注册账号；每个账号内部仍使用 max_retries 重试注册流程。"""
    try:
        account_count = int(quantity)
    except (TypeError, ValueError) as exc:
        raise DataFactoryError('请输入有效数量') from exc
    if account_count < 1:
        raise DataFactoryError('数量必须大于 0')
    if str(email or '').strip() and account_count != 1:
        raise DataFactoryError('填写邮箱时数量必须为 1；批量注册请留空邮箱')

    results = []
    for account_index in range(1, account_count + 1):
        print(f'\n================ [第 {account_index}/{account_count} 个账号] ================')
        results.append(
            _run_single_account(
                frontend_environment,
                backend_environment,
                username=username,
                password=password,
                email=email,
                amount=amount,
                max_retries=max_retries,
                operator=operator,
            )
        )

    result = dict(results[-1])
    result['emails'] = [
        str(item.get('email')).strip().lower()
        for item in results
        if str(item.get('email') or '').strip()
    ]
    result['quantity'] = account_count
    result['registered_count'] = account_count
    return result


def execute_account_add(operator, password, frontend_environment_id, backend_environment_id, email, amount, quantity):
    amount_value = _normalize_account_add_amount(amount)
    frontend_environment = Environment.objects.filter(pk=frontend_environment_id).first()
    if not frontend_environment:
        raise DataFactoryError('请选择有效前台运行环境')
    backend_environment = Environment.objects.filter(pk=backend_environment_id).first()
    if not backend_environment:
        raise DataFactoryError('请选择有效后台运行环境')
    if not getattr(frontend_environment, 'base_url', ''):
        raise DataFactoryError('请选择已配置前台地址的运行环境')
    if not getattr(backend_environment, 'login_url', ''):
        raise DataFactoryError('请选择已配置后台登录地址的运行环境')
    if not password:
        raise DataFactoryError('请输入系统密码')
    try:
        account_count = int(quantity)
    except (TypeError, ValueError) as exc:
        raise DataFactoryError('请输入有效数量') from exc
    if account_count < 1:
        raise DataFactoryError('数量必须大于 0')
    automation_result = run_full_automation(
        frontend_environment,
        backend_environment,
        username=getattr(operator, 'username', ''),
        password=password,
        email=email,
        amount=amount_value,
        operator=operator,
        quantity=account_count,
    )
    return {
        'environment_name': f'{frontend_environment.name} / {backend_environment.name}',
        'frontend_environment_name': frontend_environment.name,
        'backend_environment_name': backend_environment.name,
        'email': str(automation_result.get('email') or email or '').strip().lower(),
        'emails': list(automation_result.get('emails') or []),
        'amount': str(amount_value),
        'quantity': account_count,
        'member_id': str(automation_result.get('member_id') or ''),
        'adjustment_id': str(automation_result.get('adjustment_id') or ''),
        'status': 'executed',
    }
