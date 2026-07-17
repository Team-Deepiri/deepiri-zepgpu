import { http, HttpResponse } from 'msw'
import {
  fixtureConfig,
  fixtureGpuPool,
  fixtureInvite,
  fixtureMember,
  fixtureRoom,
  fixtureRoomNode,
  fixtureRoomNodeAwol,
  fixtureRoomNodeDisconnected,
  fixtureRoomNodeGpu,
} from '@/test/fixtures/rooms'

const rooms = [fixtureRoom]
const invites = [fixtureInvite]
const nodes = [fixtureRoomNode, fixtureRoomNodeAwol, fixtureRoomNodeDisconnected]

export const roomHandlers = [
  http.get('/api/v1/rooms', () => HttpResponse.json(rooms)),

  http.post('/api/v1/rooms', async ({ request }) => {
    const body = (await request.json()) as { name: string; description?: string | null }
    const created = {
      ...fixtureRoom,
      id: '99999999-9999-4999-8999-999999999999',
      name: body.name,
      description: body.description ?? null,
      created_at: new Date().toISOString(),
    }
    rooms.unshift(created)
    return HttpResponse.json(created, { status: 201 })
  }),

  http.get('/api/v1/rooms/:roomId', ({ params }) => {
    const room = rooms.find((r) => r.id === params.roomId)
    if (!room) {
      return HttpResponse.json({ detail: 'Room not found' }, { status: 404 })
    }
    return HttpResponse.json(room)
  }),

  http.delete('/api/v1/rooms/:roomId', ({ params }) => {
    const index = rooms.findIndex((r) => r.id === params.roomId)
    if (index === -1) {
      return HttpResponse.json({ detail: 'Room not found' }, { status: 404 })
    }
    rooms.splice(index, 1)
    return new HttpResponse(null, { status: 204 })
  }),

  http.get('/api/v1/rooms/:roomId/members', ({ params }) => {
    if (params.roomId !== fixtureRoom.id) {
      return HttpResponse.json({ detail: 'Room not found' }, { status: 404 })
    }
    return HttpResponse.json([fixtureMember])
  }),

  http.get('/api/v1/rooms/:roomId/gpu-pool', ({ params }) => {
    if (params.roomId !== fixtureRoom.id) {
      return HttpResponse.json({ detail: 'Room not found' }, { status: 404 })
    }
    return HttpResponse.json(fixtureGpuPool)
  }),

  http.get('/api/v1/rooms/:roomId/nodes', ({ params }) => {
    if (params.roomId !== fixtureRoom.id) {
      return HttpResponse.json({ detail: 'Room not found' }, { status: 404 })
    }
    return HttpResponse.json(nodes)
  }),

  http.get('/api/v1/rooms/:roomId/nodes/:peerId', ({ params }) => {
    if (params.roomId !== fixtureRoom.id) {
      return HttpResponse.json({ detail: 'Room not found' }, { status: 404 })
    }
    const node = nodes.find((n) => n.id === params.peerId)
    if (!node) {
      return HttpResponse.json({ detail: 'Node not found' }, { status: 404 })
    }
    return HttpResponse.json(node)
  }),

  http.get('/api/v1/rooms/:roomId/gpus', ({ params }) => {
    if (params.roomId !== fixtureRoom.id) {
      return HttpResponse.json({ detail: 'Room not found' }, { status: 404 })
    }
    return HttpResponse.json([fixtureRoomNodeGpu])
  }),

  http.get('/api/v1/rooms/:roomId/nodes/:peerId/gpus', ({ params }) => {
    if (params.roomId !== fixtureRoom.id) {
      return HttpResponse.json({ detail: 'Room not found' }, { status: 404 })
    }
    const node = nodes.find((n) => n.id === params.peerId)
    if (!node) {
      return HttpResponse.json({ detail: 'Node not found' }, { status: 404 })
    }
    if (node.status !== 'connected' || node.gpu_count === 0) {
      return HttpResponse.json([])
    }
    return HttpResponse.json([fixtureRoomNodeGpu])
  }),

  http.get('/api/v1/rooms/:roomId/invites', ({ params }) => {
    if (params.roomId !== fixtureRoom.id) {
      return HttpResponse.json({ detail: 'Room not found' }, { status: 404 })
    }
    return HttpResponse.json(invites.filter((i) => !i.is_revoked))
  }),

  http.post('/api/v1/rooms/:roomId/invites', async ({ params, request }) => {
    if (params.roomId !== fixtureRoom.id) {
      return HttpResponse.json({ detail: 'Room not found' }, { status: 404 })
    }
    const body = (await request.json()) as { max_uses: number; expires_at: string | null }
    const invite = {
      ...fixtureInvite,
      id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      code: 'NEWCODE1',
      max_uses: body.max_uses,
      expires_at: body.expires_at,
      use_count: 0,
      created_at: new Date().toISOString(),
    }
    invites.unshift(invite)
    return HttpResponse.json(invite, { status: 201 })
  }),

  http.delete('/api/v1/rooms/:roomId/invites/:inviteId', ({ params }) => {
    const invite = invites.find((i) => i.id === params.inviteId)
    if (!invite) {
      return HttpResponse.json({ detail: 'Room not found' }, { status: 404 })
    }
    invite.is_revoked = true
    return new HttpResponse(null, { status: 204 })
  }),

  http.post('/api/v1/rooms/join', async ({ request }) => {
    const body = (await request.json()) as { invite_code: string }
    if (body.invite_code === 'EXPIRED1') {
      return HttpResponse.json({ detail: 'Invite has expired' }, { status: 410 })
    }
    if (body.invite_code === 'REVOKED1') {
      return HttpResponse.json({ detail: 'Invite has been revoked' }, { status: 410 })
    }
    if (body.invite_code === 'LIMITED1') {
      return HttpResponse.json({ detail: 'Invite usage limit reached' }, { status: 410 })
    }
    if (body.invite_code === 'DUPEJOIN') {
      return HttpResponse.json({ detail: 'User has already joined this room' }, { status: 409 })
    }
    return HttpResponse.json({
      room: fixtureRoom,
      member: fixtureMember,
      config_available: true,
    })
  }),

  http.get('/api/v1/rooms/:roomId/config', ({ params }) => {
    if (params.roomId !== fixtureRoom.id) {
      return HttpResponse.json({ detail: 'Room not found' }, { status: 404 })
    }
    return HttpResponse.json(fixtureConfig)
  }),
]
