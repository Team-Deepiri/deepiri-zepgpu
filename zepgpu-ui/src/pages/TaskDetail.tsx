import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { tasksApi } from '@/api/client'
import { ArrowLeft, Clock, Cpu, AlertCircle, CheckCircle2 } from 'lucide-react'
import clsx from 'clsx'

export default function TaskDetail() {
  const { id } = useParams<{ id: string }>()

  const { data: task, isLoading } = useQuery({
    queryKey: ['task', id],
    queryFn: () => tasksApi.get(id!),
    refetchInterval: (query) => 
      query.state.data?.status === 'pending' || query.state.data?.status === 'running' ? 2000 : false,
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-zepgpu-500" />
      </div>
    )
  }

  if (!task) {
    return (
      <div className="text-center py-12">
        <AlertCircle className="w-12 h-12 text-red-400 mx-auto mb-4" />
        <h2 className="text-xl font-semibold text-white">Task not found</h2>
        <Link to="/tasks" className="text-zepgpu-400 hover:text-zepgpu-300 mt-2 inline-block">
          Back to tasks
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <Link to="/tasks" className="inline-flex items-center gap-2 text-slate-400 hover:text-white transition-colors">
        <ArrowLeft className="w-4 h-4" />
        Back to tasks
      </Link>

      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white">{task.name || task.id}</h1>
          <p className="text-slate-400 mt-1">Task ID: {task.id}</p>
        </div>
        <span className={clsx(
          'px-4 py-2 text-sm font-medium rounded-full',
          task.status === 'completed' ? 'bg-green-500/20 text-green-400' :
          task.status === 'failed' ? 'bg-red-500/20 text-red-400' :
          task.status === 'running' ? 'bg-blue-500/20 text-blue-400' :
          task.status === 'pending' ? 'bg-yellow-500/20 text-yellow-400' :
          'bg-slate-600/50 text-slate-300'
        )}>
          {task.status}
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-slate-800 rounded-xl p-6 border border-slate-700">
          <div className="flex items-center gap-3 mb-4">
            <Clock className="w-5 h-5 text-zepgpu-400" />
            <span className="text-slate-400">Priority</span>
          </div>
          <p className="text-2xl font-bold text-white">{task.priority}</p>
        </div>

        <div className="bg-slate-800 rounded-xl p-6 border border-slate-700">
          <div className="flex items-center gap-3 mb-4">
            <Cpu className="w-5 h-5 text-zepgpu-400" />
            <span className="text-slate-400">GPU Device</span>
          </div>
          <p className="text-2xl font-bold text-white">
            {task.gpu_device_id !== null ? `GPU ${task.gpu_device_id}` : '-'}
          </p>
        </div>

        <div className="bg-slate-800 rounded-xl p-6 border border-slate-700">
          <div className="flex items-center gap-3 mb-4">
            <CheckCircle2 className="w-5 h-5 text-zepgpu-400" />
            <span className="text-slate-400">Execution Time</span>
          </div>
          <p className="text-2xl font-bold text-white">
            {task.execution_time_ms ? `${(task.execution_time_ms / 1000).toFixed(2)}s` : '-'}
          </p>
        </div>
      </div>

      {task.error && (
        <div className="bg-red-500/10 border border-red-500/50 rounded-xl p-6">
          <h3 className="text-lg font-semibold text-red-400 mb-2 flex items-center gap-2">
            <AlertCircle className="w-5 h-5" />
            Error
          </h3>
          <pre className="text-sm text-red-300 whitespace-pre-wrap">{task.error}</pre>
        </div>
      )}

      <div className="bg-slate-800 rounded-xl border border-slate-700">
        <div className="px-6 py-4 border-b border-slate-700">
          <h2 className="text-lg font-semibold text-white">Task Details</h2>
        </div>
        <div className="p-6 space-y-4">
          <div className="grid grid-cols-2 gap-6">
            <div>
              <p className="text-sm text-slate-400">GPU Memory</p>
              <p className="text-white">{task.gpu_memory_mb} MB</p>
            </div>
            <div>
              <p className="text-sm text-slate-400">Timeout</p>
              <p className="text-white">{task.timeout_seconds}s</p>
            </div>
            <div>
              <p className="text-sm text-slate-400">Created At</p>
              <p className="text-white">{new Date(task.created_at).toLocaleString()}</p>
            </div>
            {task.started_at && (
              <div>
                <p className="text-sm text-slate-400">Started At</p>
                <p className="text-white">{new Date(task.started_at).toLocaleString()}</p>
              </div>
            )}
            {task.completed_at && (
              <div>
                <p className="text-sm text-slate-400">Completed At</p>
                <p className="text-white">{new Date(task.completed_at).toLocaleString()}</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
