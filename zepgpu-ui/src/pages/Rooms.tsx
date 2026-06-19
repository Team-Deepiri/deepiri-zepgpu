import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { format } from 'date-fns'
import { Home, Plus, Trash2, Users } from 'lucide-react'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import { roomsApi } from '@/api/rooms'
import { getRoomErrorMessage } from '@/utils/roomErrors'
import JoinRoomForm from '@/components/rooms/JoinRoomForm'
import type { Room } from '@/types'

function RoomStatusBadge({ status }: { status: Room['status'] }) {
  return (
    <span
      className={clsx(
        'text-xs px-2 py-0.5 rounded-full font-medium',
        status === 'active'
          ? 'bg-green-500/20 text-green-400'
          : 'bg-slate-700 text-slate-400',
      )}
    >
      {status}
    </span>
  )
}

export default function Rooms() {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  const {
    data: rooms,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['rooms'],
    queryFn: () => roomsApi.listRooms(),
    refetchInterval: 15000,
  })

  const createRoom = useMutation({
    mutationFn: () =>
      roomsApi.createRoom({
        name: name.trim(),
        description: description.trim() || null,
      }),
    onSuccess: (room) => {
      toast.success(`Room "${room.name}" created`)
      setName('')
      setDescription('')
      queryClient.invalidateQueries({ queryKey: ['rooms'] })
    },
    onError: (err) => {
      toast.error(getRoomErrorMessage(err, 'Failed to create room'))
    },
  })

  const deleteRoom = useMutation({
    mutationFn: (roomId: string) => roomsApi.deleteRoom(roomId),
    onSuccess: () => {
      toast.success('Room archived')
      queryClient.invalidateQueries({ queryKey: ['rooms'] })
    },
    onError: (err) => {
      toast.error(getRoomErrorMessage(err, 'Failed to archive room'))
    },
  })

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim() || createRoom.isPending) return
    createRoom.mutate()
  }

  const listError = isError ? getRoomErrorMessage(error, 'Failed to load rooms') : null

  return (
    <div className="space-y-8 max-w-6xl">
      <div>
        <h1 className="text-3xl font-bold text-white flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-500/30 to-orange-500/30 flex items-center justify-center border border-amber-500/30">
            <Home className="w-6 h-6 text-amber-400" />
          </div>
          GPU Rooms
        </h1>
        <p className="text-slate-400 mt-1">
          Create a room, invite members, and pool remote GPUs
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-xl border border-slate-700/80 bg-slate-800/40 p-5">
          <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2 mb-4">
            <Home className="w-4 h-4 text-amber-400" />
            My rooms
          </h2>

          {isLoading ? (
            <p className="text-slate-500 text-sm">Loading rooms…</p>
          ) : listError ? (
            <p className="text-sm text-red-400" role="alert">
              {listError}
            </p>
          ) : (
            <ul className="space-y-2">
              {(rooms ?? []).map((room) => (
                <li
                  key={room.id}
                  className="flex items-center gap-2 border border-slate-700 bg-slate-900/40 rounded-lg px-3 py-2"
                >
                  <Link
                    to={`/rooms/${room.id}`}
                    className="flex-1 min-w-0 text-sm hover:text-amber-200 transition-colors"
                  >
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium text-slate-200">{room.name}</span>
                      <RoomStatusBadge status={room.status} />
                    </div>
                    {room.description && (
                      <p className="text-slate-500 text-xs mt-0.5 truncate">{room.description}</p>
                    )}
                    <p className="text-slate-600 text-xs mt-1">
                      Created {format(new Date(room.created_at), 'MMM d, yyyy')}
                    </p>
                  </Link>
                  <button
                    type="button"
                    onClick={() => deleteRoom.mutate(room.id)}
                    disabled={deleteRoom.isPending}
                    title="Archive room"
                    className="p-2 rounded-lg text-slate-500 hover:text-red-400 hover:bg-red-900/20 transition-colors disabled:opacity-50"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </li>
              ))}
              {rooms?.length === 0 && (
                <p className="text-slate-500 text-sm">
                  No rooms yet — create one below or join with an invite code.
                </p>
              )}
            </ul>
          )}

          <form onSubmit={handleCreate} className="mt-4 pt-4 border-t border-slate-700 space-y-3">
            <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wide">
              Create room
            </h3>
            <div>
              <label className="block text-xs text-slate-500 mb-1" htmlFor="room-name">
                Name
              </label>
              <input
                id="room-name"
                className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="team-alpha"
                required
              />
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1" htmlFor="room-description">
                Description (optional)
              </label>
              <input
                id="room-description"
                className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Shared GPU pool for the team"
              />
            </div>
            <button
              type="submit"
              disabled={createRoom.isPending || !name.trim()}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 text-white text-sm font-medium disabled:opacity-50"
            >
              <Plus className="w-4 h-4" />
              {createRoom.isPending ? 'Creating…' : 'Create room'}
            </button>
          </form>
        </section>

        <section className="rounded-xl border border-slate-700/80 bg-slate-800/40 p-5">
          <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2 mb-4">
            <Users className="w-4 h-4 text-emerald-400" />
            Join with invite code
          </h2>
          <JoinRoomForm />
        </section>
      </div>
    </div>
  )
}
