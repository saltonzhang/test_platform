from django.db import migrations


VIEW_PERMISSION = 'automation.scene_package.view'
MANAGE_PERMISSION = 'automation.scene_package.manage'


def add_scene_package_permissions(apps, schema_editor):
    Role = apps.get_model('platform_api', 'Role')
    for role in Role.objects.all():
        permissions = role.permissions if isinstance(role.permissions, list) else []
        updated = list(permissions)
        if role.code == 'admin' or 'monitor.api.view' in updated or 'automation.view' in updated and ('automation.create' in updated or 'automation.edit' in updated):
            if VIEW_PERMISSION not in updated:
                updated.append(VIEW_PERMISSION)
        if role.code == 'admin' or 'monitor.api.manage' in updated or 'automation.delete' in updated:
            if MANAGE_PERMISSION not in updated:
                updated.append(MANAGE_PERMISSION)
        if updated != permissions:
            role.permissions = updated
            role.save(update_fields=['permissions'])


class Migration(migrations.Migration):
    dependencies = [('platform_api', '0042_monitorscenepackage_monitorscenepackageitem')]
    operations = [migrations.RunPython(add_scene_package_permissions, migrations.RunPython.noop)]
