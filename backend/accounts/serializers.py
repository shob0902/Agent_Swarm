# DRF serializers for reading user details and for email/password registration.
from dj_rest_auth.registration.serializers import RegisterSerializer as BaseRegisterSerializer
from rest_framework import serializers
from .models import User
class UserSerializer(serializers.ModelSerializer):
    # Backs /api/auth/user/ and is nested inside task responses.
    class Meta:
        model = User
        fields = ["id", "email", "name", "avatar_url", "signup_provider", "role", "created_at"]
        read_only_fields = ["id", "email", "signup_provider", "role", "created_at"]
class RegisterSerializer(BaseRegisterSerializer):
    # Drops the base class's required username field, which our model doesn't have.
    username = None
    def validate_email(self, email):
        # Rejects an already-registered email up front so a duplicate signup 400s instead of 500s.
        email = super().validate_email(email)
        if email and User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError(
                "A user is already registered with this e-mail address."
            )
        return email
    def get_cleaned_data(self):
        # Returns just the email and password, since there is no username to pass along.
        return {
            "password1": self.validated_data.get("password1", ""),
            "email": self.validated_data.get("email", ""),
        }
