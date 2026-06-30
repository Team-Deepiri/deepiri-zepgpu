import { useQuery } from '@tanstack/react-query'
import { Server } from 'lucide-react'
import { roomsApi } from '@/api/rooms'
import { getRoomErrorMessage } from '@/utils/roomErrors'
import { GpuMetricCard } from '@/components/rooms/RoomGpuPoolSummary'
import { NodeStatusBadge, formatMemoryGb, formatOptionalDate } from '@/components/rooms/roomNodeUtils'
import type { RoomNode } from '@/types'

interface RoomNodeCardProps {
  roomId: string
  node: RoomNode
}

export default function RoomNodeCard({ roomId, node }: RoomNodeCardProps) {
  const gpusQuery = useQuery({
    queryKey: ['room-node-gpus', roomId, node.id],
    queryFn: () => roomsApi.getRoomNodeGpus(roomId, node.id),
    enabled: node.is_gpu_host && node.gpu_count > 0,
    refetchInterval: 10000,
  })

  return (
    <li className="border border-slate-700/60 rounded-lg p-4 space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <Server className="w-4 h-4 text-cyan-400 shrink-0" />
            <span className="text-slate-200 font-medium">{node.username}</span>
            <NodeStatusBadge status={node.status} />
            {node.is_gpu_host && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-violet-500/20 text-violet-300">
                GPU host
              </span>
            )}
          </div>
          <p className="text-slate-500 text-xs mt-1">
            {node.vpn_ip} · Last seen {formatOptionalDate(node.last_seen)}
          </p>
          <p className="text-slate-500 text-xs mt-0.5">
            {node.gpu_count} GPU{node.gpu_count !== 1 ? 's' : ''} ·{' '}
            {node.available_gpu_count} available · {formatMemoryGb(node.available_memory_mb)} VRAM
            free
          </p>
        </div>
      </div>

      {node.is_gpu_host && node.gpu_count > 0 && (
        <div>
          {gpusQuery.isLoading ? (
            <p className="text-slate-500 text-xs">Loading GPUs…</p>
          ) : gpusQuery.isError ? (
            <p className="text-red-400 text-xs">
              {getRoomErrorMessage(gpusQuery.error, 'Failed to load GPUs')}
            </p>
          ) : (gpusQuery.data ?? []).length === 0 ? (
            <p className="text-slate-500 text-xs">No GPU metrics reported.</p>
          ) : (
            <div className="grid gap-2 sm:grid-cols-2">
              {(gpusQuery.data ?? []).map((gpu) => (
                <GpuMetricCard key={gpu.id} gpu={gpu} />
              ))}
            </div>
          )}
        </div>
      )}
    </li>
  )
}
