# Routes the /tasks REST endpoints through a DRF router.
from rest_framework.routers import DefaultRouter
from .views import TaskViewSet
router = DefaultRouter()
router.register(r"tasks", TaskViewSet, basename="task")
urlpatterns = router.urls
