from django.db import migrations


MODULE_MAPPING = {
    'frontend': {
        '用户中心': '个人中心',
        '商家工作台': '赛事',
        '交易流程': '活动',
    },
    'backend': {
        '用户服务': '个人中心',
        '订单服务': '赛事',
        '支付服务': '游戏',
    },
}
MODULE_NAMES = ['个人中心', '赛事', '游戏', '活动']


def normalize_modules(apps, schema_editor):
    AutomationModule = apps.get_model('platform_api', 'AutomationModule')
    AutomationTask = apps.get_model('platform_api', 'AutomationTask')

    for app, mapping in MODULE_MAPPING.items():
        target_modules = {}
        for sort_order, name in enumerate(MODULE_NAMES):
            module, _ = AutomationModule.objects.get_or_create(
                app=app,
                name=name,
                defaults={'sort_order': sort_order},
            )
            if module.sort_order != sort_order:
                module.sort_order = sort_order
                module.save(update_fields=['sort_order'])
            target_modules[name] = module

        for old_name, new_name in mapping.items():
            old_module = AutomationModule.objects.filter(app=app, name=old_name).first()
            if old_module:
                AutomationTask.objects.filter(module=old_module).update(module=target_modules[new_name])
                old_module.delete()


class Migration(migrations.Migration):
    dependencies = [('platform_api', '0005_normalize_interface_modules_and_headers')]
    operations = [migrations.RunPython(normalize_modules, migrations.RunPython.noop)]
