"""Celery pipeline: clone -> Planner -> Coder <-> Tester (bounded retry
loop) -> Reviewer.

Every stage's AgentRun bookkeeping (create pending row, then record
success/failure + duration + output) happens inside services/common.py's
`track_run`, used by each `run_*` service function. This module's only job
is to clone the task's github_url into a scratch directory, sequence the
stages against it, drive the retry loop, make sure one crashed stage stops
the pipeline and marks the Task failed rather than silently continuing
(Section 6), and always clean the clone up afterwards.
"""
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
    task = Task.objects.get(id=task_id)

    try:
        # `task.local_path` is deliberately not a model field: it's only
        # ever meaningful for the lifetime of this clone, so it's set as a
        # plain runtime attribute and read by planner/coder/tester instead
        # of being persisted alongside github_url.
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
    """Sets task.status, runs `fn`, and on any exception marks the task
    failed and returns None so the caller can stop the pipeline. The
    per-agent AgentRun row is already marked failed by `track_run` inside
    `fn` before the exception reaches here -- this only owns the Task-level
    status and pipeline control flow.
    """
    _set_status(task, status)
    try:
        return fn(*args)
    except Exception:
        logger.exception("Task %s failed at %s stage", task.id, stage_name)
        _set_status(task, "failed")
        return None


def _set_status(task: Task, status: str) -> None:
    task.status = status
    task.save(update_fields=["status", "updated_at"])
