import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import RoomNodeList from '@/components/rooms/RoomNodeList'
import { renderWithProviders } from '@/test/test-utils'
import {
  fixtureRoom,
  fixtureRoomNode,
  fixtureRoomNodeAwol,
  fixtureRoomNodeDisconnected,
} from '@/test/fixtures/rooms'

const { getRoomNodesMock } = vi.hoisted(() => ({
  getRoomNodesMock: vi.fn(),
}))

vi.mock('@/api/rooms', () => ({
  roomsApi: {
    getRoomNodes: getRoomNodesMock,
    getRoomNodeGpus: vi.fn().mockResolvedValue([]),
    getRoomGpuPool: vi.fn(),
  },
}))

vi.mock('@/components/rooms/RoomNodeCard', () => ({
  default: ({ node }: { node: { username: string; status: string } }) => (
    <li data-testid={`node-card-${node.username}`}>{node.status}</li>
  ),
}))

describe('RoomNodeList', () => {
  beforeEach(() => {
    getRoomNodesMock.mockReset()
  })

  it('renders empty state', async () => {
    getRoomNodesMock.mockResolvedValue([])
    renderWithProviders(<RoomNodeList roomId={fixtureRoom.id} />)

    expect(
      await screen.findByText(/No nodes connected yet/i),
    ).toBeInTheDocument()
  })

  it('renders connected node', async () => {
    getRoomNodesMock.mockResolvedValue([fixtureRoomNode])
    renderWithProviders(<RoomNodeList roomId={fixtureRoom.id} />)

    expect(await screen.findByTestId('node-card-host-user')).toHaveTextContent('connected')
    expect(screen.getByText(/1 online/i)).toBeInTheDocument()
  })

  it('renders AWOL and disconnected badges via cards', async () => {
    getRoomNodesMock.mockResolvedValue([
      fixtureRoomNode,
      fixtureRoomNodeAwol,
      fixtureRoomNodeDisconnected,
    ])
    renderWithProviders(<RoomNodeList roomId={fixtureRoom.id} />)

    expect(await screen.findByTestId('node-card-awol-user')).toHaveTextContent('awol')
    expect(screen.getByTestId('node-card-offline-user')).toHaveTextContent('disconnected')
  })

  it('refresh button invalidates queries', async () => {
    getRoomNodesMock.mockResolvedValue([fixtureRoomNode])
    const user = userEvent.setup()
    renderWithProviders(<RoomNodeList roomId={fixtureRoom.id} />)

    await screen.findByTestId('node-card-host-user')
    await user.click(screen.getByRole('button', { name: /refresh nodes/i }))
    expect(getRoomNodesMock.mock.calls.length).toBeGreaterThanOrEqual(2)
  })
})
