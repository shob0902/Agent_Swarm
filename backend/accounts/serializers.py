from dj_rest_auth.registration.serializers import RegisterSerializer as BaseRegisterSerializer
from rest_framework import serializers

from .models import User


class UserSerializer(serializers.ModelSerializer):
    """Wired in as dj_rest_auth's USER_DETAILS_SERIALIZER -- backs
    GET/PATCH /api/auth/user/ and is nested into Task responses (see
    agents.serializers.TaskSerializer) so the frontend never needs a
    separate lookup to show whose task is whose.
    """

    class Meta:
        model = User
        fields = ["id", "email", "name", "avatar_url", "signup_provider", "role", "created_at"]
        read_only_fields = ["id", "email", "signup_provider", "role", "created_at"]


class RegisterSerializer(BaseRegisterSerializer):
    """dj_rest_auth's base RegisterSerializer hardcodes a required
    `username` field regardless of ACCOUNT_SIGNUP_FIELDS (a quirk of its
    `_signup_field_required` helper) -- our User model has no username at
    all, so it's dropped here rather than worked around in settings.
    Setting a declared field to None in a subclass removes it (standard
    DRF serializer pattern).
    """

    username = None

    def get_cleaned_data(self):
        return {
            "password1": self.validated_data.get("password1", ""),
            "email": self.validated_data.get("email", ""),
        }
