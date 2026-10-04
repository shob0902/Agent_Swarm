# Tests for Google/GitHub OAuth sign-in: provider config, the code-only exchange, redirect URIs and safe account linking.
from unittest import mock
from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.github.views import GitHubOAuth2Adapter
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
PROVIDERS = {
    "google": {"APP": {"client_id": "google-id", "secret": "google-secret", "key": ""}, "SCOPE": ["profile", "email"]},
    "github": {"APP": {"client_id": "github-id", "secret": "github-secret", "key": ""}, "SCOPE": ["read:user", "user:email"]},
}
OAUTH_SETTINGS = dict(
    SOCIALACCOUNT_PROVIDERS=PROVIDERS,
    FRONTEND_BASE_URL="http://localhost:5173",
    CORS_ALLOWED_ORIGINS=["http://localhost:5173", "http://127.0.0.1:5173"],
)
GITHUB_PROFILE = {
    "id": 4242, "login": "octo", "name": "Octo Cat", "email": None,
    "avatar_url": "https://avatars.example/octo.png",
    "emails": [{"email": "octo@example.com", "primary": True, "verified": True}],
}
GOOGLE_PROFILE = {"sub": "g-777", "email": "gina@example.com", "email_verified": True, "name": "Gina", "picture": "https://img.example/g.png"}
def fake_complete_login(profile):
    # Replaces the provider profile fetch (a network call) with a canned profile.
    def complete_login(self, request, app, token, **kwargs):
        # Builds the SocialLogin exactly as allauth would from the provider's response.
        return self.get_provider().sociallogin_from_response(request, dict(profile))
    return complete_login
@override_settings(**OAUTH_SETTINGS)
class OAuthLoginTests(TestCase):
    # Drives POST /api/auth/<provider>/ end to end with the provider's HTTP calls mocked.
    def setUp(self):
        # Fresh unauthenticated client.
        self.client = APIClient()
        self.token_calls = []
    def _login(self, provider, profile, payload=None):
        # Posts a code and returns the response, recording the redirect URI used for the token exchange.
        calls = self.token_calls
        def get_access_token(client_self, code, *args, **kwargs):
            # Fake token endpoint.
            calls.append({"code": code, "callback_url": client_self.callback_url})
            return {"access_token": "provider-access-token"}
        adapter = GitHubOAuth2Adapter if provider == "github" else GoogleOAuth2Adapter
        body = {"code": "auth-code", "redirect_uri": f"http://localhost:5173/auth/callback/{provider}"}
        body.update(payload or {})
        with mock.patch.object(OAuth2Client, "get_access_token", autospec=True, side_effect=get_access_token), \
                mock.patch.object(adapter, "complete_login", autospec=True, side_effect=fake_complete_login(profile)):
            return self.client.post(f"/api/auth/{provider}/", body, format="json")
    def test_github_signup_creates_user_and_sets_cookies(self):
        # New user from the verified primary GitHub email, with name/avatar/provider, logged in via JWT cookies.
        response = self._login("github", GITHUB_PROFILE)
        self.assertEqual(response.status_code, 200, response.content)
        user = get_user_model().objects.get(email="octo@example.com")
        self.assertEqual((user.name, user.avatar_url, user.signup_provider), ("Octo Cat", "https://avatars.example/octo.png", "github"))
        self.assertIn("access_token", response.cookies)
        self.assertIn("refresh_token", response.cookies)
        self.assertEqual(self.token_calls[0]["callback_url"], "http://localhost:5173/auth/callback/github")
        self.assertTrue(SocialAccount.objects.filter(user=user, provider="github", uid="4242").exists())
        self.assertEqual(self.client.get("/api/auth/user/").json()["email"], "octo@example.com")
    def test_google_signup(self):
        # Same flow for Google.
        response = self._login("google", GOOGLE_PROFILE)
        self.assertEqual(response.status_code, 200, response.content)
        user = get_user_model().objects.get(email="gina@example.com")
        self.assertEqual((user.signup_provider, user.avatar_url), ("google", "https://img.example/g.png"))
    def test_second_login_reuses_account(self):
        # Signing in again doesn't create a duplicate.
        self._login("github", GITHUB_PROFILE)
        self.client = APIClient()
        self.assertEqual(self._login("github", GITHUB_PROFILE).status_code, 200)
        self.assertEqual(get_user_model().objects.filter(email="octo@example.com").count(), 1)
    def test_alternate_allowed_origin_is_used_for_exchange(self):
        # 127.0.0.1 is a CORS-allowed origin, so its callback URI is accepted and sent to the provider verbatim.
        self._login("github", GITHUB_PROFILE, {"redirect_uri": "http://127.0.0.1:5173/auth/callback/github"})
        self.assertEqual(self.token_calls[0]["callback_url"], "http://127.0.0.1:5173/auth/callback/github")
    def test_unknown_redirect_uri_rejected_before_contacting_provider(self):
        # An attacker-chosen redirect URI never reaches the token endpoint.
        response = self._login("github", GITHUB_PROFILE, {"redirect_uri": "https://evil.example/auth/callback/github"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.token_calls, [])
    def test_access_token_path_is_disabled(self):
        # A raw provider token (possibly minted for another app) can't be used to sign in.
        response = self.client.post("/api/auth/google/", {"access_token": "token-from-another-app"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("code", response.json())
        self.assertFalse(get_user_model().objects.exists())
    @override_settings(SOCIALACCOUNT_PROVIDERS={"google": {"APP": {"client_id": "", "secret": "", "key": ""}}, "github": PROVIDERS["github"]})
    def test_unconfigured_provider_gives_clear_error(self):
        # Missing credentials -> a readable 400, not an allauth crash.
        response = self.client.post("/api/auth/google/", {"code": "x"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("not configured", response.json()["detail"])
    def test_links_to_existing_account_with_verified_email_and_retires_unverified_password(self):
        # Someone registered octo@example.com with a password (never verified). The real owner signs in with
        # GitHub: the accounts are linked and the unproven password stops working.
        squatter = APIClient()
        squatter.post("/api/auth/registration/", {"email": "octo@example.com", "password1": "Squat-pass-123", "password2": "Squat-pass-123"}, format="json")
        response = self._login("github", GITHUB_PROFILE)
        self.assertEqual(response.status_code, 200, response.content)
        user = get_user_model().objects.get(email="octo@example.com")
        self.assertFalse(user.has_usable_password())
        self.assertTrue(SocialAccount.objects.filter(user=user, provider="github").exists())
        self.assertTrue(EmailAddress.objects.filter(user=user, email="octo@example.com", verified=True).exists())
        relogin = APIClient().post("/api/auth/login/", {"email": "octo@example.com", "password": "Squat-pass-123"}, format="json")
        self.assertEqual(relogin.status_code, 400)
    def test_unverified_provider_email_is_not_linked(self):
        # An unverified GitHub email must not take over an existing account.
        get_user_model().objects.create_user(email="victim@example.com", password="Victim-pass-123")
        profile = {**GITHUB_PROFILE, "id": 999, "emails": [{"email": "victim@example.com", "primary": True, "verified": False}]}
        response = self._login("github", profile)
        self.assertEqual(response.status_code, 400)
        self.assertIn("no verified email", str(response.json()))
        self.assertFalse(SocialAccount.objects.exists())
        self.assertTrue(get_user_model().objects.get(email="victim@example.com").check_password("Victim-pass-123"))
    def test_unverified_or_missing_email_cannot_sign_up(self):
        # No verified email -> no account at all, with a readable reason (previously a 500).
        for emails in ([{"email": "new@example.com", "primary": True, "verified": False}], []):
            response = self._login("github", {**GITHUB_PROFILE, "id": 31337, "emails": emails})
            self.assertEqual(response.status_code, 400, emails)
        self.assertFalse(get_user_model().objects.exists())
    def test_verified_secondary_email_used_when_primary_unverified(self):
        # The account is created on an address the provider actually verified.
        profile = {**GITHUB_PROFILE, "emails": [
            {"email": "unverified@example.com", "primary": True, "verified": False},
            {"email": "verified@example.com", "primary": False, "verified": True},
        ]}
        self.assertEqual(self._login("github", profile).status_code, 200)
        self.assertEqual(list(get_user_model().objects.values_list("email", flat=True)), ["verified@example.com"])
@override_settings(**OAUTH_SETTINGS)
class ProvidersEndpointTests(TestCase):
    # The frontend learns provider config from the backend instead of its own env vars.
    def test_lists_public_config_without_secrets(self):
        # Client ids and authorize URLs only; secrets never leave the server.
        response = APIClient().get("/api/auth/providers/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["google"]["client_id"], "google-id")
        self.assertTrue(data["github"]["enabled"])
        self.assertNotIn("secret", str(data))
    @override_settings(SOCIALACCOUNT_PROVIDERS={"google": {"APP": {"client_id": "only-id", "secret": "", "key": ""}}, "github": {"APP": {}}})
    def test_provider_without_secret_is_disabled(self):
        # A client id alone isn't enough to sign in, so the button stays off.
        data = APIClient().get("/api/auth/providers/").json()
        self.assertFalse(data["google"]["enabled"])
        self.assertEqual(data["google"]["client_id"], "")
        self.assertFalse(data["github"]["enabled"])
@override_settings(**OAUTH_SETTINGS)
class GoogleIdTokenTests(TestCase):
    # Runs Google's real id_token verification (with a test signing key) instead of mocking complete_login.
    KEY = "test-signing-key-that-is-long-enough-for-hs256"
    def _login_with_id_token(self, **claim_overrides):
        # Exchanges a code whose token response carries an id_token with the given claims.
        import time
        import jwt
        now = int(time.time())
        claims = {
            "iss": "https://accounts.google.com", "aud": "google-id", "sub": "g-42",
            "email": "skew@example.com", "email_verified": True, "name": "Skew", "picture": "https://img.example/s.png",
            "iat": now, "exp": now + 3600,
        }
        claims.update(claim_overrides)
        id_token = jwt.encode(claims, self.KEY, algorithm="HS256")
        with mock.patch.object(OAuth2Client, "get_access_token", return_value={"access_token": "at", "id_token": id_token}), \
                mock.patch("accounts.oauth.jwtkit.fetch_key", return_value=("HS256", self.KEY)):
            return APIClient().post("/api/auth/google/", {"code": "c", "redirect_uri": "http://localhost:5173/auth/callback/google"}, format="json")
    def test_token_issued_slightly_in_the_future_is_accepted(self):
        # A server clock a few seconds behind Google (the Windows dev case) must not break sign-in.
        import time
        response = self._login_with_id_token(iat=int(time.time()) + 5)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(get_user_model().objects.filter(email="skew@example.com", signup_provider="google").exists())
    def test_grossly_future_token_is_a_readable_400(self):
        # Beyond the leeway it's rejected -- as a 400 that names the reason, not a 500.
        import time
        response = self._login_with_id_token(iat=int(time.time()) + 3600)
        self.assertEqual(response.status_code, 400)
        self.assertIn("not yet valid", str(response.json()))
    def test_wrong_audience_rejected(self):
        # A token minted for a different Google client never signs anyone in.
        response = self._login_with_id_token(aud="someone-elses-client-id")
        self.assertEqual(response.status_code, 400)
        self.assertIn("audience", str(response.json()).lower())
        self.assertFalse(get_user_model().objects.exists())
    def test_expired_token_rejected(self):
        # Expiry is still enforced (with the same small leeway).
        import time
        response = self._login_with_id_token(iat=int(time.time()) - 7200, exp=int(time.time()) - 3600)
        self.assertEqual(response.status_code, 400)
