# Top-level URL map wiring up the admin, the auth routes and the agents API.
from django.contrib import admin
from django.urls import include, path
from .health import health
urlpatterns = [
    path("api/health/", health, name="health"),
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/", include("agents.urls")),
]
