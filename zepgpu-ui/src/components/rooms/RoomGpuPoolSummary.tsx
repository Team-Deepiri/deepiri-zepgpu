import { useQuery } from '@tanstack/react-query'
import { format } from 'date-fns'
import clsx from 'clsx'
import { roomsApi } from '@/api/rooms'
import { getRoomErrorMessage } from '@/utils/roomErrors'
import { formatMemoryGb } from '@/components/rooms/roomNodeUtils'
import type { RoomNodeGpu } from '@/types'

interface RoomGpuPoolSummaryProps {
  roomId: string
}

function GpuMetricCard({ gpu }: { gpu: RoomNodeGpu }) {
  const usedMb = gpu.total_memory_mb - gpu.available_memory_mb
  const usedPercent =
    gpu.total_memory_mb > 0 ? Math.min(100, (usedMb / gpu.total_memory_mb) * 100) : 0

  return (
    <div
      className={clsx(
        'border rounded-lg p-3 text-sm',
        gpu.is_active ? 'border-slate-600/80 bg-slate-900/40' : 'border-slate-700/40 opacity-60',
      )}
    >
      <div className="flex justify-between items-start gap-2">
        <div className="min-w-0">
          <p className="text-slate-200 font-medium truncate">
            {gpu.name ?? `GPU ${gpu.device_index}`}
          </p>
          <p className="text-slate-500 text-xs mt-0.5">
            Device {gpu.device_index} · {gpu.state}
            {!gpu.is_active && ' · inactive'}
          </p>
        </div>
        {gpu.utilization_percent != null && (
          <span className="text-cyan-400 text-xs font-medium shrink-0">
            {gpu.utilization_percent.toFixed(1)}%
          </span>
        )}
      </div>
      <div className="mt-2 h-1.5 rounded-full bg-slate-700 overflow-hidden">
        <div
          className="h-full bg-orange-500/70 rounded-full"
          style={{ width: `${usedPercent}%` }}
        />
      </div>
      <p className="text-slate-500 text-xs mt-1.5">
        {formatMemoryGb(gpu.available_memory_mb)} free of {formatMemoryGb(gpu.total_memory_mb)}
      </p>
      <p className="text-slate-600 text-xs mt-0.5">
        Updated {format(new Date(gpu.last_updated), 'MMM d, HH:mm')}
      </p>
    </div>
  )
}

export default function RoomGpuPoolSummary({ roomId }: RoomGpuPoolSummaryProps) {
  const poolQuery = useQuery({
    queryKey: ['room-gpu-pool', roomId],
    queryFn: () => roomsApi.getRoomGpuPool(roomId),
    refetchInterval: 10000,
  })

  const nodesQuery = useQuery({
    queryKey: ['room-nodes', roomId],
    queryFn: () => roomsApi.getRoomNodes(roomId),
    refetchInterval: 10000,
  })

  const onlineNodeCount = (nodesQuery.data ?? []).filter((n) => n.is_online).length

  if (poolQuery.isLoading) {
    return <p className="text-slate-500 text-sm">Loading GPU pool…</p>
  }

  if (poolQuery.isError) {
    return (
      <p className="text-sm text-red-400">
        {getRoomErrorMessage(poolQuery.error, 'Failed to load GPU pool')}
      </p>
    )
  }

  if (!poolQuery.data) {
    return null
  }

  const pool = poolQuery.data

  return (
    <div className="space-y-3 text-sm">
      <p className="text-slate-400 text-xs">
        Online nodes: <span className="text-white font-medium">{onlineNodeCount}</span>
      </p>
      <div className="grid grid-cols-2 gap-2 text-slate-300">
        <div>
          Total GPUs: <span className="text-white font-medium">{pool.total_gpus}</span>
        </div>
        <div>
          Available (usable now):{' '}
          <span className="text-white font-medium">{pool.available_gpus}</span>
        </div>
        <div>
          Allocated: <span className="text-white font-medium">{pool.allocated_gpus}</span>
        </div>
        <div>
          VRAM total: <span className="text-white font-medium">{formatMemoryGb(pool.total_memory_mb)}</span>
        </div>
        <div className="col-span-2">
          VRAM available (usable now):{' '}
          <span className="text-white font-medium">{formatMemoryGb(pool.available_memory_mb)}</span>
        </div>
      </div>
      {(pool.providers ?? []).length > 0 && (
        <div className="flex flex-wrap gap-1.5 border-t border-slate-700 pt-3">
          {pool.providers.map((provider) => (
            <span
              key={provider}
              className="text-xs px-2 py-0.5 rounded-full bg-slate-700 text-slate-300"
            >
              {provider}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

export { GpuMetricCard }
