# Runs one task end to end: clone -> analyze -> plan -> (code -> test)* -> review, retried within fixed bounds -> pull request.
# Progress is checkpointed so a failed task can be retried from the stage that failed.
from __future__ import annotations
import logging
from dataclasses import asdict, dataclass
from django.conf import settings
from django.utils import timezone
from ..github.client import GitHubClient
from ..github.pr_body import build_commit_message, build_pr_body, build_pr_title
from ..github.publisher import FileChange, PublishError, PublishRequest, PullRequestPublisher
from ..github.repo_url import parse_github_url
from ..services.analyzer import detect_project, run_analyzer
from ..services.coder import apply_files, run_coder, summarize_changes
from ..services.common import track_run
from ..services.planner import run_planner
from ..services.repo import RepoCloneError, checkout_commit, cleanup_clone, clone_repo, head_info
from ..services.reviewer import run_reviewer
from ..services.tester import TestResult, run_tester
from .context import PipelineContext
from .reporting import Reporter
from .resume import is_publishable
logger = logging.getLogger(__name__)
TERMINAL_STATUSES = {"done", "failed"}
class StageFailed(Exception):
    # Stops the pipeline with a user-facing reason attached to the stage that failed.
    def __init__(self, stage: str, message: str):
        # Keeps the stage name for the task's final_result.
        super().__init__(message)
        self.stage = stage
@dataclass
class ValidatedChange:
    # The approved result of the code/test/review loop, ready to publish.
    changes: dict
    test_result: TestResult
    review: dict
    retry_count: int
    review_cycles: int
def execute_task(reporter: Reporter, *, run_url: str = "") -> dict:
    # Entry point used by both executors. Never raises for pipeline failures; the outcome is written to the task.
    # When the task carries resume_from + a checkpoint (a Retry), stages that already succeeded are skipped.
    task = reporter.fetch_task()
    if task["status"] in TERMINAL_STATUSES:
        logger.warning("Task %s is already %s; not running it again", task["id"], task["status"])
        return {"status": task["status"], "skipped": True}
    ctx = PipelineContext(
        task_id=task["id"],
        description=task["description"],
        github_url=task["github_url"],
        reporter=reporter,
        run_url=run_url,
        checkpoint=dict(task.get("checkpoint") or {}),
    )
    resume = task.get("resume_from") or ""
    # Earlier executions' runs, so the PR's agent summary covers the whole history, not just this attempt.
    reporter.runs[:0] = [dict(r, id=f"previous-{i}") for i, r in enumerate(task.get("previous_runs") or [])]
    publish_only = resume == "github" and is_publishable(ctx.checkpoint)
    first_status, first_agent = ("publishing", "github") if publish_only else ("analyzing", "analyzer")
    _update(ctx, status=first_status, current_agent=first_agent, started_at=timezone.now(), error_message="",
            **({"workflow_run_url": run_url} if run_url else {}))
    if resume:
        logger.info("Task %s: resuming at %s", ctx.task_id, resume)
    try:
        if publish_only:
            # Everything up to an approved review is in the checkpoint; the PR step needs no clone.
            cp = ctx.checkpoint
            ctx.base_branch, ctx.base_sha = cp["base_branch"], cp["base_sha"]
            return _finish(ctx, cp["plan"], _validated_from_checkpoint(cp))
        try:
            ctx.local_path = clone_repo(ctx.github_url)
        except RepoCloneError as exc:
            raise StageFailed("clone", str(exc)) from exc
        return _run_stages(ctx, resume)
    except StageFailed as exc:
        return _fail(ctx, exc.stage, str(exc))
    except Exception as exc:  # noqa: BLE001 -- anything unexpected still has to land on the task
        logger.exception("Task %s crashed", ctx.task_id)
        return _fail(ctx, ctx.extra.get("stage", "pipeline"), f"{type(exc).__name__}: {exc}")
    finally:
        cleanup_clone(ctx.local_path)
def _run_stages(ctx: PipelineContext, resume: str = "") -> dict:
    # The pipeline stage by stage, starting at `resume` when the checkpoint supports it; helpers raise StageFailed to stop.
    cp = ctx.checkpoint
    if resume and cp.get("base_sha"):
        try:
            checkout_commit(ctx.local_path, cp["base_sha"])
        except RepoCloneError as exc:
            raise StageFailed("clone", str(exc)) from exc
        ctx.base_branch, ctx.base_sha = cp.get("base_branch", ""), cp["base_sha"]
    else:
        resume = ""
        ctx.checkpoint = {}
        base = head_info(ctx.local_path)
        ctx.base_branch, ctx.base_sha = base.branch, base.sha
        _update(ctx, base_branch=base.branch)
        _save_checkpoint(ctx, base_branch=base.branch, base_sha=base.sha)
    if resume:
        # Deterministic and cheap, so it's recomputed rather than stored; no new trace entry on a resume.
        ctx.profile = detect_project(ctx.local_path)
    else:
        _stage(ctx, "analyzing", "analyzer", run_analyzer, ctx)
    if resume in ("", "planner") or not ctx.checkpoint.get("plan"):
        plan = _stage(ctx, "planning", "planner", run_planner, ctx)
        _update(ctx, plan=plan)
        _save_checkpoint(ctx, plan=plan, changes=None, changed_files=None, modes=None, test=None, review=None, feedback=None)
        resume = ""
    else:
        plan = ctx.checkpoint["plan"]
    start, touched, feedback, prior_test = _resume_entry(ctx, resume)
    validated = _code_test_review(ctx, plan, start=start, touched=touched, feedback=feedback, prior_test=prior_test)
    return _finish(ctx, plan, validated)
def _resume_entry(ctx: PipelineContext, resume: str):
    # Where the code/test/review loop starts on a resume, after re-applying the saved code to the clean clone.
    cp = ctx.checkpoint
    changes = cp.get("changes") or {}
    if not resume or not changes:
        return "coder", set(), cp.get("feedback") if resume == "coder" else None, None
    apply_files(ctx.local_path, [{"path": p, "content": c} for p, c in changes.items()])
    touched = set(changes)
    if resume == "coder":
        return "coder", touched, cp.get("feedback"), None
    review, test = cp.get("review") or {}, cp.get("test") or {}
    if resume in ("reviewer", "github") and review and not review.get("approved"):
        return "coder", touched, _review_feedback(review.get("issues") or []), None
    if resume in ("reviewer", "github") and test.get("passed"):
        return "reviewer", touched, None, TestResult.from_dict(test)
    return "tester", touched, cp.get("feedback"), None
def _code_test_review(
    ctx: PipelineContext,
    plan: dict,
    *,
    start: str = "coder",
    touched: set[str] | None = None,
    feedback: str | None = None,
    prior_test: TestResult | None = None,
) -> ValidatedChange:
    # Coder -> Tester until validation passes (MAX_TEST_RETRIES attempts), then Reviewer; a rejection
    # restarts the Coder -> Tester loop with the review as feedback, at most MAX_REVIEW_RETRIES times.
    # Both loops are plain bounded for-loops, so the pipeline cannot spin forever. A resumed run can
    # enter at the Tester (saved code) or the Reviewer (saved code + passing tests) on its first cycle.
    max_attempts = max(1, settings.MAX_TEST_RETRIES)
    max_review_retries = max(0, settings.MAX_REVIEW_RETRIES)
    touched = set(touched or ())
    coder_runs = 0
    last_issues: list[str] = []
    for cycle in range(max_review_retries + 1):
        test_result: TestResult | None = None
        if cycle == 0 and start == "reviewer" and prior_test is not None:
            test_result = prior_test
        else:
            for attempt in range(max_attempts):
                if not (cycle == 0 and attempt == 0 and start == "tester"):
                    coder_result = _stage(ctx, "coding", "coder", run_coder, ctx, plan, feedback, coder_runs, sorted(touched))
                    touched.update(coder_result["files"])
                    coder_runs += 1
                    _update(ctx, retry_count=coder_runs - 1)
                    _checkpoint_code(ctx, touched, feedback)
                _update(ctx, test_status="pending")
                test_result = _stage(ctx, "testing", "tester", run_tester, ctx, sorted(touched), max(coder_runs - 1, 0))
                _update(ctx, test_status=test_result.status, test_results=test_result.as_dict(include_logs=False))
                if not test_result.passed:
                    feedback = "The previous attempt failed validation. Fix exactly these failures:\n" + test_result.output
                _save_checkpoint(ctx, test={**test_result.as_dict(include_logs=False), "passed": test_result.passed},
                                 feedback=None if test_result.passed else feedback)
                if test_result.passed:
                    break
            else:
                raise StageFailed("tester", f"Validation still failing after {max_attempts} Coder attempt(s) in review cycle {cycle + 1}")
        changes = summarize_changes(ctx.local_path, sorted(touched))
        _update(ctx, review_status="pending")
        review = _stage(ctx, "review", "reviewer", run_reviewer, ctx, plan, changes, test_result, cycle)
        _update(ctx, review_status="approved" if review["approved"] else "rejected", review_result=review)
        _save_checkpoint(ctx, review=review, retry_count=max(coder_runs - 1, 0), review_cycles=cycle)
        if review["approved"]:
            return ValidatedChange(changes, test_result, review, max(coder_runs - 1, 0), cycle)
        last_issues = review.get("issues") or []
        if cycle < max_review_retries:
            _update(ctx, review_cycles=cycle + 1)
            feedback = _review_feedback(last_issues)
    raise StageFailed(
        "reviewer",
        f"Reviewer rejected the change after {max_review_retries + 1} review cycle(s): " + "; ".join(last_issues[:5]),
    )
def _finish(ctx: PipelineContext, plan: dict, validated: ValidatedChange) -> dict:
    # Opens the PR (unless disabled) and marks the task done.
    pr = _publish(ctx, plan, validated)
    final = {
        "outcome": "pull_request_created" if pr else "validated_without_pr",
        "files_changed": [f["path"] for f in validated.changes["changed_files"]],
        "tests": validated.test_result.status,
        "review": "approved",
        "retry_count": validated.retry_count,
        "review_cycles": validated.review_cycles,
        **({"pr_url": pr["pr_url"], "pr_mode": pr["mode"], "head_repo": pr["head_repo"], "access": pr["access"]} if pr else {}),
    }
    _update(ctx, status="done", current_agent="", completed_at=timezone.now(), final_result=final)
    logger.info("Task %s done: %s", ctx.task_id, final)
    return final
def _review_feedback(issues: list[str]) -> str:
    # Coder instructions built from a Reviewer rejection.
    return (
        "The Reviewer rejected the previous implementation. Address every issue below while keeping "
        "the validation checks passing:\n" + "\n".join(f"- {i}" for i in issues or ["(no specific issues given)"])
    )
def _checkpoint_code(ctx: PipelineContext, touched: set[str], feedback: str | None) -> None:
    # Saves the cumulative code after a Coder run; any earlier test/review no longer applies to it.
    summary = summarize_changes(ctx.local_path, sorted(touched))
    _save_checkpoint(
        ctx,
        changes=summary["contents"],
        changed_files=summary["changed_files"],
        modes=summary["modes"],
        feedback=feedback,
        test=None,
        review=None,
    )
def _save_checkpoint(ctx: PipelineContext, **fields) -> None:
    # Merges fields into the checkpoint (None removes a key) and persists it.
    for key, value in fields.items():
        if value is None:
            ctx.checkpoint.pop(key, None)
        else:
            ctx.checkpoint[key] = value
    _update(ctx, checkpoint=ctx.checkpoint)
def _validated_from_checkpoint(cp: dict) -> ValidatedChange:
    # The approved result as saved by an earlier run, for a PR-only retry.
    changes = {
        "diff": "",
        "changed_files": cp.get("changed_files") or [{"path": p, "change": "modified"} for p in cp["changes"]],
        "file_diffs": [],
        "contents": cp["changes"],
        "modes": cp.get("modes") or {},
    }
    return ValidatedChange(changes, TestResult.from_dict(cp["test"]), cp["review"], cp.get("retry_count", 0), cp.get("review_cycles", 0))
def _publish(ctx: PipelineContext, plan: dict, validated: ValidatedChange) -> dict | None:
    # Opens the PR (branch + commit + PR) unless PR creation is switched off.
    if not settings.CREATE_PULL_REQUESTS:
        _update(ctx, pr_state="skipped")
        return None
    _update(ctx, status="publishing", current_agent="github", pr_state="creating")
    ctx.extra["stage"] = "github"
    repo = parse_github_url(ctx.github_url)
    title = build_pr_title(ctx.description, plan)
    body = build_pr_body(
        task_id=ctx.task_id,
        request=ctx.description,
        plan=plan,
        changed_files=validated.changes["changed_files"],
        test_results=validated.test_result.as_dict(include_logs=False),
        review=validated.review,
        runs=list(ctx.reporter.runs),
        retry_count=validated.retry_count,
        review_cycles=validated.review_cycles,
        run_url=ctx.run_url,
    )
    contents, modes = validated.changes["contents"], validated.changes["modes"]
    request = PublishRequest(
        repo=repo,
        task_id=ctx.task_id,
        base_branch=ctx.base_branch,
        base_sha=ctx.base_sha,
        changes=[FileChange(path=p, content=c, mode=modes.get(p, "100644")) for p, c in contents.items()],
        title=title,
        body=body,
        commit_message=build_commit_message(title, plan, ctx.task_id),
        branch_hint=title,
        labels=list(settings.PR_LABELS),
        validation_state="success",
        validation_description=f"Tests {validated.test_result.status}; reviewer approved",
        target_url=ctx.run_url,
    )
    input_context = {"repository": repo.full_name, "base_branch": ctx.base_branch, "base_sha": ctx.base_sha, "files": list(contents)}
    try:
        with track_run(ctx, agent_type="github", provider="none", input_context=input_context) as run:
            if not settings.AGENT_GITHUB_TOKEN:
                raise PublishError("AGENT_GITHUB_TOKEN is not configured, so the pull request cannot be created")
            publisher = PullRequestPublisher(
                GitHubClient(settings.AGENT_GITHUB_TOKEN, settings.GITHUB_API_URL),
                branch_prefix=settings.PR_BRANCH_PREFIX,
                allow_fork=settings.PR_ALLOW_FORKS,
                allowed_owners=settings.ALLOWED_REPO_OWNERS,
            )
            result = publisher.publish(request)
            run.output = {**asdict(result), "title": title}
    except PublishError as exc:
        _update(ctx, pr_state="failed", pr_error=str(exc))
        raise StageFailed("github", str(exc)) from exc
    _update(
        ctx,
        branch_name=result.branch,
        commit_sha=result.commit_sha,
        pr_url=result.pr_url,
        pr_number=result.pr_number,
        pr_state="open",
        pr_error="; ".join(result.warnings),
    )
    return asdict(result)
def _stage(ctx: PipelineContext, status: str, agent: str, fn, *args):
    # Marks the stage as current, runs it, and converts any exception into StageFailed.
    ctx.extra["stage"] = agent
    _update(ctx, status=status, current_agent=agent)
    try:
        return fn(*args)
    except StageFailed:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Task %s failed at %s stage", ctx.task_id, agent)
        raise StageFailed(agent, f"{agent} failed: {exc}") from exc
def _fail(ctx: PipelineContext, stage: str, message: str) -> dict:
    # Records the failure on the task; never raises, because there's nothing further up to catch it.
    logger.warning("Task %s failed at %s: %s", ctx.task_id, stage, message)
    result = {"outcome": "failed", "stage": stage, "error": message}
    try:
        _update(ctx, status="failed", completed_at=timezone.now(), error_message=message[:5000], final_result=result)
    except Exception:  # noqa: BLE001
        logger.exception("Could not record failure of task %s", ctx.task_id)
    return result
def _update(ctx: PipelineContext, **fields) -> None:
    # Single choke point for task-state writes.
    ctx.reporter.update_task(**fields)
