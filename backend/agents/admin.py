# Django admin screens for browsing tasks and their agent runs.
from django.contrib import admin
from .models import AgentRun, Task
@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    # Task list view with status filters and a truncated description column.
    list_display = ("id", "user", "status", "current_agent", "short_description", "github_url", "pr_url", "executor", "created_at", "updated_at")
    list_filter = ("status", "executor", "test_status", "review_status", "pr_state", "is_favorite", "is_archived")
    search_fields = ("description", "title", "github_url", "user__email")
    readonly_fields = ("created_at", "updated_at", "dispatched_at", "started_at", "completed_at")
    @admin.display(description="description")
    def short_description(self, obj):
        # Trims the description so the list column stays readable.
        return obj.description[:80]
@admin.register(AgentRun)
class AgentRunAdmin(admin.ModelAdmin):
    # Read-only audit view of every agent invocation, newest first.
    list_display = ("id", "task", "agent_type", "provider", "status", "retry_count", "duration_ms", "started_at")
    list_filter = ("agent_type", "provider", "status")
    search_fields = ("task__description", "task__user__email")
    readonly_fields = ("started_at",)
    ordering = ("-started_at",)
