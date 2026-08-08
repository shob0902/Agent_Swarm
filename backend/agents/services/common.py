"""Shared AgentRun bookkeeping used by every stage in the pipeline.

`track_run` creates the AgentRun row (status='pending') *before* the
agent's work happens, then always records status/duration/output on the
way out -- success or exception -- so a crashed agent is visible in the
trace instead of silently missing. Callers set `run.output` inside the
`with` block; the context manager persists it either way. `run.provider`
is also persisted on exit (not just at creation), so a stage that doesn't
know which provider actually served the call until after it returns --
e.g. the Coder's round-robin/failover between two providers, see
services/coder.py -- can just set `run.provider` before the block ends.
"""
from __future__ import annotations

import json
import logging
import re
import time
from contextlib import contextmanager
from typing import Any

from ..models import AgentRun

logger = logging.getLogger(__name__)

# First ```/```json fenced block in the response, if the model wrapped its
# JSON in one despite being told not to. Non-greedy so a fence that appears
# again later in the response doesn't swallow everything in between.
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


class AgentRunFailed(Exception):
    """Raised by a stage to signal a handled failure (e.g. malformed LLM
    JSON) that should still be recorded as a normal failed AgentRun rather
    than bubbling up as an unexpected crash."""


def parse_strict_json(text: str) -> Any:
    """Defensively parse a model response that is supposed to be strict
    JSON (Section 8: this is the single most common failure point in agent
    pipelines).

    Every agent's prompt says "strict JSON only, no prose, no fences", and a
    small model obeys that most of the time but not all of it. Three real
    deviations are tolerated here rather than being allowed to fail a run
    that the model actually got right:

      1. The whole thing wrapped in a ```json fence.
      2. Prose before the JSON ("Here is the updated file:").
      3. Anything *after* the JSON value -- a trailing explanation, a repeat
         of the object, a stray token. This is the one that used to hurt
         most: `json.loads` rejects the entire response with "Extra data:
         line 2 column 1" even though the JSON that precedes it parses
         perfectly and is exactly what was asked for.

    Parsing therefore locates the first JSON value and uses `raw_decode`,
    which stops cleanly at the end of that value instead of demanding the
    whole string be consumed. Raises AgentRunFailed -- not a raw
    JSONDecodeError -- so callers catch one exception type and fail the run
    cleanly instead of crashing the whole pipeline task.
    """
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
        # Not fatal -- the value above is complete and well-formed -- but
        # worth surfacing, since a model that keeps talking after its JSON
        # is also a model that might have meant to say something useful.
        logger.warning(
            "Discarded %d chars of trailing output after the JSON value: %r",
            len(trailing),
            trailing[:200],
        )
    return value


def _strip_code_fence(text: str) -> str:
    """Returns the contents of the first fenced block, or the original text
    if there isn't a complete one. A fence with no closing ``` (a truncated
    response) falls through deliberately -- `_first_json_start` can still
    find the JSON after the opening fence."""
    match = _FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


def _first_json_start(text: str) -> int | None:
    """Index of the first '{' or '[', i.e. where a JSON value could begin."""
    candidates = [i for i in (text.find("{"), text.find("[")) if i != -1]
    return min(candidates) if candidates else None


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
        run.save(update_fields=["status", "output", "duration_ms", "provider"])
        raise
    else:
        run.status = "success"
        run.duration_ms = int((time.monotonic() - started) * 1000)
        run.save(update_fields=["status", "output", "duration_ms", "provider"])
