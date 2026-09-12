# Celery pipeline that clones the repo then runs Planner, Coder, Tester and Reviewer in order.
from __future__ import annotations
import logging
from celery import shared_task
from django.conf import settings
from .models import Task
from .services.coder import run_coder
from .services.planner import run_planner
from .services.repo import RepoCloneError, cleanup_clone, clone_repo
from .services.reviewer import run_reviewer
from .services.tester import run_tester
logger = logging.getLogger(__name__)
@shared_task(bind=True)
def run_pipeline(self, task_id: int):
    # Entry point: clones the task's repo, runs every stage against it, then deletes the clone.
    task = Task.objects.get(id=task_id)
    try:
        task.local_path = clone_repo(task.github_url)
    except RepoCloneError as exc:
        logger.warning("Task %s: clone failed: %s", task_id, exc)
        _set_status(task, "failed")
        return {"stage": "clone", "error": str(exc)}
    try:
        return _run_pipeline_stages(task, task_id)
    finally:
        cleanup_clone(task.local_path)
def _run_pipeline_stages(task: Task, task_id: int):
    # Sequences the stages and retries the coder/tester pair until the tests pass or attempts run out.
    plan = _run_stage(task, "planning", "planner", run_planner, task)
    if plan is None:
        return {"stage": "planner", "error": "planner failed"}
    prior_test_output = None
    coder_result = None
    test_result = None
    max_retries = settings.MAX_TEST_RETRIES
    for attempt in range(max_retries):
        coder_result = _run_stage(task, "coding", "coder", run_coder, task, plan, prior_test_output, attempt)
        if coder_result is None:
            return {"stage": "coder", "error": "coder failed"}
        test_result = _run_stage(task, "testing", "tester", run_tester, task, coder_result, attempt)
        if test_result is None:
            return {"stage": "tester", "error": "tester failed"}
        if test_result.passed:
            break
        prior_test_output = test_result.output
    else:
        logger.warning("Task %s: tests still failing after %d attempts, giving up", task_id, max_retries)
        _set_status(task, "failed")
        return {"stage": "tester", "error": f"tests did not pass after {max_retries} attempts"}
    review = _run_stage(task, "review", "reviewer", run_reviewer, task, plan, coder_result)
    if review is None:
        return {"stage": "reviewer", "error": "reviewer failed"}
    _set_status(task, "done")
    return {"plan": plan, "coder_result": coder_result, "review": review}
def _run_stage(task: Task, status: str, stage_name: str, fn, *args):
    # Runs one stage and, if it throws, marks the task failed and returns None to halt the pipeline.
    _set_status(task, status)
    try:
        return fn(*args)
    except Exception:
        logger.exception("Task %s failed at %s stage", task.id, stage_name)
        _set_status(task, "failed")
        return None
def _set_status(task: Task, status: str) -> None:
    # Writes the task's new status to the database.
    task.status = status
    task.save(update_fields=["status", "updated_at"])
