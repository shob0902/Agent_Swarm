# Adds the checkpoint, resume stage and attempt counter that let a failed task be retried from the stage that failed.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agents', '0005_pipeline_state_and_pull_requests'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='attempt',
            field=models.IntegerField(default=1, help_text='How many times this task has been executed'),
        ),
        migrations.AddField(
            model_name='task',
            name='checkpoint',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='task',
            name='resume_from',
            field=models.CharField(blank=True, default='', help_text='Stage the current run resumes at; blank = full run', max_length=20),
        ),
    ]
