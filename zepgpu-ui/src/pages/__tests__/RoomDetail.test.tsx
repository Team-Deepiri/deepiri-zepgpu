import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import RoomDetail from '@/pages/RoomDetail'
import { renderWithProviders } from '@/test/test-utils'
import { fixtureGpuPool, fixtureMember, fixtureRoom } from '@/test/fixtures/rooms'
import { RoomApiError } from '@/utils/roomErrors'

const {
  getRoomMock,
  getRoomMembersMock,
  getRoomGpuPoolMock,
  leaveRoomMock,
  useRoomWebSocketMock,
  useAuthStoreMock,
  toastSuccessMock,
  toastErrorMock,
  authState,
} = vi.hoisted(() => ({
    getRoomMock: vi.fn(),
    getRoomMembersMock: vi.fn(),
    getRoomGpuPoolMock: vi.fn(),
    leaveRoomMock: vi.fn(),
    useRoomWebSocketMock: vi.fn(),
    useAuthStoreMock: vi.fn(),
    toastSuccessMock: vi.fn(),
    toastErrorMock: vi.fn(),
    authState: { user: null as { id: string } | null },
  }))

vi.mock('@/api/rooms', () => ({
  roomsApi: {
    getRoom: getRoomMock,
    getRoomMembers: getRoomMembersMock,
    getRoomGpuPool: getRoomGpuPoolMock,
    leaveRoom: leaveRoomMock,
  },
}))

vi.mock('@/components/rooms/InvitePanel', () => ({
  default: () => <div data-testid="invite-panel">Invite panel</div>,
}))

vi.mock('@/components/rooms/RoomConfigPanel', () => ({
  default: () => <div data-testid="config-panel">Config panel</div>,
}))

vi.mock('@/components/rooms/RoomGpuPoolSummary', () => ({
  default: ({ enablePolling }: { enablePolling?: boolean }) => (
    <div data-testid="gpu-pool-summary" data-enable-polling={String(enablePolling)}>
      GPU pool summary
    </div>
  ),
}))

vi.mock('@/components/rooms/RoomNodeList', () => ({
  default: ({ enablePolling }: { enablePolling?: boolean }) => (
    <div data-testid="node-list" data-enable-polling={String(enablePolling)}>
      Node list
    </div>
  ),
}))

vi.mock('@/components/rooms/RoomDispatchPanel', () => ({
  default: ({ enablePolling }: { enablePolling?: boolean }) => (
    <div data-testid="dispatch-panel" data-enable-polling={String(enablePolling)}>
      Dispatch panel
    </div>
  ),
}))

vi.mock('@/components/rooms/RoomActivityLog', () => ({
  default: ({ enablePolling }: { enablePolling?: boolean }) => (
    <div data-testid="activity-log" data-enable-polling={String(enablePolling)}>
      Activity log
    </div>
  ),
}))

vi.mock('@/hooks/useRoomWebSocket', () => ({
  useRoomWebSocket: useRoomWebSocketMock,
}))

vi.mock('@/stores/authStore', () => ({
  useAuthStore: useAuthStoreMock,
}))

vi.mock('react-hot-toast', () => ({
  default: {
    success: toastSuccessMock,
    error: toastErrorMock,
  },
}))

describe('RoomDetail page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getRoomMock.mockResolvedValue(fixtureRoom)
    getRoomMembersMock.mockResolvedValue([fixtureMember])
    getRoomGpuPoolMock.mockResolvedValue(fixtureGpuPool)
    leaveRoomMock.mockResolvedValue(undefined)
    useRoomWebSocketMock.mockReturnValue({ status: 'disconnected' })
    authState.user = { id: fixtureRoom.host_id! }
    useAuthStoreMock.mockImplementation(
      (selector: (state: typeof authState) => unknown) => selector(authState),
    )
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders room header and sections', async () => {
    renderWithProviders(<RoomDetail />, {
      route: `/rooms/${fixtureRoom.id}`,
    })

    expect(await screen.findByRole('heading', { name: 'Team Alpha' })).toBeInTheDocument()
    expect(await screen.findByText('host-user')).toBeInTheDocument()
    expect(screen.getByTestId('gpu-pool-summary')).toBeInTheDocument()
    expect(screen.getByTestId('node-list')).toBeInTheDocument()
    expect(screen.getByTestId('invite-panel')).toBeInTheDocument()
    expect(screen.getByTestId('config-panel')).toBeInTheDocument()
  })

  it('shows not found error', async () => {
    getRoomMock.mockReset()
    getRoomMock.mockRejectedValue(new RoomApiError(404, 'Room not found'))

    renderWithProviders(<RoomDetail />, {
      route: '/rooms/00000000-0000-4000-8000-000000000000',
    })

    expect(await screen.findByRole('heading', { name: 'Room not found' })).toBeInTheDocument()
  })

  it('shows access denied error', async () => {
    getRoomMock.mockReset()
    getRoomMock.mockRejectedValue(new RoomApiError(403, 'You do not have access to this room'))

    renderWithProviders(<RoomDetail />, {
      route: `/rooms/${fixtureRoom.id}`,
    })

    expect(await screen.findByText('Access denied')).toBeInTheDocument()
  })

  it.each([
    ['connected', false],
    ['connecting', true],
    ['disconnected', true],
  ] as const)('shows Live %s and sets polling fallback to %s', async (status, enablePolling) => {
    useRoomWebSocketMock.mockReturnValue({ status })

    renderWithProviders(<RoomDetail />, {
      route: `/rooms/${fixtureRoom.id}`,
    })

    expect(await screen.findByText(`Live ${status}`)).toBeInTheDocument()
    for (const testId of ['gpu-pool-summary', 'node-list', 'dispatch-panel', 'activity-log']) {
      expect(screen.getByTestId(testId)).toHaveAttribute(
        'data-enable-polling',
        String(enablePolling),
      )
    }
  })

  it('lets a non-host member leave after confirmation', async () => {
    const user = userEvent.setup()
    authState.user = { id: fixtureMember.user_id! }
    getRoomMock.mockResolvedValue({
      ...fixtureRoom,
      host_id: '99999999-9999-4999-8999-999999999999',
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    renderWithProviders(<RoomDetail />, {
      route: `/rooms/${fixtureRoom.id}`,
    })

    await user.click(await screen.findByRole('button', { name: 'Leave room' }))

    await waitFor(() => {
      expect(leaveRoomMock).toHaveBeenCalledWith(fixtureRoom.id)
      expect(toastSuccessMock).toHaveBeenCalledWith('Left room')
    })
  })

  it('does not show the leave action to the room host', async () => {
    renderWithProviders(<RoomDetail />, {
      route: `/rooms/${fixtureRoom.id}`,
    })

    expect(await screen.findByRole('heading', { name: 'Team Alpha' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Leave room' })).not.toBeInTheDocument()
  })
})
