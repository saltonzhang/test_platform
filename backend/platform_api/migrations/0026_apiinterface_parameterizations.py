from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('platform_api', '0025_classify_interface_token_headers')]
    operations = [migrations.AddField(
        model_name='apiinterface',
        name='parameterizations',
        field=models.JSONField(blank=True, default=list, verbose_name='参数化配置'),
    )]
