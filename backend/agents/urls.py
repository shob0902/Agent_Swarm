# Routes the /tasks REST endpoints through a DRF router, plus the signed /runner endpoints for the GitHub Actions runner.
from django.urls import path
from rest_framework.routers import DefaultRouter
from .runner_api import RunnerRunDetailView, RunnerRunListView, RunnerTaskView
from .views import TaskViewSet
router = DefaultRouter()
router.register(r"tasks", TaskViewSet, basename="task")
urlpatterns = router.urls + [
    path("runner/tasks/<int:task_id>/", RunnerTaskView.as_view(), name="runner-task"),
    path("runner/tasks/<int:task_id>/runs/", RunnerRunListView.as_view(), name="runner-runs"),
    path("runner/tasks/<int:task_id>/runs/<int:run_id>/", RunnerRunDetailView.as_view(), name="runner-run-detail"),
]
