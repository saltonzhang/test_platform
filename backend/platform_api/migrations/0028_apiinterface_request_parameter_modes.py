from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('platform_api', '0022_automationtask_interfaces')]

    operations = [
        migrations.AddField(
            model_name='apiinterface',
            name='request_parameter_mode',
            field=models.CharField(choices=[('template', '模板参数化'), ('full', '全参数化')], default='template', max_length=20, verbose_name='请求参数模式'),
        ),
        migrations.AddField(
            model_name='apiinterface',
            name='full_parameterizations',
            field=models.JSONField(blank=True, default=list, verbose_name='全参数化配置'),
        ),
    ]
