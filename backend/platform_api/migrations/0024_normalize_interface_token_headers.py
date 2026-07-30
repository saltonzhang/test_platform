from django.db import migrations


def normalize_token_headers(apps, schema_editor):
    ApiInterface = apps.get_model('platform_api', 'ApiInterface')
    AutomationModule = apps.get_model('platform_api', 'AutomationModule')
    backend_modules = set(AutomationModule.objects.filter(app='backend').values_list('name', flat=True))
    for interface in ApiInterface.objects.all().iterator():
        headers = dict(interface.headers or {})
        for key in list(headers):
            if key.lower() in {'authorization', 'x-token', 'x-access-token'}:
                headers.pop(key)
        headers['x-token' if interface.module_name in backend_modules else 'authorization'] = ''
        interface.headers = headers
        interface.save(update_fields=['headers'])


class Migration(migrations.Migration):
    dependencies = [('platform_api', '0023_add_code_assertion_to_interfaces')]
    operations = [migrations.RunPython(normalize_token_headers, migrations.RunPython.noop)]
