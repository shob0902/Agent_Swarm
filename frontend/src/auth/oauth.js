// Starts and verifies the Google/GitHub OAuth redirect. Provider config comes from the backend; only public client IDs reach the browser.
import { getOAuthProviders } from '../api/client'
const STATE_KEY = 'agent-swarm-oauth'
const STATE_MAX_AGE_MS = 10 * 60 * 1000
let providersPromise = null
// Fetches (once per page load) which providers the backend has fully configured.
export function loadProviders() {
  providersPromise ??= getOAuthProviders().catch((err) => {
    providersPromise = null
    throw err
  })
  return providersPromise
}
// Builds the callback URL the provider should send the user back to.
export function redirectUriFor(provider) {
  return `${window.location.origin}/auth/callback/${provider}`
}
function randomState() {
  // 256 bits from the browser's CSPRNG, hex-encoded.
  const bytes = new Uint8Array(32)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}
function readStore() {
  // sessionStorage can throw (private mode, blocked storage), so treat failures as "nothing stored".
  try {
    return JSON.parse(sessionStorage.getItem(STATE_KEY) || 'null')
  } catch {
    return null
  }
}
// Sends the browser to the provider's consent screen with a fresh anti-CSRF state value.
export function startOAuthLogin(config, provider, returnTo = '/dashboard') {
  if (!config?.enabled || !config.client_id) return
  const state = randomState()
  try {
    sessionStorage.setItem(STATE_KEY, JSON.stringify({ state, provider, returnTo, at: Date.now() }))
  } catch {
    return
  }
  const params = new URLSearchParams({
    client_id: config.client_id,
    redirect_uri: redirectUriFor(provider),
    response_type: 'code',
    scope: config.scope,
    state,
  })
  if (provider === 'google') params.set('prompt', 'select_account')
  window.location.assign(`${config.authorize_url}?${params.toString()}`)
}
// Checks the state the provider echoed back against the one this tab sent (single use), returning where to go next.
export function consumeOAuthState(provider, state) {
  const saved = readStore()
  try {
    sessionStorage.removeItem(STATE_KEY)
  } catch {
  }
  const valid =
    saved &&
    state &&
    saved.provider === provider &&
    saved.state === state &&
    Date.now() - saved.at < STATE_MAX_AGE_MS
  if (!valid) return { ok: false }
  const returnTo = typeof saved.returnTo === 'string' && saved.returnTo.startsWith('/') && !saved.returnTo.startsWith('//') ? saved.returnTo : '/dashboard'
  return { ok: true, returnTo }
}
