# Auth endpoints: email signup, the public OAuth provider config, and the server-side half of the Google and GitHub OAuth exchange.
from __future__ import annotations
from allauth.socialaccount.providers.github.views import GitHubOAuth2Adapter
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from dj_rest_auth.app_settings import api_settings as rest_auth_settings
from dj_rest_auth.jwt_auth import set_jwt_cookies
from dj_rest_auth.registration.views import RegisterView as BaseRegisterView
from dj_rest_auth.registration.views import SocialLoginView
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from . import oauth
from .serializers import CodeOnlySocialLoginSerializer
class RegisterView(BaseRegisterView):
    # Signup view that also sets the JWT cookies, which the base class skips.
    def create(self, request, *args, **kwargs):
        # Attaches the access and refresh cookies so a new signup is logged in straight away.
        response = super().create(request, *args, **kwargs)
        if rest_auth_settings.USE_JWT and response.status_code == 201:
            set_jwt_cookies(response, self.access_token, self.refresh_token)
        return response
class OAuthProvidersView(APIView):
    # GET /api/auth/providers/: public client ids and authorize URLs, so the frontend needs no OAuth config of its own.
    permission_classes = [AllowAny]
    authentication_classes: list = []
    def get(self, request):
        # Lists Google and GitHub with an "enabled" flag that is true only when the backend also has the secret.
        return Response(oauth.public_config())
class _ProviderLogin(SocialLoginView):
    # Shared code-exchange view: authorization-code only, redirect URI checked against the allow-list.
    serializer_class = CodeOnlySocialLoginSerializer
    client_class = OAuth2Client
    provider = ""
    def post(self, request, *args, **kwargs):
        # Refuses unconfigured providers and unknown redirect URIs before allauth contacts the provider.
        if not oauth.is_configured(self.provider):
            name = oauth.PROVIDERS[self.provider]["name"]
            return Response({"detail": f"{name} sign-in is not configured on this server."}, status=status.HTTP_400_BAD_REQUEST)
        redirect_uri = oauth.resolve_redirect_uri(self.provider, request.data.get("redirect_uri"))
        if not redirect_uri:
            return Response({"detail": "This redirect URI is not allowed. Add its origin to FRONTEND_BASE_URL or CORS_ALLOWED_ORIGINS."}, status=status.HTTP_400_BAD_REQUEST)
        # The code was issued for this exact redirect URI, so the token exchange must send the same one.
        self.callback_url = redirect_uri
        return super().post(request, *args, **kwargs)
class GoogleLogin(_ProviderLogin):
    # Trades a Google authorization code for a session.
    adapter_class = GoogleOAuth2Adapter
    provider = "google"
class GitHubLogin(_ProviderLogin):
    # Trades a GitHub authorization code for a session.
    adapter_class = GitHubOAuth2Adapter
    provider = "github"
