# Tests for the HMAC-signed runner API and the reporters that talk to it.
import json
from unittest import mock
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient
from agents import runner_auth
from agents.models import AgentRun, Task
from agents.pipeline.reporting import DbReporter, HttpReporter, ReporterError
from agents.services.common import track_run
from .helpers import FakeReporter
SECRET = "test-runner-secret"
class SigningTests(SimpleTestCase):
    # The signature binds method, path, body and time.
    def test_round_trip_and_tampering(self):
        # A valid signature verifies; changing any part breaks it.
        headers = runner_auth.sign(SECRET, "PATCH", "/api/runner/tasks/1/", b'{"a":1}', timestamp="1000")
        ts, sig = headers[runner_auth.TIMESTAMP_HEADER], headers[runner_auth.SIGNATURE_HEADER]
        self.assertTrue(runner_auth.verify(SECRET, "PATCH", "/api/runner/tasks/1/", b'{"a":1}', ts, sig, 300, now=1000))
        self.assertFalse(runner_auth.verify(SECRET, "PATCH", "/api/runner/tasks/2/", b'{"a":1}', ts, sig, 300, now=1000))
        self.assertFalse(runner_auth.verify(SECRET, "PATCH", "/api/runner/tasks/1/", b'{"a":2}', ts, sig, 300, now=1000))
        self.assertFalse(runner_auth.verify(SECRET, "GET", "/api/runner/tasks/1/", b'{"a":1}', ts, sig, 300, now=1000))
        self.assertFalse(runner_auth.verify("other", "PATCH", "/api/runner/tasks/1/", b'{"a":1}', ts, sig, 300, now=1000))
        self.assertFalse(runner_auth.verify(SECRET, "PATCH", "/api/runner/tasks/1/", b'{"a":1}', ts, sig, 300, now=1000 + 301))
    def test_empty_secret_never_verifies(self):
        # An unconfigured server rejects everything.
        self.assertFalse(runner_auth.verify("", "GET", "/", b"", "1", "sha256=x", 300))
@override_settings(RUNNER_SHARED_SECRET=SECRET)
class RunnerApiTests(TestCase):
    # End-to-end checks of /api/runner/... with real signatures.
    def setUp(self):
        # One queued task owned by a user.
        self.user = get_user_model().objects.create_user(email="u@example.com", password="pw-123456789")
        self.task = Task.objects.create(user=self.user, description="Add caching", github_url="https://github.com/acme/app", status="queued")
        self.client = APIClient()
    def _call(self, method, path, payload=None, secret=SECRET):
        # Sends a signed JSON request.
        body = json.dumps(payload).encode() if payload is not None else b""
        headers = runner_auth.sign(secret, method, path, body)
        return self.client.generic(method, path, data=body, content_type="application/json", headers=headers)
    def test_rejects_unsigned_and_badly_signed_requests(self):
        # No JWT cookie or wrong secret gets in.
        path = f"/api/runner/tasks/{self.task.id}/"
        self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(self._call("GET", path, secret="wrong").status_code, 403)
    @override_settings(RUNNER_SHARED_SECRET="")
    def test_closed_when_secret_unset(self):
        # Without a configured secret even a "signed" request fails.
        path = f"/api/runner/tasks/{self.task.id}/"
        body = b""
        headers = runner_auth.sign("anything", "GET", path, body)
        self.assertEqual(self.client.get(path, headers=headers).status_code, 403)
    def test_get_returns_inputs_only(self):
        # The runner sees the request, repo and resume state -- not the owner.
        response = self._call("GET", f"/api/runner/tasks/{self.task.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {"id", "description", "github_url", "status", "resume_from", "checkpoint", "previous_runs"})
    def test_patch_updates_state_but_not_inputs(self):
        # Whitelisted state fields change; description/github_url are ignored.
        response = self._call("PATCH", f"/api/runner/tasks/{self.task.id}/", {
            "status": "coding", "current_agent": "coder", "retry_count": 1,
            "description": "hijacked", "github_url": "https://github.com/evil/repo",
        })
        self.assertEqual(response.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual((self.task.status, self.task.current_agent, self.task.retry_count), ("coding", "coder", 1))
        self.assertEqual(self.task.description, "Add caching")
        self.assertEqual(self.task.github_url, "https://github.com/acme/app")
    def test_patch_validates_choices(self):
        # Unknown statuses are rejected.
        response = self._call("PATCH", f"/api/runner/tasks/{self.task.id}/", {"status": "hacked"})
        self.assertEqual(response.status_code, 400)
    def test_finished_task_is_immutable(self):
        # Once done/failed, replays get 409.
        self.task.status = "done"
        self.task.save()
        self.assertEqual(self._call("PATCH", f"/api/runner/tasks/{self.task.id}/", {"status": "coding"}).status_code, 409)
        self.assertEqual(self._call("POST", f"/api/runner/tasks/{self.task.id}/runs/", {"agent_type": "coder", "provider": "groq"}).status_code, 409)
    def test_run_lifecycle(self):
        # Create pending run, finish it once, refuse a second finish.
        created = self._call("POST", f"/api/runner/tasks/{self.task.id}/runs/", {
            "agent_type": "tester", "provider": "none", "input_context": {"checks": ["pytest"]}, "retry_count": 0,
        })
        self.assertEqual(created.status_code, 201)
        run_id = created.json()["id"]
        path = f"/api/runner/tasks/{self.task.id}/runs/{run_id}/"
        finished = self._call("PATCH", path, {"status": "success", "output": {"summary": "3 passed"}, "duration_ms": 1500, "provider": "none"})
        self.assertEqual(finished.status_code, 200)
        run = AgentRun.objects.get(pk=run_id)
        self.assertEqual((run.status, run.output, run.duration_ms), ("success", {"summary": "3 passed"}, 1500))
        self.assertEqual(self._call("PATCH", path, {"status": "failure"}).status_code, 409)
    def test_run_must_belong_to_task(self):
        # A run id from another task is a 404.
        other = Task.objects.create(user=self.user, description="x", github_url="https://github.com/acme/other")
        run = AgentRun.objects.create(task=other, agent_type="coder")
        response = self._call("PATCH", f"/api/runner/tasks/{self.task.id}/runs/{run.id}/", {"status": "success"})
        self.assertEqual(response.status_code, 404)
class DbReporterTests(TestCase):
    # The in-process reporter writes through the same whitelist as the API.
    def setUp(self):
        # One task to report on.
        user = get_user_model().objects.create_user(email="d@example.com", password="pw-123456789")
        self.task = Task.objects.create(user=user, description="d", github_url="https://github.com/acme/app")
    def test_track_run_records_success_and_failure(self):
        # Both outcomes land on AgentRun rows, with errors captured.
        reporter = DbReporter(self.task.id)
        ctx = mock.Mock(reporter=reporter)
        with track_run(ctx, agent_type="planner", provider="groq", input_context={"x": 1}) as run:
            run.output = {"plan": {"steps": ["a"]}}
        with self.assertRaises(RuntimeError):
            with track_run(ctx, agent_type="coder", provider="groq", input_context={}):
                raise RuntimeError("model exploded")
        runs = list(self.task.runs.order_by("id"))
        self.assertEqual([(r.agent_type, r.status) for r in runs], [("planner", "success"), ("coder", "failure")])
        self.assertEqual(runs[1].output, {"error": "model exploded"})
        self.assertEqual([r["status"] for r in reporter.runs], ["success", "failure"])
    def test_update_task_rejects_unknown_values(self):
        # Invalid states raise instead of being silently stored.
        reporter = DbReporter(self.task.id)
        reporter.update_task(status="testing", test_status="passed")
        self.task.refresh_from_db()
        self.assertEqual((self.task.status, self.task.test_status), ("testing", "passed"))
        with self.assertRaises(ReporterError):
            reporter.update_task(status="bogus")
class HttpReporterTests(SimpleTestCase):
    # The remote reporter signs requests and rides out cold starts.
    def _response(self, status_code, payload=None):
        # Fake requests.Response.
        response = mock.Mock(status_code=status_code, text=json.dumps(payload), content=b"x" if payload is not None else b"")
        response.json.return_value = payload
        return response
    def test_signs_and_retries_5xx(self):
        # Two 503s (cold start) then success; every attempt is freshly signed.
        session = mock.Mock()
        session.request.side_effect = [self._response(503), self._response(502), self._response(201, {"id": 42})]
        sleeps = []
        reporter = HttpReporter(3, "https://api.example.com/api", SECRET, session=session, sleep=sleeps.append)
        run_id = reporter.start_run(agent_type="coder", provider="groq", input_context={}, retry_count=0)
        self.assertEqual(run_id, 42)
        self.assertEqual(len(sleeps), 2)
        method, url = session.request.call_args.args
        kwargs = session.request.call_args.kwargs
        self.assertEqual((method, url), ("POST", "https://api.example.com/api/runner/tasks/3/runs/"))
        self.assertTrue(runner_auth.verify(
            SECRET, "POST", "/api/runner/tasks/3/runs/", kwargs["data"],
            kwargs["headers"][runner_auth.TIMESTAMP_HEADER], kwargs["headers"][runner_auth.SIGNATURE_HEADER], 300,
        ))
    def test_client_errors_are_not_retried(self):
        # A 409 means the task is finished; retrying won't help.
        session = mock.Mock()
        session.request.return_value = self._response(409, {"detail": "task is already done"})
        reporter = HttpReporter(3, "https://api.example.com/api", SECRET, session=session, sleep=lambda s: None)
        with self.assertRaises(ReporterError):
            reporter.update_task(status="coding")
        self.assertEqual(session.request.call_count, 1)
    def test_requires_secret(self):
        # Refuses to start without RUNNER_SHARED_SECRET.
        with self.assertRaises(ReporterError):
            HttpReporter(1, "https://x/api", "")
class FakeReporterSanity(SimpleTestCase):
    # The test double itself behaves like a reporter.
    def test_records_updates(self):
        # Updates are applied and listed in order.
        reporter = FakeReporter()
        reporter.update_task(status="coding")
        self.assertEqual(reporter.statuses(), ["coding"])
