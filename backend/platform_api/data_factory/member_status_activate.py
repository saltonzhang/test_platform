from ..common.database import DatabaseClient
from .account_balance import DataFactoryError


def activate_member_status(email, *, environment_name='', database_profile=None):
    email_value = str(email or '').strip().lower()
    if not email_value or '@' not in email_value:
        raise DataFactoryError('请输入有效邮箱')

    sql = '''
        UPDATE member_extra
        SET last_active_time = NOW(),kyc_status = 2, kyc_passed = 1, kyc_level = 2
        WHERE member_id = (SELECT id FROM member WHERE email = %s LIMIT 1)
    '''

    try:
        client_kwargs = {'profile': database_profile} if database_profile else {}
        with DatabaseClient(**client_kwargs) as db:
            member = db.query_one('SELECT id FROM member WHERE email = %s LIMIT 1', (email_value,))
            if not member:
                raise DataFactoryError(f'未找到邮箱对应的用户: {email_value}')
            member_id_value = str(member.get('id') or '')
            affected_rows = db.execute_write(sql, (email_value,))
        affected_rows = int(affected_rows or 0)
        if not affected_rows:
            raise DataFactoryError(f'member_extra 未找到对应记录: email={email_value}')
        return {
            'environment_name': str(environment_name or ''),
            'member_id': member_id_value,
            'affected_rows': affected_rows,
            'status': 'passed',
            'message': f'用户状态已激活，影响行数 {affected_rows}',
        }
    except DataFactoryError:
        raise
    except Exception as exc:
        raise DataFactoryError(f'用户状态激活失败：{exc}') from exc
