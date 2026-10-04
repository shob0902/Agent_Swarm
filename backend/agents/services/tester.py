# Tester agent: installs dependencies, then runs the repo's own build/test/lint commands in the sandbox, with no LLM involved.
from __future__ import annotations
import hashlib
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from django.conf import settings
from ..sandbox import SandboxError, run_in_sandbox
from .analyzer import DEPS_DIR, PY_DEPS_DIR, CheckSpec, ProjectProfile, detect_project
from .common import AgentRunFailed, track_run
_PYTEST_SUMMARY_RE = re.compile(r"(?P<counts>(?:\d+ \w+(?:, )?)+)\s+in\s+[\d.]+s")
_JEST_SUMMARY_RE = re.compile(r"^Tests:\s+(?P<counts>.+?)\s*$")
_VITEST_SUMMARY_RE = re.compile(r"^\s*Tests\s+(?P<counts>\d+ (?:passed|failed).*?)\s*$")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_MAX_STORED_LOG_CHARS = 8000
_MAX_FEEDBACK_CHARS = 6000
PYTEST_NO_TESTS_EXIT_CODE = 5
SANDBOX_ENV = {"PYTHONPATH": f"/workspace/{PY_DEPS_DIR}"}
@dataclass
class CheckResult:
    # Outcome of one validation command.
    name: str
    command: list[str]
    required: bool
    status: str
    category: str = "test"
    exit_code: int | None = None
    summary: str | None = None
    logs: str = ""
    duration_ms: int = 0
@dataclass
class TestResult:
    # Outcome of one Tester run handed back to the pipeline.
    __test__ = False
    passed: bool
    output: str
    exit_code: int
    timed_out: bool = False
    status: str = "passed"
    checks: list[CheckResult] = field(default_factory=list)
    stack: list[str] = field(default_factory=list)
    @classmethod
    def from_dict(cls, data: dict) -> "TestResult":
        # Rebuilds a result saved in a task checkpoint (logs aren't stored, so output is empty).
        known = {f for f in CheckResult.__dataclass_fields__}
        checks = [CheckResult(**{k: v for k, v in c.items() if k in known}) for c in data.get("checks") or []]
        return cls(
            passed=bool(data.get("passed", data.get("status") in ("passed", "skipped"))),
            output="",
            exit_code=0,
            timed_out=bool(data.get("timed_out")),
            status=data.get("status") or "passed",
            checks=checks,
            stack=list(data.get("stack") or []),
        )
    def as_dict(self, include_logs: bool = True) -> dict:
        # Serialisable view stored on the AgentRun and on Task.test_results.
        checks = [asdict(c) for c in self.checks]
        if not include_logs:
            for c in checks:
                c.pop("logs", None)
        return {"status": self.status, "passed": self.passed, "timed_out": self.timed_out, "checks": checks, "stack": self.stack}
def detect_test_command(repo_path: str) -> list[str]:
    # Backwards-compatible helper: the primary test command for a repo, or [] when none is detected.
    profile = detect_project(repo_path)
    for check in profile.checks:
        if check.name in {"pytest", "npm test", "django tests"}:
            return check.command
    return []
def run_tester(ctx, changed_files: list[str], attempt: int = 0) -> TestResult:
    # Installs deps when manifests changed, runs every detected check offline, and decides pass/fail from the required ones.
    profile: ProjectProfile = ctx.profile or detect_project(ctx.local_path)
    input_context = {
        "stack": profile.languages + profile.frameworks,
        "checks": [c.name for c in profile.checks],
        "changed_files": changed_files,
    }
    with track_run(ctx, agent_type="tester", provider="none", input_context=input_context, retry_count=attempt) as run:
        results: list[CheckResult] = []
        try:
            install_failure = _install_dependencies(ctx, profile, results)
            if install_failure is None:
                for spec in profile.checks:
                    results.append(_run_check(ctx.local_path, spec, changed_files))
        except SandboxError as exc:
            run.output = {"error": str(exc), "checks": [asdict(r) for r in results]}
            raise AgentRunFailed(f"Sandbox unavailable: {exc}") from exc
        result = _aggregate(results, profile)
        run.output = {**result.as_dict(), "summary": _overall_summary(result)}
        for check in run.output["checks"]:
            check["logs"] = check["logs"][-_MAX_STORED_LOG_CHARS:]
        return result
def _install_dependencies(ctx, profile: ProjectProfile, results: list[CheckResult]) -> CheckResult | None:
    # Runs the install steps (the only sandbox step with network) once, and again only if a manifest changed.
    if not settings.SANDBOX_INSTALL_DEPENDENCIES or not profile.install_steps:
        return None
    manifest_hash = _manifest_hash(ctx.local_path, profile.manifests)
    if ctx.extra.get("deps_hash") == manifest_hash:
        return None
    _exclude_from_git(ctx.local_path)
    for spec in profile.install_steps:
        result = _execute(ctx.local_path, spec, spec.command, timeout=settings.SANDBOX_INSTALL_TIMEOUT_SECONDS, allow_network=True)
        results.append(result)
        if result.status != "passed":
            return result
    ctx.extra["deps_hash"] = manifest_hash
    return None
def _run_check(repo_path: str, spec: CheckSpec, changed_files: list[str]) -> CheckResult:
    # Expands special checks (py_compile over changed files) and runs the command offline.
    command = spec.command
    if spec.kind == "py_compile":
        py_files = [f for f in changed_files if f.endswith(".py") and (Path(repo_path) / f).is_file()]
        if not py_files:
            return CheckResult(
                name=spec.name, command=["python", "-m", "py_compile"], required=spec.required,
                status="skipped", category=spec.category, summary="no Python files changed",
            )
        command = ["python", "-m", "py_compile", *py_files]
    result = _execute(repo_path, spec, command, timeout=settings.SANDBOX_TIMEOUT_SECONDS, allow_network=False)
    if spec.name == "pytest" and result.exit_code == PYTEST_NO_TESTS_EXIT_CODE:
        result.status, result.summary = "skipped", "no tests collected"
    return result
def _execute(repo_path: str, spec: CheckSpec, command: list[str], *, timeout: int, allow_network: bool) -> CheckResult:
    # Runs one command in the sandbox and converts the outcome into a CheckResult.
    started = time.monotonic()
    sandbox_result = run_in_sandbox(repo_path, command, timeout=timeout, environment=SANDBOX_ENV, allow_network=allow_network)
    logs = _ANSI_RE.sub("", sandbox_result.logs)
    if sandbox_result.timed_out:
        status = "error"
    else:
        status = "passed" if sandbox_result.exit_code == 0 else "failed"
    return CheckResult(
        name=spec.name,
        command=command,
        required=spec.required,
        status=status,
        category=spec.category,
        exit_code=sandbox_result.exit_code,
        summary=_summarize(logs) or ("timed out" if sandbox_result.timed_out else None),
        logs=logs,
        duration_ms=int((time.monotonic() - started) * 1000),
    )
def _aggregate(results: list[CheckResult], profile: ProjectProfile) -> TestResult:
    # Required failures fail the run; advisory ones (lint) are reported but never block the PR.
    # With no failures, the status is PASS only if an actual test suite ran -- a clean build alone is "skipped".
    blocking = [r for r in results if r.required and r.status in {"failed", "error"}]
    if blocking:
        status = "failed"
    elif any(r.category == "test" and r.status == "passed" for r in results):
        status = "passed"
    else:
        status = "skipped"
    feedback = "\n\n".join(
        f"$ {' '.join(r.command)}  (exit {r.exit_code})\n{r.logs[-_MAX_FEEDBACK_CHARS // max(len(blocking), 1):]}"
        for r in blocking
    )
    return TestResult(
        passed=not blocking,
        output=feedback,
        exit_code=blocking[0].exit_code if blocking and blocking[0].exit_code is not None else 0,
        timed_out=any(r.summary == "timed out" for r in results),
        status=status,
        checks=results,
        stack=profile.languages + profile.frameworks,
    )
def _overall_summary(result: TestResult) -> str:
    # e.g. "pytest: 3 passed · lint: failed (advisory)".
    parts = []
    for c in result.checks:
        text = f"{c.name}: {c.summary or c.status}"
        if not c.required and c.status == "failed":
            text += " (advisory)"
        parts.append(text)
    return " · ".join(parts) or "no checks detected"
def _summarize(logs: str) -> str | None:
    # Scans the logs backwards for a pytest/jest/vitest tally line so the UI can show "2 passed, 1 failed".
    for line in logs.splitlines()[::-1]:
        for pattern in (_PYTEST_SUMMARY_RE, _JEST_SUMMARY_RE, _VITEST_SUMMARY_RE):
            m = pattern.search(line)
            if m:
                return m.group("counts").strip()
    return None
def _manifest_hash(repo_path: str, manifests: list[str]) -> str:
    # Hash of every dependency manifest, so a Coder edit to requirements/package.json triggers a reinstall.
    digest = hashlib.sha256()
    for name in sorted(manifests):
        path = Path(repo_path) / name
        digest.update(name.encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()
def _exclude_from_git(repo_path: str) -> None:
    # Keeps the installed-dependency folder out of git status/diff for this clone only.
    exclude = Path(repo_path) / ".git" / "info" / "exclude"
    try:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        if f"/{DEPS_DIR}/" not in existing:
            exclude.write_text(existing + f"\n/{DEPS_DIR}/\n", encoding="utf-8")
    except OSError:
        pass
