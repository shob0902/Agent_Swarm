# Decides where a failed task can resume, from its checkpoint (or, for older tasks, from the recorded agent runs).
from __future__ import annotations
from datetime import timedelta
from django.utils import timezone
# Stages a run can resume at, in pipeline order. "" means a full run from the beginning.
STAGE_ORDER = ("planner", "coder", "tester", "reviewer", "github")
STAGE_LABEL = {
    "": "the beginning",
    "planner": "Planner",
    "coder": "Coder",
    "tester": "Tester",
    "reviewer": "Reviewer",
    "github": "Pull Request",
}
# Failure stages that aren't agents (infrastructure); a retry jumps to the furthest checkpoint instead.
_INFRA_STAGES = {"", "clone", "dispatch", "runner", "pipeline"}
def is_publishable(cp: dict) -> bool:
    # Everything the PR step needs: base commit, plan, changes, passing validation and an approving review.
    return bool(
        cp.get("base_sha") and cp.get("base_branch") and cp.get("plan") and cp.get("changes")
        and (cp.get("test") or {}).get("passed") and (cp.get("review") or {}).get("approved")
    )
def _available(stage: str, cp: dict) -> bool:
    # Whether the checkpoint holds what's needed to start at this stage.
    if not cp.get("base_sha"):
        return False
    if stage == "planner":
        return True
    if stage == "coder":
        return bool(cp.get("plan"))
    if stage in ("tester", "reviewer"):
        return bool(cp.get("plan") and cp.get("changes"))
    if stage == "github":
        return is_publishable(cp)
    return False
def resume_point(failed_stage: str, cp: dict) -> str:
    # The stage to restart at: the one that failed, stepped back until the checkpoint can support it.
    failed_stage = failed_stage or ""
    if failed_stage == "analyzer":
        return ""
    if failed_stage in STAGE_ORDER:
        candidate = failed_stage
    elif failed_stage in _INFRA_STAGES:
        candidate = next((s for s in reversed(STAGE_ORDER) if _available(s, cp)), "")
    else:
        candidate = ""
    while candidate and not _available(candidate, cp):
        idx = STAGE_ORDER.index(candidate)
        candidate = STAGE_ORDER[idx - 1] if idx > 0 else ""
    return candidate
def checkpoint_from_history(task) -> dict:
    # Rebuilds a checkpoint for tasks that ran before checkpoints existed, from their AgentRun records.
    runs = list(task.runs.order_by("started_at", "id"))
    analyzer = next((r for r in reversed(runs) if r.agent_type == "analyzer" and r.status == "success" and (r.output or {}).get("base_sha")), None)
    if analyzer is None:
        return {}
    cp: dict = {
        "base_sha": analyzer.output["base_sha"],
        "base_branch": analyzer.output.get("base_branch") or task.base_branch,
        "retry_count": task.retry_count,
        "review_cycles": task.review_cycles,
    }
    if (task.plan or {}).get("steps"):
        cp["plan"] = task.plan
    originals: dict[str, str] = {}
    latest: dict[str, str] = {}
    for run in runs:
        if run.agent_type != "coder" or run.status != "success":
            continue
        for diff in (run.output or {}).get("file_diffs") or []:
            originals.setdefault(diff["path"], diff.get("old_content") or "")
            latest[diff["path"]] = diff.get("new_content") or ""
    changed = [p for p in latest if latest[p] != originals[p]]
    if changed:
        cp["changes"] = {p: latest[p] for p in changed}
        cp["changed_files"] = [{"path": p, "change": "modified" if originals[p] else "added"} for p in changed]
        cp["modes"] = {}
        if task.test_status in ("passed", "skipped", "failed") and task.test_results:
            cp["test"] = {**task.test_results, "passed": task.test_status != "failed"}
        if isinstance(task.review_result, dict) and "approved" in task.review_result:
            cp["review"] = task.review_result
    return cp
def effective_checkpoint(task) -> dict:
    # The stored checkpoint, or one rebuilt from history for older tasks.
    return dict(task.checkpoint) if task.checkpoint else checkpoint_from_history(task)
# A run that never checks in is abandoned: the runner died before it could report (bad secret, cancelled job...).
STALE_QUEUED_AFTER = timedelta(minutes=10)
# The workflow's job timeout is 45 minutes; no progress for longer than that means nobody is running the task.
STALE_RUNNING_AFTER = timedelta(minutes=50)
def is_stale(task, now=None) -> bool:
    # True for a task stuck in an active state with no runner activity for too long.
    now = now or timezone.now()
    if task.status == "queued":
        since = task.dispatched_at or task.updated_at
        return bool(since) and now - since > STALE_QUEUED_AFTER
    if task.status in task.ACTIVE_STATUSES:
        return bool(task.updated_at) and now - task.updated_at > STALE_RUNNING_AFTER
    return False
def is_retryable(task) -> bool:
    # Failed tasks, and tasks whose runner evidently died, can be retried.
    return task.status == "failed" or is_stale(task)
def retry_plan(task) -> dict | None:
    # For a retryable task: {"stage", "label", "stale"} describing where Retry would restart; None otherwise.
    if not is_retryable(task):
        return None
    failed_stage = (task.final_result or {}).get("stage", "") if task.status == "failed" else "runner"
    stage = resume_point(failed_stage, effective_checkpoint(task))
    return {"stage": stage, "label": STAGE_LABEL[stage], "stale": task.status != "failed"}
