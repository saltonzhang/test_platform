from django.db import migrations


TABLE_COMMENTS = {
    'django_migrations': 'Django数据库迁移记录表',
    'django_content_type': 'Django内容类型表',
    'auth_permission': '系统权限定义表',
    'auth_group': 'Django用户组表',
    'auth_group_permissions': 'Django用户组权限关联表',
    'django_admin_log': 'Django后台操作日志表',
    'django_session': 'Django用户会话表',
    'aibet_user_groups': '用户与Django用户组关联表',
    'aibet_user_user_permissions': '用户与系统权限关联表',
}


def set_comments(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return
    quote = schema_editor.quote_name
    with schema_editor.connection.cursor() as cursor:
        for table, comment in TABLE_COMMENTS.items():
            cursor.execute(f'ALTER TABLE {quote(table)} COMMENT = %s', [comment])


def clear_comments(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return
    quote = schema_editor.quote_name
    with schema_editor.connection.cursor() as cursor:
        for table in TABLE_COMMENTS:
            cursor.execute(f'ALTER TABLE {quote(table)} COMMENT = %s', [''])


class Migration(migrations.Migration):
    dependencies = [
        ('platform_api', '0002_alter_environment_options_alter_role_options_and_more'),
        ('admin', '0003_logentry_add_action_flag_choices'),
        ('sessions', '0001_initial'),
    ]
    operations = [migrations.RunPython(set_comments, clear_comments)]
