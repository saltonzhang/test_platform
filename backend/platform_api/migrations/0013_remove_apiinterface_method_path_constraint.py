from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('platform_api', '0012_apiinterface_api_type_and_more'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='apiinterface',
            name='uniq_api_method_path',
        ),
    ]
