import axios from 'axios'

const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'

// Auth is entirely httpOnly-cookie based (see backend REST_AUTH in
// orchestrator/settings.py) -- there is no token for this client to
// attach itself. `withCredentials` is what makes the browser send/accept
// those cookies on requests to a different port than the page itself.
const client = axios.create({ baseURL, withCredentials: true })

let refreshInFlight = null

// A 401 means the access_token cookie is missing/expired. Try exactly one
// silent refresh (via the refresh_token cookie) and replay the original
// request; if that also fails, the session is genuinely over -- clear
// local auth state and send the user to /login rather than looping.
client.interceptors.response.use(
  (response) => response,
  async (error) => {
    const { config, response } = error
    const isAuthEndpoint = config?.url?.startsWith('/auth/')
    if (response?.status !== 401 || isAuthEndpoint || config._retried) {
      return Promise.reject(error)
    }
    config._retried = true
    try {
      refreshInFlight ??= client.post('/auth/token/refresh/').finally(() => {
        refreshInFlight = null
      })
      await refreshInFlight
      return client(config)
    } catch {
      if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
        window.location.assign('/login')
      }
      return Promise.reject(error)
    }
  },
)

// --- Auth --------------------------------------------------------------

export const getCurrentUser = () => client.get('/auth/user/').then((r) => r.data)

export const login = (email, password) => client.post('/auth/login/', { email, password }).then((r) => r.data)

export const signup = (email, password1, password2) =>
  client.post('/auth/registration/', { email, password1, password2 }).then((r) => r.data)

export const logout = () => client.post('/auth/logout/').then((r) => r.data)

// `code` is the OAuth authorization code the provider redirected back to
// the frontend with; `redirectUri` must be the exact same URI used to
// start the flow (see LoginPage.jsx) -- providers validate the two match.
export const socialLogin = (provider, code, redirectUri) =>
  client.post(`/auth/${provider}/`, { code, redirect_uri: redirectUri }).then((r) => r.data)

// --- Tasks ---------------------------------------------------------------

export const listTasks = (params) => client.get('/tasks/', { params }).then((r) => r.data)

export const getTask = (id) => client.get(`/tasks/${id}/`).then((r) => r.data)

export const getTaskRuns = (id) => client.get(`/tasks/${id}/runs/`).then((r) => r.data)

export const createTask = (payload) => client.post('/tasks/', payload).then((r) => r.data)

export const renameTask = (id, title) => client.patch(`/tasks/${id}/`, { title }).then((r) => r.data)

export const favoriteTask = (id) => client.post(`/tasks/${id}/favorite/`).then((r) => r.data)

export const archiveTask = (id) => client.post(`/tasks/${id}/archive/`).then((r) => r.data)

export const deleteTask = (id) => client.delete(`/tasks/${id}/`)

export default client
