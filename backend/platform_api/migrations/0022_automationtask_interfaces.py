from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('platform_api', '0027_datafactoryexecution')]

    operations = [
        migrations.AddField(
            model_name='automationtask',
            name='interfaces',
            field=models.ManyToManyField(blank=True, related_name='automation_tasks', to='platform_api.apiinterface', verbose_name='场景测试接口'),
        ),
    ]
