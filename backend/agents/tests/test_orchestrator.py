# Tests for the pipeline orchestrator: stage order, the bounded retry loops, and the pull-request stage.
from contextlib import ExitStack
from unittest import mock
from django.test import SimpleTestCase, override_settings
from agents.github.publisher import PublishError, PublishResult
from agents.pipeline import orchestrator
from agents.services.repo import CloneInfo, RepoCloneError
from agents.services.tester import TestResult
from .helpers import FakeReporter
PLAN = {"title": "Add caching", "summary": "Cache GET /users.", "steps": ["Add cache", "Add tests"]}
CHANGES = {
    "diff": "diff --git a/app.py b/app.py",
    "changed_files": [{"path": "app.py", "change": "modified"}],
    "file_diffs": [],
    "contents": {"app.py": "CACHE = {}\n"},
    "modes": {"app.py": "100644"},
}
PASS = TestResult(passed=True, output="", exit_code=0, status="passed")
FAIL = TestResult(passed=False, output="E   assert 1 == 2", exit_code=1, status="failed")
APPROVE = {"approved": True, "summary": "ok", "issues": [], "suggestions": [], "checks": {}}
REJECT = {"approved": False, "summary": "incomplete", "issues": ["Invalidate the cache on POST /users"], "suggestions": [], "checks": {}}
@override_settings(MAX_TEST_RETRIES=3, MAX_REVIEW_RETRIES=1, CREATE_PULL_REQUESTS=True, AGENT_GITHUB_TOKEN="tok")
class OrchestratorTests(SimpleTestCase):
    # Every agent is stubbed; these tests are about sequencing and bounds.
    def run_pipeline(self, *, tests=None, reviews=None, publish=None, clone_error=None, reporter=None):
        # Runs execute_task with stubbed stages and returns (result, reporter, mocks).
        reporter = reporter or FakeReporter()
        tests = list(tests or [PASS])
        reviews = list(reviews or [APPROVE])
        mocks = {}
        with ExitStack() as stack:
            def patch(name, **kwargs):
                mocks[name] = stack.enter_context(mock.patch.object(orchestrator, name, **kwargs))
            if clone_error:
                patch("clone_repo", side_effect=clone_error)
            else:
                patch("clone_repo", return_value="/tmp/clone")
            patch("cleanup_clone")
            patch("head_info", return_value=CloneInfo(branch="main", sha="abc123"))
            patch("reset_tracked_files")
            patch("apply_files")
            patch("run_analyzer")
            patch("run_planner", return_value=PLAN)
            patch("run_coder", side_effect=lambda ctx, plan, feedback, attempt, prev: {"files": ["app.py"], "diff": "", "file_diffs": []})
            patch("run_tester", side_effect=tests)
            patch("summarize_changes", return_value=CHANGES)
            patch("run_reviewer", side_effect=reviews)
            patch("GitHubClient")
            patch("PullRequestPublisher")
            if isinstance(publish, Exception):
                mocks["PullRequestPublisher"].return_value.publish.side_effect = publish
            else:
                mocks["PullRequestPublisher"].return_value.publish.return_value = publish or PublishResult(
                    branch="agent-swarm/task-1-add-caching", commit_sha="def456", pr_url="https://github.com/acme/app/pull/7",
                    pr_number=7, head_repo="acme/app", mode="direct",
                )
            result = orchestrator.execute_task(reporter, run_url="https://github.com/me/Agent_Swarm/actions/runs/9")
        return result, reporter, mocks
    def test_happy_path_creates_pr(self):
        # analyze -> plan -> code -> test -> review -> publish -> done, and the clone is always cleaned up.
        result, reporter, mocks = self.run_pipeline()
        self.assertEqual(result["outcome"], "pull_request_created")
        self.assertEqual(reporter.statuses(), ["analyzing", "analyzing", "planning", "coding", "testing", "review", "publishing", "done"])
        self.assertEqual(reporter.task["pr_url"], "https://github.com/acme/app/pull/7")
        self.assertEqual(reporter.task["pr_state"], "open")
        self.assertEqual(reporter.task["commit_sha"], "def456")
        self.assertEqual(reporter.task["workflow_run_url"], "https://github.com/me/Agent_Swarm/actions/runs/9")
        request = mocks["PullRequestPublisher"].return_value.publish.call_args.args[0]
        self.assertEqual((request.base_branch, request.base_sha), ("main", "abc123"))
        self.assertEqual([c.path for c in request.changes], ["app.py"])
        self.assertIn("Agent Swarm Generated PR", request.body)
        mocks["cleanup_clone"].assert_called_once_with("/tmp/clone")
    def test_test_failure_feeds_back_into_coder(self):
        # Tester failure -> Coder with the failure output -> Tester passes.
        result, reporter, mocks = self.run_pipeline(tests=[FAIL, PASS])
        self.assertEqual(result["outcome"], "pull_request_created")
        coder_calls = mocks["run_coder"].call_args_list
        self.assertEqual(len(coder_calls), 2)
        self.assertIsNone(coder_calls[0].args[2])
        self.assertIn("assert 1 == 2", coder_calls[1].args[2])
        self.assertEqual(coder_calls[1].args[4], ["app.py"])
        self.assertEqual(reporter.task["retry_count"], 1)
    def test_coder_output_is_restored_after_every_test_run(self):
        # Tests run against a read-write clone; afterwards the tree is reset and the Coder's checkpointed code re-applied.
        _, _, mocks = self.run_pipeline(tests=[FAIL, PASS])
        self.assertEqual(mocks["reset_tracked_files"].call_count, 2)
        mocks["reset_tracked_files"].assert_called_with("/tmp/clone")
        self.assertEqual(mocks["apply_files"].call_count, 2)
        mocks["apply_files"].assert_called_with("/tmp/clone", [{"path": "app.py", "content": "CACHE = {}\n"}])
    def test_test_retries_are_bounded(self):
        # Three failing attempts end the task; no PR is created.
        result, reporter, mocks = self.run_pipeline(tests=[FAIL, FAIL, FAIL])
        self.assertEqual((result["outcome"], result["stage"]), ("failed", "tester"))
        self.assertEqual(mocks["run_coder"].call_count, 3)
        mocks["run_reviewer"].assert_not_called()
        mocks["PullRequestPublisher"].return_value.publish.assert_not_called()
        self.assertEqual(reporter.task["status"], "failed")
        self.assertIn("Validation still failing", reporter.task["error_message"])
    def test_reviewer_rejection_loops_back_through_coder_and_tester(self):
        # Reviewer reject -> Coder (with the issues) -> Tester -> Reviewer approve.
        result, reporter, mocks = self.run_pipeline(tests=[PASS, PASS], reviews=[REJECT, APPROVE])
        self.assertEqual(result["outcome"], "pull_request_created")
        self.assertEqual(result["review_cycles"], 1)
        second_feedback = mocks["run_coder"].call_args_list[1].args[2]
        self.assertIn("Reviewer rejected", second_feedback)
        self.assertIn("Invalidate the cache on POST /users", second_feedback)
        self.assertEqual(mocks["run_tester"].call_count, 2)
        self.assertEqual(reporter.task["review_cycles"], 1)
    def test_review_retries_are_bounded(self):
        # With MAX_REVIEW_RETRIES=1, two rejections end the task without a PR.
        result, reporter, mocks = self.run_pipeline(tests=[PASS, PASS], reviews=[REJECT, REJECT])
        self.assertEqual((result["outcome"], result["stage"]), ("failed", "reviewer"))
        self.assertEqual(mocks["run_reviewer"].call_count, 2)
        mocks["PullRequestPublisher"].return_value.publish.assert_not_called()
        self.assertEqual(reporter.task["review_status"], "rejected")
    @override_settings(MAX_TEST_RETRIES=0, MAX_REVIEW_RETRIES=-5)
    def test_nonsense_limits_still_run_once(self):
        # Zero/negative limits are clamped rather than skipping the work or looping.
        result, _, mocks = self.run_pipeline()
        self.assertEqual(result["outcome"], "pull_request_created")
        self.assertEqual(mocks["run_coder"].call_count, 1)
    def test_publish_failure_marks_task_failed_with_reason(self):
        # A GitHub problem is visible on the task and in pr_error.
        result, reporter, _ = self.run_pipeline(publish=PublishError("token cannot push"))
        self.assertEqual((result["outcome"], result["stage"]), ("failed", "github"))
        self.assertEqual(reporter.task["pr_state"], "failed")
        self.assertIn("token cannot push", reporter.task["pr_error"])
    @override_settings(AGENT_GITHUB_TOKEN="")
    def test_missing_token_fails_publish_stage(self):
        # No token, no PR -- and no fake success.
        result, reporter, mocks = self.run_pipeline()
        self.assertEqual(result["stage"], "github")
        self.assertIn("AGENT_GITHUB_TOKEN", reporter.task["error_message"])
        mocks["PullRequestPublisher"].return_value.publish.assert_not_called()
    @override_settings(CREATE_PULL_REQUESTS=False)
    def test_pr_creation_can_be_disabled(self):
        # The pipeline still validates and finishes, recording that the PR was skipped.
        result, reporter, mocks = self.run_pipeline()
        self.assertEqual(result["outcome"], "validated_without_pr")
        self.assertEqual(reporter.task["pr_state"], "skipped")
        mocks["PullRequestPublisher"].assert_not_called()
    def test_clone_failure(self):
        # A bad/private repo fails at the clone stage.
        result, reporter, mocks = self.run_pipeline(clone_error=RepoCloneError("Could not clone"))
        self.assertEqual(result["stage"], "clone")
        mocks["run_planner"].assert_not_called()
    def test_agent_exception_is_captured(self):
        # An exception inside an agent fails the task with the agent named, instead of crashing the runner.
        reporter = FakeReporter()
        with mock.patch.object(orchestrator, "clone_repo", return_value="/tmp/c"), \
                mock.patch.object(orchestrator, "cleanup_clone"), \
                mock.patch.object(orchestrator, "head_info", return_value=CloneInfo("main", "abc")), \
                mock.patch.object(orchestrator, "run_analyzer"), \
                mock.patch.object(orchestrator, "run_planner", side_effect=ValueError("bad json")):
            result = orchestrator.execute_task(reporter)
        self.assertEqual(result["stage"], "planner")
        self.assertEqual(reporter.task["current_agent"], "planner")
        self.assertIn("bad json", reporter.task["error_message"])
    def test_finished_task_is_not_rerun(self):
        # A duplicate dispatch of a finished task is a no-op.
        result, reporter, mocks = self.run_pipeline(reporter=FakeReporter(status="done"))
        self.assertTrue(result["skipped"])
        mocks["clone_repo"].assert_not_called()
