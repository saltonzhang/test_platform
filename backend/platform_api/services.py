import json
import logging
import random
import re
import ssl
from copy import deepcopy
from itertools import product
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from django.conf import settings
from django.db.models import Max
from django.utils import timezone

from .executor import api_request_executor
from .common.login import build_login_headers, execute_platform_login, get_login_parameter_names, target_login_failure_message
from .models import ApiInterface, AutomationTaskResult, MonitorAlarm, MonitorApiConfig, MonitorExecution, MonitorExecutionDetail, User


logger = logging.getLogger(__name__)

PARAMETER_PLACEHOLDER = re.compile(r'\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}')
LEGACY_PARAMETER_PLACEHOLDER = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}')
CUSTOM_VALUE_PLACEHOLDER = re.compile(
    r'\$\{([A-Za-z_][A-Za-z0-9_]*)'
    r'((?:\.[A-Za-z_][A-Za-z0-9_]*|\[(?:\*|\d+(?:,\d+)*|\d*:\d*)\])*)\}'
)
CUSTOM_VALUE_ACCESSOR = re.compile(
    r'\.([A-Za-z_][A-Za-z0-9_]*)|\[(\*|\d+(?:,\d+)*|\d*:\d*)\]'
)


def _json_string_content(value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return json.dumps(text, ensure_ascii=False)[1:-1]


def _stringify_custom_replacement(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _select_custom_variable_value(name, accessor, variables):
    if name not in variables:
        raise KeyError(name)

    nodes = [variables[name]]
    is_multiple = False
    position = 0
    for match in CUSTOM_VALUE_ACCESSOR.finditer(accessor):
        if match.start() != position:
            raise ValueError(f'关联接口变量 {name}{accessor} 的取值表达式无效')
        position = match.end()
        field, selector = match.groups()
        selected = []
        if field is not None:
            for item_index, node in enumerate(nodes):
                if not isinstance(node, dict) or field not in node:
                    location = f'第 {item_index + 1} 项' if is_multiple else '返回值'
                    raise ValueError(f'关联接口变量 {name}{accessor} 的{location}不存在字段 {field}')
                selected.append(node[field])
        else:
            for node in nodes:
                if not isinstance(node, list):
                    raise ValueError(f'关联接口变量 {name}{accessor} 使用数组选择时返回值必须是列表')
                if selector == '*':
                    selected.extend(node)
                    is_multiple = True
                elif ':' in selector:
                    start_text, end_text = selector.split(':', 1)
                    start = int(start_text) if start_text else None
                    end = int(end_text) if end_text else None
                    selected.extend(node[slice(start, end)])
                    is_multiple = True
                else:
                    indexes = [int(index) for index in selector.split(',')]
                    for index in indexes:
                        if index >= len(node):
                            raise ValueError(
                                f'关联接口变量 {name}{accessor} 的数组下标 {index} 越界，当前共 {len(node)} 项'
                            )
                        selected.append(node[index])
                    if len(indexes) > 1:
                        is_multiple = True
        nodes = selected

    if position != len(accessor):
        raise ValueError(f'关联接口变量 {name}{accessor} 的取值表达式无效')
    return (nodes if is_multiple else nodes[0]), is_multiple


def _is_inside_json_string(text, index):
    in_string = False
    escaped = False
    for char in text[:index]:
        if escaped:
            escaped = False
            continue
        if char == '\\':
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
    return in_string


def _resolve_full_custom_value(rule, variables):
    template = str(rule.get('value', ''))
    unresolved_names = set()
    selected_multiple = False

    def replace(match):
        nonlocal selected_multiple
        name = match.group(1)
        accessor = match.group(2)
        try:
            value, is_multiple = _select_custom_variable_value(name, accessor, variables)
        except KeyError:
            unresolved_names.add(name)
            return match.group(0)
        selected_multiple = selected_multiple or is_multiple
        return _json_string_content(value) if _is_inside_json_string(template, match.start()) else json.dumps(value, ensure_ascii=False)

    rendered = CUSTOM_VALUE_PLACEHOLDER.sub(replace, template)
    if unresolved_names:
        names = '、'.join(sorted(unresolved_names))
        raise ValueError(f"参数 {rule.get('path', '')} 存在未解析的关联接口变量：{names}")
    try:
        value = json.loads(rendered)
    except (TypeError, ValueError):
        def replace_as_text(match):
            value, _ = _select_custom_variable_value(match.group(1), match.group(2), variables)
            return _stringify_custom_replacement(value)

        value = CUSTOM_VALUE_PLACEHOLDER.sub(replace_as_text, template)
    expands_scenarios = bool(CUSTOM_VALUE_PLACEHOLDER.fullmatch(template) and selected_multiple)
    return value, expands_scenarios


def resolve_full_custom_value(rule, variables):
    value, _ = _resolve_full_custom_value(rule, variables)
    return value


def replace_response_variables(value, variables):
    if isinstance(value, dict):
        return {key: replace_response_variables(item, variables) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_response_variables(item, variables) for item in value]
    if not isinstance(value, str):
        return value
    if value.startswith('${') and value.endswith('}') and value[2:-1] in variables:
        return variables[value[2:-1]]
    rendered = value
    for name, replacement in variables.items():
        rendered = rendered.replace('${' + name + '}', str(replacement))
    return rendered


def has_unresolved_response_variables(value):
    if isinstance(value, dict):
        return any(has_unresolved_response_variables(item) for item in value.values())
    if isinstance(value, list):
        return any(has_unresolved_response_variables(item) for item in value)
    return isinstance(value, str) and '${' in value


def collect_response_variable_placeholders(value):
    names = set()
    if isinstance(value, dict):
        for item in value.values():
            names.update(collect_response_variable_placeholders(item))
        return names
    if isinstance(value, list):
        for item in value:
            names.update(collect_response_variable_placeholders(item))
        return names
    if isinstance(value, str):
        names.update(match.group(1) for match in CUSTOM_VALUE_PLACEHOLDER.finditer(value))
    return names


def interface_response_variable_placeholders(interface):
    if interface.request_parameter_mode != 'full':
        return collect_response_variable_placeholders(interface.request_params)
    names = set()
    for rule in interface.full_parameterizations or []:
        if rule.get('value_mode') == 'fixed':
            names.update(collect_response_variable_placeholders(rule.get('values', rule.get('value'))))
        elif rule.get('variable_type') == 'custom':
            names.update(collect_response_variable_placeholders(rule.get('value', '')))
    return names


def dependency_variable_block_message(interface, dependency_failures, extracted_variables_by_interface):
    if not interface.reference_enabled or not interface.reference_interface_id:
        return ''
    expected_names = [
        str(rule.get('name', '')).strip()
        for rule in interface.response_extracts or []
        if isinstance(rule, dict) and str(rule.get('name', '')).strip()
    ]
    used_names = sorted(set(expected_names) & interface_response_variable_placeholders(interface))
    if not used_names:
        return ''
    dependency_name = interface.reference_interface.name if interface.reference_interface_id else ''
    variable_names = '、'.join(used_names)
    dependency_failure = dependency_failures.get(interface.reference_interface_id)
    if dependency_failure:
        return f'关联接口 {dependency_name or interface.reference_interface_id} 未通过，无法生成变量：{variable_names}。关联接口失败原因：{dependency_failure}'
    extracted_variables = extracted_variables_by_interface.get(interface.id, {})
    missing_names = [name for name in used_names if name not in extracted_variables]
    if missing_names:
        return f'关联接口 {dependency_name or interface.reference_interface_id} 未生成变量：{"、".join(missing_names)}，请检查返回值提取路径或关联接口响应'
    return ''


def generate_parameter_value(parameter_type, custom_value=''):
    if parameter_type == 'name':
        return random.choice(('张伟', '李娜', '王强', '陈静', '刘洋', '赵敏', '黄俊', '周倩'))
    if parameter_type == 'time':
        return timezone.now().isoformat()
    if parameter_type == 'location':
        return random.choice(('北京', '上海', '广州', '深圳', '杭州', '成都', '武汉', '重庆'))
    if parameter_type == 'phone':
        return '1' + random.choice('3456789') + ''.join(random.choice('0123456789') for _ in range(9))
    if parameter_type == 'id_card':
        birthday = timezone.now().date().replace(year=timezone.now().year - random.randint(20, 50))
        prefix = random.choice(('110101', '310101', '440101', '510101'))
        sequence = f'{random.randint(0, 999):03d}'
        body = f'{prefix}{birthday:%Y%m%d}{sequence}'
        weights = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
        checks = '10X98765432'
        return body + checks[sum(int(digit) * weight for digit, weight in zip(body, weights)) % 11]
    if parameter_type == 'email':
        return f'test{random.randint(100000, 999999)}@example.com'
    return str(custom_value)


def build_parameter_variables(parameterizations):
    variables = {}
    for item in parameterizations or []:
        if not isinstance(item, dict) or not item.get('name'):
            continue
        variables[item['name']] = generate_parameter_value(item.get('type', 'custom'), item.get('value', ''))
    return variables


def _set_parameter_path(target, path, value):
    segments = path.split('.')
    current = target
    for index, segment in enumerate(segments):
        is_last = index == len(segments) - 1
        if isinstance(current, list):
            if not segment.isdigit():
                raise ValueError(f'参数路径 {path} 的数组下标无效')
            item_index = int(segment)
            while len(current) <= item_index:
                current.append(None)
            if is_last:
                current[item_index] = deepcopy(value)
                return
            next_value = [] if segments[index + 1].isdigit() else {}
            if current[item_index] is None:
                current[item_index] = next_value
            current = current[item_index]
            continue
        if is_last:
            current[segment] = deepcopy(value)
            return
        next_value = [] if segments[index + 1].isdigit() else {}
        if segment not in current:
            current[segment] = next_value
        current = current[segment]


def build_full_parameter_scenarios(interface, response_variables=None):
    response_variables = response_variables or {}
    scenario_rules, variable_rules = [], []
    for rule in interface.full_parameterizations or []:
        if rule.get('value_mode') == 'fixed':
            values = rule.get('values')
            if values is None and 'value' in rule:
                values = [rule['value']]
            if not isinstance(values, list) or not values:
                raise ValueError(f"固定参数 {rule.get('path', '')} 没有可执行值")
            scenario_rules.append((rule['path'], values))
        elif rule.get('variable_type') == 'custom':
            value, expands_scenarios = _resolve_full_custom_value(rule, response_variables)
            if expands_scenarios:
                if not value:
                    raise ValueError(
                        f"参数 {rule.get('path', '')} 使用 {rule.get('value', '')} 未提取到可执行值，关联接口返回列表为空"
                    )
                scenario_rules.append((rule['path'], value))
            else:
                variable_rules.append((rule, value))
        else:
            variable_rules.append((rule, None))

    combinations = product(*(values for _, values in scenario_rules)) if scenario_rules else [()]
    scenarios = []
    for combination in combinations:
        wrapped_params = {}
        for (path, _), value in zip(scenario_rules, combination):
            _set_parameter_path(wrapped_params, path, value)
        for rule, resolved_value in variable_rules:
            if rule.get('variable_type') == 'custom':
                value = resolved_value
            else:
                value = generate_parameter_value(rule.get('variable_type', 'custom'), rule.get('value', ''))
            _set_parameter_path(wrapped_params, rule['path'], value)
        scenarios.append(api_request_executor.get_request_params(interface.method, wrapped_params))
    return scenarios


def build_interface_request_scenarios(interface, expand_full=False, response_variables=None):
    if interface.request_parameter_mode == 'full':
        scenarios = build_full_parameter_scenarios(interface, response_variables=response_variables)
        return scenarios if expand_full else scenarios[:1]
    return [api_request_executor.get_request_params(interface.method, interface.request_params)]


def replace_parameter_variables(value, variables):
    if isinstance(value, dict):
        return {key: replace_parameter_variables(item, variables) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_parameter_variables(item, variables) for item in value]
    if not isinstance(value, str):
        return value
    match = PARAMETER_PLACEHOLDER.fullmatch(value)
    if match and match.group(1) in variables:
        return variables[match.group(1)]
    rendered = PARAMETER_PLACEHOLDER.sub(lambda item: str(variables[item.group(1)]) if item.group(1) in variables else item.group(0), value)
    return LEGACY_PARAMETER_PLACEHOLDER.sub(lambda item: str(variables[item.group(1)]) if item.group(1) in variables else item.group(0), rendered)


def extract_response_variables(interface, response_log):
    if not interface.reference_enabled or not interface.response_extracts:
        return {}
    try:
        payload = json.loads(response_log or '')
    except (TypeError, ValueError):
        return {}
    values = {}
    for rule in interface.response_extracts:
        try:
            values[rule['name']] = api_request_executor.read_json_path(payload, rule['path'])
        except (KeyError, IndexError, TypeError, ValueError):
            logger.warning('接口 %s 响应提取失败：%s', interface.id, rule)
    return values


def build_request_url(base_url, path, method, request_params):
    url = urljoin(f'{base_url.rstrip("/")}/', path.lstrip('/'))
    if method == 'GET':
        query = urlencode(api_request_executor.get_request_params(method, request_params), doseq=True)
        if query:
            url = f'{url}{"&" if "?" in url else "?"}{query}'
    return url


def execute_task(
    task,
    operator: User,
    login_password: str,
    target_interface_id=None,
    target_request_params=None,
    login_timeout_seconds=10,
):
    task.status = 'running'
    task.save(update_fields=['status', 'updated_at'])
    execution_no = (task.execution_details.aggregate(value=Max('execution_no'))['value'] or 0) + 1
    module_names = list(task.modules.values_list('name', flat=True))
    if not module_names and task.module_id:
        module_names = [task.module.name]
    app = next(iter(task.modules.values_list('app', flat=True)), task.module.app if task.module_id else '')
    login_url = task.environment.login_url
    results = []
    access_token = ''

    account = operator.email if app == 'frontend' else operator.username
    if not login_url:
        return finish_login_failure(task, execution_no, results, '运行环境未配置登录地址')
    if not account:
        account_label = '邮箱' if app == 'frontend' else '账号'
        return finish_login_failure(task, execution_no, results, f'当前用户未配置{account_label}')
    try:
        account_parameter, password_parameter = get_login_parameter_names(task.environment)
    except ValueError as exc:
        return finish_login_failure(task, execution_no, results, str(exc))
    login_encoding = 'multipart' if app == 'backend' else 'json'
    login_headers = build_login_headers(login_encoding)
    login_outcome = execute_platform_login(
        login_url=login_url,
        account=account,
        password=login_password,
        account_parameter=account_parameter,
        password_parameter=password_parameter,
        login_encoding=login_encoding,
        login_timeout_seconds=login_timeout_seconds,
    )
    login_status = login_outcome.status if login_outcome.access_token else 'failed'
    login_message = login_outcome.message if login_outcome.access_token else target_login_failure_message(
        f'{login_outcome.message} · 登录响应未返回 access Token'
    )
    login_result = AutomationTaskResult.objects.create(
        task=task,
        execution_no=execution_no,
        interface_name='系统登录',
        method='POST',
        path=login_url,
        headers=login_headers,
        request_params={account_parameter: account},
        assertions={'status_code': 200, 'timeout_seconds': login_timeout_seconds},
        status=login_status,
        duration_ms=login_outcome.duration_ms,
        response_message=login_message,
        response_log=login_outcome.response_log if login_status == 'failed' else '',
        executed_at=timezone.now(),
    )
    results.append(login_result)
    if login_status == 'failed':
        return finish_task(task, results)

    access_token = login_outcome.access_token
    if target_interface_id:
        target_interface = ApiInterface.objects.filter(pk=target_interface_id).first()
        if not target_interface:
            return finish_login_failure(task, execution_no, results, '重试接口已不存在')
        interfaces = [target_interface]
        scenario_interface_ids = {target_interface.id} if task.task_type == 'scenario' else set()
    elif task.task_type == 'scenario':
        interfaces = list(task.interfaces.filter(can_execute_in_task=True).order_by('id'))
        interfaces = [item for item in interfaces if not api_request_executor.is_login_url(item.path, login_url)]
        scenario_interface_ids = {item.id for item in interfaces}
    else:
        interfaces = list(ApiInterface.objects.filter(module_name__in=module_names, can_execute_in_task=True).distinct())
        interfaces = [item for item in interfaces if not api_request_executor.is_login_url(item.path, login_url)]
        scenario_interface_ids = set()
    ordered_interfaces = []
    added_ids = set()

    def add_with_dependencies(interface, visiting=None):
        visiting = visiting or set()
        if interface.id in added_ids or interface.id in visiting:
            return
        visiting.add(interface.id)
        if interface.reference_enabled and interface.reference_interface_id:
            dependency = ApiInterface.objects.filter(pk=interface.reference_interface_id).first()
            if dependency and not api_request_executor.is_login_url(dependency.path, login_url):
                add_with_dependencies(dependency, visiting)
        visiting.remove(interface.id)
        added_ids.add(interface.id)
        ordered_interfaces.append(interface)

    for interface in sorted(interfaces, key=lambda item: item.id):
        add_with_dependencies(interface)

    response_variables = {}
    extracted_variables_by_interface = {}
    dependency_failures = {}
    for interface in ordered_interfaces:
        dependency_block_message = ''
        if not (target_interface_id == interface.id and target_request_params is not None):
            dependency_block_message = dependency_variable_block_message(
                interface,
                dependency_failures,
                extracted_variables_by_interface,
            )
        if dependency_block_message:
            result = AutomationTaskResult.objects.create(
                task=task,
                execution_no=execution_no,
                source_interface_id=interface.id,
                interface_name=interface.name,
                method=interface.method,
                path=build_request_url(task.environment.base_url, interface.path, interface.method, {}),
                headers=interface.headers,
                request_params={},
                assertions=interface.assertions,
                status='failed',
                duration_ms=0,
                response_message=dependency_block_message,
                response_log=dependency_block_message,
                executed_at=timezone.now(),
            )
            results.append(result)
            dependency_failures[interface.id] = dependency_block_message
            continue
        try:
            if target_interface_id == interface.id and target_request_params is not None:
                request_scenarios = [deepcopy(target_request_params)]
            else:
                request_scenarios = build_interface_request_scenarios(
                    interface,
                    expand_full=interface.id in scenario_interface_ids,
                    response_variables=response_variables,
                )
        except ValueError as exc:
            failure_message = str(exc)
            result = AutomationTaskResult.objects.create(
                task=task,
                execution_no=execution_no,
                source_interface_id=interface.id,
                interface_name=interface.name,
                method=interface.method,
                path=build_request_url(task.environment.base_url, interface.path, interface.method, {}),
                headers=interface.headers,
                request_params={},
                assertions=interface.assertions,
                status='failed',
                duration_ms=0,
                response_message=failure_message,
                response_log=failure_message,
                executed_at=timezone.now(),
            )
            results.append(result)
            dependency_failures[interface.id] = failure_message
            continue
        parameter_variables = build_parameter_variables(interface.parameterizations)
        interface_passed = False
        interface_failure_messages = []
        for scenario_params in request_scenarios:
            try:
                # Resolve response variables first; template values fill any remaining placeholders.
                request_params = replace_response_variables(scenario_params, response_variables)
                request_params = replace_parameter_variables(request_params, parameter_variables)
                url = build_request_url(task.environment.base_url, interface.path, interface.method, request_params)
                result = AutomationTaskResult.objects.create(
                    task=task,
                    execution_no=execution_no,
                    source_interface_id=interface.id,
                    interface_name=interface.name,
                    method=interface.method,
                    path=url,
                    headers=interface.headers,
                    request_params=request_params,
                    assertions=interface.assertions,
                    status='running',
                    executed_at=timezone.now(),
                )
                if has_unresolved_response_variables(request_params):
                    outcome = type('MissingVariableOutcome', (), {'status': 'failed', 'duration_ms': 0, 'message': '请求参数中存在未解析的关联接口变量', 'response_log': '', 'access_token': ''})()
                else:
                    outcome = api_request_executor.execute(
                        url=url,
                        method=interface.method,
                        headers=interface.headers,
                        request_params=request_params,
                        assertions=interface.assertions,
                        access_token=access_token,
                        login_url=login_url,
                        access_token_prefix='',
                        access_token_header='x-token' if app == 'backend' else 'authorization',
                    )
                result.status = outcome.status
                result.duration_ms = outcome.duration_ms
                result.response_message = outcome.message
                # Keep successful response bodies available for downstream interface variables.
                result.response_log = outcome.response_log
                result.save(update_fields=['status', 'duration_ms', 'response_message', 'response_log', 'updated_at'])
                access_token = outcome.access_token or access_token
                if outcome.status == 'passed':
                    interface_passed = True
                    # Extraction rules belong to the interfaces that consume this response.
                    for consumer in ordered_interfaces:
                        if consumer.reference_enabled and consumer.reference_interface_id == interface.id:
                            extracted_values = extract_response_variables(consumer, outcome.response_log)
                            if extracted_values:
                                extracted_variables_by_interface.setdefault(consumer.id, {}).update(extracted_values)
                                response_variables.update(extracted_values)
                else:
                    interface_failure_messages.append(outcome.message)
                results.append(result)
            except ValueError as exc:
                failure_message = str(exc)
                result = AutomationTaskResult.objects.create(
                    task=task,
                    execution_no=execution_no,
                    source_interface_id=interface.id,
                    interface_name=interface.name,
                    method=interface.method,
                    path=build_request_url(task.environment.base_url, interface.path, interface.method, {}),
                    headers=interface.headers,
                    request_params={},
                    assertions=interface.assertions,
                    status='failed',
                    duration_ms=0,
                    response_message=failure_message,
                    response_log=failure_message,
                    executed_at=timezone.now(),
                )
                results.append(result)
                interface_failure_messages.append(failure_message)
        if not interface_passed and interface_failure_messages:
            dependency_failures[interface.id] = interface_failure_messages[-1]

    return finish_task(task, results)


def finish_login_failure(task, execution_no, results, message):
    results.append(AutomationTaskResult.objects.create(
        task=task,
        execution_no=execution_no,
        interface_name='系统登录',
        method='POST',
        path=task.environment.login_url,
        headers={},
        request_params={},
        assertions={},
        status='failed',
        response_message=message,
        response_log=message,
        executed_at=timezone.now(),
    ))
    return finish_task(task, results)


def finish_task(task, results):
    task.status = 'passed' if results and all(item.status == 'passed' for item in results) else 'failed'
    task.save(update_fields=['status', 'updated_at'])
    notification_status, notification_message = send_feishu_task_result(task, results)
    task.notification_status = notification_status
    task.notification_message = notification_message
    task.notified_at = timezone.now() if notification_status == 'sent' else None
    task.save(update_fields=['notification_status', 'notification_message', 'notified_at', 'updated_at'])
    task._prefetched_objects_cache = {}
    return results


def send_feishu_task_result(task, results):
    webhook_url = settings.FEISHU_BOT_WEBHOOK_URL
    if not webhook_url:
        return 'disabled', '未配置飞书机器人地址'

    failed_results = [item for item in results if item.status == 'failed']
    lines = [
        '自动化任务执行完成',
        f'任务：{task.name}',
        f'环境：{task.environment.name}',
        f'结果：{"通过" if task.status == "passed" else "失败"}',
        f'接口总数：{len(results)}，成功：{len(results) - len(failed_results)}，失败：{len(failed_results)}',
    ]
    if failed_results:
        lines.append('失败接口：' + '、'.join(item.interface_name for item in failed_results[:10]))
        if len(failed_results) > 10:
            lines.append(f'其余 {len(failed_results) - 10} 个失败接口请在平台查看')

    payload = json.dumps({'msg_type': 'text', 'content': {'text': '\n'.join(lines)}}, ensure_ascii=False).encode('utf-8')
    request = Request(webhook_url, data=payload, headers={'Content-Type': 'application/json'}, method='POST')
    try:
        ssl_context = None if settings.FEISHU_BOT_SSL_VERIFY else ssl._create_unverified_context()
        with urlopen(request, timeout=5, context=ssl_context) as response:
            body = response.read().decode('utf-8', errors='replace')
            response_data = json.loads(body) if body else {}
            if response.status < 200 or response.status >= 300 or response_data.get('code', 0) != 0:
                message = response_data.get('msg') or response_data.get('StatusMessage') or f'HTTP {response.status}'
                logger.warning('飞书任务结果通知发送失败：%s', message)
                return 'failed', str(message)
            return 'sent', '飞书通知发送成功'
    except (HTTPError, URLError, OSError, ValueError) as exc:
        logger.warning('飞书任务结果通知发送失败：%s', exc)
        return 'failed', str(exc)


def retry_task_result(source, operator: User, login_password: str):
    interface = ApiInterface.objects.filter(pk=source.source_interface_id).first()
    if not interface:
        raise ValueError('原接口已不存在，无法获取最新接口信息进行重试')
    results = execute_task(
        source.task,
        operator,
        login_password,
        target_interface_id=interface.id,
        target_request_params=source.request_params,
        login_timeout_seconds=5,
    )
    return next((item for item in reversed(results) if item.source_interface_id == interface.id), results[-1])


def interval_delta(task):
    value = task.interval_value or 1
    if task.interval_unit == 'hour':
        return timezone.timedelta(hours=value)
    if task.interval_unit == 'day':
        return timezone.timedelta(days=value)
    return timezone.timedelta(minutes=value)


def calculate_next_run_time(task, base_time=None):
    if not task.enabled:
        return None
    return (base_time or timezone.now()) + interval_delta(task)


def sync_monitor_next_run_time(task):
    task.next_run_time = calculate_next_run_time(task)
    task.save(update_fields=['next_run_time', 'updated_at'])
    return task.next_run_time


def _create_monitor_detail(execution, api_config, access_token='', source='monitor'):
    url = build_request_url(execution.task.environment.base_url, api_config.path, api_config.method, api_config.request_params)
    request_params = api_request_executor.get_request_params(api_config.method, api_config.request_params)
    detail = MonitorExecutionDetail.objects.create(
        execution=execution,
        source_api_config_id=api_config.id if source == 'monitor' else None,
        source_interface_id=api_config.id if source == 'automation' else None,
        interface_name=api_config.name,
        method=api_config.method,
        path=api_config.path,
        url=url,
        module_name=api_config.module_name,
        headers=api_config.headers,
        request_params=request_params,
        assertions=api_config.assertions,
        status='running',
        executed_at=timezone.now(),
    )
    outcome = api_request_executor.execute(
        url=url,
        method=api_config.method,
        headers=api_config.headers,
        request_params=request_params,
        assertions=api_config.assertions,
        access_token=access_token,
        login_url=execution.task.environment.login_url,
    )
    detail.status = outcome.status
    detail.duration_ms = outcome.duration_ms
    detail.response_message = outcome.message
    detail.save(update_fields=['status', 'duration_ms', 'response_message', 'updated_at'])
    return detail, outcome.access_token or access_token


def _create_source_interface_detail(execution, monitor_config, interface, access_token=''):
    request_params = api_request_executor.get_request_params(interface.method, interface.request_params)
    request_params = replace_parameter_variables(request_params, build_parameter_variables(interface.parameterizations))
    url = build_request_url(execution.task.environment.base_url, interface.path, interface.method, request_params)
    detail = MonitorExecutionDetail.objects.create(
        execution=execution,
        source_api_config_id=monitor_config.id,
        source_interface_id=interface.id,
        interface_name=interface.name,
        method=interface.method,
        path=interface.path,
        url=url,
        module_name=interface.module_name,
        headers=interface.headers,
        request_params=request_params,
        assertions=interface.assertions,
        status='running',
        executed_at=timezone.now(),
    )
    outcome = api_request_executor.execute(
        url=url,
        method=interface.method,
        headers=interface.headers,
        request_params=request_params,
        assertions=interface.assertions,
        access_token=access_token,
        login_url=execution.task.environment.login_url,
    )
    detail.status = outcome.status
    detail.duration_ms = outcome.duration_ms
    detail.response_message = outcome.message
    detail.save(update_fields=['status', 'duration_ms', 'response_message', 'updated_at'])
    return detail, outcome.access_token or access_token


def execute_monitor_task(task):
    execution_no = (task.executions.aggregate(value=Max('execution_no'))['value'] or 0) + 1
    execution = MonitorExecution.objects.create(task=task, execution_no=execution_no, status='running')
    task.status = 'running'
    task.last_run_time = timezone.now()
    task.save(update_fields=['status', 'last_run_time', 'updated_at'])

    monitor_configs = [('monitor', item) for item in task.api_configs.filter(enabled=True).order_by('id')]
    automation_interfaces = [('automation', item) for item in task.automation_interfaces.filter(can_execute_in_task=True).order_by('id')]
    api_configs = monitor_configs + automation_interfaces
    login_url = task.environment.login_url
    api_configs.sort(key=lambda item: (not api_request_executor.is_login_url(item[1].path, login_url), item[0], item[1].id))
    access_token = ''
    details = []

    for source, api_config in api_configs:
        source_ids = api_config.source_interface_ids if source == 'monitor' else []
        if source_ids:
            interfaces = {item.id: item for item in ApiInterface.objects.filter(id__in=source_ids)}
            for source_id in source_ids:
                interface = interfaces.get(source_id)
                if not interface:
                    continue
                detail, access_token = _create_source_interface_detail(execution, api_config, interface, access_token=access_token)
                details.append(detail)
                if detail.status == 'failed':
                    MonitorAlarm.objects.create(
                        task=task,
                        execution=execution,
                        detail=detail,
                        level='error',
                        message=f'{interface.name} 执行失败：{detail.response_message}',
                    )
            continue
        detail, access_token = _create_monitor_detail(execution, api_config, access_token=access_token, source=source)
        details.append(detail)
        if detail.status == 'failed':
            MonitorAlarm.objects.create(
                task=task,
                execution=execution,
                detail=detail,
                level='error',
                message=f'{api_config.name} 执行失败：{detail.response_message}',
            )

    failures = [item for item in details if item.status == 'failed']
    durations = [item.duration_ms or 0 for item in details if item.duration_ms is not None]
    execution.interface_total = len(details)
    execution.failure_count = len(failures)
    execution.average_duration_ms = round(sum(durations) / len(durations)) if durations else 0
    execution.status = 'failed' if failures or not details else 'passed'
    execution.message = (
        f'监控执行完成，共 {len(details)} 个接口，失败 {len(failures)} 个'
        if details else '未找到启用的监控接口'
    )
    execution.finished_at = timezone.now()
    execution.save(update_fields=['interface_total', 'failure_count', 'average_duration_ms', 'status', 'message', 'finished_at'])

    if not details:
        MonitorAlarm.objects.create(
            task=task,
            execution=execution,
            level='warning',
            message='监控任务未配置可执行接口',
        )

    task.status = execution.status
    task.next_run_time = calculate_next_run_time(task, base_time=execution.finished_at)
    task.save(update_fields=['status', 'next_run_time', 'updated_at'])
    task._prefetched_objects_cache = {}
    return execution


def retry_monitor_detail(source):
    api_config = None
    source_kind = 'monitor'
    monitor_config = None
    if source.source_api_config_id and source.source_interface_id:
        monitor_config = MonitorApiConfig.objects.filter(pk=source.source_api_config_id).first()
        api_config = ApiInterface.objects.filter(pk=source.source_interface_id).first()
    elif source.source_api_config_id:
        api_config = MonitorApiConfig.objects.filter(pk=source.source_api_config_id).first()
    elif source.source_interface_id:
        api_config = ApiInterface.objects.filter(pk=source.source_interface_id, can_execute_in_task=True).first()
        source_kind = 'automation'
    if not api_config:
        raise ValueError('原接口已不存在或未开启任务执行，无法获取最新接口信息进行重试')
    execution_no = (source.execution.task.executions.aggregate(value=Max('execution_no'))['value'] or 0) + 1
    execution = MonitorExecution.objects.create(task=source.execution.task, execution_no=execution_no, status='running')
    if monitor_config:
        detail, _access_token = _create_source_interface_detail(execution, monitor_config, api_config)
    else:
        detail, _access_token = _create_monitor_detail(execution, api_config, source=source_kind)
    execution.interface_total = 1
    execution.failure_count = 1 if detail.status == 'failed' else 0
    execution.average_duration_ms = detail.duration_ms or 0
    execution.status = detail.status
    execution.message = f'单接口重试完成：{detail.interface_name}'
    execution.finished_at = timezone.now()
    execution.save(update_fields=['interface_total', 'failure_count', 'average_duration_ms', 'status', 'message', 'finished_at'])
    if detail.status == 'failed':
        MonitorAlarm.objects.create(
            task=execution.task,
            execution=execution,
            detail=detail,
            level='error',
            message=f'{detail.interface_name} 重试失败：{detail.response_message}',
        )
    execution.task.status = execution.status
    execution.task.last_run_time = execution.finished_at
    execution.task.next_run_time = calculate_next_run_time(execution.task, base_time=execution.finished_at)
    execution.task.save(update_fields=['status', 'last_run_time', 'next_run_time', 'updated_at'])
    return detail
