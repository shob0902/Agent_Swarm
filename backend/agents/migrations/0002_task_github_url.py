# Generated for the local-path -> GitHub-URL switch (see services/repo.py).
# repo_path values were absolute filesystem paths on the old server host --
# not meaningful as URLs -- so this is a straight remove+add rather than a
# lossy rename.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agents', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='task',
            name='repo_path',
        ),
        migrations.AddField(
            model_name='task',
            name='github_url',
            field=models.CharField(default='', help_text='Public GitHub repo URL, e.g. https://github.com/owner/repo', max_length=500),
            preserve_default=False,
        ),
    ]
