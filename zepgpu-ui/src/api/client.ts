import axios from 'axios'
import type {
  Task, TaskCreateRequest, TaskListResponse, GPUDevice, Pipeline, User, AuthToken, SystemStats,
  ScheduledTask, ScheduledTaskRun, GangTask, PreemptionRecord, FairShareBucket,
  Namespace, NamespaceMember, Team, NamespaceQuota, NamespaceUsage,
  CloudProvider, CloudRegion, CloudGPUInstance, CloudLaunchRequest, CloudCostEstimate,
  AuditLog, Alert, GPUMetrics, ServiceMetrics, TaskMetrics, LeaderboardEntry, Achievement,
  DAGData,
} from '@/types'

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
  list: async (params?: { status?: string; limit?: number; offset?: number; namespace_id?: string; service_name?: string; user_id?: string }): Promise<TaskListResponse> => {
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
  retry: async (taskId: string): Promise<Task> => {
    const { data } = await api.post<Task>(`/tasks/${taskId}/retry`)
    return data
  },
  result: async (taskId: string) => {
    const { data } = await api.get(`/tasks/${taskId}/result`)
    return data
  },
  logs: async (taskId: string, params?: { offset?: number; limit?: number }) => {
    const { data } = await api.get(`/tasks/${taskId}/logs`, { params })
    return data
  },
  metrics: async (): Promise<TaskMetrics> => {
    const { data } = await api.get<TaskMetrics>('/tasks/metrics')
    return data
  },
}

export const pipelinesApi = {
  list: async (params?: { namespace_id?: string; status?: string }): Promise<Pipeline[]> => {
    const { data } = await api.get<Pipeline[]>('/pipelines', { params })
    return data
  },
  get: async (pipelineId: string): Promise<Pipeline> => {
    const { data } = await api.get<Pipeline>(`/pipelines/${pipelineId}`)
    return data
  },
  create: async (name: string, stages: unknown[], namespace_id?: string): Promise<Pipeline> => {
    const { data } = await api.post<Pipeline>('/pipelines', { name, stages, namespace_id })
    return data
  },
  run: async (pipelineId: string): Promise<Pipeline> => {
    const { data } = await api.post<Pipeline>(`/pipelines/${pipelineId}/run`)
    return data
  },
  cancel: async (pipelineId: string): Promise<void> => {
    await api.post(`/pipelines/${pipelineId}/cancel`)
  },
  delete: async (pipelineId: string): Promise<void> => {
    await api.delete(`/pipelines/${pipelineId}`)
  },
  dag: async (pipelineId: string): Promise<DAGData> => {
    const { data } = await api.get<DAGData>(`/pipelines/${pipelineId}/dag`)
    return data
  },
}

export const gpuApi = {
  list: async (params?: { status?: string; namespace_id?: string }): Promise<GPUDevice[]> => {
    const { data } = await api.get<GPUDevice[]>('/gpu/devices', { params })
    return data
  },
  get: async (deviceId: number): Promise<GPUDevice> => {
    const { data } = await api.get<GPUDevice>(`/gpu/devices/${deviceId}`)
    return data
  },
  metrics: async (deviceId: number, params?: { period?: string }): Promise<GPUMetrics> => {
    const { data } = await api.get<GPUMetrics>(`/gpu/devices/${deviceId}/metrics`, { params })
    return data
  },
  updateStatus: async (deviceId: number, status: string): Promise<GPUDevice> => {
    const { data } = await api.put<GPUDevice>(`/gpu/devices/${deviceId}/status`, { status })
    return data
  },
  setMaintenance: async (deviceId: number, enabled: boolean): Promise<GPUDevice> => {
    const { data } = await api.post<GPUDevice>(`/gpu/devices/${deviceId}/maintenance`, { enabled })
    return data
  },
  reset: async (deviceId: number): Promise<void> => {
    await api.post(`/gpu/devices/${deviceId}/reset`)
  },
  throttle: async (deviceId: number, powerLimitWatts?: number): Promise<void> => {
    await api.post(`/gpu/devices/${deviceId}/throttle`, { power_limit_watts: powerLimitWatts })
  },
  listAvailable: async (params?: { gpu_type?: string; min_memory_mb?: number; count?: number }): Promise<GPUDevice[]> => {
    const { data } = await api.get<GPUDevice[]>('/gpu/devices/available', { params })
    return data
  },
}

export const systemApi = {
  stats: async (): Promise<SystemStats> => {
    const { data } = await api.get<SystemStats>('/stats')
    return data
  },
  health: async (): Promise<{ status: string; version: string; uptime_seconds: number }> => {
    const { data } = await api.get('/health')
    return data
  },
  metrics: async (params?: { period?: string }): Promise<{ task_throughput: { timestamp: string; value: number }[]; gpu_utilization: { timestamp: string; value: number }[]; queue_length: { timestamp: string; value: number }[] }> => {
    const { data } = await api.get('/stats/metrics', { params })
    return data
  },
}

export const schedulesApi = {
  list: async (params?: { enabled?: boolean; namespace_id?: string }): Promise<ScheduledTask[]> => {
    const { data } = await api.get<ScheduledTask[]>('/schedules', { params })
    return data
  },
  get: async (scheduleId: string): Promise<ScheduledTask> => {
    const { data } = await api.get<ScheduledTask>(`/schedules/${scheduleId}`)
    return data
  },
  create: async (schedule: {
    name: string
    description?: string
    task_template: Record<string, unknown>
    schedule_type: string
    cron_expression?: string
    interval_seconds?: number
    run_once_at?: string
    timezone?: string
    enabled?: boolean
    namespace_id?: string
  }): Promise<ScheduledTask> => {
    const { data } = await api.post<ScheduledTask>('/schedules', schedule)
    return data
  },
  update: async (scheduleId: string, updates: Partial<ScheduledTask>): Promise<ScheduledTask> => {
    const { data } = await api.put<ScheduledTask>(`/schedules/${scheduleId}`, updates)
    return data
  },
  delete: async (scheduleId: string): Promise<void> => {
    await api.delete(`/schedules/${scheduleId}`)
  },
  enable: async (scheduleId: string): Promise<ScheduledTask> => {
    const { data } = await api.post<ScheduledTask>(`/schedules/${scheduleId}/enable`)
    return data
  },
  disable: async (scheduleId: string): Promise<ScheduledTask> => {
    const { data } = await api.post<ScheduledTask>(`/schedules/${scheduleId}/disable`)
    return data
  },
  trigger: async (scheduleId: string): Promise<ScheduledTaskRun> => {
    const { data } = await api.post<ScheduledTaskRun>(`/schedules/${scheduleId}/trigger`)
    return data
  },
  runs: async (scheduleId: string, params?: { limit?: number; offset?: number }): Promise<{ runs: ScheduledTaskRun[]; total: number }> => {
    const { data } = await api.get(`/schedules/${scheduleId}/runs`, { params })
    return data
  },
  delayed: async (task: TaskCreateRequest, delaySeconds: number): Promise<Task> => {
    const { data } = await api.post<Task>('/schedules/delayed', { task, delay_seconds: delaySeconds })
    return data
  },
}

export const gangApi = {
  list: async (params?: { status?: string; user_id?: string }): Promise<GangTask[]> => {
    const { data } = await api.get<GangTask[]>('/gang', { params })
    return data
  },
  get: async (gangId: string): Promise<GangTask> => {
    const { data } = await api.get<GangTask>(`/gang/${gangId}`)
    return data
  },
  create: async (gang: {
    name: string
    task_template: Record<string, unknown>
    gpu_count: number
    priority?: number
    preemptible?: boolean
    preemption_deadline?: string
    namespace_id?: string
  }): Promise<GangTask> => {
    const { data } = await api.post<GangTask>('/gang', gang)
    return data
  },
  cancel: async (gangId: string): Promise<void> => {
    await api.delete(`/gang/${gangId}`)
  },
  retry: async (gangId: string): Promise<GangTask> => {
    const { data } = await api.post<GangTask>(`/gang/${gangId}/retry`)
    return data
  },
  preemptionCheck: async (): Promise<{ preemptible: PreemptionRecord[]; recommendation: string }> => {
    const { data } = await api.get('/gang/preemption-check')
    return data
  },
  fairShare: async (params?: { namespace_id?: string }): Promise<FairShareBucket[]> => {
    const { data } = await api.get<FairShareBucket[]>('/gang/fair-share', { params })
    return data
  },
}

export const namespacesApi = {
  list: async (): Promise<Namespace[]> => {
    const { data } = await api.get<Namespace[]>('/namespaces')
    return data
  },
  get: async (namespaceId: string): Promise<Namespace> => {
    const { data } = await api.get<Namespace>(`/namespaces/${namespaceId}`)
    return data
  },
  create: async (namespace: { name: string; display_name: string; description?: string }): Promise<Namespace> => {
    const { data } = await api.post<Namespace>('/namespaces', namespace)
    return data
  },
  update: async (namespaceId: string, updates: Partial<Namespace>): Promise<Namespace> => {
    const { data } = await api.put<Namespace>(`/namespaces/${namespaceId}`, updates)
    return data
  },
  delete: async (namespaceId: string): Promise<void> => {
    await api.delete(`/namespaces/${namespaceId}`)
  },
  members: async (namespaceId: string): Promise<NamespaceMember[]> => {
    const { data } = await api.get<NamespaceMember[]>(`/namespaces/${namespaceId}/members`)
    return data
  },
  addMember: async (namespaceId: string, userId: string, role: string): Promise<NamespaceMember> => {
    const { data } = await api.post<NamespaceMember>(`/namespaces/${namespaceId}/members`, { user_id: userId, role })
    return data
  },
  removeMember: async (namespaceId: string, memberId: string): Promise<void> => {
    await api.delete(`/namespaces/${namespaceId}/members/${memberId}`)
  },
  teams: async (namespaceId: string): Promise<Team[]> => {
    const { data } = await api.get<Team[]>(`/namespaces/${namespaceId}/teams`)
    return data
  },
  quota: async (namespaceId: string): Promise<NamespaceQuota> => {
    const { data } = await api.get<NamespaceQuota>(`/namespaces/${namespaceId}/quota`)
    return data
  },
  updateQuota: async (namespaceId: string, quota: Partial<NamespaceQuota>): Promise<NamespaceQuota> => {
    const { data } = await api.put<NamespaceQuota>(`/namespaces/${namespaceId}/quota`, quota)
    return data
  },
  usage: async (namespaceId: string): Promise<NamespaceUsage> => {
    const { data } = await api.get<NamespaceUsage>(`/namespaces/${namespaceId}/usage`)
    return data
  },
}

export const cloudApi = {
  providers: async (): Promise<CloudProvider[]> => {
    const { data } = await api.get<CloudProvider[]>('/cloud/providers')
    return data
  },
  getProvider: async (providerId: string): Promise<CloudProvider> => {
    const { data } = await api.get<CloudProvider>(`/cloud/providers/${providerId}`)
    return data
  },
  availableGPUs: async (providerId: string, params?: { region?: string; gpu_type?: string }): Promise<CloudRegion[]> => {
    const { data } = await api.get<CloudRegion[]>(`/cloud/providers/${providerId}/gpus`, { params })
    return data
  },
  launch: async (request: CloudLaunchRequest): Promise<CloudGPUInstance> => {
    const { data } = await api.post<CloudGPUInstance>('/cloud/instances/launch', request)
    return data
  },
  instances: async (params?: { provider_id?: string; status?: string; namespace_id?: string }): Promise<CloudGPUInstance[]> => {
    const { data } = await api.get<CloudGPUInstance[]>('/cloud/instances', { params })
    return data
  },
  getInstance: async (instanceId: string): Promise<CloudGPUInstance> => {
    const { data } = await api.get<CloudGPUInstance>(`/cloud/instances/${instanceId}`)
    return data
  },
  stopInstance: async (instanceId: string): Promise<void> => {
    await api.post(`/cloud/instances/${instanceId}/stop`)
  },
  startInstance: async (instanceId: string): Promise<void> => {
    await api.post(`/cloud/instances/${instanceId}/start`)
  },
  terminateInstance: async (instanceId: string): Promise<void> => {
    await api.delete(`/cloud/instances/${instanceId}`)
  },
  estimateCost: async (providerId: string, gpuType: string, gpuCount: number, hours: number): Promise<CloudCostEstimate> => {
    const { data } = await api.get<CloudCostEstimate>('/cloud/estimate-cost', { params: { provider_id: providerId, gpu_type: gpuType, gpu_count: gpuCount, hours } })
    return data
  },
  providerHealth: async (providerId: string): Promise<{ status: string; latency_ms: number }> => {
    const { data } = await api.get(`/cloud/providers/${providerId}/health`)
    return data
  },
}

export const usersApi = {
  list: async (params?: { role?: string; is_active?: boolean }): Promise<User[]> => {
    const { data } = await api.get<User[]>('/users', { params })
    return data
  },
  get: async (userId: string): Promise<User> => {
    const { data } = await api.get<User>(`/users/${userId}`)
    return data
  },
  create: async (user: { username: string; email: string; password: string; role?: string }): Promise<User> => {
    const { data } = await api.post<User>('/users', user)
    return data
  },
  update: async (userId: string, updates: Partial<User>): Promise<User> => {
    const { data } = await api.put<User>(`/users/${userId}`, updates)
    return data
  },
  delete: async (userId: string): Promise<void> => {
    await api.delete(`/users/${userId}`)
  },
  auditLogs: async (params?: { user_id?: string; action?: string; limit?: number; offset?: number }): Promise<{ logs: AuditLog[]; total: number }> => {
    const { data } = await api.get('/users/audit-logs', { params })
    return data
  },
  serviceMetrics: async (): Promise<ServiceMetrics[]> => {
    const { data } = await api.get<ServiceMetrics[]>('/users/service-metrics')
    return data
  },
  leaderboard: async (metric: string = 'tasks'): Promise<LeaderboardEntry[]> => {
    const { data } = await api.get<LeaderboardEntry[]>('/users/leaderboard', { params: { metric } })
    return data
  },
  achievements: async (userId?: string): Promise<Achievement[]> => {
    const { data } = await api.get<Achievement[]>('/users/achievements', { params: userId ? { user_id: userId } : {} })
    return data
  },
}

export const alertsApi = {
  list: async (params?: { severity?: string; acknowledged?: boolean; resolved?: boolean }): Promise<Alert[]> => {
    const { data } = await api.get<Alert[]>('/alerts', { params })
    return data
  },
  acknowledge: async (alertId: string): Promise<Alert> => {
    const { data } = await api.post<Alert>(`/alerts/${alertId}/acknowledge`)
    return data
  },
  resolve: async (alertId: string): Promise<Alert> => {
    const { data } = await api.post<Alert>(`/alerts/${alertId}/resolve`)
    return data
  },
}

export default api
