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
    """Every action here is scoped to `request.user`'s own tasks -- this is
    the multi-tenant boundary for the whole app (Section: Data Isolation &
    Security). `list` never returns another user's rows at all; object-level
    actions (retrieve/update/destroy/favorite/archive/runs) additionally go
    through `IsOwner`, which turns a foreign task id into a 403 rather than
    ever serving its data.
    """

    # IsAuthenticated first: an anonymous request must 401 before IsOwner's
    # has_object_permission ever runs (it assumes request.user is real).
    permission_classes = [IsAuthenticated, IsOwner]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return TaskDetailSerializer
        return TaskSerializer

    def get_queryset(self):
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
                qs = qs.filter(is_archived=False)  # archived tasks are opt-in via ?archived=true
            return qs
        # Object-level actions: unfiltered queryset + IsOwner.has_object_permission
        # is what makes a foreign task id 403 instead of silently 404ing
        # (which would leak whether the id exists at all).
        return Task.objects.all()

    def perform_create(self, serializer):
        task = serializer.save(user=self.request.user)
        # Imported locally to avoid importing Celery's task registry (and by
        # extension the LLM/docker SDKs) at module load time -- keeps `manage.py
        # check` and plain CRUD usage fast and dependency-light.
        from .tasks import run_pipeline

        run_pipeline.delay(task.id)

    @action(detail=True, methods=["get"])
    def runs(self, request, pk=None):
        task = self.get_object()
        runs = task.runs.all().order_by("started_at")
        serializer = AgentRunSerializer(runs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def favorite(self, request, pk=None):
        task = self.get_object()
        task.is_favorite = not task.is_favorite
        task.save(update_fields=["is_favorite", "updated_at"])
        return Response(TaskSerializer(task).data)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        task = self.get_object()
        task.is_archived = not task.is_archived
        task.save(update_fields=["is_archived", "updated_at"])
        return Response(TaskSerializer(task).data)
