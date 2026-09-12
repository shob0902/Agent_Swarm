# Database models for a task and the individual agent runs that make up its pipeline.
from django.conf import settings
from django.db import models
class Task(models.Model):
    # One unit of work for the agent swarm, owned by exactly one user and tied to one GitHub repo.
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
        # Short label used in the admin and in logs.
        return f"Task #{self.pk} [{self.status}] {self.description[:60]}"
    @property
    def display_title(self) -> str:
        # Uses the user's title if set, otherwise a truncated description.
        return self.title or (self.description[:60] + ("…" if len(self.description) > 60 else ""))
class AgentRun(models.Model):
    # Audit-trail row written for every agent invocation, created before the call and updated after.
    AGENT_TYPE_CHOICES = [
        ("planner", "planner"),
        ("coder", "coder"),
        ("tester", "tester"),
        ("reviewer", "reviewer"),
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
