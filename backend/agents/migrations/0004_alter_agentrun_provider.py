# Reorders the AgentRun provider choices after the move to a Groq-only pipeline.
from django.db import migrations, models
class Migration(migrations.Migration):
    dependencies = [
        ('agents', '0003_task_ownership'),
    ]
    operations = [
        migrations.AlterField(
            model_name='agentrun',
            name='provider',
            field=models.CharField(blank=True, choices=[('groq', 'groq'), ('none', 'none'), ('gemini', 'gemini')], default='none', max_length=20),
        ),
    ]
