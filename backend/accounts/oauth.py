# OAuth provider configuration shared by the views: which providers are usable, their public settings, allowed
# redirect URIs, and a clock-skew-tolerant Google adapter.
from __future__ import annotations
from urllib.parse import urlsplit
import jwt
from allauth.socialaccount.internal import jwtkit
from allauth.socialaccount.providers.google import views as google_views
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Error
from django.conf import settings
# Google's ID token carries Google's clock (iat/exp). allauth verifies it with zero leeway, so a server clock just
# a second behind Google sees a token "issued in the future" and rejects it. Google's own client libraries allow
# for skew; so do we.
ID_TOKEN_LEEWAY_SECONDS = 120
class ClockSkewTolerantGoogleOAuth2Adapter(GoogleOAuth2Adapter):
    # Same verification as allauth (signature, issuer, audience, expiry, replay), plus a small clock-skew allowance.
    def _decode_id_token(self, app, id_token):
        # Verifies Google's id_token, reporting the real reason when it fails instead of a bare "Invalid id_token".
        verify_signature = not self.did_fetch_access_token
        try:
            if verify_signature:
                alg, key = jwtkit.fetch_key(id_token, google_views.CERTS_URL, jwtkit.lookup_kid_pem_x509_certificate)
                algorithms = [alg]
            else:
                key, algorithms = "", None
            data = jwt.decode(
                id_token,
                key=key,
                options={"verify_signature": verify_signature, "verify_iss": True, "verify_aud": True, "verify_exp": True},
                issuer=google_views.ID_TOKEN_ISSUER,
                audience=app.client_id,
                algorithms=algorithms,
                leeway=ID_TOKEN_LEEWAY_SECONDS,
            )
        except jwt.PyJWTError as exc:
            raise OAuth2Error(f"Invalid id_token: {exc}") from exc
        jwtkit.verify_jti(data)
        return data
PROVIDERS = {
    "google": {
        "name": "Google",
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "scope": "openid email profile",
    },
    "github": {
        "name": "GitHub",
        "authorize_url": "https://github.com/login/oauth/authorize",
        "scope": "read:user user:email",
    },
}
def app_credentials(provider: str) -> tuple[str, str]:
    # The (client_id, secret) pair from SOCIALACCOUNT_PROVIDERS, or blanks when unset.
    app = settings.SOCIALACCOUNT_PROVIDERS.get(provider, {}).get("APP", {})
    return app.get("client_id", ""), app.get("secret", "")
def is_configured(provider: str) -> bool:
    # A provider is usable only when the backend has both its client id and its secret.
    client_id, secret = app_credentials(provider)
    return bool(client_id and secret)
def public_config() -> dict:
    # What the frontend needs to start a login: never the secret.
    out = {}
    for provider, meta in PROVIDERS.items():
        client_id, _ = app_credentials(provider)
        enabled = is_configured(provider)
        out[provider] = {
            "name": meta["name"],
            "enabled": enabled,
            "client_id": client_id if enabled else "",
            "authorize_url": meta["authorize_url"],
            "scope": meta["scope"],
        }
    return out
def allowed_redirect_uris(provider: str) -> list[str]:
    # <origin>/auth/callback/<provider> for FRONTEND_BASE_URL and every CORS-allowed origin, de-duplicated in order.
    origins = [settings.FRONTEND_BASE_URL, *settings.CORS_ALLOWED_ORIGINS]
    uris: list[str] = []
    for origin in origins:
        parts = urlsplit(origin)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            continue
        uri = f"{parts.scheme}://{parts.netloc}/auth/callback/{provider}"
        if uri not in uris:
            uris.append(uri)
    return uris
def resolve_redirect_uri(provider: str, requested: str | None) -> str | None:
    # Returns the requested redirect URI if it's on the allow-list, the default when none was sent, else None.
    allowed = allowed_redirect_uris(provider)
    if not requested:
        return allowed[0] if allowed else None
    return requested if requested in allowed else None
