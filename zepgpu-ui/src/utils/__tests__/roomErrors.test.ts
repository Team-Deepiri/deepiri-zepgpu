import { describe, expect, it } from 'vitest'
import { AxiosError, AxiosHeaders } from 'axios'
import { RoomApiError } from '@/utils/roomErrors'
import { getRoomErrorMessage } from '@/utils/roomErrors'

function axiosErrorWithDetail(detail: string, status: number) {
  return new AxiosError('fail', AxiosError.ERR_BAD_RESPONSE, undefined, undefined, {
    status,
    data: { detail },
    headers: {},
    config: { headers: new AxiosHeaders() },
  })
}

describe('getRoomErrorMessage', () => {
  it('returns RoomApiError detail', () => {
    const err = new RoomApiError(404, 'Room not found')
    expect(getRoomErrorMessage(err)).toBe('Room not found')
  })

  it('returns axios string detail', () => {
    expect(getRoomErrorMessage(axiosErrorWithDetail('Invite has expired', 410))).toBe(
      'Invite has expired',
    )
  })

  it('returns axios validation array detail', () => {
    const err = new AxiosError('fail', AxiosError.ERR_BAD_RESPONSE, undefined, undefined, {
      status: 422,
      data: { detail: [{ msg: 'Field required' }] },
      headers: {},
      config: { headers: new AxiosHeaders() },
    })
    expect(getRoomErrorMessage(err)).toBe('Field required')
  })

  it('returns Error message', () => {
    expect(getRoomErrorMessage(new Error('network down'))).toBe('network down')
  })

  it('returns fallback for unknown errors', () => {
    expect(getRoomErrorMessage(null, 'fallback')).toBe('fallback')
  })

  it('maps standard coordination messages', () => {
    expect(getRoomErrorMessage(new RoomApiError(403, 'You do not have access to this room'))).toBe(
      'You do not have access to this room',
    )
    expect(getRoomErrorMessage(new RoomApiError(410, 'Invite has been revoked'))).toBe(
      'Invite has been revoked',
    )
    expect(getRoomErrorMessage(new RoomApiError(409, 'User has already joined this room'))).toBe(
      'User has already joined this room',
    )
    expect(getRoomErrorMessage(new RoomApiError(410, 'Invite usage limit reached'))).toBe(
      'Invite usage limit reached',
    )
    expect(getRoomErrorMessage(new RoomApiError(403, 'Room config is not available yet'))).toBe(
      'Room config is not available yet',
    )
    expect(
      getRoomErrorMessage(
        new RoomApiError(403, 'Only the room host or an admin can perform this action'),
      ),
    ).toBe('Only the room host or an admin can perform this action')
    expect(getRoomErrorMessage(new RoomApiError(404, 'Node not found'))).toBe('Node not found')
    expect(getRoomErrorMessage(new RoomApiError(403, 'You cannot update this node'))).toBe(
      'You cannot update this node',
    )
  })
})
