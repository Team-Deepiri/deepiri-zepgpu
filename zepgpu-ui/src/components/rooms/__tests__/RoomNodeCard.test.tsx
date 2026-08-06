import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import RoomNodeCard from '@/components/rooms/RoomNodeCard'
import { renderWithProviders } from '@/test/test-utils'
import { fixtureRoom, fixtureRoomNode, fixtureRoomNodeGpu } from '@/test/fixtures/rooms'

const { getRoomNodeGpusMock } = vi.hoisted(() => ({
  getRoomNodeGpusMock: vi.fn(),
}))

vi.mock('@/api/rooms', () => ({
  roomsApi: {
    getRoomNodeGpus: getRoomNodeGpusMock,
  },
}))

describe('RoomNodeCard', () => {
  beforeEach(() => {
    getRoomNodeGpusMock.mockResolvedValue([fixtureRoomNodeGpu])
  })

  it('renders node identity and status', async () => {
    renderWithProviders(<RoomNodeCard roomId={fixtureRoom.id} node={fixtureRoomNode} />)

    expect(screen.getByText('host-user')).toBeInTheDocument()
    expect(screen.getByText('connected')).toBeInTheDocument()
    expect(screen.getByText(/10\.8\.0\.2/)).toBeInTheDocument()
    expect(screen.getByText(/GPU host/)).toBeInTheDocument()
    expect(screen.getByText('healthy')).toBeInTheDocument()
    expect(screen.getByText(/Provider is online with fresh heartbeat/)).toBeInTheDocument()
    expect(screen.getByText(/Path direct\/wan/)).toBeInTheDocument()
    expect(screen.getByText(/RTT 42\.5 ms/)).toBeInTheDocument()
    expect(screen.getByText(/CUDA 12\.4/)).toBeInTheDocument()
  })

  it('renders GPU memory and utilization', async () => {
    renderWithProviders(<RoomNodeCard roomId={fixtureRoom.id} node={fixtureRoomNode} />)

    expect(await screen.findByText('NVIDIA RTX 4090')).toBeInTheDocument()
    expect(screen.getByText(/12\.5%/)).toBeInTheDocument()
    expect(screen.getByText(/free of/)).toBeInTheDocument()
  })
})
