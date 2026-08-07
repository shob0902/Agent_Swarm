from django.contrib import admin

from .models import AgentRun, Task


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "status", "short_description", "github_url", "is_favorite", "is_archived", "created_at", "updated_at")
    list_filter = ("status", "is_favorite", "is_archived")
    search_fields = ("description", "title", "github_url", "user__email")
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="description")
    def short_description(self, obj):
        return obj.description[:80]


@admin.register(AgentRun)
class AgentRunAdmin(admin.ModelAdmin):
    list_display = ("id", "task", "agent_type", "provider", "status", "retry_count", "duration_ms", "started_at")
    list_filter = ("agent_type", "provider", "status")
    search_fields = ("task__description", "task__user__email")
    readonly_fields = ("started_at",)
    ordering = ("-started_at",)
