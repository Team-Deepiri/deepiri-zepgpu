import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Network, RefreshCw } from 'lucide-react'
import { roomsApi } from '@/api/rooms'
import { getRoomErrorMessage } from '@/utils/roomErrors'
import RoomNodeCard from '@/components/rooms/RoomNodeCard'

interface RoomNodeListProps {
  roomId: string
}

export default function RoomNodeList({ roomId }: RoomNodeListProps) {
  const queryClient = useQueryClient()

  const nodesQuery = useQuery({
    queryKey: ['room-nodes', roomId],
    queryFn: () => roomsApi.getRoomNodes(roomId),
    refetchInterval: 10000,
  })

  const onlineNodeCount = (nodesQuery.data ?? []).filter((n) => n.is_online).length

  const handleRefresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['room-nodes', roomId] })
    void queryClient.invalidateQueries({ queryKey: ['room-node-gpus', roomId] })
    void queryClient.invalidateQueries({ queryKey: ['room-gpu-pool', roomId] })
  }

  return (
    <section className="rounded-xl border border-slate-700/80 bg-slate-800/40 p-5">
      <div className="flex items-center justify-between gap-2 mb-4">
        <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2">
          <Network className="w-4 h-4 text-cyan-400" />
          Nodes
          {nodesQuery.data && (
            <span className="text-slate-500 font-normal">({onlineNodeCount} online)</span>
          )}
        </h2>
        <button
          type="button"
          onClick={handleRefresh}
          disabled={nodesQuery.isFetching}
          className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs text-slate-400 hover:text-cyan-400 hover:bg-slate-700/50 disabled:opacity-50"
          aria-label="Refresh nodes"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${nodesQuery.isFetching ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {nodesQuery.isLoading ? (
        <p className="text-slate-500 text-sm">Loading nodes…</p>
      ) : nodesQuery.isError ? (
        <p className="text-sm text-red-400">
          {getRoomErrorMessage(nodesQuery.error, 'Failed to load nodes')}
        </p>
      ) : (nodesQuery.data ?? []).length === 0 ? (
        <p className="text-slate-500 text-sm">
          No nodes connected yet. Run the node agent on a provider machine to advertise GPUs.
        </p>
      ) : (
        <ul className="space-y-3 max-h-[32rem] overflow-y-auto">
          {(nodesQuery.data ?? []).map((node) => (
            <RoomNodeCard key={node.id} roomId={roomId} node={node} />
          ))}
        </ul>
      )}
    </section>
  )
}
