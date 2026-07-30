from django.db import migrations, models


def copy_source_interface_ids(apps, schema_editor):
    MonitorApiConfig = apps.get_model('platform_api', 'MonitorApiConfig')
    for config in MonitorApiConfig.objects.exclude(source_interface_id=None):
        if config.source_interface_ids:
            continue
        config.source_interface_ids = [config.source_interface_id]
        config.save(update_fields=['source_interface_ids'])


class Migration(migrations.Migration):
    dependencies = [
        ('platform_api', '0019_automationtask_notification_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='monitorapiconfig',
            name='source_interface_ids',
            field=models.JSONField(blank=True, default=list, verbose_name='来源接口ID列表'),
        ),
        migrations.RunPython(copy_source_interface_ids, migrations.RunPython.noop),
    ]
