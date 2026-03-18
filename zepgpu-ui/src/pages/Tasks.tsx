import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { tasksApi } from '@/api/client'
import { Plus, Search, X } from 'lucide-react'
import clsx from 'clsx'
import toast from 'react-hot-toast'

export default function Tasks() {
  const [statusFilter, setStatusFilter] = useState<string>('')
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['tasks', { status: statusFilter }],
    queryFn: () => tasksApi.list({ status: statusFilter || undefined }),
  })

  const cancelMutation = useMutation({
    mutationFn: tasksApi.cancel,
    onSuccess: () => {
      toast.success('Task cancelled')
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
    onError: () => {
      toast.error('Failed to cancel task')
    },
  })

  const statusOptions = [
    { value: '', label: 'All' },
    { value: 'pending', label: 'Pending' },
    { value: 'running', label: 'Running' },
    { value: 'completed', label: 'Completed' },
    { value: 'failed', label: 'Failed' },
    { value: 'cancelled', label: 'Cancelled' },
  ]

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white">Tasks</h1>
          <p className="text-slate-400 mt-1">Manage your GPU compute tasks</p>
        </div>
        <Link
          to="/tasks/new"
          className="flex items-center gap-2 px-4 py-2 bg-zepgpu-500 hover:bg-zepgpu-600 text-white rounded-lg font-medium transition-colors"
        >
          <Plus className="w-4 h-4" />
          New Task
        </Link>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-4">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <input
            type="text"
            placeholder="Search tasks..."
            className="w-full pl-10 pr-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-zepgpu-500"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="px-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-zepgpu-500"
        >
          {statusOptions.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      </div>

      {/* Tasks List */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-slate-700">
              <th className="px-6 py-3 text-left text-xs font-medium text-slate-400 uppercase">Name</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-slate-400 uppercase">Status</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-slate-400 uppercase">Priority</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-slate-400 uppercase">GPU</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-slate-400 uppercase">Created</th>
              <th className="px-6 py-3 text-right text-xs font-medium text-slate-400 uppercase">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700">
            {isLoading ? (
              <tr>
                <td colSpan={6} className="px-6 py-8 text-center text-slate-400">Loading...</td>
              </tr>
            ) : data?.tasks.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-6 py-8 text-center text-slate-400">No tasks found</td>
              </tr>
            ) : (
              data?.tasks.map((task) => (
                <tr key={task.id} className="hover:bg-slate-700/50">
                  <td className="px-6 py-4">
                    <Link to={`/tasks/${task.id}`} className="text-white hover:text-zepgpu-400 font-medium">
                      {task.name || task.id.slice(0, 8)}
                    </Link>
                  </td>
                  <td className="px-6 py-4">
                    <span className={clsx(
                      'px-2 py-1 text-xs font-medium rounded-full',
                      task.status === 'completed' ? 'bg-green-500/20 text-green-400' :
                      task.status === 'failed' ? 'bg-red-500/20 text-red-400' :
                      task.status === 'running' ? 'bg-blue-500/20 text-blue-400' :
                      task.status === 'pending' ? 'bg-yellow-500/20 text-yellow-400' :
                      'bg-slate-600/50 text-slate-300'
                    )}>
                      {task.status}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-slate-300">{task.priority}</td>
                  <td className="px-6 py-4 text-slate-300">
                    {task.gpu_device_id !== null ? `GPU ${task.gpu_device_id}` : '-'}
                  </td>
                  <td className="px-6 py-4 text-slate-400 text-sm">
                    {new Date(task.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-6 py-4 text-right">
                    {task.status !== 'completed' && task.status !== 'failed' && task.status !== 'cancelled' && (
                      <button
                        onClick={() => cancelMutation.mutate(task.id)}
                        className="p-1 text-slate-400 hover:text-red-400 transition-colors"
                        title="Cancel task"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
