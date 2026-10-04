# Adds the execution-state, test/review and GitHub pull-request fields that replace Celery task state.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agents', '0004_alter_agentrun_provider'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='base_branch',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='task',
            name='branch_name',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='task',
            name='commit_sha',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='task',
            name='completed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='task',
            name='current_agent',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
        migrations.AddField(
            model_name='task',
            name='dispatched_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='task',
            name='error_message',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='task',
            name='executor',
            field=models.CharField(blank=True, choices=[('github_actions', 'github_actions'), ('local', 'local')], default='', max_length=20),
        ),
        migrations.AddField(
            model_name='task',
            name='final_result',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='task',
            name='plan',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='task',
            name='pr_error',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='task',
            name='pr_number',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='task',
            name='pr_state',
            field=models.CharField(blank=True, choices=[('', 'none'), ('creating', 'creating'), ('open', 'open'), ('closed', 'closed'), ('merged', 'merged'), ('skipped', 'skipped'), ('failed', 'failed')], default='', max_length=20),
        ),
        migrations.AddField(
            model_name='task',
            name='pr_url',
            field=models.URLField(blank=True, default='', max_length=500),
        ),
        migrations.AddField(
            model_name='task',
            name='retry_count',
            field=models.IntegerField(default=0, help_text='Coder attempts beyond the first, across all cycles'),
        ),
        migrations.AddField(
            model_name='task',
            name='review_cycles',
            field=models.IntegerField(default=0, help_text='Reviewer rejections that sent the work back to the Coder'),
        ),
        migrations.AddField(
            model_name='task',
            name='review_result',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='task',
            name='review_status',
            field=models.CharField(blank=True, choices=[('', 'not run'), ('pending', 'pending'), ('approved', 'approved'), ('rejected', 'rejected')], default='', max_length=20),
        ),
        migrations.AddField(
            model_name='task',
            name='started_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='task',
            name='test_results',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='task',
            name='test_status',
            field=models.CharField(blank=True, choices=[('', 'not run'), ('pending', 'pending'), ('passed', 'passed'), ('failed', 'failed'), ('skipped', 'skipped')], default='', max_length=20),
        ),
        migrations.AddField(
            model_name='task',
            name='workflow_run_url',
            field=models.URLField(blank=True, default='', max_length=500),
        ),
        migrations.AlterField(
            model_name='agentrun',
            name='agent_type',
            field=models.CharField(choices=[('analyzer', 'analyzer'), ('planner', 'planner'), ('coder', 'coder'), ('tester', 'tester'), ('reviewer', 'reviewer'), ('github', 'github')], max_length=20),
        ),
        migrations.AlterField(
            model_name='task',
            name='status',
            field=models.CharField(choices=[('pending', 'pending'), ('queued', 'queued'), ('analyzing', 'analyzing'), ('planning', 'planning'), ('coding', 'coding'), ('testing', 'testing'), ('review', 'review'), ('publishing', 'publishing'), ('done', 'done'), ('failed', 'failed')], default='pending', max_length=20),
        ),
    ]
