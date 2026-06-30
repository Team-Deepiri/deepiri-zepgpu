import clsx from 'clsx'
import type { RoomNodeStatus } from '@/types'

export function NodeStatusBadge({ status }: { status: RoomNodeStatus }) {
  return (
    <span
      className={clsx(
        'text-xs px-2 py-0.5 rounded-full font-medium',
        status === 'connected' && 'bg-green-500/20 text-green-400',
        status === 'disconnected' && 'bg-slate-700 text-slate-400',
        status === 'awol' && 'bg-red-500/20 text-red-400',
        status === 'pending' && 'bg-amber-500/20 text-amber-400',
      )}
    >
      {status}
    </span>
  )
}

export function formatOptionalDate(value: string | null | undefined): string {
  if (!value) return '—'
  return new Date(value).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatMemoryGb(mb: number): string {
  return `${(mb / 1024).toFixed(1)} GB`
}
