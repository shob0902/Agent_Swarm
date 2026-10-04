# Starts a task's pipeline outside the web process: a GitHub Actions workflow_dispatch in production, a detached subprocess locally.
from __future__ import annotations
import logging
import subprocess
import sys
from django.conf import settings
from django.utils import timezone
from ..github.client import GitHubClient, GitHubError
logger = logging.getLogger(__name__)
EXECUTORS = {"github_actions", "local"}
class DispatchError(Exception):
    # Raised when the pipeline could not be started; the message is safe to show the user.
    pass
def dispatch_task(task) -> None:
    # Marks the task queued, then hands it to the configured executor; on failure marks it failed and re-raises.
    # Queued is saved first so a fast runner's own status updates can never be overwritten by this function.
    executor = settings.PIPELINE_EXECUTOR
    task.executor = executor if executor in EXECUTORS else ""
    task.status = "queued"
    task.dispatched_at = timezone.now()
    task.save(update_fields=["executor", "status", "dispatched_at", "updated_at"])
    try:
        if executor == "github_actions":
            _dispatch_github_actions(task)
        elif executor == "local":
            _dispatch_local(task)
        else:
            raise DispatchError(f"Unknown PIPELINE_EXECUTOR {executor!r} (expected one of {sorted(EXECUTORS)})")
    except DispatchError as exc:
        task.status = "failed"
        task.error_message = str(exc)
        task.final_result = {"outcome": "failed", "stage": "dispatch", "error": str(exc)}
        task.completed_at = timezone.now()
        task.save(update_fields=["status", "error_message", "final_result", "completed_at", "updated_at"])
        raise
def _dispatch_github_actions(task) -> None:
    # Fires .github/workflows/agent-swarm.yml with only the task id; the runner fetches everything else over the signed API.
    missing = [name for name in ("GITHUB_ACTIONS_REPO", "GITHUB_DISPATCH_TOKEN", "RUNNER_SHARED_SECRET") if not getattr(settings, name)]
    if missing:
        raise DispatchError(f"GitHub Actions executor is not configured: set {', '.join(missing)}")
    client = GitHubClient(settings.GITHUB_DISPATCH_TOKEN, settings.GITHUB_API_URL)
    try:
        client.dispatch_workflow(
            settings.GITHUB_ACTIONS_REPO,
            settings.GITHUB_ACTIONS_WORKFLOW,
            settings.GITHUB_ACTIONS_REF,
            {"task_id": str(task.id)},
        )
    except GitHubError as exc:
        logger.warning("workflow_dispatch for task %s failed: %s", task.id, exc)
        raise DispatchError(f"Could not start the GitHub Actions workflow: {exc}") from exc
def _dispatch_local(task) -> None:
    # Spawns `manage.py run_agent_task` as its own process so a long pipeline never ties up a web worker.
    manage_py = settings.BASE_DIR / "manage.py"
    kwargs: dict = {"cwd": str(settings.BASE_DIR)}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen([sys.executable, str(manage_py), "run_agent_task", "--task-id", str(task.id)], **kwargs)
    except OSError as exc:
        raise DispatchError(f"Could not start the local pipeline process: {exc}") from exc
