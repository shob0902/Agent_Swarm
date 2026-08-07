"""Coder agent: plan (+ prior test failure, if retrying) -> file rewrites.

Uses Gemini -- needs the most context of any agent (plan, file contents,
prior failures), and Gemini's free-tier context window handles that better
than Groq's smaller-context free models (Section 3).

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

import re
from pathlib import Path

from git import InvalidGitRepositoryError, Repo

from .. import llm_client
from ..prompts import load_prompt
from .common import AgentRunFailed, parse_strict_json, track_run

MAX_FILE_CHARS = 4000  # per-file cap sent to the LLM
MAX_TOTAL_CONTEXT_CHARS = 20000  # combined cap across all files sent to the LLM
FALLBACK_TEXT_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".txt", ".md", ".toml", ".cfg", ".ini", ".yml", ".yaml",
}
IGNORE_DIRS = {".git", "node_modules", "__pycache__", "venv", ".venv", "env", "dist", "build"}

_PATH_TOKEN_RE = re.compile(r"[\w./-]+\.\w+")


def run_coder(task, plan: dict, prior_test_output: str | None, attempt: int) -> dict:
    """Selects relevant files, calls Gemini for whole-file rewrites, applies
    them to task.local_path, and returns {"diff": str, "files": [path, ...],
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

    with track_run(task, agent_type="coder", provider="gemini", input_context=input_context, retry_count=attempt) as run:
        response = llm_client.call_llm(
            "gemini",
            [
                {"role": "system", "content": "You output strict JSON only, never prose or markdown fences."},
                {"role": "user", "content": prompt},
            ],
            # Unlike the Planner's step list or the Reviewer's verdict, this
            # response embeds one or more COMPLETE rewritten files as JSON
            # string values -- the default 4096 is easy to blow through on
            # anything beyond a short file (JSON-escaping alone inflates
            # length), which truncates mid-string and fails downstream as a
            # cryptic JSON parse error rather than an obvious token-budget
            # one. 16384 gives real headroom; llm_client.call_llm now also
            # raises a clear error if a response is cut off before this.
            max_output_tokens=16384,
        )
        files = _validate_files(response.text)
        diff, file_diffs = _apply_files_and_diff(task.local_path, files)
        result = {"diff": diff, "files": [f["path"] for f in files], "file_diffs": file_diffs}
        run.output = {"raw_response": response.text, "raw": response.raw, **result}
        return result


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
    return data["files"]


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
