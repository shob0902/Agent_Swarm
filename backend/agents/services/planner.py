"""Planner agent: task description + repo file tree -> ordered JSON step plan.

Runs on Groq with its own dedicated key (GROQ_API_KEY_PLANNER), so a
Planner call can never eat into the Coder's or Reviewer's quota -- see
Section 3. Takes no action on the repo itself; purely produces a plan for
the Coder agent to follow.
"""
from __future__ import annotations

from pathlib import Path

from django.conf import settings

from .. import llm_client
from ..prompts import load_prompt
from .common import AgentRunFailed, parse_strict_json, track_run

# Directories skipped when building the file tree sent to the LLM -- keeps
# the prompt token-efficient per Section 3's free-tier budget guidance.
IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", "venv", ".venv", "env",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build", "egg-info",
}
MAX_TREE_ENTRIES = 400
MAX_PLAN_OUTPUT_TOKENS = 1500


def build_file_tree(repo_path: str) -> str:
    """Flat, sorted listing of the repo (relative paths), skipping noise
    dirs and capped at MAX_TREE_ENTRIES so it stays cheap to send to the LLM."""
    root = Path(repo_path)
    if not root.exists():
        return "(local checkout does not exist)"

    lines: list[str] = []
    for path in sorted(root.rglob("*")):
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        rel = path.relative_to(root)
        lines.append(str(rel) + ("/" if path.is_dir() else ""))
        if len(lines) >= MAX_TREE_ENTRIES:
            lines.append("... (truncated)")
            break
    return "\n".join(lines) if lines else "(empty repository)"


def run_planner(task) -> dict:
    """Returns the parsed plan dict: {"steps": [str, ...]}.

    Raises AgentRunFailed if the model output isn't valid JSON in the
    expected shape; raises llm_client.LLMError if the provider call itself
    fails (auth, exhausted retries, etc). Both are caught by the pipeline
    task, which is what actually marks the Task failed.
    """
    file_tree = build_file_tree(task.local_path)
    prompt = load_prompt("planner_prompt", task_description=task.description, file_tree=file_tree)
    input_context = {"task_description": task.description, "file_tree": file_tree}

    with track_run(task, agent_type="planner", provider="groq", input_context=input_context) as run:
        response = llm_client.call_llm(
            "groq",
            [
                {"role": "system", "content": "You output strict JSON only, never prose or markdown fences."},
                {"role": "user", "content": prompt},
            ],
            api_key=settings.GROQ_API_KEY_PLANNER,
            # A plan is a short list of one-line steps, so this doesn't need
            # the 4096 default -- and asking for it actively hurts: Groq's
            # free tier counts prompt + completion against one ~6000
            # tokens/minute ceiling, and the file tree in this prompt is the
            # big half. Reserving only what the output actually needs is
            # what leaves room for a large repo's tree to fit at all.
            max_output_tokens=MAX_PLAN_OUTPUT_TOKENS,
        )
        plan = _validate_plan(response.text)
        run.output = {"raw_response": response.text, "raw": response.raw, "plan": plan}
        return plan


def _validate_plan(text: str) -> dict:
    data = parse_strict_json(text)
    if not isinstance(data, dict) or not isinstance(data.get("steps"), list) or not data["steps"]:
        raise AgentRunFailed(f"Planner JSON missing a non-empty 'steps' list. Raw output: {text[:500]!r}")
    if not all(isinstance(s, str) for s in data["steps"]):
        raise AgentRunFailed(f"Planner 'steps' must all be strings. Raw output: {text[:500]!r}")
    return data
