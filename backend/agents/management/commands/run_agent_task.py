# Runner entry point: executes one task's pipeline. Used by the GitHub Actions workflow (--remote) and the local executor.
import os
import sys
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from agents.pipeline.orchestrator import TERMINAL_STATUSES, execute_task
from agents.pipeline.reporting import DbReporter, HttpReporter, ReporterError
class Command(BaseCommand):
    # Wires the runner up as `python manage.py run_agent_task --task-id N [--remote]`.
    help = "Run the Planner -> Coder -> Tester -> Reviewer -> Pull Request pipeline for one task."
    # The GitHub Actions runner has no database, so skip checks that might touch one.
    requires_system_checks: list = []
    def add_arguments(self, parser):
        # --remote reports over the signed runner API instead of the ORM; --mark-failed is the workflow's crash handler.
        parser.add_argument("--task-id", type=int, required=True)
        parser.add_argument("--remote", action="store_true", help="Report state to AGENT_SWARM_API_URL instead of the local database")
        parser.add_argument("--mark-failed", metavar="REASON", help="Only mark the task failed (if it isn't finished) and exit")
        parser.add_argument("--check", action="store_true", help="Only verify the runner can reach and authenticate with the API, then exit")
    def handle(self, *args, **options):
        # Builds the right reporter and runs (or fails) the task, exiting non-zero when the task did not succeed.
        task_id = options["task_id"]
        try:
            reporter = (
                HttpReporter(task_id, settings.AGENT_SWARM_API_URL, settings.RUNNER_SHARED_SECRET)
                if options["remote"]
                else DbReporter(task_id)
            )
            if options["check"]:
                task = reporter.fetch_task()
                self.stdout.write(f"Runner API OK: task {task['id']} is '{task['status']}' (resume_from={task.get('resume_from') or '-'})")
                return
            if options["mark_failed"]:
                self._mark_failed(reporter, options["mark_failed"])
                return
            result = execute_task(reporter, run_url=_actions_run_url())
        except ReporterError as exc:
            message = f"Could not reach task state for task {task_id}: {exc}"
            _annotate("Runner API", message)
            raise CommandError(message) from exc
        self.stdout.write(f"Task {task_id}: {result}")
        if result.get("outcome") == "failed":
            _annotate(f"Task failed at {result.get('stage', '?')}", str(result.get("error", ""))[:500])
            sys.exit(1)
    def _mark_failed(self, reporter, reason: str) -> None:
        # Fails the task only if the pipeline didn't already record an outcome.
        task = reporter.fetch_task()
        if task["status"] in TERMINAL_STATUSES:
            self.stdout.write(f"Task {task['id']} already {task['status']}; leaving it alone")
            return
        fields = {"status": "failed", "error_message": reason, "completed_at": timezone.now(),
                  "final_result": {"outcome": "failed", "stage": "runner", "error": reason}}
        run_url = _actions_run_url()
        if run_url:
            fields["workflow_run_url"] = run_url
        reporter.update_task(**fields)
        self.stdout.write(f"Task {task['id']} marked failed: {reason}")
def _annotate(title: str, message: str) -> None:
    # Inside GitHub Actions, surfaces the error as a run annotation (shown on the run page and in failure emails).
    if os.environ.get("GITHUB_ACTIONS") == "true":
        flat = " ".join(message.replace("%", "%25").split())
        print(f"::error title={title}::{flat}", flush=True)
def _actions_run_url() -> str:
    # Link to the current GitHub Actions run, when running inside one.
    server, repo, run_id = (os.environ.get(k, "") for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    return f"{server}/{repo}/actions/runs/{run_id}" if server and repo and run_id else ""
