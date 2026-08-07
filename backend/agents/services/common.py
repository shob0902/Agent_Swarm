"""Shared AgentRun bookkeeping used by every stage in the pipeline.

`track_run` creates the AgentRun row (status='pending') *before* the
agent's work happens, then always records status/duration/output on the
way out -- success or exception -- so a crashed agent is visible in the
trace instead of silently missing. Callers set `run.output` inside the
`with` block; the context manager persists it either way.
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from typing import Any

from ..models import AgentRun


class AgentRunFailed(Exception):
    """Raised by a stage to signal a handled failure (e.g. malformed LLM
    JSON) that should still be recorded as a normal failed AgentRun rather
    than bubbling up as an unexpected crash."""


def parse_strict_json(text: str) -> Any:
    """Defensively parse a model response that is supposed to be strict
    JSON (Section 8: this is the single most common failure point in agent
    pipelines). Strips accidental ```json fences before parsing, and
    raises AgentRunFailed -- not a raw JSONDecodeError -- on failure so
    callers can catch one exception type and fail the run cleanly instead
    of crashing the whole pipeline task.
    """
    try:
        return json.loads(_strip_code_fence(text))
    except json.JSONDecodeError as exc:
        raise AgentRunFailed(f"Model returned invalid JSON ({exc}). Raw output: {text[:500]!r}") from exc


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:]
    return stripped.strip()


@contextmanager
def track_run(task, agent_type: str, provider: str, input_context: dict, retry_count: int = 0):
    run = AgentRun.objects.create(
        task=task,
        agent_type=agent_type,
        provider=provider,
        input_context=input_context,
        output={},
        status="pending",
        retry_count=retry_count,
    )
    started = time.monotonic()
    try:
        yield run
    except Exception as exc:
        run.status = "failure"
        if not run.output:
            run.output = {"error": str(exc)}
        run.duration_ms = int((time.monotonic() - started) * 1000)
        run.save(update_fields=["status", "output", "duration_ms"])
        raise
    else:
        run.status = "success"
        run.duration_ms = int((time.monotonic() - started) * 1000)
        run.save(update_fields=["status", "output", "duration_ms"])
