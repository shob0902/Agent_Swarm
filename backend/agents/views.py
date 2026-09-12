# REST API viewset for tasks, scoped so a user only ever sees their own rows.
from django.db.models import Q
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import AgentRun, Task
from .permissions import IsOwner
from .serializers import AgentRunSerializer, TaskDetailSerializer, TaskSerializer
class TaskViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    # Full CRUD for tasks plus the favorite, archive and runs sub-actions.
    permission_classes = [IsAuthenticated, IsOwner]
    def get_serializer_class(self):
        # Uses the detail serializer for retrieve so the response includes the agent runs.
        if self.action == "retrieve":
            return TaskDetailSerializer
        return TaskSerializer
    def get_queryset(self):
        # Filters the list view by owner plus the search, favorite and archived query params.
        if self.action == "list":
            qs = Task.objects.filter(user=self.request.user)
            search = self.request.query_params.get("search")
            if search:
                qs = qs.filter(Q(title__icontains=search) | Q(description__icontains=search))
            favorite = self.request.query_params.get("favorite")
            if favorite is not None:
                qs = qs.filter(is_favorite=favorite.lower() in ("1", "true", "yes"))
            archived = self.request.query_params.get("archived")
            if archived is not None:
                qs = qs.filter(is_archived=archived.lower() in ("1", "true", "yes"))
            else:
                qs = qs.filter(is_archived=False)
            return qs
        return Task.objects.all()
    def perform_create(self, serializer):
        # Saves the task against the current user and kicks off the Celery pipeline.
        task = serializer.save(user=self.request.user)
        from .tasks import run_pipeline
        run_pipeline.delay(task.id)
    @action(detail=True, methods=["get"])
    def runs(self, request, pk=None):
        # Returns the task's agent runs in the order they started.
        task = self.get_object()
        runs = task.runs.all().order_by("started_at")
        serializer = AgentRunSerializer(runs, many=True)
        return Response(serializer.data)
    @action(detail=True, methods=["post"])
    def favorite(self, request, pk=None):
        # Toggles the favorite flag on the task.
        task = self.get_object()
        task.is_favorite = not task.is_favorite
        task.save(update_fields=["is_favorite", "updated_at"])
        return Response(TaskSerializer(task).data)
    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        # Toggles the archived flag on the task.
        task = self.get_object()
        task.is_archived = not task.is_archived
        task.save(update_fields=["is_archived", "updated_at"])
        return Response(TaskSerializer(task).data)
