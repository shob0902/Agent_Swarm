# WSGI entry point used by gunicorn and other sync servers to serve the project.
import os
from django.core.wsgi import get_wsgi_application
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "orchestrator.settings")
application = get_wsgi_application()
