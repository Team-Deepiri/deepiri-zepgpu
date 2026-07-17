import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Play, Send } from 'lucide-react'
import toast from 'react-hot-toast'
import clsx from 'clsx'
import { roomsApi } from '@/api/rooms'
import { getRoomErrorMessage } from '@/utils/roomErrors'
import { DEFAULT_GPU_MEMORY_MB } from '@/constants/tasks'
import type { RoomNode, RoomNodeGpu } from '@/types'

interface RoomDispatchPanelProps {
  roomId: string
  onTaskDispatched: (taskId: string) => void
  enablePolling?: boolean
}

type RoomDispatchMode = 'room_auto' | 'room_specific_node'

function isDispatchableNode(node: RoomNode): boolean {
  return node.is_online && node.is_gpu_host && node.available_gpu_count > 0
}

function maxAvailableGpuMemory(gpus: RoomNodeGpu[]): number | undefined {
  const capacities = gpus
    .filter((gpu) => gpu.is_active && gpu.available_memory_mb > 0)
    .map((gpu) => gpu.available_memory_mb)
  return capacities.length > 0 ? Math.max(...capacities) : undefined
}

export default function RoomDispatchPanel({
  roomId,
  onTaskDispatched,
  enablePolling = true,
}: RoomDispatchPanelProps) {
  const [dispatchMode, setDispatchMode] = useState<RoomDispatchMode>('room_auto')
  const [name, setName] = useState('')
  const [funcName, setFuncName] = useState('')
  const [funcTouched, setFuncTouched] = useState(false)
  const [gpuMemoryMb, setGpuMemoryMb] = useState(DEFAULT_GPU_MEMORY_MB)
  const [targetPeerId, setTargetPeerId] = useState('')
  const [targetGpuShareId, setTargetGpuShareId] = useState('')

  const nodesQuery = useQuery({
    queryKey: ['room-nodes', roomId],
    queryFn: () => roomsApi.getRoomNodes(roomId),
    refetchInterval: enablePolling ? 10000 : false,
  })

  const dispatchableNodes = useMemo(
    () => (nodesQuery.data ?? []).filter(isDispatchableNode),
    [nodesQuery.data],
  )

  const selectedNode = dispatchableNodes.find((node) => node.id === targetPeerId)

  const roomGpusQuery = useQuery({
    queryKey: ['room-gpus', roomId],
    queryFn: () => roomsApi.getRoomGpus(roomId),
    enabled: dispatchMode === 'room_auto',
    refetchInterval: enablePolling ? 10000 : false,
  })

  const gpusQuery = useQuery({
    queryKey: ['room-node-gpus', roomId, targetPeerId],
    queryFn: () => roomsApi.getRoomNodeGpus(roomId, targetPeerId),
    enabled: dispatchMode === 'room_specific_node' && !!targetPeerId,
    refetchInterval: enablePolling ? 10000 : false,
  })

  const availableGpus = useMemo(
    () => (gpusQuery.data ?? []).filter((gpu) => gpu.is_active && gpu.available_memory_mb > 0),
    [gpusQuery.data],
  )

  const maxGpuMemoryMb = useMemo(() => {
    if (dispatchMode === 'room_specific_node') {
      const targetGpu = availableGpus.find((gpu) => gpu.id === targetGpuShareId)
      if (targetGpu) return targetGpu.available_memory_mb
      return maxAvailableGpuMemory(availableGpus)
    }

    return maxAvailableGpuMemory(roomGpusQuery.data ?? [])
  }, [availableGpus, dispatchMode, roomGpusQuery.data, targetGpuShareId])

  useEffect(() => {
    if (maxGpuMemoryMb != null && gpuMemoryMb > maxGpuMemoryMb) {
      setGpuMemoryMb(maxGpuMemoryMb)
    }
  }, [gpuMemoryMb, maxGpuMemoryMb])

  const exceedsAvailableMemory =
    maxGpuMemoryMb != null && gpuMemoryMb > maxGpuMemoryMb

  const funcMissing = funcTouched && !funcName.trim()

  const dispatchMutation = useMutation({
    mutationFn: () =>
      roomsApi.dispatchTask({
        room_id: roomId,
        dispatch_mode: dispatchMode,
        func_name: funcName.trim(),
        name: name.trim() || undefined,
        gpu_memory_mb: gpuMemoryMb,
        target_peer_id: dispatchMode === 'room_specific_node' ? targetPeerId : undefined,
        target_gpu_share_id:
          dispatchMode === 'room_specific_node' && targetGpuShareId ? targetGpuShareId : undefined,
      }),
    onSuccess: (task) => {
      toast.success(`Task dispatched (${task.id.slice(0, 8)}…)`)
      onTaskDispatched(task.id)
      setName('')
    },
    onError: (err) => {
      toast.error(getRoomErrorMessage(err, 'Failed to dispatch task'))
    },
  })

  const handleModeChange = (mode: RoomDispatchMode) => {
    setDispatchMode(mode)
    if (mode === 'room_auto') {
      setTargetPeerId('')
      setTargetGpuShareId('')
    }
  }

  const handlePeerChange = (peerId: string) => {
    setTargetPeerId(peerId)
    setTargetGpuShareId('')
  }

  const handleDispatch = () => {
    if (!funcName.trim()) {
      setFuncTouched(true)
      toast.error('Function is required')
      return
    }
    if (dispatchMode === 'room_specific_node' && !targetPeerId) {
      toast.error('Select a target node')
      return
    }
    if (exceedsAvailableMemory) {
      toast.error(`GPU memory request exceeds available capacity (${maxGpuMemoryMb} MB)`)
      return
    }
    dispatchMutation.mutate()
  }

  return (
    <section className="rounded-xl border border-slate-700/80 bg-slate-800/40 p-5">
      <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2 mb-4">
        <Send className="w-4 h-4 text-emerald-400" />
        Dispatch task
      </h2>

      <div className="space-y-4">
        <div className="flex flex-wrap gap-2">
          {(['room_auto', 'room_specific_node'] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => handleModeChange(mode)}
              className={clsx(
                'px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors',
                dispatchMode === mode
                  ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-300'
                  : 'border-slate-600 text-slate-400 hover:border-slate-500 hover:text-slate-200',
              )}
            >
              {mode === 'room_auto' ? 'Auto-select GPU' : 'Specific node'}
            </button>
          ))}
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="block text-xs text-slate-500 mb-1" htmlFor="dispatch-name">
              Task name (optional)
            </label>
            <input
              id="dispatch-name"
              type="text"
              className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white"
              placeholder="Room smoke task"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1" htmlFor="dispatch-func">
              Function
            </label>
            <input
              id="dispatch-func"
              type="text"
              className={clsx(
                'w-full bg-slate-900 border rounded-lg px-3 py-2 text-sm text-white font-mono',
                funcMissing ? 'border-red-500' : 'border-slate-600',
              )}
              placeholder="package.module.function"
              value={funcName}
              onChange={(e) => setFuncName(e.target.value)}
              onBlur={() => setFuncTouched(true)}
              aria-invalid={funcMissing}
            />
            {funcMissing && (
              <p className="text-xs text-red-400 mt-1">Function is required.</p>
            )}
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1" htmlFor="dispatch-gpu-mem">
              GPU memory (MB)
            </label>
            <input
              id="dispatch-gpu-mem"
              type="number"
              min={0}
              max={maxGpuMemoryMb}
              className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white"
              value={gpuMemoryMb}
              onChange={(e) => setGpuMemoryMb(Math.max(0, Number(e.target.value)))}
            />
            {maxGpuMemoryMb != null && (
              <p className="text-xs text-slate-500 mt-1">
                Max per GPU currently available: {maxGpuMemoryMb.toLocaleString()} MB
              </p>
            )}
            {exceedsAvailableMemory && (
              <p className="text-xs text-amber-400 mt-1">
                Request exceeds currently available GPU memory.
              </p>
            )}
          </div>
        </div>

        {dispatchMode === 'room_specific_node' && (
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="block text-xs text-slate-500 mb-1" htmlFor="dispatch-peer">
                Target node
              </label>
              <select
                id="dispatch-peer"
                className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white"
                value={targetPeerId}
                onChange={(e) => handlePeerChange(e.target.value)}
              >
                <option value="">Select node…</option>
                {dispatchableNodes.map((node) => (
                  <option key={node.id} value={node.id}>
                    {node.username} ({node.available_gpu_count} GPU
                    {node.available_gpu_count !== 1 ? 's' : ''} free)
                  </option>
                ))}
              </select>
              {nodesQuery.isSuccess && dispatchableNodes.length === 0 && (
                <p className="text-xs text-amber-400 mt-1">
                  No online GPU hosts with available capacity.
                </p>
              )}
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1" htmlFor="dispatch-gpu-share">
                GPU share (optional)
              </label>
              <select
                id="dispatch-gpu-share"
                className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white disabled:opacity-50"
                value={targetGpuShareId}
                onChange={(e) => setTargetGpuShareId(e.target.value)}
                disabled={!targetPeerId || gpusQuery.isLoading}
              >
                <option value="">Any available GPU</option>
                {availableGpus.map((gpu) => (
                  <option key={gpu.id} value={gpu.id}>
                    {formatGpuOption(gpu)}
                  </option>
                ))}
              </select>
              {selectedNode && gpusQuery.isFetching && (
                <p className="text-xs text-slate-500 mt-1">Loading GPUs…</p>
              )}
              {selectedNode &&
                !gpusQuery.isFetching &&
                gpusQuery.isSuccess &&
                availableGpus.length === 0 && (
                  <p className="text-xs text-amber-400 mt-1">
                    No active GPUs reported on this node.
                  </p>
                )}
            </div>
          </div>
        )}

        <button
          type="button"
          onClick={handleDispatch}
          disabled={
            dispatchMutation.isPending ||
            !funcName.trim() ||
            exceedsAvailableMemory ||
            (dispatchMode === 'room_specific_node' && !targetPeerId)
          }
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium text-white"
        >
          <Play className="w-4 h-4" />
          {dispatchMutation.isPending ? 'Dispatching…' : 'Dispatch to room'}
        </button>
      </div>
    </section>
  )
}

function formatGpuOption(gpu: RoomNodeGpu): string {
  const vramGb = (gpu.available_memory_mb / 1024).toFixed(1)
  return `GPU ${gpu.device_index}: ${gpu.name} (${vramGb} GB free)`
}
