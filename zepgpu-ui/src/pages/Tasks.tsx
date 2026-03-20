import { useState, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { tasksApi } from '@/api/client'
import {
  Plus, Search, X, RotateCcw, Cpu,
  Eye
} from 'lucide-react'
import clsx from 'clsx'
import toast from 'react-hot-toast'

export default function Tasks() {
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [serviceFilter, setServiceFilter] = useState<string>('')
  const [search, setSearch] = useState('')
  const [view, setView] = useState<'table' | 'cards'>('table')
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['tasks', { status: statusFilter, service_name: serviceFilter }],
    queryFn: () => tasksApi.list({ status: statusFilter || undefined, service_name: serviceFilter || undefined }),
    refetchInterval: 5000,
  })

  const cancelMutation = useMutation({
    mutationFn: tasksApi.cancel,
    onSuccess: () => { toast.success('Task cancelled'); queryClient.invalidateQueries({ queryKey: ['tasks'] }) },
    onError: () => toast.error('Failed to cancel task'),
  })

  const retryMutation = useMutation({
    mutationFn: tasksApi.retry,
    onSuccess: () => { toast.success('Task resubmitted'); queryClient.invalidateQueries({ queryKey: ['tasks'] }) },
    onError: () => toast.error('Failed to retry task'),
  })

  const filtered = useMemo(() => {
    if (!data?.tasks) return []
    if (!search) return data.tasks
    const q = search.toLowerCase()
    return data.tasks.filter(t =>
      (t.name || t.id).toLowerCase().includes(q) ||
      t.service_name?.toLowerCase().includes(q) ||
      t.gpu_device_id?.toString().includes(q)
    )
  }, [data, search])

  const services = useMemo(() => {
    const svcs = new Set(data?.tasks.map(t => t.service_name).filter(Boolean))
    return Array.from(svcs) as string[]
  }, [data])

  const statusOptions = [
    { value: '', label: 'All' },
    { value: 'pending', label: 'Pending', color: 'text-yellow-400', bg: 'bg-yellow-500/20' },
    { value: 'queued', label: 'Queued', color: 'text-cyan-400', bg: 'bg-cyan-500/20' },
    { value: 'scheduled', label: 'Scheduled', color: 'text-purple-400', bg: 'bg-purple-500/20' },
    { value: 'running', label: 'Running', color: 'text-blue-400', bg: 'bg-blue-500/20' },
    { value: 'completed', label: 'Completed', color: 'text-green-400', bg: 'bg-green-500/20' },
    { value: 'failed', label: 'Failed', color: 'text-red-400', bg: 'bg-red-500/20' },
    { value: 'cancelled', label: 'Cancelled', color: 'text-slate-400', bg: 'bg-slate-500/20' },
    { value: 'timeout', label: 'Timeout', color: 'text-orange-400', bg: 'bg-orange-500/20' },
  ]

  const selectedStatus = statusOptions.find(s => s.value === statusFilter)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-green-500/30 to-emerald-500/30 flex items-center justify-center border border-green-500/30">
              <Cpu className="w-6 h-6 text-green-400" />
            </div>
            Task Command Center
          </h1>
          <p className="text-slate-400 mt-1">
            {data?.total ?? 0} tasks · {filtered.length} shown
            {selectedStatus && <span className={clsx('ml-2', selectedStatus.color)}>· {selectedStatus.label}</span>}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex bg-slate-800 rounded-lg p-1">
            <button onClick={() => setView('table')} className={clsx('px-3 py-1.5 rounded-md text-xs font-medium transition-colors', view === 'table' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white')}>
              Table
            </button>
            <button onClick={() => setView('cards')} className={clsx('px-3 py-1.5 rounded-md text-xs font-medium transition-colors', view === 'cards' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white')}>
              Cards
            </button>
          </div>
          <Link to="/tasks/new" className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-green-600 to-emerald-600 hover:from-green-500 hover:to-emerald-500 text-white rounded-lg font-medium transition-all shadow-lg shadow-green-500/20">
            <Plus className="w-4 h-4" /> New Task
          </Link>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <input
            type="text" placeholder="Search tasks, services, GPU IDs..."
            value={search} onChange={e => setSearch(e.target.value)}
            className="w-full pl-10 pr-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-green-500"
          />
        </div>
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}
          className="px-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white text-sm focus:outline-none focus:ring-2 focus:ring-green-500">
          {statusOptions.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        {services.length > 0 && (
          <select value={serviceFilter} onChange={e => setServiceFilter(e.target.value)}
            className="px-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white text-sm focus:outline-none focus:ring-2 focus:ring-green-500">
            <option value="">All Services</option>
            {services.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        )}
        {(statusFilter || serviceFilter || search) && (
          <button onClick={() => { setStatusFilter(''); setServiceFilter(''); setSearch('') }}
            className="px-3 py-2 text-xs text-slate-400 hover:text-white bg-slate-800 rounded-lg border border-slate-700">
            Clear filters
          </button>
        )}
      </div>

      {/* Task List */}
      {view === 'table' ? (
        <div className="bg-slate-800/80 rounded-2xl border border-slate-700/50 overflow-hidden backdrop-blur-sm">
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-700/50 bg-slate-800/50">
                <th className="px-5 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">Task</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">Status</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">Priority</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">GPU</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">Memory</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">Service</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">Runtime</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">Created</th>
                <th className="px-5 py-3 text-right text-xs font-medium text-slate-400 uppercase tracking-wider">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/30">
              {isLoading ? (
                <tr><td colSpan={9} className="px-5 py-12 text-center text-slate-400">Loading...</td></tr>
              ) : filtered.length === 0 ? (
                <tr><td colSpan={9} className="px-5 py-12 text-center text-slate-400">No tasks found</td></tr>
              ) : filtered.map(task => (
                <tr key={task.id} className="hover:bg-slate-700/30 transition-colors group">
                  <td className="px-5 py-3.5">
                    <Link to={`/tasks/${task.id}`} className="text-white hover:text-green-400 font-medium">
                      {task.name || task.id.slice(0, 12)}
                    </Link>
                    <p className="text-xs text-slate-500 font-mono mt-0.5">{task.id.slice(0, 12)}</p>
                  </td>
                  <td className="px-5 py-3.5">
                    <span className={clsx(
                      'px-2.5 py-1 text-xs font-medium rounded-full',
                      task.status === 'completed' ? 'bg-green-500/20 text-green-400' :
                      task.status === 'failed' ? 'bg-red-500/20 text-red-400' :
                      task.status === 'running' ? 'bg-blue-500/20 text-blue-400 animate-pulse' :
                      task.status === 'pending' ? 'bg-yellow-500/20 text-yellow-400' :
                      task.status === 'queued' ? 'bg-cyan-500/20 text-cyan-400' :
                      task.status === 'scheduled' ? 'bg-purple-500/20 text-purple-400' :
                      task.status === 'cancelled' ? 'bg-slate-500/20 text-slate-400' :
                      task.status === 'timeout' ? 'bg-orange-500/20 text-orange-400' :
                      'bg-slate-600/20 text-slate-400'
                    )}>
                      {task.status}
                    </span>
                  </td>
                  <td className="px-5 py-3.5">
                    <span className={clsx(
                      'text-sm font-bold',
                      task.priority >= 100 ? 'text-red-400' :
                      task.priority >= 50 ? 'text-yellow-400' :
                      'text-slate-300'
                    )}>
                      #{task.priority}
                    </span>
                  </td>
                  <td className="px-5 py-3.5">
                    {task.gpu_device_id != null ? (
                      <Link to={`/gpus/${task.gpu_device_id}`} className="text-blue-400 hover:text-blue-300 text-sm">
                        GPU {task.gpu_device_id}
                      </Link>
                    ) : <span className="text-slate-500 text-sm">—</span>}
                  </td>
                  <td className="px-5 py-3.5 text-sm text-slate-300">
                    {task.gpu_memory_mb > 0 ? `${Math.round(task.gpu_memory_mb / 1024)}GB` : '—'}
                  </td>
                  <td className="px-5 py-3.5">
                    {task.service_name ? (
                      <span className="text-xs bg-purple-500/20 text-purple-300 px-2 py-0.5 rounded-full">
                        {task.service_name}
                      </span>
                    ) : <span className="text-slate-500 text-sm">—</span>}
                  </td>
                  <td className="px-5 py-3.5 text-sm text-slate-300">
                    {task.execution_time_ms ? `${(task.execution_time_ms / 1000).toFixed(1)}s` : '—'}
                  </td>
                  <td className="px-5 py-3.5 text-sm text-slate-400">
                    {new Date(task.created_at).toLocaleString()}
                  </td>
                  <td className="px-5 py-3.5">
                    <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      {task.status === 'running' || task.status === 'pending' || task.status === 'queued' ? (
                        <button onClick={() => cancelMutation.mutate(task.id)}
                          className="p-1.5 text-slate-400 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors"
                          title="Cancel">
                          <X className="w-4 h-4" />
                        </button>
                      ) : task.status === 'failed' ? (
                        <button onClick={() => retryMutation.mutate(task.id)}
                          className="p-1.5 text-slate-400 hover:text-green-400 hover:bg-green-500/10 rounded-lg transition-colors"
                          title="Retry">
                          <RotateCcw className="w-4 h-4" />
                        </button>
                      ) : null}
                      <Link to={`/tasks/${task.id}`}
                        className="p-1.5 text-slate-400 hover:text-white hover:bg-slate-600 rounded-lg transition-colors"
                        title="View details">
                        <Eye className="w-4 h-4" />
                      </Link>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {filtered.map(task => (
            <div key={task.id} className="bg-slate-800/80 rounded-2xl border border-slate-700/50 p-5 backdrop-blur-sm hover:border-slate-600 transition-all">
              <div className="flex items-center justify-between mb-3">
                <Link to={`/tasks/${task.id}`} className="text-white font-medium hover:text-green-400 truncate">
                  {task.name || task.id.slice(0, 12)}
                </Link>
                <span className={clsx(
                  'px-2 py-0.5 text-xs font-medium rounded-full flex-shrink-0',
                  task.status === 'completed' ? 'bg-green-500/20 text-green-400' :
                  task.status === 'failed' ? 'bg-red-500/20 text-red-400' :
                  task.status === 'running' ? 'bg-blue-500/20 text-blue-400' :
                  task.status === 'pending' ? 'bg-yellow-500/20 text-yellow-400' :
                  'bg-slate-600/20 text-slate-400'
                )}>
                  {task.status}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs mb-3">
                <div className="bg-slate-900/50 rounded-lg p-2">
                  <p className="text-slate-500">GPU</p>
                  <p className="text-white font-medium">{task.gpu_device_id ?? '—'}</p>
                </div>
                <div className="bg-slate-900/50 rounded-lg p-2">
                  <p className="text-slate-500">Priority</p>
                  <p className="text-white font-medium">#{task.priority}</p>
                </div>
                <div className="bg-slate-900/50 rounded-lg p-2">
                  <p className="text-slate-500">Memory</p>
                  <p className="text-white font-medium">{task.gpu_memory_mb > 0 ? `${Math.round(task.gpu_memory_mb / 1024)}GB` : '—'}</p>
                </div>
                <div className="bg-slate-900/50 rounded-lg p-2">
                  <p className="text-slate-500">Runtime</p>
                  <p className="text-white font-medium">{task.execution_time_ms ? `${(task.execution_time_ms / 1000).toFixed(1)}s` : '—'}</p>
                </div>
              </div>
              {task.service_name && (
                <span className="text-xs bg-purple-500/20 text-purple-300 px-2 py-0.5 rounded-full">
                  {task.service_name}
                </span>
              )}
              {task.error && (
                <p className="text-xs text-red-400 mt-2 truncate">{task.error}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
