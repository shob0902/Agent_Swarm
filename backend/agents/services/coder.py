"""Coder agent: plan (+ prior test failure, if retrying) -> file rewrites.

Needs the most context of any agent (plan, file contents, prior failures)
and is called the most often (once per plan, once per retry attempt), so
unlike Planner/Reviewer it isn't pinned to a single API key: it rotates
between two dedicated Groq keys (GROQ_API_KEY_CODER_A / _B), with automatic
failover to the other if the first one it picks fails. The selection rule
lives in services/key_pool.py; see Section 3 for why the whole pipeline
runs on Groq.

Output format: strict JSON {"files": [{"path", "content"}, ...]} where
"content" is the COMPLETE new file, not a unified diff. This was chosen
over unified-diff output because LLM-generated diffs are fragile to parse
(context-line drift, off-by-one hunks); whole-file rewrites are simple to
apply and simple to validate. The Coder agent writes these directly into
the local clone (task.local_path, see services/repo.py) *before* the
sandbox is invoked for testing (Section 7), then a real `git diff` against
the clone is computed from the result -- so the diff shown to the Reviewer
and the frontend is always a genuine, well-formed diff even though the
model never produced one itself.
"""
from __future__ import annotations

import logging
import re
import threading
from pathlib import Path

from django.conf import settings
from git import InvalidGitRepositoryError, Repo

from .. import llm_client
from ..prompts import load_prompt
from . import key_pool
from .common import AgentRunFailed, parse_strict_json, track_run

logger = logging.getLogger(__name__)

MAX_FILE_CHARS = 4000  # per-file cap sent to the LLM
MAX_TOTAL_CONTEXT_CHARS = 20000  # combined cap across all files sent to the LLM
FALLBACK_TEXT_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".txt", ".md", ".toml", ".cfg", ".ini", ".yml", ".yaml",
}
IGNORE_DIRS = {".git", "node_modules", "__pycache__", "venv", ".venv", "env", "dist", "build"}

_PATH_TOKEN_RE = re.compile(r"[\w./-]+\.\w+")

CODER_PROVIDER = "groq"

# The Coder is by far the highest-volume agent -- one call for the initial
# plan, then one more per retry attempt -- so it's the one agent given two
# independent Groq keys instead of one. Which of the two serves a given call
# is decided by KeyPool: least-recently-used first, with a per-key cooldown
# applied on 429s so an exhausted key stops being picked, and failover to
# the sibling key if the first choice fails for any reason. The full rule
# (and why a plain alternate-by-attempt counter wasn't good enough) is
# documented in services/key_pool.py.
#
# Built lazily rather than at import time so Django settings are guaranteed
# loaded, and cached module-level so the per-key state it accumulates
# actually survives across pipeline runs in the same worker process.
_CODER_KEY_POOL: key_pool.KeyPool | None = None
_CODER_KEY_POOL_LOCK = threading.Lock()


def _coder_key_pool() -> key_pool.KeyPool:
    global _CODER_KEY_POOL
    with _CODER_KEY_POOL_LOCK:
        if _CODER_KEY_POOL is None:
            _CODER_KEY_POOL = key_pool.KeyPool.from_pairs(
                [
                    ("coder-a", settings.GROQ_API_KEY_CODER_A),
                    ("coder-b", settings.GROQ_API_KEY_CODER_B),
                ]
            )
        return _CODER_KEY_POOL


# Whole-file rewrites need real output-token headroom (see the comment on
# the call below), but Groq's free tier for llama-3.1-8b-instant enforces a
# combined prompt+completion cap of ~6000 tokens per minute -- confirmed
# empirically: requesting a 16384 ceiling gets a 413 every time ("Request
# too large ... Limit 6000, Requested 18269"), because max_output_tokens
# alone already blows through it before the prompt is even counted. Capped
# at 3000 so a Coder task whose prompt + completion fit under 6000 actually
# gets a chance to succeed, instead of every attempt being a guaranteed,
# wasted 413.
_CODER_MAX_OUTPUT_TOKENS = 3000

# How many times to re-ask when the model returns something that isn't usable
# JSON. Two extra tries is the sweet spot: each costs one Groq call against a
# free-tier quota, and an 8B model that mangles its output three times running
# is not going to get it right on the fourth -- at that point the honest
# outcome is a failed run with the raw output recorded for inspection.
MAX_MALFORMED_RETRIES = 2


def run_coder(task, plan: dict, prior_test_output: str | None, attempt: int) -> dict:
    """Selects relevant files, calls Groq on one of the two rotating Coder
    keys for whole-file rewrites, applies them to task.local_path, and returns
    {"diff": str, "files": [path, ...],
    "file_diffs": [{"path", "old_content", "new_content"}, ...]}.
    """
    relevant = _select_relevant_files(task.local_path, plan)
    file_contents = _format_file_contents(task.local_path, relevant)
    retry_context = (
        f"\nPrior test run failed with this output -- fix this specifically:\n{prior_test_output[:3000]}\n"
        if prior_test_output
        else ""
    )
    prompt = load_prompt(
        "coder_prompt",
        plan_json=_plan_json(plan),
        file_contents=file_contents,
        retry_context=retry_context,
    )
    input_context = {
        "plan": plan,
        "relevant_files": relevant,
        "attempt": attempt,
        "prior_test_output": prior_test_output,
    }

    messages = [
        {"role": "system", "content": "You output strict JSON only, never prose or markdown fences."},
        {"role": "user", "content": prompt},
    ]

    with track_run(task, agent_type="coder", provider=CODER_PROVIDER, input_context=input_context, retry_count=attempt) as run:
        try:
            files, response, served_by, tried, malformed = _request_files(messages, attempt)
        except _CoderKeysExhausted as exc:
            # Every key that was actually tried failed -- record all of them
            # so the trace/admin shows the failure was the whole pool, not
            # one unlucky key.
            run.output = {"error": str(exc), "keys_tried": exc.attempted}
            raise

        diff, file_diffs = _apply_files_and_diff(task.local_path, files)
        result = {"diff": diff, "files": [f["path"] for f in files], "file_diffs": file_diffs}
        # `key_slot` is whoever actually served it (the frontend's Agent Trace
        # surfaces it as "via groq · key A"); `keys_tried` keeps the full
        # attempt list, so a silent failover is still visible after the fact.
        run.output = {
            "raw_response": response.text,
            "raw": response.raw,
            "key_slot": served_by,
            "keys_tried": tried,
            "malformed_responses": malformed,
            **result,
        }
        return result


def _request_files(messages: list[dict], attempt: int):
    """Ask for the file rewrites, re-asking if the model returns something
    that isn't usable JSON. Returns
    (files, response, serving_slot, all_slots_tried, malformed_count).

    A malformed response is a *transient* failure, not a permanent one --
    an 8B model at temperature 0.2 will occasionally stop mid-string or
    close a quote early on output that it gets right on the very next call
    (observed live: the same prompt against the same repo produced clean
    JSON once and a response truncated at 2051 chars the next time, with
    Groq reporting finish_reason="stop" both times, so there is nothing to
    detect up front).

    Without this loop a single such response fails the whole pipeline:
    tasks.py only loops the Coder back around when the *Tester* rejects the
    code, so a Coder that never produced parseable code at all just aborts
    the run. Re-asking here is the cheap fix -- and each re-ask naturally
    lands on the other API key, since the pool hands out least-recently-used
    first.
    """
    tried: list[str] = []
    last_exc: AgentRunFailed | None = None

    for reask in range(MAX_MALFORMED_RETRIES + 1):
        current = messages if reask == 0 else [*messages, *_reask_turn(last_exc)]
        # attempt + reask keeps rotating the key-pool tiebreak, so a retry
        # isn't biased back toward the key that just produced junk.
        response, slot, slots = _call_coder_llm(current, attempt + reask)
        tried.extend(s for s in slots if s not in tried)
        try:
            return _validate_files(response.text), response, slot, tried, reask
        except AgentRunFailed as exc:
            last_exc = exc
            logger.warning(
                "Coder: unusable response from %s (%s)%s",
                slot,
                str(exc)[:200],
                " -- re-asking" if reask < MAX_MALFORMED_RETRIES else " -- out of re-asks",
            )

    raise last_exc


def _reask_turn(exc: AgentRunFailed | None) -> list[dict]:
    """Corrective turn appended on a re-ask. Deliberately does NOT echo the
    bad response back -- it can be multiple KB of half-escaped file content,
    and re-sending it would push the request over Groq's ~6000 tokens/minute
    prompt+completion ceiling, turning a recoverable blip into a hard 413."""
    return [
        {
            "role": "user",
            "content": (
                f"Your previous response could not be parsed: {str(exc)[:200]}. "
                "Return ONLY the JSON object, complete, with every string properly "
                "escaped and closed, and nothing before or after it. If the files are "
                "long, include fewer files rather than truncating the JSON."
            ),
        }
    ]


class _CoderKeysExhausted(llm_client.LLMError):
    """Every key slot the Coder tried failed. Carries which slots were
    actually attempted so the caller can record that accurately."""

    def __init__(self, message: str, attempted: list[str]):
        super().__init__(message)
        self.attempted = attempted


def _call_coder_llm(messages: list[dict], attempt: int) -> tuple[llm_client.LLMResponse, str, list[str]]:
    """Walk the key pool's preference order, failing over to the next key if
    one fails for any reason, and report each outcome back so the pool's
    ordering improves for the next call. See services/key_pool.py for the
    selection rule. Returns (response, serving_slot, slots_actually_tried)."""
    pool = _coder_key_pool()
    candidates = pool.select(tiebreak=attempt)
    if not candidates:
        raise _CoderKeysExhausted(
            "no Coder API key configured -- set GROQ_API_KEY_CODER_A and/or "
            "GROQ_API_KEY_CODER_B in backend/.env",
            [],
        )

    attempted: list[str] = []
    last_exc: llm_client.LLMError | None = None
    for i, candidate in enumerate(candidates):
        attempted.append(candidate.slot)
        pool.mark_used(candidate.slot)
        try:
            response = llm_client.call_llm(
                CODER_PROVIDER,
                messages,
                api_key=candidate.api_key,
                # Unlike the Planner's step list or the Reviewer's verdict,
                # this response embeds one or more COMPLETE rewritten files
                # as JSON string values -- the default 4096 is easy to blow
                # through on anything beyond a short file (JSON-escaping
                # alone inflates length), which truncates mid-string and
                # fails downstream as a cryptic JSON parse error rather than
                # an obvious token-budget one. See _CODER_MAX_OUTPUT_TOKENS
                # for the ceiling; llm_client.call_llm also raises a clear
                # error if a response is cut off before reaching it.
                max_output_tokens=_CODER_MAX_OUTPUT_TOKENS,
            )
        except llm_client.LLMRateLimitError as exc:
            # Out of quota, not a bad request -- cool this key off so the
            # next call skips straight to its sibling instead of paying
            # call_llm's full backoff cycle here all over again.
            pool.mark_rate_limited(candidate.slot)
            last_exc = exc
            _log_key_failure(candidate.slot, exc, has_more=i < len(candidates) - 1)
        except llm_client.LLMError as exc:
            pool.mark_failed(candidate.slot)
            last_exc = exc
            _log_key_failure(candidate.slot, exc, has_more=i < len(candidates) - 1)
        else:
            pool.mark_success(candidate.slot)
            return response, candidate.slot, attempted

    raise _CoderKeysExhausted(str(last_exc), attempted) from last_exc


def _log_key_failure(slot: str, exc: Exception, *, has_more: bool) -> None:
    logger.warning(
        "Coder: key %s failed (%s)%s",
        slot,
        exc,
        " -- failing over to the next key" if has_more else " -- no more keys to try",
    )


def _plan_json(plan: dict) -> str:
    import json

    return json.dumps(plan, indent=2)


def _select_relevant_files(repo_path: str, plan: dict) -> list[str]:
    """Heuristic file selection to keep the prompt token-efficient
    (Section 3): prefer files literally named in the plan's steps, and only
    fall back to a size-capped sweep of the whole repo if the plan doesn't
    name anything that exists.
    """
    root = Path(repo_path)
    if not root.exists():
        return []

    all_files = [
        p for p in root.rglob("*")
        if p.is_file() and not any(part in IGNORE_DIRS for part in p.parts)
    ]
    all_rel = {str(p.relative_to(root)).replace("\\", "/") for p in all_files}

    mentioned_tokens: set[str] = set()
    for step in plan.get("steps", []):
        mentioned_tokens.update(_PATH_TOKEN_RE.findall(step))

    candidates = {rel for rel in all_rel if rel in mentioned_tokens or Path(rel).name in mentioned_tokens}
    if candidates:
        return sorted(candidates)

    # Fallback: no filename overlap found (e.g. a vague task description) --
    # sweep readable text files up to a total char budget instead of
    # sending the entire repo.
    budget = MAX_TOTAL_CONTEXT_CHARS
    fallback: list[str] = []
    for rel in sorted(all_rel):
        if Path(rel).suffix not in FALLBACK_TEXT_SUFFIXES:
            continue
        size = (root / rel).stat().st_size
        if size > budget:
            continue
        budget -= size
        fallback.append(rel)
        if budget <= 0:
            break
    return fallback


def _format_file_contents(repo_path: str, relative_paths: list[str]) -> str:
    if not relative_paths:
        return "(no existing files matched the plan -- create new files as needed)"

    root = Path(repo_path)
    blocks = []
    remaining = MAX_TOTAL_CONTEXT_CHARS
    for rel in relative_paths:
        if remaining <= 0:
            blocks.append("... (remaining files omitted to stay within the context budget)")
            break
        path = root / rel
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        truncated = content[:MAX_FILE_CHARS]
        if len(content) > MAX_FILE_CHARS:
            truncated += "\n... (truncated)"
        remaining -= len(truncated)
        blocks.append(f"### {rel}\n```\n{truncated}\n```")
    return "\n\n".join(blocks)


def _validate_files(text: str) -> list[dict]:
    data = parse_strict_json(text)
    if not isinstance(data, dict) or not isinstance(data.get("files"), list) or not data["files"]:
        raise AgentRunFailed(f"Coder JSON missing a non-empty 'files' list. Raw output: {text[:500]!r}")
    for entry in data["files"]:
        if not isinstance(entry, dict) or not entry.get("path") or "content" not in entry:
            raise AgentRunFailed(f"Coder 'files' entries need 'path' and 'content'. Raw output: {text[:500]!r}")

    # The model sometimes emits the same path twice -- e.g. a first pass at a
    # file followed by a corrected version of it (observed live: a "files"
    # list of ["app.py", "app.py"]). Left alone that writes the file twice,
    # and the second file_diffs entry captures the *first* rewrite as its
    # "old_content" -- so the diff viewer shows a phantom before/after
    # between two generated versions instead of against the real original.
    # Last entry wins: it's the model's final intent for that path.
    deduped = {entry["path"]: entry for entry in data["files"]}
    if len(deduped) != len(data["files"]):
        logger.warning(
            "Coder returned duplicate paths %s -- keeping the last entry for each",
            [p for p in {e["path"] for e in data["files"]} if sum(e["path"] == p for e in data["files"]) > 1],
        )
    return list(deduped.values())


def _apply_files_and_diff(repo_path: str, files: list[dict]) -> str:
    root = Path(repo_path).resolve()
    written: list[str] = []
    file_diffs: list[dict] = []
    for entry in files:
        rel = _safe_relative_path(root, entry["path"])
        abs_path = root / rel
        old_content = abs_path.read_text(encoding="utf-8", errors="replace") if abs_path.exists() else ""
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(entry["content"], encoding="utf-8")
        rel_str = str(rel).replace("\\", "/")
        written.append(rel_str)
        # old/new content pairs -- consumed by the frontend's DiffViewer
        # (react-diff-viewer-continued wants oldValue/newValue, not a
        # unified-diff patch), kept alongside the real `git diff` text below.
        file_diffs.append({"path": rel_str, "old_content": old_content, "new_content": entry["content"]})

    try:
        repo = Repo(repo_path)
    except InvalidGitRepositoryError as exc:
        raise AgentRunFailed(f"repo_path {repo_path!r} is not a git repository: {exc}") from exc

    if written:
        # Intent-to-add so brand-new files show up in `git diff` too, without
        # actually staging their content (keeps the working tree state simple
        # for the Tester stage that runs right after this).
        try:
            repo.git.add("-N", *written)
        except Exception:  # noqa: BLE001 - diffing still proceeds without this
            pass
    diff_text = repo.git.diff("--no-color", *written) if written else ""
    return diff_text, file_diffs


def _safe_relative_path(root: Path, raw_path: str) -> Path:
    """Reject any path that would write outside the repo (e.g. '../../etc/passwd')."""
    candidate = (root / raw_path).resolve()
    try:
        return candidate.relative_to(root)
    except ValueError as exc:
        raise AgentRunFailed(f"Coder attempted to write outside the repo root: {raw_path!r}") from exc
