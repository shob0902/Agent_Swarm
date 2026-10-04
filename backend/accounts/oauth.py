# OAuth provider configuration shared by the views: which providers are usable, their public settings, and allowed redirect URIs.
from __future__ import annotations
from urllib.parse import urlsplit
from django.conf import settings
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
