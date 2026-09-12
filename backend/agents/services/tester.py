# Tester agent: runs the repo's real test suite in the sandbox and reads the result, with no LLM involved.
from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path
from ..sandbox import SandboxError, run_in_sandbox
from .common import track_run
_PYTEST_SUMMARY_RE = re.compile(
    r"(?P<counts>(?:\d+ \w+(?:, )?)+)\s+in\s+[\d.]+s"
)
_MAX_STORED_LOG_CHARS = 8000
@dataclass
class TestResult:
    # Outcome of one test run handed back to the pipeline.
    passed: bool
    output: str
    exit_code: int
    timed_out: bool = False
def detect_test_command(repo_path: str) -> list[str]:
    # Picks npm test for a Node repo, otherwise falls back to pytest.
    root = Path(repo_path)
    if (root / "package.json").exists():
        return ["npm", "test", "--silent"]
    return ["python", "-m", "pytest", "-q", "--no-header"]
def run_tester(task, coder_result: dict, attempt: int = 0) -> TestResult:
    # Executes the test command in the sandbox and records the exit code, logs and a short summary.
    command = detect_test_command(task.local_path)
    input_context = {"command": command, "changed_files": coder_result.get("files", [])}
    with track_run(task, agent_type="tester", provider="none", input_context=input_context, retry_count=attempt) as run:
        try:
            sandbox_result = run_in_sandbox(task.local_path, command)
        except SandboxError as exc:
            run.output = {"command": command, "error": str(exc)}
            return TestResult(passed=False, output=str(exc), exit_code=-1)
        passed = sandbox_result.exit_code == 0 and not sandbox_result.timed_out
        run.output = {
            "command": command,
            "exit_code": sandbox_result.exit_code,
            "timed_out": sandbox_result.timed_out,
            "logs": sandbox_result.logs[-_MAX_STORED_LOG_CHARS:],
            "summary": _summarize(sandbox_result.logs),
        }
        return TestResult(
            passed=passed,
            output=sandbox_result.logs,
            exit_code=sandbox_result.exit_code,
            timed_out=sandbox_result.timed_out,
        )
def _summarize(logs: str) -> str | None:
    # Scans the logs backwards for the pytest tally line so the UI can show "2 passed, 1 failed".
    match = None
    for line in logs.splitlines()[::-1]:
        m = _PYTEST_SUMMARY_RE.search(line)
        if m:
            match = m
            break
    return match.group("counts").strip() if match else None
