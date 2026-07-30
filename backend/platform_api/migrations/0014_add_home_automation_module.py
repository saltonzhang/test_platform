from django.db import migrations


MODULE_NAMES = ['首页', '个人中心', '赛事', '游戏', '活动']


def add_home_module(apps, schema_editor):
    AutomationModule = apps.get_model('platform_api', 'AutomationModule')
    for app in ['frontend', 'backend']:
        for sort_order, name in enumerate(MODULE_NAMES):
            module, _ = AutomationModule.objects.get_or_create(
                app=app,
                name=name,
                defaults={'sort_order': sort_order},
            )
            if module.sort_order != sort_order:
                module.sort_order = sort_order
                module.save(update_fields=['sort_order'])


class Migration(migrations.Migration):
    dependencies = [('platform_api', '0013_remove_apiinterface_method_path_constraint')]
    operations = [migrations.RunPython(add_home_module, migrations.RunPython.noop)]
