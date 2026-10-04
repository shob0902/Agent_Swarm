# Reviewer agent: structured code review of the cumulative diff, backed by deterministic safety checks that can veto the model.
from __future__ import annotations
import json
from django.conf import settings
from .. import llm_client
from ..prompts import load_prompt
from .common import AgentRunFailed, parse_strict_json, track_run
from .safety import scan_changes
MAX_REVIEW_OUTPUT_TOKENS = 1024
MAX_DIFF_CHARS = 6000
MAX_CHANGED_FILES_BEFORE_WARNING = 15
REGRESSION_RISKS = {"low", "medium", "high"}
CHECK_KEYS = (
    "implements_request", "follows_conventions", "tests_pass", "regression_risk",
    "unnecessary_changes", "security_concerns", "ready_for_review",
)
def run_reviewer(ctx, plan: dict, changes: dict, test_result=None, attempt: int = 0) -> dict:
    # Sends request, plan, validation results and diff to the model, then merges in the deterministic findings.
    diff = changes.get("diff") or "(no diff produced)"
    changed_files = changes.get("changed_files") or []
    test_summary = _test_summary(test_result)
    stack_summary = ctx.profile.summary() if ctx.profile else "(not analysed)"
    prompt = load_prompt(
        "reviewer_prompt",
        task_description=ctx.description,
        stack_summary=stack_summary,
        plan_json=json.dumps(plan, indent=2),
        test_summary=test_summary,
        changed_files="\n".join(f"- {f['path']} ({f.get('change', 'modified')})" for f in changed_files) or "(none)",
        diff=diff[:MAX_DIFF_CHARS] + ("\n... (diff truncated)" if len(diff) > MAX_DIFF_CHARS else ""),
    )
    input_context = {"plan": plan, "diff": diff[:MAX_DIFF_CHARS], "test_summary": test_summary, "changed_files": changed_files}
    with track_run(ctx, agent_type="reviewer", provider="groq", input_context=input_context, retry_count=attempt) as run:
        blocking, warnings = _deterministic_findings(changes, test_result)
        if not changed_files:
            blocking.append("The Coder produced no effective change to the repository.")
        response = llm_client.call_llm(
            "groq",
            [
                {"role": "system", "content": "You output strict JSON only, never prose or markdown fences."},
                {"role": "user", "content": prompt},
            ],
            api_key=settings.GROQ_API_KEY_REVIEWER,
            max_output_tokens=MAX_REVIEW_OUTPUT_TOKENS,
        )
        model_review = _validate_review(response.text)
        review = _merge(model_review, blocking, warnings)
        run.output = {"raw_response": response.text, "raw": response.raw, "model_review": model_review, **review}
        return review
def _deterministic_findings(changes: dict, test_result) -> tuple[list[str], list[str]]:
    # Checks the model can't talk its way past: secrets, protected paths, failing required checks, sprawling diffs.
    blocking = [f.as_issue() for f in scan_changes(changes.get("contents") or {})]
    warnings: list[str] = []
    if test_result is not None and not test_result.passed:
        blocking.append("Required validation checks are failing.")
    count = len(changes.get("changed_files") or [])
    if count > MAX_CHANGED_FILES_BEFORE_WARNING:
        warnings.append(f"{count} files changed -- check that every one is needed for this request.")
    return blocking, warnings
def _merge(model_review: dict, blocking: list[str], warnings: list[str]) -> dict:
    # Final verdict: the model's, unless a deterministic check blocks it.
    issues = list(model_review["issues"])
    if blocking:
        issues = blocking + [i for i in issues if i not in blocking]
    approved = model_review["approved"] and not blocking
    if approved:
        suggestions = model_review["suggestions"] + [i for i in issues if i not in model_review["suggestions"]]
        issues = []
    else:
        suggestions = list(model_review["suggestions"])
    suggestions += [w for w in warnings if w not in suggestions]
    summary = model_review["summary"]
    if blocking and model_review["approved"]:
        summary = f"Rejected by automated safety checks. {summary}".strip()
    return {
        "approved": approved,
        "summary": summary,
        "issues": issues,
        "suggestions": suggestions,
        "checks": model_review["checks"],
    }
def _validate_review(text: str) -> dict:
    # Normalises the model's verdict into {approved, summary, issues, suggestions, checks}, tolerating the old "concerns" key.
    data = parse_strict_json(text)
    if not isinstance(data, dict) or not isinstance(data.get("approved"), bool):
        raise AgentRunFailed(f"Reviewer JSON missing boolean 'approved'. Raw output: {text[:500]!r}")
    issues = data.get("issues", data.get("concerns", []))
    suggestions = data.get("suggestions", [])
    if not isinstance(issues, list) or not isinstance(suggestions, list):
        raise AgentRunFailed(f"Reviewer 'issues'/'suggestions' must be lists. Raw output: {text[:500]!r}")
    raw_checks = data.get("checks") if isinstance(data.get("checks"), dict) else {}
    checks = {k: raw_checks[k] for k in CHECK_KEYS if k in raw_checks}
    if checks.get("regression_risk") not in REGRESSION_RISKS:
        checks.pop("regression_risk", None)
    return {
        "approved": data["approved"],
        "summary": data["summary"].strip() if isinstance(data.get("summary"), str) else "",
        "issues": [str(i) for i in issues if str(i).strip()],
        "suggestions": [str(s) for s in suggestions if str(s).strip()],
        "checks": checks,
    }
def _test_summary(test_result) -> str:
    # Compact, token-cheap description of what the Tester ran and how it went.
    if test_result is None:
        return "(not run)"
    lines = [f"Overall: {test_result.status.upper()}"]
    for check in test_result.checks:
        advisory = "" if check.required else " (advisory)"
        lines.append(f"- {check.name}{advisory}: {check.status}" + (f" -- {check.summary}" if check.summary else ""))
    if not test_result.checks:
        lines.append("- no test suite, build or lint configuration was detected")
    return "\n".join(lines)
