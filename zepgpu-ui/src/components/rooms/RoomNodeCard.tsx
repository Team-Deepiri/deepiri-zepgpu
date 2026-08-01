import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Ban, Server } from 'lucide-react'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import { roomsApi } from '@/api/rooms'
import { getRoomErrorMessage } from '@/utils/roomErrors'
import { GpuMetricCard } from '@/components/rooms/RoomGpuPoolSummary'
import { NodeStatusBadge, formatMemoryGb, formatOptionalDate } from '@/components/rooms/roomNodeUtils'
import type { RoomNode, RoomNodeHealthState } from '@/types'

interface RoomNodeCardProps {
  roomId: string
  node: RoomNode
  enablePolling?: boolean
  canRevoke?: boolean
}

const HEALTH_STYLES: Record<string, string> = {
  healthy: 'bg-green-500/20 text-green-300',
  degraded: 'bg-amber-500/20 text-amber-300',
  stale: 'bg-orange-500/20 text-orange-300',
  offline: 'bg-slate-600/40 text-slate-300',
  revoked: 'bg-red-500/20 text-red-300',
  incompatible: 'bg-fuchsia-500/20 text-fuchsia-300',
  claim_timeout: 'bg-red-500/20 text-red-300',
}

function HealthBadge({ state }: { state: RoomNodeHealthState | string }) {
  return (
    <span
      className={clsx(
        'text-xs px-2 py-0.5 rounded-full',
        HEALTH_STYLES[state] ?? 'bg-slate-700 text-slate-300',
      )}
    >
      {state}
    </span>
  )
}

export default function RoomNodeCard({
  roomId,
  node,
  enablePolling = true,
  canRevoke = false,
}: RoomNodeCardProps) {
  const queryClient = useQueryClient()
  const isRevoked = Boolean(node.revoked_at)

  const gpusQuery = useQuery({
    queryKey: ['room-node-gpus', roomId, node.id],
    queryFn: () => roomsApi.getRoomNodeGpus(roomId, node.id),
    enabled: !isRevoked && node.is_gpu_host && node.gpu_count > 0,
    refetchInterval: enablePolling ? 10000 : false,
  })

  const revokeProvider = useMutation({
    mutationFn: () => roomsApi.revokeRoomProvider(roomId, node.id),
    onSuccess: () => {
      toast.success('Provider revoked')
      void queryClient.invalidateQueries({ queryKey: ['room-nodes', roomId] })
      void queryClient.invalidateQueries({ queryKey: ['room-node-gpus', roomId] })
      void queryClient.invalidateQueries({ queryKey: ['room-gpu-pool', roomId] })
      void queryClient.invalidateQueries({ queryKey: ['room-members', roomId] })
    },
    onError: (err) => {
      toast.error(getRoomErrorMessage(err, 'Failed to revoke provider'))
    },
  })

  const handleRevoke = () => {
    if (
      window.confirm(
        `Revoke provider ${node.node_name || node.username}? Active assignments will be failed.`,
      )
    ) {
      revokeProvider.mutate()
    }
  }

  const rtt =
    node.path?.coordinator_rtt_ms != null
      ? `${node.path.coordinator_rtt_ms.toFixed(1)} ms`
      : null

  return (
    <li className="border border-slate-700/60 rounded-lg p-4 space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <Server className="w-4 h-4 text-cyan-400 shrink-0" />
            <span className="text-slate-200 font-medium">
              {node.node_name || node.username}
            </span>
            <NodeStatusBadge status={isRevoked ? 'disconnected' : node.status} />
            {node.health_state && <HealthBadge state={node.health_state} />}
            {isRevoked && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-red-500/20 text-red-300">
                Revoked
              </span>
            )}
            {node.is_gpu_host && !isRevoked && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-violet-500/20 text-violet-300">
                GPU host
              </span>
            )}
          </div>
          {node.health_reason && (
            <p className="text-slate-400 text-xs mt-1">{node.health_reason}</p>
          )}
          <p className="text-slate-500 text-xs mt-1">
            {node.vpn_ip} · Last seen {formatOptionalDate(node.last_seen)}
            {node.provider_mode && <> · {node.provider_mode}</>}
            {node.agent_version && <> · v{node.agent_version}</>}
          </p>
          <p className="text-slate-500 text-xs mt-0.5">
            {node.gpu_count} GPU{node.gpu_count !== 1 ? 's' : ''} ·{' '}
            {node.available_gpu_count} available · {formatMemoryGb(node.available_memory_mb)} VRAM
            free
          </p>
          {(node.path || node.capabilities) && (
            <p className="text-slate-500 text-xs mt-0.5">
              {node.path && (
                <>
                  Path {node.path.path_type}/{node.path.path_class}
                  {rtt && <> · RTT {rtt}</>}
                  {node.path.is_measured ? ' · measured' : ' · estimated'}
                </>
              )}
              {node.path && node.capabilities && <> · </>}
              {node.capabilities && (
                <>
                  CUDA {node.capabilities.cuda_version ?? 'unavailable'}
                  {node.capabilities.pytorch_version != null && (
                    <> · PyTorch {node.capabilities.pytorch_version}</>
                  )}
                </>
              )}
            </p>
          )}
        </div>
        {canRevoke && !isRevoked && (
          <button
            type="button"
            onClick={handleRevoke}
            disabled={revokeProvider.isPending}
            className="inline-flex items-center gap-1 px-2 py-1 rounded bg-red-900/30 text-red-300 text-xs hover:bg-red-900/50 disabled:opacity-50"
          >
            <Ban className="w-3 h-3" />
            {revokeProvider.isPending ? 'Revoking…' : 'Revoke provider'}
          </button>
        )}
      </div>

      {!isRevoked && node.is_gpu_host && node.gpu_count > 0 && (
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
