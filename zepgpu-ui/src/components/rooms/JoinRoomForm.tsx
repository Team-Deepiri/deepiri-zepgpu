import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import { UserPlus } from 'lucide-react'
import toast from 'react-hot-toast'
import { roomsApi } from '@/api/rooms'
import { getRoomErrorMessage } from '@/utils/roomErrors'

export default function JoinRoomForm() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [inviteCode, setInviteCode] = useState('')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const join = useMutation({
    mutationFn: () => roomsApi.joinRoom({ invite_code: inviteCode.trim() }),
    onSuccess: (response) => {
      setErrorMessage(null)
      setInviteCode('')
      toast.success(`Joined ${response.room.name}`)
      queryClient.invalidateQueries({ queryKey: ['rooms'] })
      navigate(`/rooms/${response.room.id}`)
    },
    onError: (err) => {
      const msg = getRoomErrorMessage(err, 'Failed to join room')
      setErrorMessage(msg)
      toast.error(msg)
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!inviteCode.trim() || join.isPending) return
    setErrorMessage(null)
    join.mutate()
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <input
        className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white font-mono"
        value={inviteCode}
        onChange={(e) => setInviteCode(e.target.value.toUpperCase())}
        placeholder="Invite code"
        aria-label="Invite code"
      />
      {errorMessage && (
        <p className="text-sm text-red-400" role="alert">
          {errorMessage}
        </p>
      )}
      <button
        type="submit"
        disabled={join.isPending || !inviteCode.trim()}
        className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium disabled:opacity-50"
      >
        <UserPlus className="w-4 h-4" />
        {join.isPending ? 'Joining…' : 'Join room'}
      </button>
    </form>
  )
}
