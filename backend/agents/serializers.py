from rest_framework import serializers

from accounts.serializers import UserSerializer

from .models import AgentRun, Task
from .services.repo import is_valid_github_url


class AgentRunSerializer(serializers.ModelSerializer):
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
        # Fail fast at task-creation time with a normal 400, instead of the
        # task silently going straight to 'failed' once the Celery worker
        # picks it up and services/repo.py's clone_repo rejects it.
        if not is_valid_github_url(value):
            raise serializers.ValidationError(
                "Must be a public GitHub repo URL, e.g. https://github.com/owner/repo"
            )
        return value


class TaskDetailSerializer(TaskSerializer):
    runs = AgentRunSerializer(many=True, read_only=True)

    class Meta(TaskSerializer.Meta):
        fields = TaskSerializer.Meta.fields + ["runs"]
