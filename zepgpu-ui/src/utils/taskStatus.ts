import type { Task, TaskStatus } from '@/types'

export const ACTIVE_TASK_STATUSES: readonly TaskStatus[] = [
  'pending',
  'queued',
  'scheduled',
  'assigned',
  'running',
]

export const TERMINAL_TASK_STATUSES: readonly TaskStatus[] = [
  'completed',
  'failed',
  'cancelled',
  'timeout',
]

export function isActiveStatus(status: TaskStatus | null | undefined): boolean {
  return status != null && ACTIVE_TASK_STATUSES.includes(status)
}

export function isTerminalTaskStatus(status: TaskStatus | null | undefined): boolean {
  return status != null && TERMINAL_TASK_STATUSES.includes(status)
}

export function shouldPollTask(task: Task | undefined): boolean {
  return !task || !isTerminalTaskStatus(task.status)
}
