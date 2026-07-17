import type { NodeTaskResult, Task } from '@/types'
import { fixtureRoom, fixtureRoomNode } from '@/test/fixtures/rooms'

export const fixtureRoomTaskAssignment = {
  assignment_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  room_id: fixtureRoom.id,
  peer_id: fixtureRoomNode.id,
  gpu_share_id: '77777777-7777-4777-8777-777777777777',
  status: 'assigned' as const,
}

export const fixtureDispatchedTask: Task = {
  id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  name: 'Room smoke task',
  status: 'assigned',
  priority: 2,
  gpu_memory_mb: 1024,
  timeout_seconds: 3600,
  gpu_type: null,
  gpu_device_id: null,
  created_at: '2026-06-01T13:00:00.000Z',
  started_at: null,
  completed_at: null,
  error: null,
  execution_time_ms: null,
  user_id: '11111111-1111-4111-8111-111111111111',
  namespace_id: null,
  service_name: null,
  tags: [],
  metadata: {},
  result_url: null,
  room_id: fixtureRoom.id,
  dispatch_mode: 'room_auto',
  target_peer_id: null,
  target_gpu_share_id: null,
  assignment: fixtureRoomTaskAssignment,
}

export const fixtureCompletedRoomTask: Task = {
  ...fixtureDispatchedTask,
  status: 'completed',
  completed_at: '2026-06-01T13:05:00.000Z',
  execution_time_ms: 1200,
  assignment: {
    ...fixtureRoomTaskAssignment,
    status: 'completed',
  },
}

export const fixtureNodeTaskResult: NodeTaskResult = {
  assignment_id: fixtureRoomTaskAssignment.assignment_id,
  task_id: fixtureDispatchedTask.id,
  status: 'completed',
  assignment_status: 'completed',
  result_metadata: { remote_result: { ok: true } },
  result_ref: 's3://bucket/result.bin',
  result_size_bytes: 4096,
  error: null,
}
