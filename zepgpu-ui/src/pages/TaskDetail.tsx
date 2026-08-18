import { useParams, Link } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { tasksApi } from '@/api/client'
import { nodeTasksApi } from '@/api/nodeTasks'
import { AssignmentStatusBadge, TaskStatusBadge } from '@/components/tasks/StatusBadges'
import { isActiveStatus } from '@/utils/taskStatus'
import { ArrowLeft, Clock, Cpu, AlertCircle, CheckCircle2, Home } from 'lucide-react'

export default function TaskDetail() {
  const { id } = useParams<{ id: string }>()

  const { data: task, isLoading } = useQuery({
    queryKey: ['task', id],
    queryFn: () => tasksApi.get(id!),
    refetchInterval: (query) => (isActiveStatus(query.state.data?.status) ? 2000 : false),
  })

  const assignmentId = task?.assignment?.assignment_id
  const isRoomDispatch = task?.dispatch_mode && task.dispatch_mode !== 'local'
  const canFetchRemoteResult =
    !!assignmentId &&
    !!task &&
    !isActiveStatus(task.status) &&
    isRoomDispatch

  const remoteResultQuery = useQuery({
    queryKey: ['node-task-result', assignmentId],
    queryFn: () => nodeTasksApi.getResult(assignmentId!),
    enabled: canFetchRemoteResult,
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

  const backHref = task.room_id ? `/rooms/${task.room_id}` : '/tasks'
  const backLabel = task.room_id ? 'Back to room' : 'Back to tasks'

  return (
    <div className="space-y-6">
      <Link
        to={backHref}
        className="inline-flex items-center gap-2 text-slate-400 hover:text-white transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        {backLabel}
      </Link>

      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white">{task.name || task.id}</h1>
          <p className="text-slate-400 mt-1">Task ID: {task.id}</p>
        </div>
        <TaskStatusBadge status={task.status} size="lg" />
      </div>

      {isRoomDispatch && (
        <div className="bg-slate-800 rounded-xl border border-slate-700 p-6 space-y-4">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <Home className="w-5 h-5 text-amber-400" />
            Room dispatch
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
            <div>
              <p className="text-slate-400">Dispatch mode</p>
              <p className="text-white">{task.dispatch_mode}</p>
            </div>
            {task.room_id && (
              <div>
                <p className="text-slate-400">Room</p>
                <Link to={`/rooms/${task.room_id}`} className="text-cyan-400 hover:text-cyan-300">
                  {task.room_id}
                </Link>
              </div>
            )}
            {task.target_peer_id && (
              <div>
                <p className="text-slate-400">Target peer</p>
                <p className="text-white font-mono text-xs">{task.target_peer_id}</p>
              </div>
            )}
            {task.target_gpu_share_id && (
              <div>
                <p className="text-slate-400">Target GPU share</p>
                <p className="text-white font-mono text-xs">{task.target_gpu_share_id}</p>
              </div>
            )}
          </div>

          {task.assignment && (
            <div className="rounded-lg border border-slate-700/80 bg-slate-900/40 p-4 space-y-2">
              <p className="text-sm font-medium text-slate-200">Assignment</p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
                <div>
                  <p className="text-slate-400">Assignment ID</p>
                  <p className="text-white font-mono text-xs">{task.assignment.assignment_id}</p>
                </div>
                <div>
                  <p className="text-slate-400">Status</p>
                  <AssignmentStatusBadge status={task.assignment.status} />
                </div>
                <div>
                  <p className="text-slate-400">Peer</p>
                  <p className="text-white font-mono text-xs">{task.assignment.peer_id || '—'}</p>
                </div>
                <div>
                  <p className="text-slate-400">GPU share</p>
                  <p className="text-white font-mono text-xs">{task.assignment.gpu_share_id || '—'}</p>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

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
            {task.gpu_device_id != null ? `GPU ${task.gpu_device_id}` : '-'}
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

      {canFetchRemoteResult && (
        <div className="bg-slate-800 rounded-xl border border-slate-700">
          <div className="px-6 py-4 border-b border-slate-700">
            <h2 className="text-lg font-semibold text-white">Remote result</h2>
          </div>
          <div className="p-6">
            {remoteResultQuery.isLoading ? (
              <p className="text-slate-400 text-sm">Loading remote result…</p>
            ) : remoteResultQuery.isError ? (
              <p className="text-red-400 text-sm">Failed to load remote result.</p>
            ) : remoteResultQuery.data ? (
              <div className="space-y-3 text-sm">
                <p className="text-slate-400">
                  Assignment status:{' '}
                  <span className="text-white">{remoteResultQuery.data.assignment_status}</span>
                </p>
                {remoteResultQuery.data.result_ref && (
                  <p className="text-slate-300 font-mono break-all">
                    ref: {remoteResultQuery.data.result_ref}
                  </p>
                )}
                {remoteResultQuery.data.result_size_bytes != null && (
                  <p className="text-slate-400">
                    Size: {remoteResultQuery.data.result_size_bytes} bytes
                  </p>
                )}
                {Object.keys(remoteResultQuery.data.result_metadata ?? {}).length > 0 && (
                  <pre className="text-slate-300 whitespace-pre-wrap break-all bg-slate-900/60 rounded-lg p-4 border border-slate-700">
                    {JSON.stringify(remoteResultQuery.data.result_metadata, null, 2)}
                  </pre>
                )}
                {remoteResultQuery.data.error && (
                  <p className="text-red-400">{remoteResultQuery.data.error}</p>
                )}
              </div>
            ) : null}
          </div>
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
