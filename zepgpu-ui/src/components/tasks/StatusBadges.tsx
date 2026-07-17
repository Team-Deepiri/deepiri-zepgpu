import clsx from 'clsx'
import type { NodeAssignmentStatus, TaskStatus } from '@/types'

export function TaskStatusBadge({
  status,
  size = 'sm',
}: {
  status: TaskStatus
  size?: 'sm' | 'lg'
}) {
  return (
    <span
      className={clsx(
        'rounded-full font-medium',
        size === 'lg' ? 'px-4 py-2 text-sm' : 'px-2 py-0.5 text-xs',
        status === 'completed' && 'bg-green-500/20 text-green-400',
        status === 'failed' && 'bg-red-500/20 text-red-400',
        status === 'running' && 'bg-blue-500/20 text-blue-400',
        status === 'assigned' && 'bg-violet-500/20 text-violet-300',
        (status === 'pending' || status === 'queued' || status === 'scheduled') &&
          'bg-yellow-500/20 text-yellow-400',
        (status === 'cancelled' || status === 'timeout') && 'bg-slate-600/50 text-slate-300',
      )}
    >
      {status}
    </span>
  )
}

export function AssignmentStatusBadge({ status }: { status: NodeAssignmentStatus }) {
  return (
    <span
      className={clsx(
        'inline-flex rounded-full px-2 py-0.5 text-xs font-medium',
        status === 'completed' && 'bg-green-500/20 text-green-400',
        (status === 'failed' || status === 'cancelled') && 'bg-red-500/20 text-red-400',
        (status === 'running' || status === 'accepted') && 'bg-blue-500/20 text-blue-400',
        status === 'assigned' && 'bg-violet-500/20 text-violet-300',
      )}
    >
      {status}
    </span>
  )
}
