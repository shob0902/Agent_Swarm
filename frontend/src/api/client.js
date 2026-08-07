import axios from 'axios'

const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'

const client = axios.create({ baseURL })

export const listTasks = () => client.get('/tasks/').then((r) => r.data)

export const getTask = (id) => client.get(`/tasks/${id}/`).then((r) => r.data)

export const getTaskRuns = (id) => client.get(`/tasks/${id}/runs/`).then((r) => r.data)

export const createTask = (payload) => client.post('/tasks/', payload).then((r) => r.data)

export default client
