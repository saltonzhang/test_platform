from django.db import migrations


def normalize_api_interface_type(apps, schema_editor):
    ApiInterface = apps.get_model('platform_api', 'ApiInterface')
    ApiInterface.objects.exclude(api_type='系统录入').update(api_type='系统录入')


class Migration(migrations.Migration):
    dependencies = [
        ('platform_api', '0020_monitorapiconfig_source_interface_ids'),
    ]

    operations = [
        migrations.RunPython(normalize_api_interface_type, migrations.RunPython.noop),
    ]
