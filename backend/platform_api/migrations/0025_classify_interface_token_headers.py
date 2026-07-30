from django.db import migrations


def classify_token_headers(apps, schema_editor):
    ApiInterface = apps.get_model('platform_api', 'ApiInterface')
    for interface in ApiInterface.objects.all().iterator():
        headers = dict(interface.headers or {})
        for key in list(headers):
            if key.lower() in {'authorization', 'x-token', 'x-access-token'}:
                headers.pop(key)
        is_backend = interface.path.startswith('/api/v2') or interface.path == '/sport/v1/load'
        headers['x-token' if is_backend else 'authorization'] = ''
        interface.headers = headers
        interface.save(update_fields=['headers'])


class Migration(migrations.Migration):
    dependencies = [('platform_api', '0024_normalize_interface_token_headers')]
    operations = [migrations.RunPython(classify_token_headers, migrations.RunPython.noop)]
