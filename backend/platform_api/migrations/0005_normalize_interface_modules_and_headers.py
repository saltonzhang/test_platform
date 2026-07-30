from django.db import migrations


def normalize_interfaces(apps, schema_editor):
    ApiInterface = apps.get_model('platform_api', 'ApiInterface')
    ApiInterface.objects.filter(module_name='用户服务').update(module_name='个人中心')
    ApiInterface.objects.filter(module_name='环境配置').update(module_name='活动')
    for interface in ApiInterface.objects.all():
        headers = dict(interface.headers or {})
        if headers.get('Content-Type') in (None, 'application/json'):
            headers['Content-Type'] = 'application/json; charset=utf-8'
            interface.headers = headers
            interface.save(update_fields=['headers'])


class Migration(migrations.Migration):
    dependencies = [('platform_api', '0004_apiinterface_headers_apiinterface_request_params')]
    operations = [migrations.RunPython(normalize_interfaces, migrations.RunPython.noop)]
