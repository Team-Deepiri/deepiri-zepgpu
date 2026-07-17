import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Activity, ExternalLink } from 'lucide-react'
import { tasksApi } from '@/api/client'
import { nodeTasksApi } from '@/api/nodeTasks'
import { AssignmentStatusBadge, TaskStatusBadge } from '@/components/tasks/StatusBadges'
import { isTerminalTaskStatus, shouldPollTask } from '@/utils/taskStatus'
import type { NodeTaskResult } from '@/types'

interface RoomActivityLogProps {
  roomId: string
  taskIds: string[]
}

export default function RoomActivityLog({ roomId, taskIds }: RoomActivityLogProps) {
  return (
    <section className="rounded-xl border border-slate-700/80 bg-slate-800/40 p-5">
      <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2 mb-4">
        <Activity className="w-4 h-4 text-sky-400" />
        Session activity
      </h2>

      {taskIds.length === 0 ? (
        <p className="text-slate-500 text-sm">
          Dispatched tasks appear here with live status until they finish.
        </p>
      ) : (
        <ul className="space-y-3">
          {taskIds.map((taskId) => (
            <ActivityRow key={taskId} roomId={roomId} taskId={taskId} />
          ))}
        </ul>
      )}
    </section>
  )
}

function ActivityRow({ roomId, taskId }: { roomId: string; taskId: string }) {
  const taskQuery = useQuery({
    queryKey: ['task', taskId],
    queryFn: () => tasksApi.get(taskId),
    refetchInterval: (query) => (shouldPollTask(query.state.data) ? 3000 : false),
  })

  const task = taskQuery.data
  const assignmentId = task?.assignment?.assignment_id
  const canFetchResult =
    !!assignmentId &&
    !!task &&
    isTerminalTaskStatus(task.status) &&
    task.dispatch_mode !== 'local'

  const resultQuery = useQuery({
    queryKey: ['node-task-result', assignmentId],
    queryFn: () => nodeTasksApi.getResult(assignmentId!),
    enabled: canFetchResult,
  })

  if (taskQuery.isLoading) {
    return (
      <li className="border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-slate-500">
        Loading {taskId.slice(0, 8)}…
      </li>
    )
  }

  if (taskQuery.isError || !task) {
    return (
      <li className="border border-red-800/40 rounded-lg px-3 py-2 text-sm text-red-400">
        Failed to load task {taskId.slice(0, 8)}…
      </li>
    )
  }

  if (task.room_id && task.room_id !== roomId) {
    return null
  }

  return (
    <li className="border border-slate-700/50 rounded-lg px-3 py-3 space-y-2">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-slate-200 text-sm font-medium truncate">
            {task.name || task.id}
          </p>
          <p className="text-slate-500 text-xs mt-0.5">
            {task.dispatch_mode ?? 'local'}
            {task.assignment?.peer_id && (
              <> · peer {task.assignment.peer_id.slice(0, 8)}…</>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <TaskStatusBadge status={task.status} />
          <Link
            to={`/tasks/${task.id}`}
            className="inline-flex items-center gap-1 text-xs text-cyan-400 hover:text-cyan-300"
          >
            Details
            <ExternalLink className="w-3 h-3" />
          </Link>
        </div>
      </div>

      {task.assignment && (
        <div className="flex items-center gap-2 text-xs text-slate-400">
          Assignment:{' '}
          <AssignmentStatusBadge status={task.assignment.status} />
        </div>
      )}

      {task.error && (
        <p className="text-xs text-red-400 truncate" title={task.error}>
          {task.error}
        </p>
      )}

      {canFetchResult && resultQuery.isLoading && (
        <p className="text-xs text-slate-500">Loading remote result…</p>
      )}

      {resultQuery.data && <RemoteResultSummary result={resultQuery.data} />}
    </li>
  )
}

function RemoteResultSummary({ result }: { result: NodeTaskResult }) {
  const metadataKeys = Object.keys(result.result_metadata ?? {})

  return (
    <div className="rounded-lg bg-slate-900/60 border border-slate-700/50 px-3 py-2 text-xs space-y-1">
      <p className="text-slate-400">
        Remote result · assignment {result.assignment_status}
      </p>
      {result.result_ref && (
        <p className="text-slate-300 font-mono truncate">ref: {result.result_ref}</p>
      )}
      {result.result_size_bytes != null && (
        <p className="text-slate-400">{result.result_size_bytes} bytes</p>
      )}
      {metadataKeys.length > 0 && (
        <pre className="text-slate-300 whitespace-pre-wrap break-all">
          {JSON.stringify(result.result_metadata, null, 2)}
        </pre>
      )}
      {result.error && <p className="text-red-400">{result.error}</p>}
    </div>
  )
}
