# Database models for a task and the individual agent runs that make up its pipeline.
from django.conf import settings
from django.db import models
class Task(models.Model):
    # One unit of work for the agent swarm, owned by exactly one user and tied to one GitHub repo.
    STATUS_CHOICES = [
        ("pending", "pending"),
        ("queued", "queued"),
        ("analyzing", "analyzing"),
        ("planning", "planning"),
        ("coding", "coding"),
        ("testing", "testing"),
        ("review", "review"),
        ("publishing", "publishing"),
        ("done", "done"),
        ("failed", "failed"),
    ]
    ACTIVE_STATUSES = {"pending", "queued", "analyzing", "planning", "coding", "testing", "review", "publishing"}
    TERMINAL_STATUSES = {"done", "failed"}
    EXECUTOR_CHOICES = [
        ("github_actions", "github_actions"),
        ("local", "local"),
    ]
    CHECK_STATUS_CHOICES = [
        ("", "not run"),
        ("pending", "pending"),
        ("passed", "passed"),
        ("failed", "failed"),
        ("skipped", "skipped"),
    ]
    REVIEW_STATUS_CHOICES = [
        ("", "not run"),
        ("pending", "pending"),
        ("approved", "approved"),
        ("rejected", "rejected"),
    ]
    PR_STATE_CHOICES = [
        ("", "none"),
        ("creating", "creating"),
        ("open", "open"),
        ("closed", "closed"),
        ("merged", "merged"),
        ("skipped", "skipped"),
        ("failed", "failed"),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="tasks", on_delete=models.CASCADE)
    title = models.CharField(max_length=200, blank=True, help_text="User-editable; falls back to a truncated description when blank")
    description = models.TextField(help_text="e.g. 'Add input validation to the /signup endpoint'")
    github_url = models.CharField(max_length=500, help_text="Public GitHub repo URL, e.g. https://github.com/owner/repo")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    is_favorite = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    # Execution state, written by whichever executor ran the pipeline (via a Reporter).
    executor = models.CharField(max_length=20, choices=EXECUTOR_CHOICES, blank=True, default="")
    current_agent = models.CharField(max_length=20, blank=True, default="")
    retry_count = models.IntegerField(default=0, help_text="Coder attempts beyond the first, across all cycles")
    review_cycles = models.IntegerField(default=0, help_text="Reviewer rejections that sent the work back to the Coder")
    plan = models.JSONField(default=dict, blank=True)
    test_status = models.CharField(max_length=20, choices=CHECK_STATUS_CHOICES, blank=True, default="")
    test_results = models.JSONField(default=dict, blank=True)
    review_status = models.CharField(max_length=20, choices=REVIEW_STATUS_CHOICES, blank=True, default="")
    review_result = models.JSONField(default=dict, blank=True)
    # GitHub output. Never the default branch -- see agents/github/publisher.py.
    base_branch = models.CharField(max_length=255, blank=True, default="")
    branch_name = models.CharField(max_length=255, blank=True, default="")
    commit_sha = models.CharField(max_length=64, blank=True, default="")
    pr_url = models.URLField(max_length=500, blank=True, default="")
    pr_number = models.IntegerField(null=True, blank=True)
    pr_state = models.CharField(max_length=20, choices=PR_STATE_CHOICES, blank=True, default="")
    pr_error = models.TextField(blank=True, default="")
    workflow_run_url = models.URLField(max_length=500, blank=True, default="")
    final_result = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default="")
    # Resume support: what each stage produced (base commit, plan, cumulative file contents, last test
    # result, review), so a retry can restart at the stage that failed instead of from scratch.
    checkpoint = models.JSONField(default=dict, blank=True)
    resume_from = models.CharField(max_length=20, blank=True, default="", help_text="Stage the current run resumes at; blank = full run")
    attempt = models.IntegerField(default=1, help_text="How many times this task has been executed")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        ordering = ["-created_at"]
    def __str__(self):
        # Short label used in the admin and in logs.
        return f"Task #{self.pk} [{self.status}] {self.description[:60]}"
    @property
    def is_terminal(self) -> bool:
        # True once the pipeline has finished one way or the other and must not be written to again.
        return self.status in self.TERMINAL_STATUSES
    @property
    def display_title(self) -> str:
        # Uses the user's title if set, otherwise a truncated description.
        return self.title or (self.description[:60] + ("…" if len(self.description) > 60 else ""))
class AgentRun(models.Model):
    # Audit-trail row written for every agent invocation, created before the call and updated after.
    AGENT_TYPE_CHOICES = [
        ("analyzer", "analyzer"),
        ("planner", "planner"),
        ("coder", "coder"),
        ("tester", "tester"),
        ("reviewer", "reviewer"),
        ("github", "github"),
    ]
    PROVIDER_CHOICES = [
        ("groq", "groq"),
        ("none", "none"),
        ("gemini", "gemini"),
    ]
    STATUS_CHOICES = [
        ("pending", "pending"),
        ("success", "success"),
        ("failure", "failure"),
    ]
    task = models.ForeignKey(Task, related_name="runs", on_delete=models.CASCADE)
    agent_type = models.CharField(max_length=20, choices=AGENT_TYPE_CHOICES)
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, blank=True, default="none")
    input_context = models.JSONField(default=dict)
    output = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    retry_count = models.IntegerField(default=0)
    started_at = models.DateTimeField(auto_now_add=True)
    duration_ms = models.IntegerField(null=True, blank=True)
    class Meta:
        ordering = ["started_at"]
    def __str__(self):
        # Short label used in the admin and in logs.
        return f"{self.agent_type} run #{self.pk} for Task #{self.task_id} [{self.status}]"
