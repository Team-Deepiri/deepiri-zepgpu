import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import Rooms from '@/pages/Rooms'
import { fixtureRoom } from '@/test/fixtures/rooms'
import { renderWithProviders } from '@/test/test-utils'

const { listRoomsMock, createRoomMock, deleteRoomMock } = vi.hoisted(() => ({
  listRoomsMock: vi.fn(),
  createRoomMock: vi.fn(),
  deleteRoomMock: vi.fn(),
}))

vi.mock('@/api/rooms', () => ({
  roomsApi: {
    listRooms: listRoomsMock,
    createRoom: createRoomMock,
    deleteRoom: deleteRoomMock,
    joinRoom: vi.fn(),
  },
}))

vi.mock('@/components/rooms/JoinRoomForm', () => ({
  default: () => <div data-testid="join-room-form">Join form</div>,
}))

vi.mock('react-hot-toast', () => ({
  default: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

describe('Rooms page', () => {
  beforeEach(() => {
    vi.clearAllMocks()

    listRoomsMock.mockResolvedValue([fixtureRoom])
    createRoomMock.mockResolvedValue({
      ...fixtureRoom,
      id: 'new-room',
      name: 'Created Room',
      transport_mode: 'dialout',
    })
    deleteRoomMock.mockResolvedValue(undefined)
  })

  it('shows loading then room list', async () => {
    renderWithProviders(<Rooms />, { route: '/rooms' })

    expect(await screen.findByText('Team Alpha')).toBeInTheDocument()
  })

  it('shows empty state', async () => {
    listRoomsMock.mockResolvedValue([])

    renderWithProviders(<Rooms />)

    expect(
      await screen.findByText(/No rooms yet — create one below/i),
    ).toBeInTheDocument()
  })

  it('creates a room', async () => {
    const user = userEvent.setup()

    renderWithProviders(<Rooms />)

    await screen.findByText('Team Alpha')
    await user.type(screen.getByLabelText(/^name$/i), 'Created Room')
    await user.click(screen.getByRole('button', { name: /create room/i }))

    await waitFor(() => {
      expect(createRoomMock).toHaveBeenCalledTimes(1)
      expect(createRoomMock).toHaveBeenCalledWith({
        name: 'Created Room',
        description: null,
        transport_mode: 'dialout',
      })
    })
  })

  it('links to room detail', async () => {
    renderWithProviders(<Rooms />)

    const link = await screen.findByRole('link', { name: /Team Alpha/i })

    expect(link).toHaveAttribute('href', `/rooms/${fixtureRoom.id}`)
  })

  it('embeds join form', async () => {
    renderWithProviders(<Rooms />)

    expect(await screen.findByTestId('join-room-form')).toBeInTheDocument()
  })
})
