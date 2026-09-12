# Adds the owner link plus the rename, favorite and archive fields to Task.
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('agents', '0002_task_github_url'),
    ]
    operations = [
        migrations.AddField(
            model_name='task',
            name='user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tasks', to=settings.AUTH_USER_MODEL, default=None),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='task',
            name='title',
            field=models.CharField(blank=True, help_text='User-editable; falls back to a truncated description when blank', max_length=200),
        ),
        migrations.AddField(
            model_name='task',
            name='is_favorite',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='task',
            name='is_archived',
            field=models.BooleanField(default=False),
        ),
    ]
