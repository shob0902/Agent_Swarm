from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import AgentRun, Task
from .serializers import AgentRunSerializer, TaskDetailSerializer, TaskSerializer


class TaskViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = Task.objects.all()

    def get_serializer_class(self):
        if self.action == "retrieve":
            return TaskDetailSerializer
        return TaskSerializer

    def perform_create(self, serializer):
        task = serializer.save()
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
