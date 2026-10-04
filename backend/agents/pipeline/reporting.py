# Where pipeline state goes: straight into the database (local executor) or over signed HTTP to Django (GitHub Actions).
from __future__ import annotations
import json
import logging
import time
from datetime import datetime
from typing import Any
from urllib.parse import urlparse
import requests
from .. import runner_auth
logger = logging.getLogger(__name__)
class ReporterError(Exception):
    # Raised when task state could not be read or written.
    pass
class Reporter:
    # Common interface; also keeps a local copy of every run so the PR body can summarise the trace.
    def __init__(self, task_id: int):
        # Remembers which task this reporter writes to.
        self.task_id = task_id
        self.runs: list[dict] = []
    def fetch_task(self) -> dict:
        # Returns the task inputs plus resume state (see RunnerTaskSerializer).
        raise NotImplementedError
    def update_task(self, **fields: Any) -> None:
        # Writes a partial update of the task's execution state.
        raise NotImplementedError
    def start_run(self, *, agent_type: str, provider: str, input_context: dict, retry_count: int) -> Any:
        # Creates the AgentRun row (status pending) before the agent does any work, returning its id.
        run_id = self._start_run(agent_type=agent_type, provider=provider, input_context=input_context, retry_count=retry_count)
        self.runs.append({"id": run_id, "agent_type": agent_type, "status": "pending", "retry_count": retry_count, "duration_ms": None})
        return run_id
    def finish_run(self, run_id: Any, *, status: str, output: dict, duration_ms: int, provider: str) -> None:
        # Records the run's outcome.
        self._finish_run(run_id, status=status, output=output, duration_ms=duration_ms, provider=provider)
        for run in self.runs:
            if run["id"] == run_id:
                run.update(status=status, duration_ms=duration_ms)
    def _start_run(self, **kwargs) -> Any:
        # Backend-specific creation of the run row.
        raise NotImplementedError
    def _finish_run(self, run_id: Any, **kwargs) -> None:
        # Backend-specific completion of the run row.
        raise NotImplementedError
class DbReporter(Reporter):
    # Writes through the Django ORM; used when the pipeline runs on a machine with database access.
    def fetch_task(self) -> dict:
        # Reads the task row.
        from ..models import Task
        from ..serializers import RunnerTaskSerializer
        return _jsonable(RunnerTaskSerializer(Task.objects.get(pk=self.task_id)).data)
    def update_task(self, **fields: Any) -> None:
        # Validates through the same serializer the runner API uses, so both paths accept exactly the same fields.
        from ..models import Task
        from ..serializers import TaskStateSerializer
        task = Task.objects.get(pk=self.task_id)
        serializer = TaskStateSerializer(task, data=_jsonable(fields), partial=True)
        if not serializer.is_valid():
            raise ReporterError(f"invalid task update {sorted(fields)}: {serializer.errors}")
        serializer.save()
    def _start_run(self, *, agent_type, provider, input_context, retry_count):
        # Inserts the pending AgentRun row.
        from ..models import AgentRun
        run = AgentRun.objects.create(
            task_id=self.task_id,
            agent_type=agent_type,
            provider=provider,
            input_context=_jsonable(input_context),
            output={},
            status="pending",
            retry_count=retry_count,
        )
        return run.id
    def _finish_run(self, run_id, *, status, output, duration_ms, provider):
        # Updates the AgentRun row in place.
        from ..models import AgentRun
        AgentRun.objects.filter(pk=run_id, task_id=self.task_id).update(
            status=status, output=_jsonable(output), duration_ms=duration_ms, provider=provider,
        )
class HttpReporter(Reporter):
    # Calls Django's runner API with HMAC-signed requests; the runner never holds database credentials.
    MAX_ATTEMPTS = 6
    TIMEOUT_SECONDS = 30
    def __init__(self, task_id: int, api_url: str, secret: str, session: requests.Session | None = None, sleep=time.sleep):
        # api_url is the API root, e.g. https://example.onrender.com/api
        super().__init__(task_id)
        if not secret:
            raise ReporterError("RUNNER_SHARED_SECRET must be set for the GitHub Actions runner")
        self.api_url = api_url.rstrip("/")
        self.secret = secret
        self.session = session or requests.Session()
        self._sleep = sleep
    def fetch_task(self) -> dict:
        # GET /runner/tasks/<id>/
        return self._call("GET", f"/runner/tasks/{self.task_id}/")
    def update_task(self, **fields: Any) -> None:
        # PATCH /runner/tasks/<id>/
        self._call("PATCH", f"/runner/tasks/{self.task_id}/", _jsonable(fields))
    def _start_run(self, *, agent_type, provider, input_context, retry_count):
        # POST /runner/tasks/<id>/runs/
        data = self._call("POST", f"/runner/tasks/{self.task_id}/runs/", _jsonable({
            "agent_type": agent_type,
            "provider": provider,
            "input_context": input_context,
            "retry_count": retry_count,
        }))
        return data["id"]
    def _finish_run(self, run_id, *, status, output, duration_ms, provider):
        # PATCH /runner/tasks/<id>/runs/<run_id>/
        self._call("PATCH", f"/runner/tasks/{self.task_id}/runs/{run_id}/", _jsonable({
            "status": status, "output": output, "duration_ms": duration_ms, "provider": provider,
        }))
    def _call(self, method: str, path: str, payload: Any = None) -> Any:
        # Signs and sends one request, retrying connection errors and 5xx (free-tier hosts cold-start slowly).
        url = f"{self.api_url}{path}"
        body = json.dumps(payload).encode() if payload is not None else b""
        signed_path = urlparse(url).path
        last_error = ""
        for attempt in range(self.MAX_ATTEMPTS):
            headers = {"Content-Type": "application/json", **runner_auth.sign(self.secret, method, signed_path, body)}
            try:
                response = self.session.request(method, url, data=body or None, headers=headers, timeout=self.TIMEOUT_SECONDS)
            except requests.RequestException as exc:
                last_error = str(exc)
            else:
                if response.status_code < 500:
                    if response.status_code >= 400:
                        raise ReporterError(f"{method} {path} -> {response.status_code}: {response.text[:300]}")
                    return response.json() if response.content else None
                last_error = f"HTTP {response.status_code}"
            if attempt < self.MAX_ATTEMPTS - 1:
                delay = min(2 ** (attempt + 1), 30)
                logger.warning("Runner API %s %s failed (%s); retrying in %ss", method, path, last_error, delay)
                self._sleep(delay)
        raise ReporterError(f"{method} {path} failed after {self.MAX_ATTEMPTS} attempts: {last_error}")
def _jsonable(value: Any) -> Any:
    # Round-trips through JSON so datetimes and SDK objects become plain, storable values.
    return json.loads(json.dumps(value, default=_default))
def _default(obj: Any) -> Any:
    # JSON fallback: ISO strings for datetimes, str() for anything else.
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)
