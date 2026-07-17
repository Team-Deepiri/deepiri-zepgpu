import { http, HttpResponse } from 'msw'
import { fixtureRoom } from '@/test/fixtures/rooms'
import {
  fixtureCompletedRoomTask,
  fixtureDispatchedTask,
  fixtureNodeTaskResult,
} from '@/test/fixtures/tasks'
import type { DispatchMode, Task } from '@/types'

const tasksById = new Map<string, Task>([
  [fixtureDispatchedTask.id, fixtureDispatchedTask],
  [fixtureCompletedRoomTask.id, fixtureCompletedRoomTask],
])

export const taskHandlers = [
  http.post('/api/v1/tasks', async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>
    if (!body.func_name) {
      return HttpResponse.json({ detail: 'func_name required' }, { status: 422 })
    }
    if (body.dispatch_mode === 'room_specific_node' && !body.target_peer_id) {
      return HttpResponse.json({ detail: 'target_peer_id required' }, { status: 422 })
    }

    const created: Task = {
      ...fixtureDispatchedTask,
      id: `task-${Date.now()}`,
      name: (body.name as string | undefined) ?? fixtureDispatchedTask.name,
      dispatch_mode: ((body.dispatch_mode as DispatchMode | undefined) ?? 'room_auto'),
      room_id: (body.room_id as string | undefined) ?? fixtureRoom.id,
      target_peer_id: (body.target_peer_id as string | undefined) ?? null,
      target_gpu_share_id: (body.target_gpu_share_id as string | undefined) ?? null,
      created_at: new Date().toISOString(),
    }
    tasksById.set(created.id, created)
    return HttpResponse.json(created, { status: 201 })
  }),

  http.get('/api/v1/tasks/:taskId', ({ params }) => {
    const task = tasksById.get(String(params.taskId))
    if (!task) {
      return HttpResponse.json({ detail: 'Task not found' }, { status: 404 })
    }
    return HttpResponse.json(task)
  }),

  http.get('/api/v1/node-tasks/:assignmentId/result', ({ params }) => {
    if (params.assignmentId !== fixtureNodeTaskResult.assignment_id) {
      return HttpResponse.json({ detail: 'Assignment not found' }, { status: 404 })
    }
    return HttpResponse.json(fixtureNodeTaskResult)
  }),
]
