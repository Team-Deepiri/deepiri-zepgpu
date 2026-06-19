import type {
  Room,
  RoomMember,
  RoomGpuPoolSummary,
  RoomInvite,
  RoomConnectionConfig,
} from '@/types'

export const fixtureRoom: Room = {
  id: '22222222-2222-4222-8222-222222222222',
  name: 'Team Alpha',
  description: 'Test room',
  host_id: '11111111-1111-4111-8111-111111111111',
  status: 'active',
  created_at: '2026-06-01T12:00:00.000Z',
  updated_at: null,
}

export const fixtureMember: RoomMember = {
  id: '33333333-3333-4333-8333-333333333333',
  user_id: '11111111-1111-4111-8111-111111111111',
  display_name: 'host-user',
  status: 'connected',
  joined_at: '2026-06-01T12:05:00.000Z',
  last_seen_at: '2026-06-01T12:30:00.000Z',
}

export const fixtureGpuPool: RoomGpuPoolSummary = {
  room_id: fixtureRoom.id,
  total_gpus: 4,
  available_gpus: 2,
  allocated_gpus: 2,
  total_memory_mb: 98304,
  available_memory_mb: 49152,
  providers: [{ id: 'gpu-1', name: 'RTX 4090' }],
}

export const fixtureInvite: RoomInvite = {
  id: '55555555-5555-4555-8555-555555555555',
  room_id: fixtureRoom.id,
  code: 'TEAMALPHA',
  created_by: fixtureRoom.host_id,
  expires_at: '2027-01-01T00:00:00.000Z',
  max_uses: 10,
  use_count: 1,
  is_revoked: false,
  created_at: '2026-06-01T12:10:00.000Z',
}

export const fixtureConfig: RoomConnectionConfig = {
  room_id: fixtureRoom.id,
  peer_id: '33333333-3333-4333-8333-333333333333',
  filename: 'room-test.conf',
  config: '[Interface]\nPrivateKey = TEST\n',
}
