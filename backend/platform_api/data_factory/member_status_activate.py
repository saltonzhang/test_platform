from ..common.database import DatabaseClient
from .account_balance import DataFactoryError


def activate_member_status(member_id, *, environment_name=''):
    member_id_value = str(member_id or '').strip()
    if not member_id_value:
        raise DataFactoryError('请输入 member_id')
    if not member_id_value.isdigit():
        raise DataFactoryError('member_id 必须是数字')

    sql = '''
        UPDATE member_extra
        SET last_active_time = NOW()
        WHERE member_id = %s
    '''

    try:
        with DatabaseClient() as db:
            affected_rows = db.execute_write(sql, (member_id_value,))
        affected_rows = int(affected_rows or 0)
        if not affected_rows:
            raise DataFactoryError(f'member_extra 未找到对应记录: member_id={member_id_value}')
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
