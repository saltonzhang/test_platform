from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('platform_api', '0043_scene_package_permissions'),
    ]

    operations = [
        migrations.AddField(
            model_name='automationtask',
            name='scene_interface_order',
            field=models.JSONField(blank=True, default=list, verbose_name='场景接口执行顺序'),
        ),
        migrations.AddField(
            model_name='automationtask',
            name='scene_package',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='automation_tasks', to='platform_api.monitorscenepackage', verbose_name='来源场景包'),
        ),
    ]
