/**
 * Room API client — calls /api/v1/rooms/* via the shared axios instance in client.ts.
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
  RoomNode,
  RoomNodeGpu,
  RoomDispatchRequest,
  Task,
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

  getRoomNodes: async (roomId: string): Promise<RoomNode[]> => {
    const { data } = await api.get<RoomNode[]>(`/rooms/${roomId}/nodes`)
    return data
  },

  getRoomNode: async (roomId: string, peerId: string): Promise<RoomNode> => {
    const { data } = await api.get<RoomNode>(`/rooms/${roomId}/nodes/${peerId}`)
    return data
  },

  getRoomNodeGpus: async (roomId: string, peerId: string): Promise<RoomNodeGpu[]> => {
    const { data } = await api.get<RoomNodeGpu[]>(`/rooms/${roomId}/nodes/${peerId}/gpus`)
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

  dispatchTask: async (req: RoomDispatchRequest): Promise<Task> => {
    const { data } = await api.post<Task>('/tasks', req)
    return data
  },
}
