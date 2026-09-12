# Sets up the Celery app that runs the agent pipeline in the background, backed by Redis.
import os
from celery import Celery
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "orchestrator.settings")
app = Celery("orchestrator")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
@app.task(bind=True)
def debug_task(self):
    # Prints the request, handy for checking the worker is picking jobs up.
    print(f"Request: {self.request!r}")
