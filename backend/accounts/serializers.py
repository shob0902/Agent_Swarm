# DRF serializers for reading user details, email/password registration, and the OAuth code exchange.
from dj_rest_auth.registration.serializers import RegisterSerializer as BaseRegisterSerializer
from allauth.socialaccount.providers.oauth2.client import OAuth2Error
from dj_rest_auth.registration.serializers import SocialLoginSerializer
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
class CodeOnlySocialLoginSerializer(SocialLoginSerializer):
    # Accepts only an authorization code. The base class would also accept a raw access_token/id_token,
    # which lets a token issued to some *other* app be replayed here to sign in.
    access_token = None
    id_token = None
    code = serializers.CharField(required=True, allow_blank=False, max_length=2048)
    redirect_uri = serializers.CharField(required=False, allow_blank=True, max_length=500)
    def validate(self, attrs):
        # Drops anything but the code before handing off to the dj-rest-auth/allauth exchange. Provider-side
        # failures (bad id_token, unreachable key endpoint) become a readable 400 instead of a 500.
        attrs = {"code": attrs["code"]}
        try:
            return super().validate(attrs)
        except OAuth2Error as exc:
            raise serializers.ValidationError({"detail": f"The sign-in provider's response could not be verified: {exc}"}) from exc
