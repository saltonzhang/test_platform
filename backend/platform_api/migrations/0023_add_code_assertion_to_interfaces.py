from django.db import migrations


def add_code_assertion(apps, schema_editor):
    ApiInterface = apps.get_model('platform_api', 'ApiInterface')
    for interface in ApiInterface.objects.all().iterator():
        assertions = dict(interface.assertions or {})
        assertions['json_path'] = 'code'
        assertions['expected_value'] = 0
        interface.assertions = assertions
        interface.save(update_fields=['assertions'])


def remove_code_assertion(apps, schema_editor):
    ApiInterface = apps.get_model('platform_api', 'ApiInterface')
    for interface in ApiInterface.objects.all().iterator():
        assertions = dict(interface.assertions or {})
        if assertions.get('json_path') == 'code':
            assertions.pop('json_path', None)
            assertions.pop('expected_value', None)
            interface.assertions = assertions
            interface.save(update_fields=['assertions'])


class Migration(migrations.Migration):
    dependencies = [('platform_api', '0022_apiinterface_reference_enabled_and_more')]

    operations = [migrations.RunPython(add_code_assertion, remove_code_assertion)]
