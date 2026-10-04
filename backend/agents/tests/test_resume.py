# Tests for retrying a failed task from the stage that failed: resume rules, checkpoints, the retry API and the resumed pipeline.
from contextlib import ExitStack
from unittest import mock
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient
from agents.github.publisher import PublishResult
from agents.models import AgentRun, Task
from agents.pipeline import orchestrator
from agents.pipeline.resume import checkpoint_from_history, resume_point, retry_plan
from agents.services.repo import CloneInfo
from agents.services.tester import TestResult
from .helpers import FakeReporter
PLAN = {"title": "Add MAX_USERS", "summary": "Limit signups.", "steps": ["Add constant", "Return 503", "Add test"]}
PASSED_TEST = {"status": "passed", "passed": True, "checks": [{"name": "pytest", "command": ["pytest"], "required": True, "status": "passed", "category": "test", "summary": "9 passed"}], "stack": ["Python"]}
APPROVED = {"approved": True, "summary": "Looks good.", "issues": [], "suggestions": [], "checks": {}}
REJECTED = {"approved": False, "summary": "Incomplete.", "issues": ["Also guard POST /users"], "suggestions": [], "checks": {}}
FULL_CP = {
    "base_sha": "abc123", "base_branch": "main", "plan": PLAN,
    "changes": {"app.py": "MAX_USERS = 100\n"}, "changed_files": [{"path": "app.py", "change": "modified"}], "modes": {"app.py": "100644"},
    "test": PASSED_TEST, "review": APPROVED, "retry_count": 1, "review_cycles": 0,
}
class ResumePointTests(SimpleTestCase):
    # The failed stage, stepped back to what the checkpoint can actually support.
    def test_resumes_at_failed_stage_when_checkpoint_supports_it(self):
        # Each agent failure restarts at that agent.
        for stage in ("planner", "coder", "tester", "reviewer", "github"):
            self.assertEqual(resume_point(stage, FULL_CP), stage)
    def test_steps_back_when_prerequisites_missing(self):
        # No approved review -> can't just publish; no changes -> back to the Coder; no plan -> Planner.
        self.assertEqual(resume_point("github", {**FULL_CP, "review": REJECTED}), "reviewer")
        self.assertEqual(resume_point("tester", {k: v for k, v in FULL_CP.items() if k != "changes"}), "coder")
        self.assertEqual(resume_point("coder", {"base_sha": "abc"}), "planner")
    def test_analyzer_or_no_base_restarts_from_scratch(self):
        # Without a base commit nothing later can be trusted.
        self.assertEqual(resume_point("analyzer", FULL_CP), "")
        self.assertEqual(resume_point("github", {k: v for k, v in FULL_CP.items() if k != "base_sha"}), "")
    def test_infrastructure_failures_jump_to_furthest_checkpoint(self):
        # A crashed runner or failed clone resumes as far along as the saved work allows.
        self.assertEqual(resume_point("runner", FULL_CP), "github")
        self.assertEqual(resume_point("clone", {**FULL_CP, "review": None, "test": None}), "reviewer")
        self.assertEqual(resume_point("dispatch", {}), "")
class HistoryCheckpointTests(TestCase):
    # Tasks from before checkpoints existed are rebuilt from their recorded runs.
    def test_rebuilds_from_runs(self):
        # Base commit from the Analyzer, cumulative code from Coder attempts, test/review from the task.
        user = get_user_model().objects.create_user(email="h@example.com", password="pw-123456789")
        task = Task.objects.create(
            user=user, description="d", github_url="https://github.com/acme/app", status="failed",
            plan=PLAN, test_status="passed", test_results=PASSED_TEST, review_status="approved", review_result=APPROVED,
            final_result={"outcome": "failed", "stage": "github", "error": "AGENT_GITHUB_TOKEN is not configured"},
        )
        AgentRun.objects.create(task=task, agent_type="analyzer", status="success", output={"base_sha": "abc123", "base_branch": "main"})
        AgentRun.objects.create(task=task, agent_type="coder", status="success", output={"file_diffs": [
            {"path": "app.py", "old_content": "v0\n", "new_content": "v1\n"},
            {"path": "new.py", "old_content": "", "new_content": "X = 1\n"},
        ]})
        AgentRun.objects.create(task=task, agent_type="coder", status="failure", output={"file_diffs": [{"path": "app.py", "old_content": "v1\n", "new_content": "BROKEN\n"}]})
        AgentRun.objects.create(task=task, agent_type="coder", status="success", output={"file_diffs": [{"path": "app.py", "old_content": "v1\n", "new_content": "v2\n"}]})
        cp = checkpoint_from_history(task)
        self.assertEqual((cp["base_sha"], cp["base_branch"], cp["plan"]), ("abc123", "main", PLAN))
        self.assertEqual(cp["changes"], {"app.py": "v2\n", "new.py": "X = 1\n"})
        self.assertEqual(cp["changed_files"], [{"path": "app.py", "change": "modified"}, {"path": "new.py", "change": "added"}])
        self.assertTrue(cp["test"]["passed"])
        self.assertEqual(retry_plan(task), {"stage": "github", "label": "Pull Request", "stale": False})
@override_settings(PIPELINE_EXECUTOR="local")
class RetryEndpointTests(TestCase):
    # POST /api/tasks/<id>/retry/
    def setUp(self):
        # A task that got all the way through review and failed only at the PR step.
        self.user = get_user_model().objects.create_user(email="r@example.com", password="pw-123456789")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.task = Task.objects.create(
            user=self.user, description="Add MAX_USERS", github_url="https://github.com/acme/app", status="failed",
            plan=PLAN, checkpoint=FULL_CP, test_status="passed", test_results=PASSED_TEST, review_status="approved",
            review_result=APPROVED, pr_state="failed", pr_error="AGENT_GITHUB_TOKEN is not configured",
            error_message="AGENT_GITHUB_TOKEN is not configured", final_result={"outcome": "failed", "stage": "github"},
        )
    def _retry(self, payload=None):
        # Calls the endpoint with the local executor's subprocess mocked out.
        with mock.patch("agents.pipeline.dispatch.subprocess.Popen") as popen:
            response = self.client.post(f"/api/tasks/{self.task.id}/retry/", payload or {}, format="json")
        self.task.refresh_from_db()
        return response, popen
    def test_detail_offers_retry_from_failed_stage(self):
        # The UI learns where Retry would resume.
        data = self.client.get(f"/api/tasks/{self.task.id}/").json()
        self.assertEqual(data["retry"], {"stage": "github", "label": "Pull Request", "stale": False})
        self.assertNotIn("checkpoint", data)
    def test_retry_resumes_and_keeps_earlier_results(self):
        # Only the PR step reruns; plan, tests and review are kept; the failure is cleared and the run dispatched.
        response, popen = self._retry()
        self.assertEqual(response.status_code, 200, response.content)
        popen.assert_called_once()
        self.assertEqual((self.task.status, self.task.resume_from, self.task.attempt), ("queued", "github", 2))
        self.assertEqual((self.task.error_message, self.task.final_result, self.task.pr_state), ("", {}, ""))
        self.assertEqual((self.task.test_status, self.task.review_status, self.task.plan), ("passed", "approved", PLAN))
        self.assertEqual(self.task.checkpoint["base_sha"], "abc123")
        self.assertIsNone(response.json()["retry"])
    def test_retry_from_tester_clears_test_and_review(self):
        # Stages that will run again start blank in the UI.
        self.task.final_result = {"outcome": "failed", "stage": "tester"}
        self.task.save()
        self._retry()
        self.assertEqual(self.task.resume_from, "tester")
        self.assertEqual((self.task.test_status, self.task.review_status), ("", ""))
        self.assertEqual(self.task.plan, PLAN)
    def test_retry_from_start_discards_checkpoint(self):
        # The escape hatch: a completely fresh run.
        self._retry({"from_start": True})
        self.assertEqual((self.task.resume_from, self.task.checkpoint, self.task.plan), ("", {}, {}))
    def test_only_failed_tasks(self):
        # Running or finished tasks can't be retried.
        self.task.status = "done"
        self.task.save()
        response, popen = self._retry()
        self.assertEqual(response.status_code, 409)
        popen.assert_not_called()
    def test_other_users_cannot_retry(self):
        # Ownership applies.
        other = APIClient()
        other.force_authenticate(get_user_model().objects.create_user(email="o@example.com", password="pw-123456789"))
        self.assertEqual(other.post(f"/api/tasks/{self.task.id}/retry/").status_code, 403)
PASS = TestResult(passed=True, output="", exit_code=0, status="passed")
FAIL = TestResult(passed=False, output="E assert 1 == 2", exit_code=1, status="failed")
SUMMARY = {"diff": "d", "changed_files": [{"path": "app.py", "change": "modified"}], "file_diffs": [], "contents": {"app.py": "MAX_USERS = 100\n"}, "modes": {"app.py": "100644"}}
@override_settings(MAX_TEST_RETRIES=2, MAX_REVIEW_RETRIES=1, CREATE_PULL_REQUESTS=True, AGENT_GITHUB_TOKEN="tok")
class ResumedPipelineTests(SimpleTestCase):
    # The orchestrator skips stages that already succeeded.
    def execute(self, resume, checkpoint, *, tests=(PASS,), reviews=(APPROVED,)):
        # Runs execute_task as a retry and returns (result, reporter, mocks).
        reporter = FakeReporter(status="queued")
        reporter.task.update(resume_from=resume, checkpoint=checkpoint, previous_runs=[{"agent_type": "planner", "status": "success", "retry_count": 0, "duration_ms": 900}])
        mocks = {}
        with ExitStack() as stack:
            def patch(name, **kwargs):
                mocks[name] = stack.enter_context(mock.patch.object(orchestrator, name, **kwargs))
            patch("clone_repo", return_value="/tmp/clone")
            patch("cleanup_clone")
            patch("checkout_commit")
            patch("head_info", return_value=CloneInfo("main", "fresh-sha"))
            patch("apply_files")
            patch("reset_tracked_files")
            patch("detect_project")
            patch("run_analyzer")
            patch("run_planner", return_value=PLAN)
            patch("run_coder", return_value={"files": ["app.py"], "diff": "", "file_diffs": []})
            patch("run_tester", side_effect=list(tests))
            patch("summarize_changes", return_value=SUMMARY)
            patch("run_reviewer", side_effect=list(reviews))
            patch("GitHubClient")
            patch("PullRequestPublisher")
            mocks["PullRequestPublisher"].return_value.publish.return_value = PublishResult(
                branch="agent-swarm/task-1-add-max-users", commit_sha="def", pr_url="https://github.com/acme/app/pull/3", pr_number=3, head_repo="acme/app", mode="direct",
            )
            result = orchestrator.execute_task(reporter)
        return result, reporter, mocks
    def test_pr_only_retry_needs_no_clone_or_agents(self):
        # The exact case from the dashboard: everything passed, only the token was missing.
        result, reporter, mocks = self.execute("github", FULL_CP)
        self.assertEqual(result["outcome"], "pull_request_created")
        for name in ("clone_repo", "run_planner", "run_coder", "run_tester", "run_reviewer"):
            mocks[name].assert_not_called()
        request = mocks["PullRequestPublisher"].return_value.publish.call_args.args[0]
        self.assertEqual((request.base_sha, request.base_branch), ("abc123", "main"))
        self.assertEqual([(c.path, c.content) for c in request.changes], [("app.py", "MAX_USERS = 100\n")])
        self.assertIn("| 1 | Planner |", request.body)
        self.assertEqual(reporter.statuses(), ["publishing", "publishing", "done"])
    def test_tester_retry_reapplies_code_on_original_base(self):
        # The saved code goes back onto the same commit and the Tester runs before any new Coder call.
        cp = {**FULL_CP, "test": None, "review": None}
        result, _, mocks = self.execute("tester", cp)
        self.assertEqual(result["outcome"], "pull_request_created")
        mocks["checkout_commit"].assert_called_once_with("/tmp/clone", "abc123")
        # Applied once on resume, and again after the test run to undo anything the tests wrote.
        saved = mock.call("/tmp/clone", [{"path": "app.py", "content": "MAX_USERS = 100\n"}])
        self.assertEqual(mocks["apply_files"].call_args_list, [saved, saved])
        mocks["reset_tracked_files"].assert_called_once_with("/tmp/clone")
        mocks["run_coder"].assert_not_called()
        mocks["run_planner"].assert_not_called()
        mocks["run_analyzer"].assert_not_called()
        mocks["head_info"].assert_not_called()
    def test_tester_retry_falls_back_to_coder_with_failure_feedback(self):
        # Saved code still failing -> the Coder gets the failure output and a fresh attempt budget.
        result, _, mocks = self.execute("tester", {**FULL_CP, "test": None, "review": None}, tests=(FAIL, PASS))
        self.assertEqual(result["outcome"], "pull_request_created")
        self.assertIn("assert 1 == 2", mocks["run_coder"].call_args.args[2])
    def test_reviewer_retry_skips_tester_when_tests_passed(self):
        # A Reviewer crash doesn't re-run passing tests.
        result, _, mocks = self.execute("reviewer", {**FULL_CP, "review": None})
        self.assertEqual(result["outcome"], "pull_request_created")
        mocks["run_tester"].assert_not_called()
        self.assertEqual(mocks["run_reviewer"].call_args.args[3].status, "passed")
    def test_reviewer_rejection_retry_goes_back_to_coder_with_issues(self):
        # A rejected review restarts the Coder with the review as instructions.
        result, _, mocks = self.execute("reviewer", {**FULL_CP, "review": REJECTED})
        self.assertEqual(result["outcome"], "pull_request_created")
        self.assertIn("Also guard POST /users", mocks["run_coder"].call_args.args[2])
    def test_planner_retry_skips_analyzer_trace(self):
        # The analysis is recomputed silently; the Planner runs again.
        result, _, mocks = self.execute("planner", {"base_sha": "abc123", "base_branch": "main"})
        self.assertEqual(result["outcome"], "pull_request_created")
        mocks["run_analyzer"].assert_not_called()
        mocks["detect_project"].assert_called_once()
        mocks["run_planner"].assert_called_once()
    def test_fresh_run_checkpoints_every_stage(self):
        # A normal run leaves behind everything a later retry needs.
        result, reporter, _ = self.execute("", {})
        cp = reporter.task["checkpoint"]
        self.assertEqual((cp["base_sha"], cp["base_branch"], cp["plan"]), ("fresh-sha", "main", PLAN))
        self.assertEqual(cp["changes"], {"app.py": "MAX_USERS = 100\n"})
        self.assertTrue(cp["test"]["passed"])
        self.assertTrue(cp["review"]["approved"])
    def test_failed_publish_leaves_publishable_checkpoint(self):
        # After a PR failure, the saved state supports a PR-only retry.
        reporter = FakeReporter(status="queued")
        with mock.patch.object(orchestrator, "clone_repo", return_value="/tmp/c"), \
                mock.patch.object(orchestrator, "cleanup_clone"), \
                mock.patch.object(orchestrator, "head_info", return_value=CloneInfo("main", "sha1")), \
                mock.patch.object(orchestrator, "run_analyzer"), \
                mock.patch.object(orchestrator, "run_planner", return_value=PLAN), \
                mock.patch.object(orchestrator, "run_coder", return_value={"files": ["app.py"]}), \
                mock.patch.object(orchestrator, "run_tester", return_value=PASS), \
                mock.patch.object(orchestrator, "reset_tracked_files"), \
                mock.patch.object(orchestrator, "apply_files"), \
                mock.patch.object(orchestrator, "summarize_changes", return_value=SUMMARY), \
                mock.patch.object(orchestrator, "run_reviewer", return_value=APPROVED), \
                override_settings(AGENT_GITHUB_TOKEN=""):
            result = orchestrator.execute_task(reporter)
        self.assertEqual(result["stage"], "github")
        self.assertEqual(resume_point(result["stage"], reporter.task["checkpoint"]), "github")
@override_settings(PIPELINE_EXECUTOR="local")
class StaleTaskRetryTests(TestCase):
    # A task whose runner died before reporting anything must not be stuck "queued" forever.
    def setUp(self):
        # A task dispatched long ago that never heard back from its runner.
        from datetime import timedelta
        from django.utils import timezone
        self.user = get_user_model().objects.create_user(email="s@example.com", password="pw-123456789")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.task = Task.objects.create(user=self.user, description="d", github_url="https://github.com/acme/app", status="queued", executor="github_actions")
        Task.objects.filter(pk=self.task.pk).update(dispatched_at=timezone.now() - timedelta(minutes=30))
        self.task.refresh_from_db()
    def test_abandoned_queued_task_is_retryable_from_scratch(self):
        # No checkpoint yet, so it restarts from the beginning; it's flagged as stale for the UI.
        self.assertEqual(retry_plan(self.task), {"stage": "", "label": "the beginning", "stale": True})
        with mock.patch("agents.pipeline.dispatch.subprocess.Popen") as popen:
            response = self.client.post(f"/api/tasks/{self.task.id}/retry/")
        self.assertEqual(response.status_code, 200, response.content)
        popen.assert_called_once()
        self.task.refresh_from_db()
        self.assertEqual((self.task.status, self.task.attempt), ("queued", 2))
    def test_abandoned_task_with_checkpoint_resumes_furthest_point(self):
        # A runner that died mid-way resumes where its checkpoint allows.
        self.task.checkpoint = FULL_CP
        self.task.save()
        self.assertEqual(retry_plan(self.task)["stage"], "github")
    def test_recently_dispatched_task_is_not_retryable(self):
        # A runner may simply still be starting up; don't offer a duplicate run.
        from django.utils import timezone
        Task.objects.filter(pk=self.task.pk).update(dispatched_at=timezone.now())
        self.task.refresh_from_db()
        self.assertIsNone(retry_plan(self.task))
        with mock.patch("agents.pipeline.dispatch.subprocess.Popen") as popen:
            response = self.client.post(f"/api/tasks/{self.task.id}/retry/")
        self.assertEqual(response.status_code, 409)
        popen.assert_not_called()
