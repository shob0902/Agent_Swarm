from rest_framework.permissions import BasePermission


class IsOwner(BasePermission):
    """Object-level check for the multi-tenant boundary: a Task's owner is
    the only one allowed to retrieve/update/delete/act on it (or view its
    AgentRuns, which are reached through `TaskViewSet.runs` -- see
    `get_object()` there). DRF's default behavior when `has_object_permission`
    returns False is already a 403 (not a 404) as long as the view-level
    `IsAuthenticated` check (the global default, see settings.REST_FRAMEWORK)
    passed -- which is exactly the "403 for unauthorized resource access"
    behavior the isolation requirements ask for.
    """

    def has_object_permission(self, request, view, obj):
        return obj.user_id == request.user.id
