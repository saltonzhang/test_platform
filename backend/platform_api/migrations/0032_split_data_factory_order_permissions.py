from django.db import migrations


LEGACY_PERMISSION = 'data_factory.order_result_push'
SPLIT_PERMISSIONS = (
    'data_factory.rollback_settlement',
    'data_factory.bet_cancel',
    'data_factory.rollback_bet_cancel',
)


def preserve_legacy_order_operation_access(apps, schema_editor):
    Role = apps.get_model('platform_api', 'Role')
    for role in Role.objects.all().iterator():
        permissions = role.permissions if isinstance(role.permissions, list) else []
        if LEGACY_PERMISSION not in permissions:
            continue
        updated_permissions = [*permissions]
        for permission in SPLIT_PERMISSIONS:
            if permission not in updated_permissions:
                updated_permissions.append(permission)
        if updated_permissions != permissions:
            role.permissions = updated_permissions
            role.save(update_fields=['permissions'])


class Migration(migrations.Migration):
    dependencies = [
        ('platform_api', '0031_add_user_platform_account'),
    ]

    operations = [
        migrations.RunPython(preserve_legacy_order_operation_access, migrations.RunPython.noop),
    ]
