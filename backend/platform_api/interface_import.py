import ast
import json
import re
from urllib.parse import parse_qsl, urlsplit

from .constants import BUSINESS_MODULE_NAMES


MAX_IMPORT_TEXT_LENGTH = 2 * 1024 * 1024
MAX_IMPORT_ITEMS = 500
_FETCH_PATTERN = re.compile(r'\bfetch\s*\(', re.IGNORECASE)
_TRAILING_COMMA_PATTERN = re.compile(r',\s*([}\]])')
_IGNORED_HEADERS = {
    'accept-language', 'access-control-allow-origin-type', 'connection', 'content-length',
    'cookie', 'host', 'origin', 'priority', 'referer', 'sec-ch-ua', 'sec-ch-ua-mobile',
    'sec-ch-ua-platform', 'sec-fetch-dest', 'sec-fetch-mode', 'sec-fetch-site', 'user-agent',
}


class InterfaceImportError(ValueError):
    pass


def _read_balanced(text, opening_index, opening='{', closing='}'):
    depth = 0
    quote = None
    escaped = False
    for index in range(opening_index, len(text)):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {'"', "'", '`'}:
            quote = char
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return text[opening_index:index + 1]
    raise InterfaceImportError('fetch 配置括号不完整')


def _split_top_level(value, separator=','):
    pieces, start, depth, quote, escaped = [], 0, 0, None, False
    for index, char in enumerate(value):
        if quote:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {'"', "'", '`'}:
            quote = char
        elif char in '([{':
            depth += 1
        elif char in ')]}':
            depth -= 1
        elif char == separator and depth == 0:
            pieces.append(value[start:index].strip())
            start = index + 1
    pieces.append(value[start:].strip())
    return pieces


def _decode_string(value):
    value = value.strip()
    if len(value) < 2 or value[0] not in {'"', "'", '`'} or value[-1] != value[0]:
        raise InterfaceImportError('fetch URL 必须是字符串')
    if value[0] == '`':
        return value[1:-1]
    try:
        return ast.literal_eval(value)
    except (SyntaxError, ValueError) as exc:
        raise InterfaceImportError('fetch URL 字符串格式不正确') from exc


def _decode_object(value):
    normalized = _TRAILING_COMMA_PATTERN.sub(r'\1', value.strip())
    normalized = re.sub(r'\bundefined\b', 'null', normalized)
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError:
        # Accept common copied snippets that use single-quoted Python-like objects.
        try:
            parsed = ast.literal_eval(normalized)
        except (SyntaxError, ValueError) as exc:
            raise InterfaceImportError('fetch 配置对象必须是有效 JSON') from exc
    if not isinstance(parsed, dict):
        raise InterfaceImportError('fetch 配置对象必须是 JSON 对象')
    return parsed


def _parse_fetch_calls(text):
    calls = []
    for match in _FETCH_PATTERN.finditer(text):
        call = _read_balanced(text, match.end() - 1, '(', ')')[1:-1]
        parts = _split_top_level(call)
        if not parts or not parts[0]:
            raise InterfaceImportError('fetch 缺少请求 URL')
        url = _decode_string(parts[0])
        options = _decode_object(parts[1]) if len(parts) > 1 and parts[1] else {}
        calls.append((url, options))
    if not calls:
        raise InterfaceImportError('未识别到 fetch(...) 请求，请粘贴完整请求文本')
    if len(calls) > MAX_IMPORT_ITEMS:
        raise InterfaceImportError(f'单次最多批量录入 {MAX_IMPORT_ITEMS} 个接口')
    return calls


def _infer_module(url):
    parsed = urlsplit(url)
    target = f'{parsed.netloc}{parsed.path}'.lower()
    if any(item in target for item in ('/sport/', '/match', '/tournament', '/event')):
        return '赛事'
    if any(item in target for item in ('/game', '/casino', '/jackpot')):
        return '游戏'
    if any(item in target for item in ('/promotion', '/activity', '/banner')):
        return '活动'
    if any(item in target for item in ('/member/', '/user', '/auth', '/account')):
        return '个人中心'
    if 'admin' in parsed.netloc.lower() or '/admin/' in parsed.path.lower():
        return '后台'
    return '首页'


def _normalize_headers(headers):
    if not isinstance(headers, dict):
        raise InterfaceImportError('Headers 必须是 JSON 对象')
    normalized = {}
    for key, value in headers.items():
        name = str(key).strip()
        if not name or name.lower() in _IGNORED_HEADERS or name.lower() in {'authorization', 'x-token', 'x-access-token'}:
            continue
        normalized[name] = value
    return normalized


def _request_parts(url, method, options):
    parsed = urlsplit(url)
    path = parsed.path or '/'
    if not path.startswith('/'):
        path = f'/{path}'
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    query = {}
    for key, value in query_pairs:
        if key in query:
            query[key] = query[key] if isinstance(query[key], list) else [query[key]]
            query[key].append(value)
        else:
            query[key] = value

    params = {'query': query} if method == 'GET' and query else {}
    body = options.get('body')
    if method != 'GET' and body not in (None, ''):
        if isinstance(body, dict):
            params = {'body': body}
        elif isinstance(body, str):
            try:
                parsed_body = json.loads(body)
            except json.JSONDecodeError:
                parsed_body = {'raw': body}
            params = {'body': parsed_body if isinstance(parsed_body, dict) else {'value': parsed_body}}
    return path, params


def parse_fetch_text(text, module_name=''):
    if not isinstance(text, str) or not text.strip():
        raise InterfaceImportError('请输入需要批量录入的 fetch 文本')
    if len(text) > MAX_IMPORT_TEXT_LENGTH:
        raise InterfaceImportError('批量录入文本不能超过 2 MB')
    module_name = str(module_name or '').strip()
    if module_name and module_name not in BUSINESS_MODULE_NAMES:
        raise InterfaceImportError('请选择有效的业务模块')
    parsed = []
    for url, options in _parse_fetch_calls(text):
        if not url.startswith(('http://', 'https://')):
            raise InterfaceImportError(f'仅支持 http/https URL：{url}')
        method = str(options.get('method', 'GET')).upper().strip()
        if method not in {'GET', 'POST', 'PUT', 'PATCH', 'DELETE'}:
            raise InterfaceImportError(f'不支持的请求方法：{method}')
        path, request_params = _request_parts(url, method, options)
        endpoint_name = urlsplit(url).path.rstrip('/').split('/')[-1] or method
        parsed.append({
            'name': endpoint_name[:200],
            'method': method,
            'path': path,
            'module_name': module_name or _infer_module(url),
            'api_type': '系统录入',
            'description': '批量录入',
            'headers': _normalize_headers(options.get('headers', {})),
            'request_params': request_params,
            'parameterizations': [],
            'assertions': {'status_code': 200, 'timeout_seconds': 3, 'json_path': 'code', 'expected_value': 0},
            'reference_enabled': False,
            'reference_interface': None,
            'response_extracts': [],
            'can_execute_in_task': True,
        })
    return parsed
