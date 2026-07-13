import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { format } from 'date-fns'
import clsx from 'clsx'
import { ArrowLeft, Home, UserPlus, Users, Shield } from 'lucide-react'
import { getRoomErrorMessage, getRoomErrorStatus } from '@/utils/roomErrors'
import { roomsApi } from '@/api/rooms'
import InvitePanel from '@/components/rooms/InvitePanel'
import RoomConfigPanel from '@/components/rooms/RoomConfigPanel'
import RoomGpuPoolSummary from '@/components/rooms/RoomGpuPoolSummary'
import RoomNodeList from '@/components/rooms/RoomNodeList'
import RoomDispatchPanel from '@/components/rooms/RoomDispatchPanel'
import RoomActivityLog from '@/components/rooms/RoomActivityLog'
import type { RoomMember, RoomMemberStatus } from '@/types'

function getErrorStatus(err: unknown): number | null {
  return getRoomErrorStatus(err)
}

function MemberStatusBadge({ status }: { status: RoomMemberStatus }) {
  return (
    <span
      className={clsx(
        'text-xs px-2 py-0.5 rounded-full font-medium',
        status === 'connected' && 'bg-green-500/20 text-green-400',
        status === 'disconnected' && 'bg-slate-700 text-slate-400',
        status === 'pending' && 'bg-amber-500/20 text-amber-400',
      )}
    >
      {status}
    </span>
  )
}

function formatOptionalDate(value: string | null): string {
  if (!value) return '—'
  return format(new Date(value), 'MMM d, yyyy HH:mm')
}

function MemberRow({ member }: { member: RoomMember }) {
  const label = member.display_name ?? member.user_id ?? 'Unknown member'
  return (
    <li className="flex justify-between items-center gap-3 border border-slate-700/50 rounded-lg px-3 py-2 text-sm">
      <div className="min-w-0">
        <span className="text-slate-200">{label}</span>
        <p className="text-slate-500 text-xs mt-0.5">
          Joined {formatOptionalDate(member.joined_at)}
          {member.last_seen_at && (
            <> · Last seen {formatOptionalDate(member.last_seen_at)}</>
          )}
        </p>
      </div>
      <MemberStatusBadge status={member.status} />
    </li>
  )
}

export default function RoomDetail() {
  const { roomId } = useParams<{ roomId: string }>()
  const [dispatchedTaskIds, setDispatchedTaskIds] = useState<string[]>([])

  const roomQuery = useQuery({
    queryKey: ['room', roomId],
    queryFn: () => roomsApi.getRoom(roomId!),
    enabled: !!roomId,
    retry: false,
  })

  const membersQuery = useQuery({
    queryKey: ['room-members', roomId],
    queryFn: () => roomsApi.getRoomMembers(roomId!),
    enabled: !!roomId && roomQuery.isSuccess,
    refetchInterval: 10000,
  })

  const handleTaskDispatched = (taskId: string) => {
    setDispatchedTaskIds((prev) => (prev.includes(taskId) ? prev : [taskId, ...prev]))
  }

  if (!roomId) {
    return (
      <div className="max-w-6xl">
        <p className="text-red-400">Invalid room URL.</p>
        <Link to="/rooms" className="text-cyan-400 text-sm mt-2 inline-block">
          ← Back to rooms
        </Link>
      </div>
    )
  }

  if (roomQuery.isLoading) {
    return (
      <div className="max-w-6xl">
        <p className="text-slate-500">Loading room…</p>
      </div>
    )
  }

  if (roomQuery.isError) {
    const status = getErrorStatus(roomQuery.error)
    const message = getRoomErrorMessage(roomQuery.error, 'Failed to load room')
    const isNotFound = status === 404 || message === 'Room not found'
    const isForbidden = status === 403 || message.includes('access')

    return (
      <div className="max-w-6xl space-y-4">
        <Link
          to="/rooms"
          className="inline-flex items-center gap-1 text-sm text-cyan-400 hover:text-cyan-300"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to rooms
        </Link>
        <div className="rounded-xl border border-red-800/50 bg-red-900/20 p-6">
          <h1 className="text-xl font-semibold text-red-200">
            {isNotFound ? 'Room not found' : isForbidden ? 'Access denied' : 'Unable to load room'}
          </h1>
          <p className="text-red-300/80 mt-2 text-sm">{message}</p>
        </div>
      </div>
    )
  }

  if (!roomQuery.data) {
    return (
      <div className="max-w-6xl">
        <p className="text-slate-500">Room not available.</p>
      </div>
    )
  }

  const room = roomQuery.data

  return (
    <div className="space-y-8 max-w-6xl">
      <div>
        <Link
          to="/rooms"
          className="inline-flex items-center gap-1 text-sm text-cyan-400 hover:text-cyan-300"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to rooms
        </Link>
        <div className="mt-4 flex flex-wrap items-start gap-4">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-500/30 to-orange-500/30 flex items-center justify-center border border-amber-500/30">
            <Home className="w-6 h-6 text-amber-400" />
          </div>
          <div>
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-3xl font-bold text-white">{room.name}</h1>
              <span
                className={clsx(
                  'text-xs px-2 py-0.5 rounded-full font-medium',
                  room.status === 'active'
                    ? 'bg-green-500/20 text-green-400'
                    : 'bg-slate-700 text-slate-400',
                )}
              >
                {room.status}
              </span>
            </div>
            {room.description && (
              <p className="text-slate-400 mt-1">{room.description}</p>
            )}
            <p className="text-slate-500 text-sm mt-2">
              Host <span className="font-mono text-slate-400">{room.host_id}</span>
              {' · '}
              Created {format(new Date(room.created_at), 'MMM d, yyyy')}
            </p>
          </div>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <RoomDispatchPanel roomId={roomId} onTaskDispatched={handleTaskDispatched} />
        <RoomActivityLog roomId={roomId} taskIds={dispatchedTaskIds} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-xl border border-slate-700/80 bg-slate-800/40 p-5">
          <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2 mb-4">
            <Users className="w-4 h-4 text-pink-400" />
            Members
          </h2>
          {membersQuery.isLoading ? (
            <p className="text-slate-500 text-sm">Loading members…</p>
          ) : membersQuery.isError ? (
            <p className="text-sm text-red-400">
              {getRoomErrorMessage(membersQuery.error, 'Failed to load members')}
            </p>
          ) : (membersQuery.data ?? []).length === 0 ? (
            <p className="text-slate-500 text-sm">No members yet.</p>
          ) : (
            <ul className="space-y-2 max-h-64 overflow-y-auto">
              {(membersQuery.data ?? []).map((member) => (
                <MemberRow key={member.id} member={member} />
              ))}
            </ul>
          )}
        </section>

        <section className="rounded-xl border border-slate-700/80 bg-slate-800/40 p-5">
          <h2 className="text-sm font-semibold text-slate-200 mb-4">GPU pool</h2>
          <RoomGpuPoolSummary roomId={roomId} />
        </section>
      </div>

      <RoomNodeList roomId={roomId} />

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-xl border border-slate-700/80 bg-slate-800/40 p-5">
          <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2 mb-4">
            <UserPlus className="w-4 h-4 text-violet-400" />
            Invites
          </h2>
          <InvitePanel roomId={roomId} />
        </section>

        <section className="rounded-xl border border-slate-700/80 bg-slate-800/40 p-5">
          <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2 mb-4">
            <Shield className="w-4 h-4 text-cyan-400" />
            Connection config
          </h2>
          <RoomConfigPanel roomId={roomId} />
        </section>
      </div>
    </div>
  )
}
