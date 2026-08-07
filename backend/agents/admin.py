from django.contrib import admin

from .models import AgentRun, Task


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "short_description", "repo_path", "created_at", "updated_at")
    list_filter = ("status",)
    search_fields = ("description", "repo_path")
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="description")
    def short_description(self, obj):
        return obj.description[:80]


@admin.register(AgentRun)
class AgentRunAdmin(admin.ModelAdmin):
    list_display = ("id", "task", "agent_type", "provider", "status", "retry_count", "duration_ms", "started_at")
    list_filter = ("agent_type", "provider", "status")
    search_fields = ("task__description",)
    readonly_fields = ("started_at",)
    ordering = ("-started_at",)
