# Auth endpoints: email signup plus the server-side half of the Google and GitHub OAuth exchange.
from __future__ import annotations
from allauth.socialaccount.providers.github.views import GitHubOAuth2Adapter
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from dj_rest_auth.app_settings import api_settings as rest_auth_settings
from dj_rest_auth.jwt_auth import set_jwt_cookies
from dj_rest_auth.registration.views import RegisterView as BaseRegisterView
from dj_rest_auth.registration.views import SocialLoginView
from django.conf import settings
class RegisterView(BaseRegisterView):
    # Signup view that also sets the JWT cookies, which the base class skips.
    def create(self, request, *args, **kwargs):
        # Attaches the access and refresh cookies so a new signup is logged in straight away.
        response = super().create(request, *args, **kwargs)
        if rest_auth_settings.USE_JWT and response.status_code == 201:
            set_jwt_cookies(response, self.access_token, self.refresh_token)
        return response
class GoogleLogin(SocialLoginView):
    # Trades a Google authorization code for a session.
    adapter_class = GoogleOAuth2Adapter
    client_class = OAuth2Client
    callback_url = settings.FRONTEND_OAUTH_CALLBACK_URLS["google"]
class GitHubLogin(SocialLoginView):
    # Trades a GitHub authorization code for a session.
    adapter_class = GitHubOAuth2Adapter
    client_class = OAuth2Client
    callback_url = settings.FRONTEND_OAUTH_CALLBACK_URLS["github"]
