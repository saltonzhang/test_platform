from ..common.database import query_one
from .account_balance import DataFactoryError


def query_member_by_email(email, *, environment_name=''):
    normalized_email = str(email or '').strip().lower()
    if not normalized_email:
        raise DataFactoryError('请输入会员邮箱')
    try:
        row = query_one(
            'SELECT id, uuid, id_number, email, nickname FROM member WHERE email = %s LIMIT 1',
            (normalized_email,),
        )
    except Exception as exc:
        raise DataFactoryError(f'查询用户信息失败：{exc}') from exc
    if not row:
        raise DataFactoryError('未找到该邮箱对应的用户')
    return {
        'environment_name': str(environment_name or ''),
        'email': str(row.get('email') or normalized_email),
        'uid': str(row.get('uuid') or ''),
        'cpf': str(row.get('id_number') or ''),
        'member_id': str(row.get('id') or ''),
        'nickname': str(row.get('nickname') or ''),
    }
