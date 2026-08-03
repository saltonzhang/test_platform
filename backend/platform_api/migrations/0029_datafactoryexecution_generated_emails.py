from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('platform_api', '0028_apiinterface_request_parameter_modes')]

    operations = [
        migrations.AddField(
            model_name='datafactoryexecution',
            name='generated_emails',
            field=models.JSONField(blank=True, default=list, verbose_name='生成邮箱'),
        ),
    ]
