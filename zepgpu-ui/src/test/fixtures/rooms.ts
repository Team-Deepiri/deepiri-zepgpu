import type {
  Room,
  RoomMember,
  RoomGpuPoolSummary,
  RoomInvite,
  RoomConnectionConfig,
  RoomNode,
  RoomNodeGpu,
} from '@/types'

export const fixtureRoom: Room = {
  id: '22222222-2222-4222-8222-222222222222',
  name: 'Team Alpha',
  description: 'Test room',
  host_id: '11111111-1111-4111-8111-111111111111',
  status: 'active',
  transport_mode: 'dialout',
  transport_experimental: false,
  requires_wireguard_udp: false,
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
  providers: ['nvidia'],
}

export const fixtureGpuPoolOffline: RoomGpuPoolSummary = {
  room_id: fixtureRoom.id,
  total_gpus: 4,
  available_gpus: 0,
  allocated_gpus: 2,
  total_memory_mb: 98304,
  available_memory_mb: 0,
  providers: ['nvidia'],
}

export const fixtureInvite: RoomInvite = {
  id: '55555555-5555-4555-8555-555555555555',
  room_id: fixtureRoom.id,
  code: 'TEAMALPHA',
  created_by: '11111111-1111-4111-8111-111111111111',
  expires_at: '2027-01-01T00:00:00.000Z',
  max_uses: 10,
  use_count: 1,
  is_revoked: false,
  created_at: '2026-06-01T12:10:00.000Z',
  coordinator_url: 'https://coordinator.example',
  join_command:
    'zepgpu-node join --invite TEAMALPHA --coordinator https://coordinator.example',
}

export const fixtureConfig: RoomConnectionConfig = {
  room_id: fixtureRoom.id,
  peer_id: '33333333-3333-4333-8333-333333333333',
  filename: 'room-test.conf',
  config: '[Interface]\nPrivateKey = TEST\n',
  transport_mode: 'wireguard',
  requires_wireguard_udp: true,
}

export const fixtureRoomNode: RoomNode = {
  id: '33333333-3333-4333-8333-333333333333',
  room_id: fixtureRoom.id,
  user_id: '11111111-1111-4111-8111-111111111111',
  username: 'host-user',
  vpn_ip: '10.8.0.2',
  status: 'connected',
  is_gpu_host: true,
  is_online: true,
  last_seen: '2026-06-01T12:30:00.000Z',
  gpu_count: 2,
  available_gpu_count: 1,
  total_memory_mb: 49152,
  available_memory_mb: 24576,
  health_state: 'healthy',
  health_reason: 'Provider is online with fresh heartbeat',
  capabilities: {
    gpu_count: 2,
    cuda_version: '12.4',
    pytorch_version: '2.4.0',
    driver_version: '550.54.15',
  },
  path: {
    path_type: 'direct',
    path_class: 'wan',
    coordinator_rtt_ms: 42.5,
    measurement_kind: 'measured',
    freshness_at: '2026-06-01T12:30:00.000Z',
    is_measured: true,
  },
}

export const fixtureRoomNodeAwol: RoomNode = {
  ...fixtureRoomNode,
  id: '44444444-4444-4444-8444-444444444444',
  username: 'awol-user',
  vpn_ip: '10.8.0.3',
  status: 'awol',
  is_online: false,
  gpu_count: 1,
  available_gpu_count: 0,
  available_memory_mb: 0,
}

export const fixtureRoomNodeDisconnected: RoomNode = {
  ...fixtureRoomNode,
  id: '66666666-6666-4666-8666-666666666666',
  username: 'offline-user',
  vpn_ip: '10.8.0.4',
  status: 'disconnected',
  is_online: false,
  is_gpu_host: false,
  gpu_count: 0,
  available_gpu_count: 0,
  total_memory_mb: 0,
  available_memory_mb: 0,
}

export const fixtureRoomNodeGpu: RoomNodeGpu = {
  id: '77777777-7777-4777-8777-777777777777',
  peer_id: fixtureRoomNode.id,
  room_id: fixtureRoom.id,
  device_index: 0,
  name: 'NVIDIA RTX 4090',
  total_memory_mb: 24576,
  available_memory_mb: 18000,
  compute_capability: '8.9',
  gpu_type: 'nvidia',
  state: 'idle',
  utilization_percent: 12.5,
  is_active: true,
  last_updated: '2026-06-01T12:30:00.000Z',
}
