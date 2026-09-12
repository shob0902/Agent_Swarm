# Object-level permission that keeps one user's tasks invisible to everyone else.
from rest_framework.permissions import BasePermission
class IsOwner(BasePermission):
    # Allows access only when the logged-in user owns the object.
    def has_object_permission(self, request, view, obj):
        # Returns True only if the row belongs to the requesting user, otherwise DRF returns 403.
        return obj.user_id == request.user.id
