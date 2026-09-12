# Planner agent: turns the task description plus the repo file tree into an ordered list of steps.
from __future__ import annotations
from pathlib import Path
from django.conf import settings
from .. import llm_client
from ..prompts import load_prompt
from .common import AgentRunFailed, parse_strict_json, track_run
IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", "venv", ".venv", "env",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build", "egg-info",
}
MAX_TREE_ENTRIES = 400
MAX_PLAN_OUTPUT_TOKENS = 1500
def build_file_tree(repo_path: str) -> str:
    # Builds a flat sorted listing of the repo, skipping noise directories and capping the length.
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
    # Asks the model for a plan and returns it as a dict of steps, recording the run as it goes.
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
            max_output_tokens=MAX_PLAN_OUTPUT_TOKENS,
        )
        plan = _validate_plan(response.text)
        run.output = {"raw_response": response.text, "raw": response.raw, "plan": plan}
        return plan
def _validate_plan(text: str) -> dict:
    # Confirms the model returned a non-empty list of string steps before we act on it.
    data = parse_strict_json(text)
    if not isinstance(data, dict) or not isinstance(data.get("steps"), list) or not data["steps"]:
        raise AgentRunFailed(f"Planner JSON missing a non-empty 'steps' list. Raw output: {text[:500]!r}")
    if not all(isinstance(s, str) for s in data["steps"]):
        raise AgentRunFailed(f"Planner 'steps' must all be strings. Raw output: {text[:500]!r}")
    return data
