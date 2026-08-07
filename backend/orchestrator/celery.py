"""Celery application config for the orchestrator project.

Redis is used as both the broker and the result backend (see settings.py /
REDIS_URL). Run the worker with:

    celery -A orchestrator worker --loglevel=info -P solo   # Windows needs -P solo
"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "orchestrator.settings")

app = Celery("orchestrator")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
