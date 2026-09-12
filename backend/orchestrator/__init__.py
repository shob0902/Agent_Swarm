# Exposes the Celery app so it starts up together with Django.
from .celery import app as celery_app
__all__ = ("celery_app",)
