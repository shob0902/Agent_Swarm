# Coder agent: turns the plan into whole-file rewrites, applies them to the clone and diffs the result.
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
from .safety import is_blocked_path
logger = logging.getLogger(__name__)
MAX_FILE_CHARS = 4000
MAX_TOTAL_CONTEXT_CHARS = 20000
FALLBACK_TEXT_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".txt", ".md", ".toml", ".cfg", ".ini", ".yml", ".yaml",
}
IGNORE_DIRS = {".git", "node_modules", "__pycache__", "venv", ".venv", "env", "dist", "build", ".agent_swarm"}
_PATH_TOKEN_RE = re.compile(r"[\w./-]+\.\w+")
CODER_PROVIDER = "groq"
_CODER_KEY_POOL: key_pool.KeyPool | None = None
_CODER_KEY_POOL_LOCK = threading.Lock()
def _coder_key_pool() -> key_pool.KeyPool:
    # Builds the two-key pool on first use and caches it so its state survives across runs.
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
_CODER_MAX_OUTPUT_TOKENS = 3000
MAX_MALFORMED_RETRIES = 2
MAX_FEEDBACK_CHARS = 3000
def run_coder(ctx, plan: dict, feedback: str | None, attempt: int, previously_changed: list[str] | None = None) -> dict:
    # Picks the relevant files, asks the model to rewrite them, writes them out and returns the diff.
    # feedback is failing test/build output or a Reviewer rejection, already phrased by the pipeline.
    relevant = sorted(set(_select_relevant_files(ctx.local_path, plan)) | set(previously_changed or []))
    file_contents = _format_file_contents(ctx.local_path, relevant)
    retry_context = f"\n{feedback[:MAX_FEEDBACK_CHARS]}\n" if feedback else ""
    prompt = load_prompt(
        "coder_prompt",
        task_description=ctx.description,
        plan_json=_plan_json(plan),
        file_contents=file_contents,
        retry_context=retry_context,
    )
    input_context = {
        "plan": plan,
        "relevant_files": relevant,
        "attempt": attempt,
        "feedback": feedback,
    }
    messages = [
        {"role": "system", "content": "You output strict JSON only, never prose or markdown fences."},
        {"role": "user", "content": prompt},
    ]
    with track_run(ctx, agent_type="coder", provider=CODER_PROVIDER, input_context=input_context, retry_count=attempt) as run:
        try:
            files, response, served_by, tried, malformed = _request_files(messages, attempt)
        except _CoderKeysExhausted as exc:
            run.output = {"error": str(exc), "keys_tried": exc.attempted}
            raise
        diff, file_diffs = _apply_files_and_diff(ctx.local_path, files)
        result = {"diff": diff, "files": [f["path"] for f in file_diffs], "file_diffs": file_diffs}
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
    # Asks for the rewrites and re-asks a couple of times if the model hands back unusable JSON.
    tried: list[str] = []
    last_exc: AgentRunFailed | None = None
    for reask in range(MAX_MALFORMED_RETRIES + 1):
        current = messages if reask == 0 else [*messages, *_reask_turn(last_exc)]
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
    # Builds the nudge message for a re-ask, without echoing the oversized bad response back.
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
    # Raised when every Coder key the pool offered has failed.
    def __init__(self, message: str, attempted: list[str]):
        # Keeps the list of slots actually tried so the trace can show the full picture.
        super().__init__(message)
        self.attempted = attempted
def _call_coder_llm(messages: list[dict], attempt: int) -> tuple[llm_client.LLMResponse, str, list[str]]:
    # Walks the key pool in preference order, failing over on error and reporting each outcome back.
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
                max_output_tokens=_CODER_MAX_OUTPUT_TOKENS,
            )
        except llm_client.LLMRateLimitError as exc:
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
    # Logs which key failed and whether there is another one left to fall back on.
    logger.warning(
        "Coder: key %s failed (%s)%s",
        slot,
        exc,
        " -- failing over to the next key" if has_more else " -- no more keys to try",
    )
def _plan_json(plan: dict) -> str:
    # Pretty-prints the plan for embedding in the prompt.
    import json
    return json.dumps(plan, indent=2)
def _select_relevant_files(repo_path: str, plan: dict) -> list[str]:
    # Prefers files named in the plan, falling back to a size-capped sweep when nothing matches.
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
    # Renders the chosen files as fenced blocks, trimming each one and the total to the context budget.
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
    # Checks each entry has a path and content, and collapses duplicate paths keeping the last one.
    data = parse_strict_json(text)
    if not isinstance(data, dict) or not isinstance(data.get("files"), list) or not data["files"]:
        raise AgentRunFailed(f"Coder JSON missing a non-empty 'files' list. Raw output: {text[:500]!r}")
    for entry in data["files"]:
        if not isinstance(entry, dict) or not entry.get("path") or "content" not in entry:
            raise AgentRunFailed(f"Coder 'files' entries need 'path' and 'content'. Raw output: {text[:500]!r}")
    deduped = {entry["path"]: entry for entry in data["files"]}
    if len(deduped) != len(data["files"]):
        logger.warning(
            "Coder returned duplicate paths %s -- keeping the last entry for each",
            [p for p in {e["path"] for e in data["files"]} if sum(e["path"] == p for e in data["files"]) > 1],
        )
    return list(deduped.values())
def _apply_files_and_diff(repo_path: str, files: list[dict]) -> str:
    # Writes each rewritten file into the clone and returns the real git diff plus per-file before/after pairs.
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
        file_diffs.append({"path": rel_str, "old_content": old_content, "new_content": entry["content"]})
    try:
        repo = Repo(repo_path)
    except InvalidGitRepositoryError as exc:
        raise AgentRunFailed(f"repo_path {repo_path!r} is not a git repository: {exc}") from exc
    with repo:
        if written:
            try:
                repo.git.add("-N", *written)
            except Exception:  # noqa: BLE001
                pass
        diff_text = repo.git.diff("--no-color", *written) if written else ""
    return diff_text, file_diffs
def apply_files(repo_path: str, files: list[dict]) -> None:
    # Writes saved {path, content} entries back into a clone (used when a retry resumes after the Coder).
    _apply_files_and_diff(repo_path, files)
def _safe_relative_path(root: Path, raw_path: str) -> Path:
    # Blocks any path that would escape the repo root, such as one using '..'.
    candidate = (root / raw_path).resolve()
    try:
        rel = candidate.relative_to(root)
    except ValueError as exc:
        raise AgentRunFailed(f"Coder attempted to write outside the repo root: {raw_path!r}") from exc
    if is_blocked_path(str(rel)):
        raise AgentRunFailed(f"Coder attempted to write a protected path (secrets, CI or .git): {raw_path!r}")
    return rel
def summarize_changes(repo_path: str, paths: list[str]) -> dict:
    # Cumulative view of every file touched across attempts, against the original commit:
    # the git diff, per-file before/after, final contents, and the original git modes.
    with Repo(repo_path) as repo:
        return _summarize_changes(repo, repo_path, paths)
def _summarize_changes(repo: Repo, repo_path: str, paths: list[str]) -> dict:
    # Body of summarize_changes, split out so the Repo handle is always closed (Windows locks the clone otherwise).
    changed: list[dict] = []
    file_diffs: list[dict] = []
    contents: dict[str, str] = {}
    modes: dict[str, str] = {}
    for rel in sorted(set(paths)):
        abs_path = Path(repo_path) / rel
        if not abs_path.is_file():
            continue
        new_content = abs_path.read_text(encoding="utf-8", errors="replace")
        tree_entry = repo.git.ls_tree("HEAD", "--", rel).split()
        if tree_entry:
            # Normalise line endings the same way read_text does, so CRLF blobs don't read as changed.
            old_content = repo.git.show(f"HEAD:{rel}", strip_newline_in_stdout=False).replace("\r\n", "\n")
            if old_content == new_content:
                continue
            change, mode = "modified", tree_entry[0]
        else:
            old_content, change, mode = "", "added", "100644"
        changed.append({"path": rel, "change": change})
        contents[rel] = new_content
        modes[rel] = mode
        file_diffs.append({"path": rel, "old_content": old_content, "new_content": new_content})
    diff = repo.git.diff("--no-color", "HEAD", "--", *contents) if contents else ""
    return {"diff": diff, "changed_files": changed, "file_diffs": file_diffs, "contents": contents, "modes": modes}
