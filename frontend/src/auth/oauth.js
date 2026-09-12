// Starts the OAuth login redirect for Google and GitHub; only public client IDs live here.
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
// Reports whether a client ID was actually configured for this provider.
export function isProviderConfigured(provider) {
  return Boolean(PROVIDERS[provider]?.clientId)
}
// Builds the callback URL the provider should send the user back to.
export function redirectUriFor(provider) {
  return `${window.location.origin}/auth/callback/${provider}`
}
// Sends the browser off to the provider's consent screen to begin the login.
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
