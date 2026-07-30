from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


def success(data=None, message='success', status=200):
    return Response({'code': 200, 'message': message, 'data': data}, status=status)


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        return response
    message = '请求失败'
    if isinstance(response.data, dict):
        detail = response.data.get('detail')
        if detail:
            message = str(detail)
        else:
            first_value = next(iter(response.data.values()), message)
            if isinstance(first_value, list) and first_value:
                message = str(first_value[0])
            else:
                message = str(first_value)
    return Response({'code': response.status_code, 'message': message, 'data': response.data}, status=response.status_code)
