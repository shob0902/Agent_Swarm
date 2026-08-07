from django.conf import settings
from django.db import models


class Task(models.Model):
    """A single unit of work handed to the agent swarm.

    One `github_url` per task (v1 has no multi-repo support). The pipeline
    shallow-clones this public GitHub repo into a throwaway temp directory
    at run time (see services/repo.py) and bind-mounts *that* into the
    sandbox container -- nothing here ever touches a path on the machine
    running Django/Celery directly, so this works for anyone's repo, not
    just one physically checked out on the server's disk.

    Ownership: every Task belongs to exactly one `user` -- this is the
    entire multi-tenant boundary for the app (AgentRun has no `user_id` of
    its own; it's isolated transitively through `AgentRun.task.user`, see
    `agents/permissions.py` and `agents/views.py`).
    """

    STATUS_CHOICES = [
        ("pending", "pending"),
        ("planning", "planning"),
        ("coding", "coding"),
        ("testing", "testing"),
        ("review", "review"),
        ("done", "done"),
        ("failed", "failed"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="tasks", on_delete=models.CASCADE)
    title = models.CharField(max_length=200, blank=True, help_text="User-editable; falls back to a truncated description when blank")
    description = models.TextField(help_text="e.g. 'Add input validation to the /signup endpoint'")
    github_url = models.CharField(max_length=500, help_text="Public GitHub repo URL, e.g. https://github.com/owner/repo")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    is_favorite = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Task #{self.pk} [{self.status}] {self.description[:60]}"

    @property
    def display_title(self) -> str:
        return self.title or (self.description[:60] + ("…" if len(self.description) > 60 else ""))


class AgentRun(models.Model):
    """One audit-trail row per agent invocation within a task's pipeline.

    Created with status='pending' *before* the LLM/sandbox call, then
    updated afterwards -- including on exceptions -- so a crashed agent is
    always visible in the trace, never silently missing.
    """

    AGENT_TYPE_CHOICES = [
        ("planner", "planner"),
        ("coder", "coder"),
        ("tester", "tester"),
        ("reviewer", "reviewer"),
    ]
    PROVIDER_CHOICES = [
        ("gemini", "gemini"),
        ("groq", "groq"),
        ("none", "none"),
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
        return f"{self.agent_type} run #{self.pk} for Task #{self.task_id} [{self.status}]"
