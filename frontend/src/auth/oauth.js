// Client IDs are public by design (they identify the app, not authenticate
// it) -- safe to ship in the frontend bundle. The matching secrets stay
// backend-only (see backend/.env.example) and never reach the browser; the
// actual code-for-token exchange happens server-side in accounts/views.py.
const PROVIDERS = {
  google: {
    clientId: import.meta.env.VITE_GOOGLE_CLIENT_ID,
    authorizeUrl: 'https://accounts.google.com/o/oauth2/v2/auth',
    scope: 'openid email profile',
  },
  github: {
    clientId: import.meta.env.VITE_GITHUB_CLIENT_ID,
    authorizeUrl: 'https://github.com/login/oauth/authorize',
    scope: 'user:email',
  },
}

export function isProviderConfigured(provider) {
  return Boolean(PROVIDERS[provider]?.clientId)
}

export function redirectUriFor(provider) {
  return `${window.location.origin}/auth/callback/${provider}`
}

// Full-page redirect to the provider's consent screen; it redirects back
// to redirectUriFor(provider) with `?code=...`, which AuthCallbackPage.jsx
// picks up and POSTs to the backend.
export function startOAuthLogin(provider) {
  const cfg = PROVIDERS[provider]
  if (!cfg?.clientId) return
  const params = new URLSearchParams({
    client_id: cfg.clientId,
    redirect_uri: redirectUriFor(provider),
    response_type: 'code',
    scope: cfg.scope,
  })
  window.location.href = `${cfg.authorizeUrl}?${params.toString()}`
}
