from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('platform_api', '0040_seed_environment_packages'),
    ]

    operations = [
        migrations.AddField(
            model_name='environmentpackage',
            name='database_profile',
            field=models.CharField(blank=True, default='', max_length=100, verbose_name='数据库配置标识'),
        ),
    ]
