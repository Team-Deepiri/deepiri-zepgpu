/**
 * Room API client — calls /api/v1/rooms/* via the shared axios instance in client.ts.
 *
 * Coordination Doc / Phase 1 Work endpoint map:
 * | Function           | Method | Path                                      |
 * |--------------------|--------|-------------------------------------------|
 * | createRoom         | POST   | /api/v1/rooms                             |
 * | listRooms          | GET    | /api/v1/rooms                             |
 * | getRoom            | GET    | /api/v1/rooms/{room_id}                   |
 * | deleteRoom         | DELETE | /api/v1/rooms/{room_id}        → 204     |
 * | getRoomMembers     | GET    | /api/v1/rooms/{room_id}/members           |
 * | getRoomGpuPool     | GET    | /api/v1/rooms/{room_id}/gpu-pool          |
 * | createRoomInvite   | POST   | /api/v1/rooms/{room_id}/invites           |
 * | listRoomInvites    | GET    | /api/v1/rooms/{room_id}/invites           |
 * | revokeRoomInvite   | DELETE | /api/v1/rooms/{room_id}/invites/{invite_id} → 204 |
 * | joinRoom           | POST   | /api/v1/rooms/join                        |
 * | getRoomConfig      | GET    | /api/v1/rooms/{room_id}/config           |
 */
import api from '@/api/client'
import type {
  Room,
  RoomCreateRequest,
  RoomMember,
  RoomGpuPoolSummary,
  RoomInvite,
  RoomInviteCreateRequest,
  RoomJoinRequest,
  RoomJoinResponse,
  RoomConnectionConfig,
} from '@/types'

export const roomsApi = {
  createRoom: async (req: RoomCreateRequest): Promise<Room> => {
    const { data } = await api.post<Room>('/rooms', req)
    return data
  },

  listRooms: async (): Promise<Room[]> => {
    const { data } = await api.get<Room[]>('/rooms')
    return data
  },

  getRoom: async (roomId: string): Promise<Room> => {
    const { data } = await api.get<Room>(`/rooms/${roomId}`)
    return data
  },

  deleteRoom: async (roomId: string): Promise<void> => {
    await api.delete(`/rooms/${roomId}`)
  },

  getRoomMembers: async (roomId: string): Promise<RoomMember[]> => {
    const { data } = await api.get<RoomMember[]>(`/rooms/${roomId}/members`)
    return data
  },

  getRoomGpuPool: async (roomId: string): Promise<RoomGpuPoolSummary> => {
    const { data } = await api.get<RoomGpuPoolSummary>(`/rooms/${roomId}/gpu-pool`)
    return data
  },

  createRoomInvite: async (roomId: string, req: RoomInviteCreateRequest): Promise<RoomInvite> => {
    const { data } = await api.post<RoomInvite>(`/rooms/${roomId}/invites`, req)
    return data
  },

  listRoomInvites: async (roomId: string): Promise<RoomInvite[]> => {
    const { data } = await api.get<RoomInvite[]>(`/rooms/${roomId}/invites`)
    return data
  },

  revokeRoomInvite: async (roomId: string, inviteId: string): Promise<void> => {
    await api.delete(`/rooms/${roomId}/invites/${inviteId}`)
  },

  joinRoom: async (req: RoomJoinRequest): Promise<RoomJoinResponse> => {
    const { data } = await api.post<RoomJoinResponse>('/rooms/join', req)
    return data
  },

  getRoomConfig: async (roomId: string): Promise<RoomConnectionConfig> => {
    const { data } = await api.get<RoomConnectionConfig>(`/rooms/${roomId}/config`)
    return data
  },
}
