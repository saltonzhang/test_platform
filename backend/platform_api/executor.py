import json
import uuid
from dataclasses import dataclass
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


@dataclass
class ExecutionOutcome:
    status: str
    duration_ms: int
    message: str
    access_token: str = ''
    response_log: str = ''


class ApiRequestExecutor:
    """Shared HTTP execution pipeline used by task runs and single-item retries."""

    def execute(self, *, url, method, headers, request_params, assertions=None, access_token='', login_url='', request_encoding='json', access_token_prefix='Bearer ', access_token_header=''):
        assertions = assertions or {}
        timeout_seconds = assertions.get('timeout_seconds', 3)
        request_headers = dict(headers or {})
        if access_token and access_token_header:
            preferred = access_token_header.lower()
            for key in list(request_headers):
                if key.lower() in {'authorization', 'x-token', 'x-access-token'} and key.lower() != preferred:
                    request_headers.pop(key)
            current_key = next((key for key in request_headers if key.lower() == preferred), access_token_header)
            request_headers[current_key] = f'{access_token_prefix}{access_token}'
        elif access_token:
            token_header = next((key for key in request_headers if key.lower() in {'x-token', 'x-access-token'}), None)
            authorization_header = next((key for key in request_headers if key.lower() == 'authorization'), None)
            if token_header:
                request_headers[token_header] = access_token
            elif authorization_header:
                request_headers[authorization_header] = f'{access_token_prefix}{access_token}'
            else:
                request_headers['Authorization'] = f'{access_token_prefix}{access_token}'
        request_params = self.get_request_params(method, request_params)
        payload = None
        if method != 'GET':
            if request_encoding == 'multipart':
                content_type, payload = self.encode_multipart_form_data(request_params)
                for key in list(request_headers):
                    if key.lower() == 'content-type':
                        request_headers.pop(key)
                request_headers['Content-Type'] = content_type
            else:
                payload = json.dumps(request_params, ensure_ascii=False).encode('utf-8')
        started_at = perf_counter()

        try:
            request = Request(url, data=payload, headers=request_headers, method=method)
            with urlopen(request, timeout=timeout_seconds) as response:
                body = response.read().decode('utf-8', errors='replace')
                passed, assertion_message = self.assert_response(response.status, body, assertions)
                duration_ms = self.elapsed_ms(started_at)
                if duration_ms > timeout_seconds * 1000:
                    passed = False
                    assertion_message = f'耗时断言失败，实际 {duration_ms} ms，阈值 {timeout_seconds * 1000:g} ms'
                token = self.extract_access_token(body) if self.is_login_url(url, login_url) and passed else ''
                message = f'HTTP {response.status} · {assertion_message}'
                if token:
                    message = f'HTTP {response.status} · 登录成功 · {assertion_message}'
                return ExecutionOutcome('passed' if passed else 'failed', duration_ms, message, token, body)
        except HTTPError as exc:
            body = exc.read().decode('utf-8', errors='replace')
            return ExecutionOutcome('failed', self.elapsed_ms(started_at), f'HTTP {exc.code}' + (f' · {body}' if body else ''), response_log=body)
        except TimeoutError:
            return ExecutionOutcome('failed', self.elapsed_ms(started_at), f'接口执行超时，阈值 {timeout_seconds:g} 秒', response_log='请求超时，未收到响应')
        except URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                return ExecutionOutcome('failed', self.elapsed_ms(started_at), f'接口执行超时，阈值 {timeout_seconds:g} 秒', response_log='请求超时，未收到响应')
            return ExecutionOutcome('failed', self.elapsed_ms(started_at), f'请求失败：{exc}', response_log=str(exc))
        except OSError as exc:
            return ExecutionOutcome('failed', self.elapsed_ms(started_at), f'请求失败：{exc}', response_log=str(exc))

    def assert_response(self, status_code, body, assertions):
        expected_status = assertions.get('status_code', 200)
        if isinstance(expected_status, list):
            status_passed = status_code in expected_status
        else:
            status_passed = status_code == expected_status
        if not status_passed:
            return False, f'状态码断言失败，实际 {status_code}，期望 {expected_status}'

        contains = assertions.get('body_contains')
        if contains and contains not in body:
            return False, f'响应内容断言失败，未包含 {contains}'

        json_path = assertions.get('json_path')
        if json_path:
            try:
                actual = self.read_json_path(json.loads(body), json_path)
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                return False, f'JSON 断言失败：{exc}'
            expected = assertions.get('expected_value')
            if actual != expected:
                return False, f'JSON 断言失败，{json_path} 实际为 {actual!r}，期望 {expected!r}'
        return True, '断言通过'

    @staticmethod
    def get_request_params(method, request_params):
        if not isinstance(request_params, dict):
            return {}
        wrapper = 'query' if method == 'GET' else 'body'
        wrapped_params = request_params.get(wrapper)
        return wrapped_params if isinstance(wrapped_params, dict) else request_params

    @staticmethod
    def encode_multipart_form_data(params):
        boundary = f'----AibetAuto{uuid.uuid4().hex}'
        lines = []
        for key, value in params.items():
            rendered_value = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            lines.extend((
                f'--{boundary}',
                f'Content-Disposition: form-data; name="{key}"',
                '',
                rendered_value,
            ))
        lines.extend((f'--{boundary}--', ''))
        return f'multipart/form-data; boundary={boundary}', '\r\n'.join(lines).encode('utf-8')

    @staticmethod
    def read_json_path(data, path):
        value = data
        for part in path.split('.'):
            value = value[int(part)] if isinstance(value, list) else value[part]
        return value

    @staticmethod
    def extract_access_token(body):
        try:
            payload = json.loads(body)
            data = payload.get('data', payload)
            if not isinstance(data, dict):
                return ''
            token = data.get('access') or data.get('access_token') or data.get('authorization') or data.get('token')
            if isinstance(token, dict):
                token = token.get('authorization') or token.get('access') or token.get('access_token') or token.get('token')
            return token if isinstance(token, str) else ''
        except (ValueError, AttributeError, TypeError):
            return ''

    @staticmethod
    def is_login_url(url, login_url=''):
        if login_url:
            configured = urlsplit(login_url).path.rstrip('/')
            actual = urlsplit(url).path.rstrip('/')
            return bool(configured) and actual == configured
        return urlsplit(url).path.rstrip('/').endswith('/api/v1/auth/login')

    @staticmethod
    def elapsed_ms(started_at):
        return max(1, round((perf_counter() - started_at) * 1000))


api_request_executor = ApiRequestExecutor()
