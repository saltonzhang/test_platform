from ..common.database import query_one
from .account_balance import DataFactoryError


def query_member_by_email(search_term, *, environment_name='', database_profile=None):
    normalized_term = str(search_term or '').strip()
    if not normalized_term:
        raise DataFactoryError('请输入邮箱或昵称')
    try:
        query_kwargs = {'profile': database_profile} if database_profile else {}
        row = query_one(
            'SELECT id, uuid, id_number, email, nickname FROM member WHERE email = %s OR nickname = %s LIMIT 1',
            (normalized_term.lower(), normalized_term),
            **query_kwargs,
        )
    except Exception as exc:
        raise DataFactoryError(f'查询用户信息失败：{exc}') from exc
    if not row:
        raise DataFactoryError('未找到匹配邮箱或昵称的用户')
    return {
        'environment_name': str(environment_name or ''),
        'email': str(row.get('email') or ''),
        'uid': str(row.get('uuid') or ''),
        'cpf': str(row.get('id_number') or ''),
        'member_id': str(row.get('id') or ''),
        'nickname': str(row.get('nickname') or ''),
    }
