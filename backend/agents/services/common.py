# Shared helpers for recording agent runs and for parsing the JSON a model gives back.
from __future__ import annotations
import json
import logging
import os
import re
import time
from contextlib import contextmanager
from typing import Any
logger = logging.getLogger(__name__)
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
class AgentRunFailed(Exception):
    # Raised for a handled stage failure that should still be logged as a failed run.
    pass
def list_repo_files(root: str, skip: set[str] | frozenset[str], limit: int | None = None) -> list[str]:
    # Repo-relative POSIX paths of every file, never descending into skipped directories (node_modules,
    # installed deps...), so a clone with dependencies installed is still cheap to scan. Unordered.
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
        prefix = "" if rel_dir == "." else rel_dir + "/"
        for name in filenames:
            if name not in skip:
                out.append(prefix + name)
                if limit is not None and len(out) >= limit:
                    return out
    return out
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
class RunHandle:
    # The object an agent sees inside track_run: it sets .output (and may change .provider) before the block exits.
    def __init__(self, run_id: Any, provider: str):
        # Starts with an empty output that the agent fills in.
        self.id = run_id
        self.provider = provider
        self.output: dict = {}
@contextmanager
def track_run(ctx, agent_type: str, provider: str, input_context: dict, retry_count: int = 0):
    # Creates the AgentRun up front (via the context's reporter) and always writes back status, duration and output on the way out.
    reporter = ctx.reporter
    run = RunHandle(
        reporter.start_run(agent_type=agent_type, provider=provider, input_context=input_context, retry_count=retry_count),
        provider,
    )
    started = time.monotonic()
    try:
        yield run
    except Exception as exc:
        if not run.output:
            run.output = {"error": str(exc)}
        _finish(reporter, run, "failure", started)
        raise
    else:
        _finish(reporter, run, "success", started)
def _finish(reporter, run: RunHandle, status: str, started: float) -> None:
    # Writes the outcome, logging rather than raising so a reporting hiccup never masks the agent's own error.
    try:
        reporter.finish_run(
            run.id,
            status=status,
            output=run.output,
            duration_ms=int((time.monotonic() - started) * 1000),
            provider=run.provider,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Could not record the outcome of run %s", run.id)
