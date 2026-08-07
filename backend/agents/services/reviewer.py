"""Reviewer agent: final "does this diff look reasonable / match the plan"
check, once tests have already passed. Uses Groq -- fast/cheap/low-latency
is exactly what a bounded final sanity check needs (Section 3).
"""
from __future__ import annotations

import json

from .. import llm_client
from ..prompts import load_prompt
from .common import AgentRunFailed, parse_strict_json, track_run


def run_reviewer(task, plan: dict, coder_result: dict) -> dict:
    """Returns {"approved": bool, "concerns": [str, ...]}."""
    diff = coder_result.get("diff") or "(no diff produced)"
    prompt = load_prompt("reviewer_prompt", plan_json=json.dumps(plan, indent=2), diff=diff[:6000])
    input_context = {"plan": plan, "diff": diff[:6000]}

    with track_run(task, agent_type="reviewer", provider="groq", input_context=input_context) as run:
        response = llm_client.call_llm(
            "groq",
            [
                {"role": "system", "content": "You output strict JSON only, never prose or markdown fences."},
                {"role": "user", "content": prompt},
            ],
        )
        review = _validate_review(response.text)
        run.output = {"raw_response": response.text, "raw": response.raw, **review}
        return review


def _validate_review(text: str) -> dict:
    data = parse_strict_json(text)
    if not isinstance(data, dict) or "approved" not in data or not isinstance(data["approved"], bool):
        raise AgentRunFailed(f"Reviewer JSON missing boolean 'approved'. Raw output: {text[:500]!r}")
    concerns = data.get("concerns", [])
    if not isinstance(concerns, list):
        raise AgentRunFailed(f"Reviewer 'concerns' must be a list. Raw output: {text[:500]!r}")
    return {"approved": data["approved"], "concerns": concerns}
