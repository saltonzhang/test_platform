from django.db import migrations


def seed_packages(apps, schema_editor):
    Package = apps.get_model('platform_api', 'EnvironmentPackage')
    Environment = apps.get_model('platform_api', 'Environment')
    for environment in Environment.objects.all():
        name = environment.name
        package_name = '前后台测试环境包' if ('前台' in name or '后台' in name) and '测试' in name else name
        package_type = 'frontend_backend' if package_name == '前后台测试环境包' else 'custom'
        package, _ = Package.objects.get_or_create(name=package_name, defaults={'package_type': package_type, 'description': '由原环境配置自动归档'})
        environment.package_id = package.id
        environment.save(update_fields=['package'])


class Migration(migrations.Migration):
    dependencies = [('platform_api', '0039_environmentpackage_environment_package')]
    operations = [migrations.RunPython(seed_packages, migrations.RunPython.noop)]
