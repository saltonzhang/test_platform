from django.db import migrations


BUSINESS_MODULE_NAMES = ['首页', '个人中心', '游戏', '赛事', '活动']


def reorder_business_modules(apps, schema_editor):
    AutomationModule = apps.get_model('platform_api', 'AutomationModule')
    for app in ['frontend', 'backend']:
        for sort_order, name in enumerate(BUSINESS_MODULE_NAMES):
            module, _ = AutomationModule.objects.get_or_create(
                app=app,
                name=name,
                defaults={'sort_order': sort_order},
            )
            if module.sort_order != sort_order:
                module.sort_order = sort_order
                module.save(update_fields=['sort_order'])


class Migration(migrations.Migration):
    dependencies = [('platform_api', '0014_add_home_automation_module')]
    operations = [migrations.RunPython(reorder_business_modules, migrations.RunPython.noop)]
