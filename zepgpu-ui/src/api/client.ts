import axios from 'axios'
import type { Task, TaskCreateRequest, TaskListResponse, GPUDevice, Pipeline, User, AuthToken, SystemStats } from '@/types'

const api = axios.create({
  baseURL: '/api/v1',
  headers: {
    'Content-Type': 'application/json',
  },
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

export const authApi = {
  login: async (username: string, password: string): Promise<AuthToken> => {
    const formData = new URLSearchParams()
    formData.append('username', username)
    formData.append('password', password)
    const { data } = await api.post<AuthToken>('/auth/login', formData, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })
    return data
  },
  register: async (username: string, email: string, password: string): Promise<User> => {
    const { data } = await api.post<User>('/auth/register', { username, email, password })
    return data
  },
  me: async (): Promise<User> => {
    const { data } = await api.get<User>('/users/me')
    return data
  },
}

export const tasksApi = {
  list: async (params?: { status?: string; limit?: number; offset?: number }): Promise<TaskListResponse> => {
    const { data } = await api.get<TaskListResponse>('/tasks', { params })
    return data
  },
  get: async (taskId: string): Promise<Task> => {
    const { data } = await api.get<Task>(`/tasks/${taskId}`)
    return data
  },
  create: async (task: TaskCreateRequest): Promise<Task> => {
    const { data } = await api.post<Task>('/tasks', task)
    return data
  },
  cancel: async (taskId: string): Promise<void> => {
    await api.delete(`/tasks/${taskId}`)
  },
  result: async (taskId: string) => {
    const { data } = await api.get(`/tasks/${taskId}/result`)
    return data
  },
}

export const pipelinesApi = {
  list: async (): Promise<Pipeline[]> => {
    const { data } = await api.get<Pipeline[]>('/pipelines')
    return data
  },
  get: async (pipelineId: string): Promise<Pipeline> => {
    const { data } = await api.get<Pipeline>(`/pipelines/${pipelineId}`)
    return data
  },
  create: async (name: string, stages: unknown[]): Promise<Pipeline> => {
    const { data } = await api.post<Pipeline>('/pipelines', { name, stages })
    return data
  },
  run: async (pipelineId: string): Promise<Pipeline> => {
    const { data } = await api.post<Pipeline>(`/pipelines/${pipelineId}/run`)
    return data
  },
  delete: async (pipelineId: string): Promise<void> => {
    await api.delete(`/pipelines/${pipelineId}`)
  },
}

export const gpuApi = {
  list: async (): Promise<GPUDevice[]> => {
    const { data } = await api.get<GPUDevice[]>('/gpu/devices')
    return data
  },
  get: async (deviceId: number): Promise<GPUDevice> => {
    const { data } = await api.get<GPUDevice>(`/gpu/devices/${deviceId}`)
    return data
  },
}

export const systemApi = {
  stats: async (): Promise<SystemStats> => {
    const { data } = await api.get<SystemStats>('/stats')
    return data
  },
  health: async (): Promise<{ status: string }> => {
    const { data } = await api.get<{ status: string }>('/health')
    return data
  },
}

export default api
