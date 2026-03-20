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
  namespace_id: string | null
  service_name: string | null
  tags: string[]
  metadata: Record<string, unknown>
  result_url: string | null
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
  namespace_id?: string
  service_name?: string
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
  status: GPUStatus
  utilization_percent: number
  temperature_celsius: number
  power_watts: number
  memory_used_mb: number
  fan_speed_percent: number
  uuid: string | null
  pci_bus_id: string | null
  driver_version: string | null
  cuda_version: string | null
  current_task_id: string | null
  current_user: string | null
  power_limit_watts: number | null
  memory_reserved_mb: number | null
  error_message: string | null
  last_health_check: string | null
  namespace_id: string | null
  tags: string[]
}

export type GPUStatus = 'available' | 'busy' | 'gang_allocated' | 'preempting' | 'maintenance' | 'error' | 'offline'

export interface Pipeline {
  id: string
  name: string
  status: TaskStatus
  stages: PipelineStage[]
  created_at: string
  started_at: string | null
  completed_at: string | null
  error: string | null
  namespace_id: string | null
  priority: number
  total_tasks: number
  completed_tasks: number
  failed_tasks: number
}

export interface PipelineStage {
  name: string
  task_id: string
  depends_on: string[]
  gpu_device_id: number | null
  status: TaskStatus
}

export interface User {
  id: string
  username: string
  email: string
  role: UserRole
  is_active: boolean
  created_at: string
  last_login: string | null
  namespace_ids: string[]
  total_tasks: number
  total_gpu_hours: number
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
  queued_tasks: number
  scheduled_tasks: number
  total_tasks: number
  gang_running: number
  gang_queued: number
}

export interface SystemStats {
  queue: QueueStats
  gpus: GPUDevice[]
  uptime_seconds: number
  total_gpu_hours: number
  avg_gpu_utilization: number
  task_success_rate: number
  tasks_last_24h: number
  failures_last_24h: number
  active_namespaces: number
}

export interface ScheduledTask {
  id: string
  name: string
  description: string | null
  task_template: Record<string, unknown>
  schedule_type: ScheduleType
  cron_expression: string | null
  interval_seconds: number | null
  run_once_at: string | null
  enabled: boolean
  timezone: string
  namespace_id: string | null
  created_by: string | null
  created_at: string
  updated_at: string
  last_run_at: string | null
  next_run_at: string | null
  run_count: number
  failure_count: number
}

export type ScheduleType = 'cron' | 'interval' | 'run_once'

export interface ScheduledTaskRun {
  id: string
  schedule_id: string
  task_id: string | null
  status: TaskStatus
  started_at: string
  completed_at: string | null
  error: string | null
  execution_time_ms: number | null
}

export interface GangTask {
  id: string
  name: string
  status: TaskStatus
  gpu_count: number
  gpu_ids: number[]
  task_ids: string[]
  priority: number
  created_by: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  error: string | null
  preemptible: boolean
  preemption_deadline: string | null
}

export interface PreemptionRecord {
  id: string
  gang_task_id: string
  task_id: string
  preempted_at: string
  reason: string
  resumed_at: string | null
}

export interface FairShareBucket {
  id: string
  namespace_id: string
  weight: number
  current_usage_seconds: number
  period_start: string
  period_end: string
  tasks_executed: number
}

export interface Namespace {
  id: string
  name: string
  display_name: string
  description: string | null
  is_active: boolean
  created_at: string
  created_by: string | null
  member_count: number
  team_count: number
  quota: NamespaceQuota | null
  usage: NamespaceUsage | null
}

export interface NamespaceMember {
  id: string
  namespace_id: string
  user_id: string
  role: 'owner' | 'admin' | 'member'
  joined_at: string
  username?: string
  email?: string
}

export interface Team {
  id: string
  namespace_id: string
  name: string
  description: string | null
  created_at: string
  member_count: number
}

export interface TeamMember {
  id: string
  team_id: string
  user_id: string
  role: 'lead' | 'member'
  joined_at: string
  username?: string
  email?: string
}

export interface NamespaceQuota {
  namespace_id: string
  max_gpus: number
  max_tasks_per_day: number
  max_gpu_memory_mb: number
  priority_boost: number
  max_scheduled_tasks: number
}

export interface NamespaceUsage {
  namespace_id: string
  current_gpus: number
  tasks_today: number
  current_gpu_memory_mb: number
  active_schedules: number
}

export interface CloudProvider {
  id: string
  name: string
  provider_type: CloudProviderType
  status: 'healthy' | 'degraded' | 'unavailable'
  enabled: boolean
  regions: CloudRegion[]
  gpu_types: string[]
  total_available_gpus: number
  api_endpoint: string | null
  credentials_configured: boolean
  last_health_check: string | null
}

export type CloudProviderType = 'runpod' | 'lambdalabs' | 'aws' | 'custom'

export interface CloudRegion {
  id: string
  name: string
  display_name: string
  available_gpus: number
  gpu_types: string[]
  hourly_price_usd: number | null
  status: 'available' | 'limited' | 'unavailable'
}

export interface CloudGPUInstance {
  id: string
  provider_id: string
  instance_id: string
  name: string
  gpu_type: string
  gpu_count: number
  region: string
  status: CloudInstanceStatus
  public_ip: string | null
  private_ip: string | null
  created_at: string
  hourly_cost_usd: number | null
  uptime_hours: number | null
  namespace_id: string | null
}

export type CloudInstanceStatus = 'launching' | 'running' | 'stopping' | 'stopped' | 'error' | 'terminated'

export interface CloudLaunchRequest {
  provider_id: string
  gpu_type: string
  gpu_count: number
  region: string
  name: string
  namespace_id?: string
  disk_size_gb?: number
  container_disk_size_gb?: number
  min_free_memory_gb?: number
  ports?: string[]
  env?: Record<string, string>
}

export interface CloudCostEstimate {
  provider_id: string
  gpu_type: string
  gpu_count: number
  hours: number
  total_cost_usd: number
  cost_per_hour_usd: number
  provider: string
}

export interface AuditLog {
  id: string
  user_id: string
  username: string
  action: string
  resource_type: string
  resource_id: string | null
  details: Record<string, unknown>
  ip_address: string | null
  timestamp: string
}

export interface Alert {
  id: string
  type: AlertType
  severity: AlertSeverity
  message: string
  resource_type: string | null
  resource_id: string | null
  created_at: string
  acknowledged: boolean
  acknowledged_by: string | null
  acknowledged_at: string | null
  resolved: boolean
}

export type AlertType = 'gpu_overload' | 'gpu_temperature' | 'gpu_memory' | 'task_failure' | 'pipeline_failure' | 'quota_exceeded' | 'scheduled_task_failure' | 'cloud_provider_error' | 'preemption' | 'health_check_failed'

export type AlertSeverity = 'critical' | 'warning' | 'info'

export interface MetricsDataPoint {
  timestamp: string
  value: number
}

export interface GPUMetrics {
  gpu_id: number
  gpu_name: string
  utilization_history: MetricsDataPoint[]
  memory_history: MetricsDataPoint[]
  temperature_history: MetricsDataPoint[]
  power_history: MetricsDataPoint[]
  fan_speed_history: MetricsDataPoint[]
  current_utilization: number
  current_memory_mb: number
  current_temperature: number
  current_power_watts: number
  current_fan_speed: number
}

export interface ServiceMetrics {
  service_name: string
  tasks_executed: number
  avg_runtime_ms: number
  success_rate: number
  avg_gpu_utilization: number
  total_gpu_hours: number
  tasks_last_24h: number
  tasks_last_7d: number
}

export interface TaskMetrics {
  total_tasks: number
  completed_tasks: number
  failed_tasks: number
  cancelled_tasks: number
  avg_runtime_ms: number
  p50_runtime_ms: number
  p95_runtime_ms: number
  p99_runtime_ms: number
  throughput_per_hour: number
  success_rate: number
}

export interface LeaderboardEntry {
  rank: number
  user_id: string
  username: string
  metric: string
  value: number
  avatar_url: string | null
}

export interface Achievement {
  id: string
  name: string
  description: string
  icon: string
  unlocked_at: string | null
  progress: number
  threshold: number
}

export interface DAGNode {
  id: string
  label: string
  status: TaskStatus
  gpu_id: number | null
  x?: number
  y?: number
}

export interface DAGEdge {
  id: string
  source: string
  target: string
}

export interface DAGData {
  nodes: DAGNode[]
  edges: DAGEdge[]
}
