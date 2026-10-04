# REST API viewset for tasks, scoped so a user only ever sees their own rows.
import logging
from django.conf import settings
from django.db.models import Q
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .github.client import GitHubClient, GitHubError
from .github.repo_url import parse_github_url
from .models import AgentRun, Task
from .permissions import IsOwner
from .pipeline.dispatch import DispatchError, dispatch_task
from .pipeline.resume import STAGE_ORDER, effective_checkpoint, is_retryable, resume_point
from .serializers import AgentRunSerializer, TaskDetailSerializer, TaskSerializer
logger = logging.getLogger(__name__)
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
        # Saves the task and hands it to the executor (GitHub Actions or local); the web process never runs agents itself.
        task = serializer.save(user=self.request.user)
        try:
            dispatch_task(task)
        except DispatchError:
            # dispatch_task already stored the reason on the task; the client sees status=failed + error_message.
            pass
    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        # Re-runs a failed task from the stage that failed (or from scratch with {"from_start": true}),
        # reusing everything earlier stages produced instead of asking for the repo and request again.
        task = self.get_object()
        if not is_retryable(task):
            return Response({"detail": "Only a failed task, or one whose runner stopped reporting, can be retried."}, status=409)
        # A stale task's runner died without recording anything; treat it as a runner failure.
        failed_stage = (task.final_result or {}).get("stage", "") if task.status == "failed" else "runner"
        from_start = str(request.data.get("from_start", "")).lower() in ("1", "true", "yes")
        checkpoint = {} if from_start else effective_checkpoint(task)
        stage = "" if from_start else resume_point(failed_stage, checkpoint)
        _reset_for_retry(task, stage, checkpoint)
        task.save()
        try:
            dispatch_task(task)
        except DispatchError:
            pass
        task.refresh_from_db()
        return Response(TaskDetailSerializer(task).data)
    @action(detail=True, methods=["post"])
    def refresh_pr(self, request, pk=None):
        # Re-reads the PR from GitHub so the UI can show open / merged / closed.
        task = self.get_object()
        if not task.pr_number:
            return Response({"detail": "This task has no pull request."}, status=400)
        client = GitHubClient(settings.GITHUB_DISPATCH_TOKEN, settings.GITHUB_API_URL)
        try:
            pr = client.get_pull_request(parse_github_url(task.github_url).full_name, task.pr_number)
        except GitHubError as exc:
            logger.warning("Could not refresh PR for task %s: %s", task.id, exc)
            return Response({"detail": "Could not reach GitHub to refresh the pull request."}, status=502)
        task.pr_state = "merged" if pr.get("merged") else pr.get("state", task.pr_state)
        task.save(update_fields=["pr_state", "updated_at"])
        return Response(TaskSerializer(task).data)
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
def _reset_for_retry(task: Task, stage: str, checkpoint: dict) -> None:
    # Clears the failure and the state of every stage that will run again; keeps what earlier stages produced.
    order = ["", *STAGE_ORDER]
    rerun = set(order[order.index(stage):]) if stage in order else set(order)
    task.attempt += 1
    task.resume_from = stage
    task.checkpoint = checkpoint
    task.error_message = ""
    task.final_result = {}
    task.completed_at = None
    task.current_agent = ""
    if "" in rerun or "planner" in rerun:
        task.plan = {}
        task.retry_count = 0
        task.review_cycles = 0
    if rerun & {"", "planner", "coder", "tester"}:
        task.test_status, task.test_results = "", {}
    if rerun & {"", "planner", "coder", "tester", "reviewer"}:
        task.review_status, task.review_result = "", {}
    task.pr_state, task.pr_error = "", ""
