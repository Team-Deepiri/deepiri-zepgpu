import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import RoomDetail from '@/pages/RoomDetail'
import { renderWithProviders } from '@/test/test-utils'
import { fixtureGpuPool, fixtureMember, fixtureRoom } from '@/test/fixtures/rooms'
import { RoomApiError } from '@/utils/roomErrors'

const { getRoomMock, getRoomMembersMock, getRoomGpuPoolMock, useRoomWebSocketMock } =
  vi.hoisted(() => ({
    getRoomMock: vi.fn(),
    getRoomMembersMock: vi.fn(),
    getRoomGpuPoolMock: vi.fn(),
    useRoomWebSocketMock: vi.fn(),
  }))

vi.mock('@/api/rooms', () => ({
  roomsApi: {
    getRoom: getRoomMock,
    getRoomMembers: getRoomMembersMock,
    getRoomGpuPool: getRoomGpuPoolMock,
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

describe('RoomDetail page', () => {
  beforeEach(() => {
    getRoomMock.mockResolvedValue(fixtureRoom)
    getRoomMembersMock.mockResolvedValue([fixtureMember])
    getRoomGpuPoolMock.mockResolvedValue(fixtureGpuPool)
    useRoomWebSocketMock.mockReturnValue({ status: 'disconnected' })
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
})
