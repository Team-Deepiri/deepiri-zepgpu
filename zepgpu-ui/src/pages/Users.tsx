import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { usersApi } from '@/api/client'
import {
  Users as UsersIcon, Award, Trophy,
  Trash2, Edit2, Search,
  Star, ScrollText
} from 'lucide-react'
import clsx from 'clsx'

export default function Users() {
  const [tab, setTab] = useState<'users' | 'audit' | 'leaderboard' | 'achievements'>('users')
  const [search, setSearch] = useState('')

  const { data: users, isLoading } = useQuery({
    queryKey: ['users'],
    queryFn: () => usersApi.list(),
  })

  const { data: auditLogs } = useQuery({
    queryKey: ['audit-logs'],
    queryFn: () => usersApi.auditLogs({ limit: 50 }),
    refetchInterval: 10000,
  })

  const { data: leaderboard } = useQuery({
    queryKey: ['leaderboard', 'tasks'],
    queryFn: () => usersApi.leaderboard('tasks'),
  })

  const { data: achievements } = useQuery({
    queryKey: ['achievements'],
    queryFn: () => usersApi.achievements(),
  })

  const filtered = (users ?? []).filter(u =>
    !search || u.username.toLowerCase().includes(search.toLowerCase()) || u.email.toLowerCase().includes(search.toLowerCase())
  )

  const roleColors: Record<string, string> = {
    admin: 'bg-red-500/20 text-red-400',
    researcher: 'bg-purple-500/20 text-purple-400',
    user: 'bg-blue-500/20 text-blue-400',
    guest: 'bg-slate-500/20 text-slate-400',
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-500/30 to-fuchsia-500/30 flex items-center justify-center border border-violet-500/30">
              <UsersIcon className="w-6 h-6 text-violet-400" />
            </div>
            User Management & Ops
          </h1>
          <p className="text-slate-400 mt-1">
              {(users ?? []).length} users · {(users ?? []).filter(u => u.is_active).length} active
          </p>
        </div>
      </div>

      {/* Tab Nav */}
      <div className="flex gap-2 border-b border-slate-700 pb-2">
        {[
          { key: 'users', label: 'Users', icon: UsersIcon },
          { key: 'audit', label: 'Audit Logs', icon: ScrollText },
          { key: 'leaderboard', label: 'Leaderboard', icon: Trophy },
          { key: 'achievements', label: 'Achievements', icon: Award },
        ].map(t => (
          <button key={t.key} onClick={() => setTab(t.key as typeof tab)}
            className={clsx('px-4 py-2 text-sm font-medium rounded-t-lg transition-colors flex items-center gap-2', tab === t.key ? 'bg-slate-800 text-white border border-b-0 border-slate-700' : 'text-slate-400 hover:text-white')}>
            <t.icon className="w-4 h-4" /> {t.label}
          </button>
        ))}
      </div>

      {tab === 'users' && (
        <>
          <div className="flex items-center gap-3">
            <div className="relative flex-1 max-w-md">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input value={search} onChange={e => setSearch(e.target.value)}
                className="w-full pl-10 pr-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-violet-500"
                placeholder="Search users..." />
            </div>
            <div className="flex gap-2">
              {['admin', 'researcher', 'user', 'guest'].map(role => (
                <span key={role} className={clsx('px-3 py-1 text-xs rounded-full font-medium capitalize', roleColors[role])}>
                  {role}
                </span>
              ))}
            </div>
          </div>

          <div className="bg-slate-800/80 rounded-2xl border border-slate-700/50 overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-700/50">
                  {['User', 'Role', 'Tasks', 'GPU Hours', 'Status', 'Last Login', 'Actions'].map(h => (
                    <th key={h} className="px-5 py-3 text-left text-xs font-medium text-slate-400 uppercase">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/30">
                {isLoading ? (
                  <tr><td colSpan={7} className="px-5 py-8 text-center text-slate-400">Loading...</td></tr>
                ) : filtered?.length === 0 ? (
                  <tr><td colSpan={7} className="px-5 py-8 text-center text-slate-400">No users found</td></tr>
                ) : filtered?.map(user => (
                  <tr key={user.id} className="hover:bg-slate-700/30">
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-500 flex items-center justify-center text-xs font-bold text-white">
                          {user.username[0].toUpperCase()}
                        </div>
                        <div>
                          <p className="text-white font-medium">{user.username}</p>
                          <p className="text-xs text-slate-400">{user.email}</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-3.5">
                      <span className={clsx('px-2 py-0.5 text-xs rounded-full font-medium capitalize', roleColors[user.role])}>
                        {user.role}
                      </span>
                    </td>
                    <td className="px-5 py-3.5 text-slate-300">{user.total_tasks}</td>
                    <td className="px-5 py-3.5 text-slate-300">{user.total_gpu_hours.toFixed(1)}h</td>
                    <td className="px-5 py-3.5">
                      <span className={clsx('px-2 py-0.5 text-xs rounded-full font-medium', user.is_active ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400')}>
                        {user.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td className="px-5 py-3.5 text-slate-400 text-sm">
                      {user.last_login ? new Date(user.last_login).toLocaleString() : 'Never'}
                    </td>
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-1">
                        <button className="p-1.5 text-slate-400 hover:text-white hover:bg-slate-700 rounded-lg transition-colors">
                          <Edit2 className="w-4 h-4" />
                        </button>
                        <button className="p-1.5 text-slate-400 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors">
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {tab === 'audit' && (
        <div className="bg-slate-800/80 rounded-2xl border border-slate-700/50 overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-700/50">
                {['Timestamp', 'User', 'Action', 'Resource', 'Details', 'IP'].map(h => (
                  <th key={h} className="px-5 py-3 text-left text-xs font-medium text-slate-400 uppercase">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/30">
              {auditLogs?.logs.map(log => (
                <tr key={log.id} className="hover:bg-slate-700/30">
                  <td className="px-5 py-3.5 text-slate-400 text-sm">
                    {new Date(log.timestamp).toLocaleString()}
                  </td>
                  <td className="px-5 py-3.5 text-white text-sm">{log.username}</td>
                  <td className="px-5 py-3.5">
                    <span className="px-2 py-0.5 text-xs bg-blue-500/20 text-blue-400 rounded-full font-mono">
                      {log.action}
                    </span>
                  </td>
                  <td className="px-5 py-3.5 text-slate-300 text-sm">
                    <span className="font-mono">{log.resource_type}</span>
                    {log.resource_id && <span className="text-slate-500 ml-1">#{log.resource_id.slice(0, 6)}</span>}
                  </td>
                  <td className="px-5 py-3.5 text-slate-400 text-xs max-w-[200px] truncate">
                    {JSON.stringify(log.details)}
                  </td>
                  <td className="px-5 py-3.5 text-slate-500 text-xs font-mono">{log.ip_address ?? '—'}</td>
                </tr>
              )) || (
                <tr><td colSpan={6} className="px-5 py-8 text-center text-slate-400">No audit logs</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'leaderboard' && (
        <div className="space-y-4">
          {/* Top 3 podium */}
          {leaderboard && leaderboard.length >= 3 && (
            <div className="grid grid-cols-3 gap-4 mb-6">
              {[1, 0, 2].map(pos => {
                const entry = leaderboard[pos]
                if (!entry) return null
                const medals = ['🥇', '🥈', '🥉']
                return (
                  <div key={pos} className={clsx(
                    'rounded-2xl border p-6 text-center',
                    pos === 0 ? 'bg-gradient-to-b from-yellow-500/10 to-orange-500/10 border-yellow-500/30 order-2' :
                    pos === 1 ? 'bg-gradient-to-b from-slate-400/10 to-slate-500/10 border-slate-400/30 order-1' :
                    'bg-gradient-to-b from-orange-600/10 to-red-600/10 border-orange-600/30 order-3'
                  )}>
                    <div className="w-16 h-16 rounded-full bg-gradient-to-br from-blue-500 to-purple-500 flex items-center justify-center text-xl font-bold text-white mx-auto mb-3">
                      {entry.username[0].toUpperCase()}
                    </div>
                    <p className="text-2xl mb-1">{medals[pos]}</p>
                    <p className="text-white font-semibold">{entry.username}</p>
                    <p className="text-3xl font-bold text-white mt-2">{entry.value.toLocaleString()}</p>
                    <p className="text-xs text-slate-400 capitalize">{entry.metric.replace('_', ' ')}</p>
                  </div>
                )
              })}
            </div>
          )}

          {/* Full list */}
          <div className="bg-slate-800/80 rounded-2xl border border-slate-700/50 overflow-hidden">
            {leaderboard?.map((entry) => (
              <div key={entry.user_id} className="flex items-center gap-4 px-5 py-3 hover:bg-slate-700/30 border-b border-slate-700/30 last:border-0">
                <span className={clsx(
                  'w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold',
                  entry.rank === 1 ? 'bg-yellow-500/20 text-yellow-400' :
                  entry.rank === 2 ? 'bg-slate-300/20 text-slate-300' :
                  entry.rank === 3 ? 'bg-orange-600/20 text-orange-400' :
                  'bg-slate-700 text-slate-400'
                )}>
                  {entry.rank}
                </span>
                <div className="w-10 h-10 rounded-full bg-gradient-to-br from-blue-500 to-purple-500 flex items-center justify-center text-sm font-bold text-white">
                  {entry.username[0].toUpperCase()}
                </div>
                <div className="flex-1">
                  <p className="text-white font-medium">{entry.username}</p>
                </div>
                <span className="text-2xl font-bold text-white">{entry.value.toLocaleString()}</span>
                <span className="text-sm text-slate-400 capitalize">{entry.metric.replace('_', ' ')}</span>
              </div>
            )) || (
              <div className="text-center py-12 text-slate-400">No leaderboard data</div>
            )}
          </div>
        </div>
      )}

      {tab === 'achievements' && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {achievements?.map(ach => (
            <div key={ach.id} className={clsx(
              'rounded-2xl border p-5 transition-all',
              ach.unlocked_at
                ? 'bg-gradient-to-br from-yellow-500/10 to-orange-500/10 border-yellow-500/30'
                : 'bg-slate-800/60 border-slate-700/50 opacity-60'
            )}>
              <div className="flex items-center gap-3 mb-3">
                <span className="text-3xl">{ach.icon}</span>
                <div>
                  <h3 className="text-white font-semibold">{ach.name}</h3>
                  <p className="text-xs text-slate-400">{ach.description}</p>
                </div>
              </div>
              {ach.unlocked_at ? (
                <div className="flex items-center gap-2 text-xs text-yellow-400">
                  <Star className="w-3 h-3" />
                  Unlocked {new Date(ach.unlocked_at).toLocaleDateString()}
                </div>
              ) : (
                <div className="mt-2">
                  <div className="w-full bg-slate-700 rounded-full h-2 mb-1">
                    <div className="bg-yellow-500 h-2 rounded-full transition-all"
                      style={{ width: `${Math.min((ach.progress / ach.threshold) * 100, 100)}%` }} />
                  </div>
                  <p className="text-xs text-slate-400">{ach.progress} / {ach.threshold}</p>
                </div>
              )}
            </div>
          )) || (
            <div className="col-span-full text-center py-12 text-slate-400">No achievements yet</div>
          )}
        </div>
      )}
    </div>
  )
}
