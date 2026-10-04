# Signed callback API the GitHub Actions runner uses to read its task and write progress; no user auth, HMAC only.
from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView
from . import runner_auth
from .models import AgentRun, Task
from .serializers import AgentRunCreateSerializer, AgentRunFinishSerializer, RunnerTaskSerializer, TaskStateSerializer
class HasRunnerSignature(BasePermission):
    # Accepts a request only if it carries a fresh, valid HMAC signature over method, path and body.
    message = "Missing or invalid runner signature."
    def has_permission(self, request, view):
        # Verifies against RUNNER_SHARED_SECRET; with no secret configured, the whole API is closed.
        return runner_auth.verify(
            settings.RUNNER_SHARED_SECRET,
            request.method,
            request.path,
            request.body,
            request.headers.get(runner_auth.TIMESTAMP_HEADER, ""),
            request.headers.get(runner_auth.SIGNATURE_HEADER, ""),
            settings.RUNNER_SIGNATURE_MAX_AGE_SECONDS,
        )
class _RunnerView(APIView):
    # Base: signature auth instead of JWT cookies, and no browsable/session machinery.
    authentication_classes: list = []
    permission_classes = [HasRunnerSignature]
    def _finished(self, task: Task) -> Response:
        # 409 for any write to a task that already has an outcome, so a replayed or late request can't rewrite history.
        return Response({"detail": f"task is already {task.status}"}, status=status.HTTP_409_CONFLICT)
class RunnerTaskView(_RunnerView):
    # GET the task's inputs; PATCH its execution state.
    def get(self, request, task_id: int):
        # Returns description, repo URL and status.
        task = get_object_or_404(Task, pk=task_id)
        return Response(RunnerTaskSerializer(task).data)
    def patch(self, request, task_id: int):
        # Applies a whitelisted partial update of execution-state fields.
        task = get_object_or_404(Task, pk=task_id)
        if task.is_terminal:
            return self._finished(task)
        serializer = TaskStateSerializer(task, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"id": task.id, "status": task.status})
class RunnerRunListView(_RunnerView):
    # POST creates a pending AgentRun for the task.
    def post(self, request, task_id: int):
        # Records the start of an agent invocation and returns its id.
        task = get_object_or_404(Task, pk=task_id)
        if task.is_terminal:
            return self._finished(task)
        serializer = AgentRunCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        run = serializer.save(task=task, status="pending", output={})
        return Response({"id": run.id}, status=status.HTTP_201_CREATED)
class RunnerRunDetailView(_RunnerView):
    # PATCH records the outcome of a still-pending AgentRun.
    def patch(self, request, task_id: int, run_id: int):
        # Finishes the run once; later writes are rejected.
        run = get_object_or_404(AgentRun, pk=run_id, task_id=task_id)
        if run.status != "pending":
            return Response({"detail": f"run is already {run.status}"}, status=status.HTTP_409_CONFLICT)
        serializer = AgentRunFinishSerializer(run, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"id": run.id, "status": run.status})
