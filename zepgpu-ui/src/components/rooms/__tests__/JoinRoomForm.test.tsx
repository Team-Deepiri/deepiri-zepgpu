import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import JoinRoomForm from '@/components/rooms/JoinRoomForm'
import { renderWithProviders } from '@/test/test-utils'
import { fixtureRoom } from '@/test/fixtures/rooms'
import { RoomApiError } from '@/utils/roomErrors'

const { joinRoomMock } = vi.hoisted(() => ({
  joinRoomMock: vi.fn(),
}))

const navigateMock = vi.fn()

vi.mock('@/api/rooms', () => ({
  roomsApi: {
    joinRoom: joinRoomMock,
  },
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    useNavigate: () => navigateMock,
  }
})

vi.mock('react-hot-toast', () => ({
  default: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

describe('JoinRoomForm', () => {
  beforeEach(() => {
    joinRoomMock.mockReset()
    navigateMock.mockReset()
  })

  it('blocks empty submit', () => {
    renderWithProviders(<JoinRoomForm />)
    expect(screen.getByRole('button', { name: /join room/i })).toBeDisabled()
  })

  it('joins with valid code', async () => {
    joinRoomMock.mockResolvedValue({
      room: fixtureRoom,
      member: {},
      config_available: true,
    })
    const user = userEvent.setup()
    renderWithProviders(<JoinRoomForm />)

    await user.type(screen.getByLabelText(/invite code/i), 'TEAMALPHA')
    await user.click(screen.getByRole('button', { name: /join room/i }))

    await waitFor(() => {
      expect(joinRoomMock).toHaveBeenCalledWith({ invite_code: 'TEAMALPHA' })
      expect(navigateMock).toHaveBeenCalledWith(`/rooms/${fixtureRoom.id}`)
    })
  })

  it('shows expired invite error', async () => {
    joinRoomMock.mockRejectedValue(new RoomApiError(410, 'Invite has expired'))
    const user = userEvent.setup()
    renderWithProviders(<JoinRoomForm />)

    await user.type(screen.getByLabelText(/invite code/i), 'EXPIRED1')
    await user.click(screen.getByRole('button', { name: /join room/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Invite has expired')
  })

  it('shows revoked invite error', async () => {
    joinRoomMock.mockRejectedValue(new RoomApiError(410, 'Invite has been revoked'))
    const user = userEvent.setup()
    renderWithProviders(<JoinRoomForm />)

    await user.type(screen.getByLabelText(/invite code/i), 'REVOKED1')
    await user.click(screen.getByRole('button', { name: /join room/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Invite has been revoked')
  })

  it('shows duplicate join error', async () => {
    joinRoomMock.mockRejectedValue(new RoomApiError(409, 'User has already joined this room'))
    const user = userEvent.setup()
    renderWithProviders(<JoinRoomForm />)

    await user.type(screen.getByLabelText(/invite code/i), 'DUPEJOIN')
    await user.click(screen.getByRole('button', { name: /join room/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent('User has already joined this room')
  })
})
