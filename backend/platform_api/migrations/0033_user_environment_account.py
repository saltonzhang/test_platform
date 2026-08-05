import django.db.models.deletion
from django.db import migrations, models


def copy_platform_accounts_to_environments(apps, schema_editor):
    User = apps.get_model('platform_api', 'User')
    Environment = apps.get_model('platform_api', 'Environment')
    UserEnvironmentAccount = apps.get_model('platform_api', 'UserEnvironmentAccount')
    environments = list(Environment.objects.values_list('id', flat=True))
    mappings = []
    for user in User.objects.exclude(platform_account='').iterator():
        account = str(user.platform_account).strip()
        if not account:
            continue
        mappings.extend(
            UserEnvironmentAccount(user_id=user.id, environment_id=environment_id, account=account)
            for environment_id in environments
        )
    if mappings:
        UserEnvironmentAccount.objects.bulk_create(mappings, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [
        ('platform_api', '0032_split_data_factory_order_permissions'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserEnvironmentAccount',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('account', models.CharField(max_length=100, verbose_name='目标系统账号')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('environment', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='user_accounts', to='platform_api.environment', verbose_name='运行环境')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='environment_accounts', to='platform_api.user', verbose_name='用户')),
            ],
            options={
                'verbose_name': '用户环境账号',
                'verbose_name_plural': '用户环境账号',
                'db_table': 'aibet_user_environment_account',
                'db_table_comment': '用户运行环境账号配置表',
            },
        ),
        migrations.AddConstraint(
            model_name='userenvironmentaccount',
            constraint=models.UniqueConstraint(fields=('user', 'environment'), name='uniq_user_environment_account'),
        ),
        migrations.RunPython(copy_platform_accounts_to_environments, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='user',
            name='platform_account',
        ),
    ]
