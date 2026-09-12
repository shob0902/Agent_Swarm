# Shared helpers for recording agent runs and for parsing the JSON a model gives back.
from __future__ import annotations
import json
import logging
import re
import time
from contextlib import contextmanager
from typing import Any
from ..models import AgentRun
logger = logging.getLogger(__name__)
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
class AgentRunFailed(Exception):
    # Raised for a handled stage failure that should still be logged as a failed run.
    pass
def parse_strict_json(text: str) -> Any:
    # Pulls the first JSON value out of a model response, tolerating code fences and surrounding prose.
    candidate = _strip_code_fence(text)
    start = _first_json_start(candidate)
    if start is None:
        raise AgentRunFailed(f"Model returned no JSON object or array at all. Raw output: {text[:500]!r}")
    try:
        value, end = json.JSONDecoder().raw_decode(candidate, start)
    except json.JSONDecodeError as exc:
        raise AgentRunFailed(f"Model returned invalid JSON ({exc}). Raw output: {text[:500]!r}") from exc
    trailing = candidate[end:].strip()
    if trailing:
        logger.warning(
            "Discarded %d chars of trailing output after the JSON value: %r",
            len(trailing),
            trailing[:200],
        )
    return value
def _strip_code_fence(text: str) -> str:
    # Returns the inside of the first fenced block, or the text unchanged if there isn't one.
    match = _FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()
def _first_json_start(text: str) -> int | None:
    # Finds the index of the first brace or bracket, where a JSON value could start.
    candidates = [i for i in (text.find("{"), text.find("[")) if i != -1]
    return min(candidates) if candidates else None
@contextmanager
def track_run(task, agent_type: str, provider: str, input_context: dict, retry_count: int = 0):
    # Creates the AgentRun row up front and always writes back status, duration and output on the way out.
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
        run.save(update_fields=["status", "output", "duration_ms", "provider"])
        raise
    else:
        run.status = "success"
        run.duration_ms = int((time.monotonic() - started) * 1000)
        run.save(update_fields=["status", "output", "duration_ms", "provider"])
