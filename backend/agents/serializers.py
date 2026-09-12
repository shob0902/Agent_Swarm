# DRF serializers that shape Task and AgentRun payloads for the API.
from rest_framework import serializers
from accounts.serializers import UserSerializer
from .models import AgentRun, Task
from .services.repo import is_valid_github_url
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
    # Standard task payload with the owner nested inline.
    user = UserSerializer(read_only=True)
    display_title = serializers.CharField(read_only=True)
    class Meta:
        model = Task
        fields = [
            "id", "user", "title", "display_title", "description", "github_url",
            "status", "is_favorite", "is_archived", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "user", "display_title", "status", "created_at", "updated_at"]
    def validate_github_url(self, value):
        # Rejects a bad repo URL at creation time so the task doesn't fail later in the worker.
        if not is_valid_github_url(value):
            raise serializers.ValidationError(
                "Must be a public GitHub repo URL, e.g. https://github.com/owner/repo"
            )
        return value
class TaskDetailSerializer(TaskSerializer):
    # Same as TaskSerializer but also embeds the full list of agent runs.
    runs = AgentRunSerializer(many=True, read_only=True)
    class Meta(TaskSerializer.Meta):
        fields = TaskSerializer.Meta.fields + ["runs"]
