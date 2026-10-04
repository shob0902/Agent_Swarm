# Tests for the user-facing task API and the executors that replaced Celery.
from unittest import mock
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from agents.github.client import GitHubError
from agents.models import Task
from agents.pipeline.dispatch import DispatchError, dispatch_task
ACTIONS_SETTINGS = dict(
    PIPELINE_EXECUTOR="github_actions",
    GITHUB_ACTIONS_REPO="me/Agent_Swarm",
    GITHUB_ACTIONS_WORKFLOW="agent-swarm.yml",
    GITHUB_ACTIONS_REF="main",
    GITHUB_DISPATCH_TOKEN="dispatch-token",
    RUNNER_SHARED_SECRET="s",
    GITHUB_VALIDATE_REPOS=False,
)
@override_settings(**ACTIONS_SETTINGS)
class TaskCreateTests(TestCase):
    # POST /api/tasks/ creates the task and dispatches the workflow; it never runs agents in-process.
    def setUp(self):
        # Authenticated client.
        self.user = get_user_model().objects.create_user(email="u@example.com", password="pw-123456789")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
    def test_create_dispatches_workflow_with_only_the_task_id(self):
        # The workflow input carries no secrets or user text.
        with mock.patch("agents.pipeline.dispatch.GitHubClient") as client_cls:
            response = self.client.post("/api/tasks/", {
                "github_url": "https://github.com/acme/app",
                "description": "Improve API performance and add appropriate caching.",
            }, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual((body["status"], body["executor"], body["is_active"]), ("queued", "github_actions", True))
        client_cls.assert_called_once_with("dispatch-token", mock.ANY)
        client_cls.return_value.dispatch_workflow.assert_called_once_with(
            "me/Agent_Swarm", "agent-swarm.yml", "main", {"task_id": str(body["id"])},
        )
        task = Task.objects.get(pk=body["id"])
        self.assertIsNotNone(task.dispatched_at)
    def test_dispatch_failure_is_persisted_and_returned(self):
        # The task exists, is failed, and says why.
        with mock.patch("agents.pipeline.dispatch.GitHubClient") as client_cls:
            client_cls.return_value.dispatch_workflow.side_effect = GitHubError("Not Found", 404)
            response = self.client.post("/api/tasks/", {"github_url": "https://github.com/acme/app", "description": "x"}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], "failed")
        self.assertIn("Could not start the GitHub Actions workflow", response.json()["error_message"])
    @override_settings(GITHUB_DISPATCH_TOKEN="")
    def test_missing_configuration_fails_fast(self):
        # Misconfiguration surfaces as a task error rather than a silent hang.
        response = self.client.post("/api/tasks/", {"github_url": "https://github.com/acme/app", "description": "x"}, format="json")
        self.assertEqual(response.json()["status"], "failed")
        self.assertIn("GITHUB_DISPATCH_TOKEN", response.json()["error_message"])
    def test_invalid_repo_url_rejected(self):
        # Validation happens before any dispatch.
        with mock.patch("agents.pipeline.dispatch.GitHubClient") as client_cls:
            response = self.client.post("/api/tasks/", {"github_url": "https://gitlab.com/a/b", "description": "x"}, format="json")
        self.assertEqual(response.status_code, 400)
        client_cls.assert_not_called()
    @override_settings(ALLOWED_REPO_OWNERS=["acme"])
    def test_owner_allow_list(self):
        # Repos from other owners are refused at the form.
        response = self.client.post("/api/tasks/", {"github_url": "https://github.com/stranger/app", "description": "x"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("acme", str(response.json()))
    @override_settings(GITHUB_VALIDATE_REPOS=True)
    def test_remote_validation_rejects_missing_and_private_repos(self):
        # A 404 or a private repo is a form error; a GitHub outage is not.
        with mock.patch("agents.github.validation.GitHubClient") as client_cls:
            client_cls.return_value.get_repo.side_effect = GitHubError("Not Found", 404)
            r1 = self.client.post("/api/tasks/", {"github_url": "https://github.com/acme/nope", "description": "x"}, format="json")
            client_cls.return_value.get_repo.side_effect = None
            client_cls.return_value.get_repo.return_value = {"private": True}
            r2 = self.client.post("/api/tasks/", {"github_url": "https://github.com/acme/secret", "description": "x"}, format="json")
            client_cls.return_value.get_repo.side_effect = GitHubError("rate limited", 403)
            with mock.patch("agents.pipeline.dispatch.GitHubClient"):
                r3 = self.client.post("/api/tasks/", {"github_url": "https://github.com/acme/app", "description": "x"}, format="json")
        self.assertEqual((r1.status_code, r2.status_code, r3.status_code), (400, 400, 201))
class TaskStateApiTests(TestCase):
    # Persisted state is exposed read-only so a page refresh shows the same thing.
    def setUp(self):
        # A finished task with a PR.
        self.user = get_user_model().objects.create_user(email="s@example.com", password="pw-123456789")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.task = Task.objects.create(
            user=self.user, description="Add caching", github_url="https://github.com/acme/app",
            status="done", branch_name="agent-swarm/task-1-add-caching", commit_sha="abc", pr_url="https://github.com/acme/app/pull/7",
            pr_number=7, pr_state="open", test_status="passed", review_status="approved",
        )
    def test_detail_includes_pipeline_and_pr_state(self):
        # Every persisted field the dashboard needs comes back.
        data = self.client.get(f"/api/tasks/{self.task.id}/").json()
        for key, value in {"status": "done", "pr_number": 7, "pr_state": "open", "test_status": "passed", "review_status": "approved", "is_active": False}.items():
            self.assertEqual(data[key], value, key)
        self.assertIn("runs", data)
    def test_users_cannot_write_state_or_inputs(self):
        # PATCH can rename, but not fake a PR or retarget the repo.
        self.client.patch(f"/api/tasks/{self.task.id}/", {
            "title": "Renamed", "pr_url": "https://evil.example", "status": "failed", "github_url": "https://github.com/evil/x",
        }, format="json")
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, "Renamed")
        self.assertEqual((self.task.pr_url, self.task.status), ("https://github.com/acme/app/pull/7", "done"))
        self.assertEqual(self.task.github_url, "https://github.com/acme/app")
    def test_other_users_cannot_see_task(self):
        # Ownership still applies.
        other = get_user_model().objects.create_user(email="o@example.com", password="pw-123456789")
        client = APIClient()
        client.force_authenticate(other)
        self.assertEqual(client.get(f"/api/tasks/{self.task.id}/").status_code, 403)
    def test_refresh_pr_records_merge(self):
        # A merged PR is reflected in pr_state.
        with mock.patch("agents.views.GitHubClient") as client_cls:
            client_cls.return_value.get_pull_request.return_value = {"state": "closed", "merged": True}
            data = self.client.post(f"/api/tasks/{self.task.id}/refresh_pr/").json()
        client_cls.return_value.get_pull_request.assert_called_once_with("acme/app", 7)
        self.assertEqual(data["pr_state"], "merged")
@override_settings(PIPELINE_EXECUTOR="local")
class LocalExecutorTests(TestCase):
    # The development executor spawns `manage.py run_agent_task` instead of using a broker.
    def test_spawns_runner_subprocess(self):
        # The child gets only the task id on its command line.
        user = get_user_model().objects.create_user(email="l@example.com", password="pw-123456789")
        task = Task.objects.create(user=user, description="x", github_url="https://github.com/acme/app")
        with mock.patch("agents.pipeline.dispatch.subprocess.Popen") as popen:
            dispatch_task(task)
        args = popen.call_args.args[0]
        self.assertTrue(args[1].endswith("manage.py"))
        self.assertEqual(args[2:], ["run_agent_task", "--task-id", str(task.id)])
        task.refresh_from_db()
        self.assertEqual((task.status, task.executor), ("queued", "local"))
    @override_settings(PIPELINE_EXECUTOR="celery")
    def test_unknown_executor(self):
        # Leftover Celery configuration is rejected loudly.
        user = get_user_model().objects.create_user(email="c@example.com", password="pw-123456789")
        task = Task.objects.create(user=user, description="x", github_url="https://github.com/acme/app")
        with self.assertRaises(DispatchError):
            dispatch_task(task)
        task.refresh_from_db()
        self.assertEqual(task.status, "failed")
