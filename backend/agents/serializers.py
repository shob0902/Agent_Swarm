from rest_framework import serializers

from .models import AgentRun, Task


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
    class Meta:
        model = Task
        fields = ["id", "description", "repo_path", "status", "created_at", "updated_at"]
        read_only_fields = ["id", "status", "created_at", "updated_at"]


class TaskDetailSerializer(TaskSerializer):
    runs = AgentRunSerializer(many=True, read_only=True)

    class Meta(TaskSerializer.Meta):
        fields = TaskSerializer.Meta.fields + ["runs"]
