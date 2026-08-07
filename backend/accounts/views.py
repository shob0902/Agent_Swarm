"""OAuth login endpoints.

Both views follow dj_rest_auth's documented SPA pattern: the *frontend*
owns the OAuth redirect (it sends the user to the provider with its own
`redirect_uri`, e.g. http://localhost:5173/auth/callback/google) and gets
back an authorization `code`; it POSTs that `code` here, and this is where
the actual code-for-token exchange happens server-side (using the client
secret, which never reaches the browser). See `AuthCallbackPage.jsx` /
`AuthContext.jsx` on the frontend for the other half of this flow.
"""
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
    """dj_rest_auth's base RegisterView returns the JWT pair in the
    response body but -- unlike LoginView -- never sets them as cookies,
    which leaves a just-signed-up user with tokens in the JSON but no
    access_token cookie, i.e. logged out again on the very next request.
    Setting them here is what makes signup "seamless" (no separate login
    call needed right after).
    """

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        if rest_auth_settings.USE_JWT and response.status_code == 201:
            set_jwt_cookies(response, self.access_token, self.refresh_token)
        return response


class GoogleLogin(SocialLoginView):
    adapter_class = GoogleOAuth2Adapter
    client_class = OAuth2Client
    callback_url = settings.FRONTEND_OAUTH_CALLBACK_URLS["google"]


class GitHubLogin(SocialLoginView):
    adapter_class = GitHubOAuth2Adapter
    client_class = OAuth2Client
    callback_url = settings.FRONTEND_OAUTH_CALLBACK_URLS["github"]
