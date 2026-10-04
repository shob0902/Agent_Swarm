# DRF serializers that shape Task and AgentRun payloads for the user API and for the runner API.
from rest_framework import serializers
from accounts.serializers import UserSerializer
from .github.validation import repository_error
from .models import AgentRun, Task
from .pipeline.resume import retry_plan
# Execution-state fields: written only by a pipeline runner, read-only to users.
STATE_FIELDS = [
    "status", "current_agent", "retry_count", "review_cycles", "plan",
    "test_status", "test_results", "review_status", "review_result",
    "base_branch", "branch_name", "commit_sha", "pr_url", "pr_number", "pr_state", "pr_error",
    "workflow_run_url", "final_result", "error_message", "started_at", "completed_at",
]
# Runner-only state: written by the pipeline, never sent to the browser (it holds whole file contents).
RUNNER_STATE_FIELDS = ["checkpoint"]
class AgentRunSerializer(serializers.ModelSerializer):
    # Read-only view of a single agent invocation in the trace.
    class Meta:
        model = AgentRun
        fields = [
            "id",
            "task",
            "agent_type",
            "provider",
            "input_context",
            "output",
            "status",
            "retry_count",
            "started_at",
            "duration_ms",
        ]
        read_only_fields = fields
class TaskSerializer(serializers.ModelSerializer):
    # Standard task payload with the owner nested inline; everything but title/favorite/archive is read-only after creation.
    user = UserSerializer(read_only=True)
    display_title = serializers.CharField(read_only=True)
    is_active = serializers.SerializerMethodField()
    class Meta:
        model = Task
        fields = [
            "id", "user", "title", "display_title", "description", "github_url",
            "is_favorite", "is_archived", "executor", "is_active",
            *STATE_FIELDS, "resume_from", "attempt",
            "dispatched_at", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "user", "display_title", "executor", "is_active",
            *STATE_FIELDS, "resume_from", "attempt",
            "dispatched_at", "created_at", "updated_at",
        ]
    def get_is_active(self, obj) -> bool:
        # True while the pipeline is still queued or running, so the UI knows to keep polling.
        return obj.status in Task.ACTIVE_STATUSES
    def validate_github_url(self, value):
        # Rejects a bad, private, archived or disallowed repo at creation time instead of minutes later in the runner.
        # On update the repo is immutable (see update()), so there is nothing to check.
        if self.instance is not None:
            return self.instance.github_url
        value = value.strip()
        error = repository_error(value)
        if error:
            raise serializers.ValidationError(error)
        return value
    def validate_description(self, value):
        # The improvement request must say something.
        if self.instance is not None:
            return self.instance.description
        if not value.strip():
            raise serializers.ValidationError("Describe the improvement you want.")
        return value.strip()
    def update(self, instance, validated_data):
        # The request and repo are fixed once the pipeline has been dispatched.
        validated_data.pop("description", None)
        validated_data.pop("github_url", None)
        return super().update(instance, validated_data)
class TaskDetailSerializer(TaskSerializer):
    # Same as TaskSerializer but also embeds the full list of agent runs and, for a failed task, where Retry would resume.
    runs = AgentRunSerializer(many=True, read_only=True)
    retry = serializers.SerializerMethodField()
    class Meta(TaskSerializer.Meta):
        fields = TaskSerializer.Meta.fields + ["runs", "retry"]
    def get_retry(self, obj):
        # {"stage": "github", "label": "Pull Request"} for a failed task; null otherwise.
        return retry_plan(obj)
class TaskStateSerializer(serializers.ModelSerializer):
    # The only task fields a runner may write, shared by the runner API and the in-process DbReporter.
    class Meta:
        model = Task
        fields = STATE_FIELDS + RUNNER_STATE_FIELDS
        extra_kwargs = {name: {"required": False} for name in STATE_FIELDS + RUNNER_STATE_FIELDS}
class RunnerTaskSerializer(serializers.ModelSerializer):
    # What the runner reads back about its task: the inputs and resume state, never the owner.
    previous_runs = serializers.SerializerMethodField()
    class Meta:
        model = Task
        fields = ["id", "description", "github_url", "status", "resume_from", "checkpoint", "previous_runs"]
        read_only_fields = fields
    def get_previous_runs(self, obj):
        # Summary of runs from earlier attempts, so a resumed run's PR describes the whole history.
        return [
            {"agent_type": r.agent_type, "status": r.status, "retry_count": r.retry_count, "duration_ms": r.duration_ms}
            for r in obj.runs.order_by("started_at", "id")
        ]
class AgentRunCreateSerializer(serializers.ModelSerializer):
    # Runner-side creation of a pending AgentRun.
    class Meta:
        model = AgentRun
        fields = ["id", "agent_type", "provider", "input_context", "retry_count"]
        read_only_fields = ["id"]
class AgentRunFinishSerializer(serializers.ModelSerializer):
    # Runner-side completion of an AgentRun.
    status = serializers.ChoiceField(choices=["success", "failure"])
    class Meta:
        model = AgentRun
        fields = ["status", "output", "duration_ms", "provider"]
