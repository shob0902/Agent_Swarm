"""Tester agent: runs the repo's real test suite inside the sandbox and
parses the raw output programmatically. Deliberately has no LLM involved --
"testing should be deterministic, not LLM-judged" (Section 3).
"""
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
    passed: bool
    output: str
    exit_code: int
    timed_out: bool = False


def detect_test_command(repo_path: str) -> list[str]:
    """Only Python/pytest is exercised end-to-end by the bundled sandbox
    image (see docker/sandbox.Dockerfile); npm is detected for repos that
    have it but requires swapping SANDBOX_IMAGE to one with Node installed.
    """
    root = Path(repo_path)
    if (root / "package.json").exists():
        return ["npm", "test", "--silent"]
    return ["python", "-m", "pytest", "-q", "--no-header"]


def run_tester(task, coder_result: dict, attempt: int = 0) -> TestResult:
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
    """Best-effort one-line pytest summary (e.g. '2 passed, 1 failed') for
    quick display in the trace UI, without re-parsing full logs client-side."""
    match = None
    for line in logs.splitlines()[::-1]:
        m = _PYTEST_SUMMARY_RE.search(line)
        if m:
            match = m
            break
    return match.group("counts").strip() if match else None
