from collections import defaultdict

from django.db import migrations


def merge_split_tasks(apps, schema_editor):
    AutomationTask = apps.get_model('platform_api', 'AutomationTask')
    tasks = list(AutomationTask.objects.order_by('id'))
    groups = defaultdict(list)
    for task in tasks:
        created_second = task.created_at.replace(microsecond=0) if task.created_at else None
        groups[(task.name, task.task_type, task.environment_id, task.owner_id, created_second)].append(task)

    for group in groups.values():
        if len(group) < 2:
            continue
        primary = group[0]
        for duplicate in group[1:]:
            primary.modules.add(*duplicate.modules.values_list('id', flat=True))
            if duplicate.module_id:
                primary.modules.add(duplicate.module_id)
            duplicate.execution_details.update(task_id=primary.id)
            duplicate.delete()
        primary.status = (
            'failed' if any(item.status == 'failed' for item in group)
            else 'running' if any(item.status == 'running' for item in group)
            else 'passed' if all(item.status == 'passed' for item in group)
            else 'pending'
        )
        primary.save(update_fields=['status', 'updated_at'])


class Migration(migrations.Migration):

    dependencies = [
        ('platform_api', '0016_automationtask_modules_alter_automationtask_module'),
    ]

    operations = [
        migrations.RunPython(merge_split_tasks, migrations.RunPython.noop),
    ]
