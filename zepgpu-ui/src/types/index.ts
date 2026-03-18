export interface Task {
  id: string
  name: string | null
  status: TaskStatus
  priority: number
  gpu_memory_mb: number
  timeout_seconds: number
  gpu_type: string | null
  gpu_device_id: number | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  error: string | null
  execution_time_ms: number | null
  user_id: string | null
}

export type TaskStatus = 'pending' | 'queued' | 'scheduled' | 'running' | 'completed' | 'failed' | 'cancelled' | 'timeout'

export interface TaskCreateRequest {
  name?: string
  func_name?: string
  serialized_func?: string
  args?: string
  kwargs?: string
  priority?: number
  gpu_memory_mb?: number
  cpu_cores?: number
  timeout_seconds?: number
  gpu_type?: string
  allow_fallback_cpu?: boolean
  tags?: string[]
  metadata?: Record<string, unknown>
  callback_url?: string
}

export interface TaskListResponse {
  tasks: Task[]
  total: number
  limit: number
  offset: number
}

export interface GPUDevice {
  id: number
  device_index: number
  name: string
  gpu_type: string
  total_memory_mb: number
  compute_capability: string
  status: string
  utilization_percent: number
  temperature_celsius: number
  power_watts: number
}

export interface Pipeline {
  id: string
  name: string
  status: TaskStatus
  stages: PipelineStage[]
  created_at: string
  started_at: string | null
  completed_at: string | null
  error: string | null
}

export interface PipelineStage {
  name: string
  task_id: string
  depends_on: string[]
}

export interface User {
  id: string
  username: string
  email: string
  role: UserRole
  is_active: boolean
  created_at: string
}

export type UserRole = 'admin' | 'researcher' | 'user' | 'guest'

export interface AuthToken {
  access_token: string
  token_type: string
  expires_in: number
}

export interface QueueStats {
  pending_tasks: number
  running_tasks: number
  completed_tasks: number
  failed_tasks: number
  total_tasks: number
}

export interface SystemStats {
  queue: QueueStats
  gpus: GPUDevice[]
  uptime_seconds: number
}
