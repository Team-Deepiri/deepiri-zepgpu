import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { vpnApi } from '@/api/client'
import {
  Network, Users, Cpu, Copy, LogOut, UserPlus, Check, Shield,
} from 'lucide-react'
import clsx from 'clsx'
import toast from 'react-hot-toast'

export default function Vpn() {
  const queryClient = useQueryClient()
  const [selectedNetId, setSelectedNetId] = useState<string | null>(null)
  const [newNetName, setNewNetName] = useState('')
  const [joinCode, setJoinCode] = useState('')
  const [joinGpuHost, setJoinGpuHost] = useState(false)
  const [inviteMaxUses, setInviteMaxUses] = useState(10)
  const [inviteDays, setInviteDays] = useState(7)
  const [configPreview, setConfigPreview] = useState<string | null>(null)

  const { data: networks, isLoading: netsLoading } = useQuery({
    queryKey: ['vpn-networks'],
    queryFn: () => vpnApi.listNetworks(),
    refetchInterval: 15000,
  })

  const { data: pool } = useQuery({
    queryKey: ['vpn-gpu-pool', selectedNetId],
    queryFn: () => vpnApi.getGpuPool(selectedNetId ?? undefined),
    refetchInterval: 10000,
  })

  const { data: peers } = useQuery({
    queryKey: ['vpn-peers', selectedNetId],
    queryFn: () => vpnApi.listPeers(selectedNetId!),
    enabled: !!selectedNetId,
    refetchInterval: 10000,
  })

  const { data: invites } = useQuery({
    queryKey: ['vpn-invites'],
    queryFn: () => vpnApi.listInvites(),
    refetchInterval: 30000,
  })

  const { data: friends } = useQuery({
    queryKey: ['vpn-friends'],
    queryFn: () => vpnApi.listFriends(),
    refetchInterval: 20000,
  })

  const createNet = useMutation({
    mutationFn: () =>
      vpnApi.createNetwork({
        name: newNetName.trim() || 'my-network',
        cidr: '10.8.0.0/24',
      }),
    onSuccess: () => {
      toast.success('VPN network created')
      setNewNetName('')
      queryClient.invalidateQueries({ queryKey: ['vpn-networks'] })
    },
    onError: () => toast.error('Failed to create network'),
  })

  const createInv = useMutation({
    mutationFn: () => {
      if (!selectedNetId) throw new Error('no network')
      return vpnApi.createInvite(selectedNetId, {
        max_uses: inviteMaxUses,
        expires_in_days: inviteDays,
      })
    },
    onSuccess: (inv) => {
      toast.success(`Invite code: ${inv.code}`)
      queryClient.invalidateQueries({ queryKey: ['vpn-invites'] })
    },
    onError: () => toast.error('Failed to create invite'),
  })

  const leaveNet = useMutation({
    mutationFn: (id: string) => vpnApi.leaveNetwork(id),
    onSuccess: () => {
      toast.success('Left network')
      setSelectedNetId(null)
      queryClient.invalidateQueries({ queryKey: ['vpn-networks'] })
      queryClient.invalidateQueries({ queryKey: ['vpn-gpu-pool'] })
    },
    onError: () => toast.error('Failed to leave network'),
  })

  const joinMut = useMutation({
    mutationFn: () =>
      vpnApi.joinNetwork({
        invite_code: joinCode.trim(),
        is_gpu_host: joinGpuHost,
      }),
    onSuccess: (cfg) => {
      toast.success(`Joined — VPN IP ${cfg.vpn_ip}`)
      setJoinCode('')
      setConfigPreview(cfg.config_text)
      queryClient.invalidateQueries({ queryKey: ['vpn-networks'] })
    },
    onError: (e: unknown) => {
      const msg = e && typeof e === 'object' && 'response' in e
        ? (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
        : null
      toast.error(typeof msg === 'string' ? msg : 'Join failed')
    },
  })

  const fetchConfig = useMutation({
    mutationFn: () => {
      if (!selectedNetId) throw new Error('no network')
      return vpnApi.getConfig(selectedNetId)
    },
    onSuccess: (c) => {
      setConfigPreview(c.config_text)
      toast.success('Config loaded — copy to your machine')
    },
    onError: () => toast.error('Failed to load WireGuard config'),
  })

  const acceptFriend = useMutation({
    mutationFn: (friendshipId: string) => vpnApi.acceptFriend(friendshipId),
    onSuccess: () => {
      toast.success('Friend request accepted')
      queryClient.invalidateQueries({ queryKey: ['vpn-friends'] })
    },
    onError: () => toast.error('Accept failed'),
  })

  const selected = networks?.find((n) => n.id === selectedNetId)

  return (
    <div className="space-y-8 max-w-6xl">
      <div>
        <h1 className="text-3xl font-bold text-white flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500/30 to-cyan-500/30 flex items-center justify-center border border-emerald-500/30">
            <Network className="w-6 h-6 text-emerald-400" />
          </div>
          VPN &amp; GPU pool
        </h1>
        <p className="text-slate-400 mt-1">
          Mesh networks, invites, and pooled remote GPUs
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-xl border border-slate-700/80 bg-slate-800/40 p-5">
          <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2 mb-4">
            <Shield className="w-4 h-4 text-cyan-400" />
            My networks
          </h2>
          {netsLoading ? (
            <p className="text-slate-500 text-sm">Loading…</p>
          ) : (
            <ul className="space-y-2">
              {(networks ?? []).map((n) => (
                <li key={n.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedNetId(n.id)}
                    className={clsx(
                      'w-full text-left px-3 py-2 rounded-lg border text-sm transition-colors',
                      selectedNetId === n.id
                        ? 'border-cyan-500/50 bg-cyan-500/10 text-cyan-100'
                        : 'border-slate-700 bg-slate-900/40 text-slate-300 hover:border-slate-600',
                    )}
                  >
                    <span className="font-medium">{n.name}</span>
                    <span className="text-slate-500 ml-2">
                      {n.peer_count} peers · {n.cidr}
                    </span>
                  </button>
                </li>
              ))}
              {networks?.length === 0 && (
                <p className="text-slate-500 text-sm">No networks yet — create one below.</p>
              )}
            </ul>
          )}

          <div className="mt-4 flex flex-wrap gap-2 items-end">
            <div>
              <label className="block text-xs text-slate-500 mb-1">New network name</label>
              <input
                className="bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white w-48"
                value={newNetName}
                onChange={(e) => setNewNetName(e.target.value)}
                placeholder="team-alpha"
              />
            </div>
            <button
              type="button"
              onClick={() => createNet.mutate()}
              disabled={createNet.isPending}
              className="px-4 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white text-sm font-medium disabled:opacity-50"
            >
              Create
            </button>
          </div>

          {selected && (
            <div className="mt-4 pt-4 border-t border-slate-700 space-y-3">
              <p className="text-xs text-slate-500">
                Selected: <span className="text-slate-300">{selected.name}</span>
              </p>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => fetchConfig.mutate()}
                  disabled={fetchConfig.isPending}
                  className="px-3 py-1.5 rounded-lg bg-slate-700 text-slate-100 text-xs hover:bg-slate-600"
                >
                  Download WireGuard config
                </button>
                <button
                  type="button"
                  onClick={() => leaveNet.mutate(selected.id)}
                  disabled={leaveNet.isPending}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-red-900/40 text-red-200 text-xs border border-red-800/50 hover:bg-red-900/60"
                >
                  <LogOut className="w-3 h-3" />
                  Leave network
                </button>
              </div>
              <div className="flex flex-wrap gap-2 items-end">
                <div>
                  <label className="block text-xs text-slate-500 mb-1">Max uses</label>
                  <input
                    type="number"
                    className="bg-slate-900 border border-slate-600 rounded-lg px-2 py-1.5 text-sm text-white w-20"
                    value={inviteMaxUses}
                    onChange={(e) => setInviteMaxUses(Number(e.target.value))}
                    min={1}
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-500 mb-1">Expires (days)</label>
                  <input
                    type="number"
                    className="bg-slate-900 border border-slate-600 rounded-lg px-2 py-1.5 text-sm text-white w-20"
                    value={inviteDays}
                    onChange={(e) => setInviteDays(Number(e.target.value))}
                    min={1}
                  />
                </div>
                <button
                  type="button"
                  onClick={() => createInv.mutate()}
                  disabled={createInv.isPending}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-violet-600 text-white text-xs hover:bg-violet-500"
                >
                  <UserPlus className="w-3 h-3" />
                  Create invite
                </button>
              </div>
            </div>
          )}
        </section>

        <section className="rounded-xl border border-slate-700/80 bg-slate-800/40 p-5">
          <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2 mb-4">
            <Users className="w-4 h-4 text-violet-400" />
            Join with code
          </h2>
          <div className="space-y-3">
            <input
              className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white font-mono"
              value={joinCode}
              onChange={(e) => setJoinCode(e.target.value.toUpperCase())}
              placeholder="Invite code"
            />
            <label className="flex items-center gap-2 text-sm text-slate-400">
              <input
                type="checkbox"
                checked={joinGpuHost}
                onChange={(e) => setJoinGpuHost(e.target.checked)}
                className="rounded border-slate-600"
              />
              Register as GPU host
            </label>
            <button
              type="button"
              onClick={() => joinMut.mutate()}
              disabled={joinMut.isPending || !joinCode.trim()}
              className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium disabled:opacity-50"
            >
              Join network
            </button>
          </div>

          <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wide mt-6 mb-2">Active invites</h3>
          <ul className="text-sm space-y-1 max-h-32 overflow-y-auto">
            {(invites ?? []).filter((i) => !i.is_revoked).map((i) => (
              <li key={i.id} className="text-slate-400 font-mono">
                {i.code}
                <span className="text-slate-600 ml-2">{i.vpn_network_name}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-xl border border-slate-700/80 bg-slate-800/40 p-5">
          <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2 mb-4">
            <Cpu className="w-4 h-4 text-orange-400" />
            GPU pool
            {selected && (
              <span className="text-slate-500 font-normal text-xs ml-2">({selected.name})</span>
            )}
          </h2>
          {pool ? (
            <div className="space-y-3 text-sm">
              <div className="grid grid-cols-2 gap-2 text-slate-300">
                <div>Total GPUs: <span className="text-white font-medium">{pool.total_gpus}</span></div>
                <div>VRAM total: <span className="text-white font-medium">{(pool.total_memory_mb / 1024).toFixed(1)} GB</span></div>
                <div>Available VRAM: <span className="text-white font-medium">{(pool.available_memory_mb / 1024).toFixed(1)} GB</span></div>
                <div>Online hosts: <span className="text-white font-medium">{pool.online_gpu_hosts}</span></div>
              </div>
              <ul className="max-h-48 overflow-y-auto space-y-1 border-t border-slate-700 pt-3">
                {pool.gpu_breakdown.map((g) => (
                  <li key={g.id} className="text-slate-400 flex justify-between gap-2">
                    <span className="text-slate-200">{g.name}</span>
                    <span>{g.username} · {(g.total_memory_mb / 1024).toFixed(0)} GB · {g.state}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="text-slate-500 text-sm">Select a network or join one to see pool stats.</p>
          )}
        </section>

        <section className="rounded-xl border border-slate-700/80 bg-slate-800/40 p-5">
          <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2 mb-4">
            <Users className="w-4 h-4 text-pink-400" />
            Peers
          </h2>
          {!selectedNetId ? (
            <p className="text-slate-500 text-sm">Select a network to list peers.</p>
          ) : (
            <ul className="text-sm space-y-2 max-h-64 overflow-y-auto">
              {(peers ?? []).map((p) => (
                <li
                  key={p.id}
                  className="flex justify-between items-center border border-slate-700/50 rounded-lg px-3 py-2"
                >
                  <div>
                    <span className="text-slate-200">{p.username}</span>
                    <span className="text-slate-500 ml-2 font-mono text-xs">{p.vpn_ip}</span>
                  </div>
                  <span
                    className={clsx(
                      'text-xs px-2 py-0.5 rounded-full',
                      p.is_online ? 'bg-green-500/20 text-green-400' : 'bg-slate-700 text-slate-400',
                    )}
                  >
                    {p.is_online ? 'online' : 'offline'}
                    {p.is_gpu_host ? ' · GPU' : ''}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section className="rounded-xl border border-slate-700/80 bg-slate-800/40 p-5">
        <h2 className="text-sm font-semibold text-slate-200 mb-3">Friends</h2>
        <div className="grid md:grid-cols-2 gap-4 text-sm">
          <div>
            <h3 className="text-xs text-slate-500 uppercase mb-2">Connected</h3>
            <ul className="space-y-1">
              {(friends?.friends ?? []).map((f) => (
                <li key={f.id} className="text-slate-300">{f.username}</li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="text-xs text-slate-500 uppercase mb-2">Pending (incoming)</h3>
            <ul className="space-y-2">
              {(friends?.pending ?? []).map((f) => (
                <li key={f.id} className="flex items-center justify-between gap-2">
                  <span className="text-slate-300">{f.username}</span>
                  <button
                    type="button"
                    onClick={() => acceptFriend.mutate(f.id)}
                    className="inline-flex items-center gap-1 px-2 py-1 rounded bg-slate-700 text-xs text-white hover:bg-slate-600"
                  >
                    <Check className="w-3 h-3" />
                    Accept
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {configPreview && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
          <div className="bg-slate-900 border border-slate-600 rounded-xl max-w-2xl w-full max-h-[80vh] flex flex-col">
            <div className="flex justify-between items-center px-4 py-3 border-b border-slate-700">
              <span className="text-white font-medium text-sm">WireGuard config</span>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => {
                    void navigator.clipboard.writeText(configPreview)
                    toast.success('Copied')
                  }}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-cyan-600 text-white text-xs"
                >
                  <Copy className="w-3 h-3" />
                  Copy
                </button>
                <button
                  type="button"
                  onClick={() => setConfigPreview(null)}
                  className="px-3 py-1.5 rounded-lg bg-slate-700 text-slate-200 text-xs"
                >
                  Close
                </button>
              </div>
            </div>
            <pre className="p-4 overflow-auto text-xs text-green-400 font-mono flex-1">{configPreview}</pre>
          </div>
        </div>
      )}
    </div>
  )
}
