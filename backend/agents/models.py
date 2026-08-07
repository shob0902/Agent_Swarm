from django.db import models


class Task(models.Model):
    """A single unit of work handed to the agent swarm.

    One `repo_path` per task (v1 has no multi-repo support) pointing at a
    local git repo that gets bind-mounted into the sandbox container.
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

    description = models.TextField(help_text="e.g. 'Add input validation to the /signup endpoint'")
    repo_path = models.CharField(max_length=500, help_text="Absolute path to a local git repo")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Task #{self.pk} [{self.status}] {self.description[:60]}"


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
