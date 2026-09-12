// Axios wrapper for the backend API, with a one-shot silent token refresh on 401.
import axios from 'axios'
const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'
const client = axios.create({ baseURL, withCredentials: true })
let refreshInFlight = null
client.interceptors.response.use(
  (response) => response,
  async (error) => {
    // On a 401, tries the refresh endpoint once and replays the request, else sends the user to login.
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
// Fetches the logged-in user's profile.
export const getCurrentUser = () => client.get('/auth/user/').then((r) => r.data)
// Logs in with an email and password.
export const login = (email, password) => client.post('/auth/login/', { email, password }).then((r) => r.data)
// Registers a new account with an email and confirmed password.
export const signup = (email, password1, password2) =>
  client.post('/auth/registration/', { email, password1, password2 }).then((r) => r.data)
// Ends the session and clears the auth cookies.
export const logout = () => client.post('/auth/logout/').then((r) => r.data)
// Exchanges an OAuth authorization code for a session; the redirect URI must match the one used to start the flow.
export const socialLogin = (provider, code, redirectUri) =>
  client.post(`/auth/${provider}/`, { code, redirect_uri: redirectUri }).then((r) => r.data)
// Lists the current user's tasks, optionally filtered by the given query params.
export const listTasks = (params) => client.get('/tasks/', { params }).then((r) => r.data)
// Fetches one task including its agent runs.
export const getTask = (id) => client.get(`/tasks/${id}/`).then((r) => r.data)
// Fetches just the agent runs for a task.
export const getTaskRuns = (id) => client.get(`/tasks/${id}/runs/`).then((r) => r.data)
// Creates a new task and starts its pipeline.
export const createTask = (payload) => client.post('/tasks/', payload).then((r) => r.data)
// Updates a task's title.
export const renameTask = (id, title) => client.patch(`/tasks/${id}/`, { title }).then((r) => r.data)
// Toggles a task's favorite flag.
export const favoriteTask = (id) => client.post(`/tasks/${id}/favorite/`).then((r) => r.data)
// Toggles a task's archived flag.
export const archiveTask = (id) => client.post(`/tasks/${id}/archive/`).then((r) => r.data)
// Permanently deletes a task.
export const deleteTask = (id) => client.delete(`/tasks/${id}/`)
export default client
