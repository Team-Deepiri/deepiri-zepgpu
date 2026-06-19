import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { format } from 'date-fns'
import { Copy, UserPlus, Ban } from 'lucide-react'
import toast from 'react-hot-toast'
import { roomsApi } from '@/api/rooms'
import { getRoomErrorMessage } from '@/utils/roomErrors'

interface InvitePanelProps {
  roomId: string
}

export default function InvitePanel({ roomId }: InvitePanelProps) {
  const queryClient = useQueryClient()
  const [maxUses, setMaxUses] = useState(10)
  const [expiresInDays, setExpiresInDays] = useState(7)
  const [lastCreatedCode, setLastCreatedCode] = useState<string | null>(null)

  const { data: invites, isLoading } = useQuery({
    queryKey: ['room-invites', roomId],
    queryFn: () => roomsApi.listRoomInvites(roomId),
    refetchInterval: 30000,
  })

  const createInvite = useMutation({
    mutationFn: () => {
      const expires_at =
        expiresInDays > 0
          ? new Date(Date.now() + expiresInDays * 24 * 60 * 60 * 1000).toISOString()
          : null
      return roomsApi.createRoomInvite(roomId, {
        max_uses: maxUses,
        expires_at,
      })
    },
    onSuccess: (invite) => {
      setLastCreatedCode(invite.code)
      toast.success(`Invite created: ${invite.code}`)
      queryClient.invalidateQueries({ queryKey: ['room-invites', roomId] })
    },
    onError: (err) => {
      toast.error(getRoomErrorMessage(err, 'Failed to create invite'))
    },
  })

  const revokeInvite = useMutation({
    mutationFn: (inviteId: string) => roomsApi.revokeRoomInvite(roomId, inviteId),
    onSuccess: () => {
      toast.success('Invite revoked')
      queryClient.invalidateQueries({ queryKey: ['room-invites', roomId] })
    },
    onError: (err) => {
      toast.error(getRoomErrorMessage(err, 'Failed to revoke invite'))
    },
  })

  const copyCode = async (code: string) => {
    await navigator.clipboard.writeText(code)
    toast.success('Invite code copied')
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2 items-end">
        <div>
          <label className="block text-xs text-slate-500 mb-1" htmlFor="invite-max-uses">
            Max uses
          </label>
          <input
            id="invite-max-uses"
            type="number"
            min={1}
            className="bg-slate-900 border border-slate-600 rounded-lg px-2 py-1.5 text-sm text-white w-20"
            value={maxUses}
            onChange={(e) => setMaxUses(Number(e.target.value))}
          />
        </div>
        <div>
          <label className="block text-xs text-slate-500 mb-1" htmlFor="invite-expires-days">
            Expires (days)
          </label>
          <input
            id="invite-expires-days"
            type="number"
            min={0}
            className="bg-slate-900 border border-slate-600 rounded-lg px-2 py-1.5 text-sm text-white w-20"
            value={expiresInDays}
            onChange={(e) => setExpiresInDays(Number(e.target.value))}
          />
        </div>
        <button
          type="button"
          onClick={() => createInvite.mutate()}
          disabled={createInvite.isPending}
          className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-violet-600 text-white text-sm hover:bg-violet-500 disabled:opacity-50"
        >
          <UserPlus className="w-4 h-4" />
          {createInvite.isPending ? 'Creating…' : 'Create invite'}
        </button>
      </div>

      {lastCreatedCode && (
        <div className="flex items-center gap-2 p-3 rounded-lg bg-violet-500/10 border border-violet-500/30">
          <span className="text-sm text-slate-300">New code:</span>
          <code className="text-violet-200 font-mono text-sm">{lastCreatedCode}</code>
          <button
            type="button"
            onClick={() => void copyCode(lastCreatedCode)}
            className="ml-auto inline-flex items-center gap-1 px-2 py-1 rounded bg-slate-700 text-xs text-white hover:bg-slate-600"
          >
            <Copy className="w-3 h-3" />
            Copy
          </button>
        </div>
      )}

      <div>
        <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-2">
          Active invites
        </h3>
        {isLoading ? (
          <p className="text-slate-500 text-sm">Loading invites…</p>
        ) : (invites ?? []).length === 0 ? (
          <p className="text-slate-500 text-sm">No active invites.</p>
        ) : (
          <ul className="space-y-2 max-h-48 overflow-y-auto">
            {(invites ?? []).map((invite) => (
              <li
                key={invite.id}
                className="flex items-start justify-between gap-2 border border-slate-700/50 rounded-lg px-3 py-2 text-sm"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <code className="text-slate-200 font-mono">{invite.code}</code>
                    <button
                      type="button"
                      onClick={() => void copyCode(invite.code)}
                      className="p-1 rounded text-slate-500 hover:text-cyan-400"
                      title="Copy code"
                    >
                      <Copy className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  <p className="text-slate-500 text-xs mt-1">
                    Uses {invite.use_count}/{invite.max_uses}
                    {invite.expires_at && (
                      <> · Expires {format(new Date(invite.expires_at), 'MMM d, yyyy')}</>
                    )}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => revokeInvite.mutate(invite.id)}
                  disabled={revokeInvite.isPending}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded bg-red-900/30 text-red-300 text-xs hover:bg-red-900/50 disabled:opacity-50"
                >
                  <Ban className="w-3 h-3" />
                  Revoke
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
