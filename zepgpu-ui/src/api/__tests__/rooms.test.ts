import { describe, expect, it, beforeEach } from 'vitest'
import { roomsApi } from '@/api/rooms'
import { fixtureRoom } from '@/test/fixtures/rooms'

describe('roomsApi (MSW)', () => {
  beforeEach(() => {
    localStorage.setItem('token', 'test-token')
  })

  it('listRooms returns rooms', async () => {
    const rooms = await roomsApi.listRooms()
    expect(rooms.length).toBeGreaterThan(0)
    expect(rooms[0].name).toBe('Team Alpha')
  })

  it('getRoom returns a room by id', async () => {
    const room = await roomsApi.getRoom(fixtureRoom.id)
    expect(room.id).toBe(fixtureRoom.id)
  })

  it('createRoom posts name and description', async () => {
    const room = await roomsApi.createRoom({
      name: 'New Room',
      description: 'desc',
    })
    expect(room.name).toBe('New Room')
    expect(room.description).toBe('desc')
  })

  it('getRoomMembers returns members', async () => {
    const members = await roomsApi.getRoomMembers(fixtureRoom.id)
    expect(members).toHaveLength(1)
    expect(members[0].display_name).toBe('host-user')
  })

  it('getRoomGpuPool returns pool summary', async () => {
    const pool = await roomsApi.getRoomGpuPool(fixtureRoom.id)
    expect(pool.total_gpus).toBe(4)
    expect(pool.providers).toHaveLength(1)
  })

  it('createRoomInvite returns invite', async () => {
    const invite = await roomsApi.createRoomInvite(fixtureRoom.id, { max_uses: 5, expires_at: null })
    expect(invite.code).toBe('NEWCODE1')
    expect(invite.max_uses).toBe(5)
  })

  it('listRoomInvites returns active invites', async () => {
    const invites = await roomsApi.listRoomInvites(fixtureRoom.id)
    expect(invites.length).toBeGreaterThan(0)
  })

  it('revokeRoomInvite completes without body', async () => {
    await expect(
      roomsApi.revokeRoomInvite(fixtureRoom.id, '55555555-5555-4555-8555-555555555555'),
    ).resolves.toBeUndefined()
  })

  it('joinRoom sends invite_code and parses response', async () => {
    const response = await roomsApi.joinRoom({ invite_code: 'TEAMALPHA' })
    expect(response.room.id).toBe(fixtureRoom.id)
    expect(response.config_available).toBe(true)
  })

  it('getRoomConfig returns config and filename', async () => {
    const config = await roomsApi.getRoomConfig(fixtureRoom.id)
    expect(config.filename).toBe('room-test.conf')
    expect(config.config).toContain('[Interface]')
  })

  it('getRoom throws for unknown id', async () => {
    await expect(roomsApi.getRoom('00000000-0000-4000-8000-000000000000')).rejects.toThrow()
  })

  it('deleteRoom completes without body', async () => {
    const created = await roomsApi.createRoom({ name: 'To Delete', description: null })
    await expect(roomsApi.deleteRoom(created.id)).resolves.toBeUndefined()
  })
})
