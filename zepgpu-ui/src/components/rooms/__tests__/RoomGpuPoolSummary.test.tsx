import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import RoomGpuPoolSummary from '@/components/rooms/RoomGpuPoolSummary'
import { renderWithProviders } from '@/test/test-utils'
import { fixtureGpuPool, fixtureGpuPoolOffline, fixtureRoom, fixtureRoomNode } from '@/test/fixtures/rooms'

const { getRoomGpuPoolMock, getRoomNodesMock } = vi.hoisted(() => ({
  getRoomGpuPoolMock: vi.fn(),
  getRoomNodesMock: vi.fn(),
}))

vi.mock('@/api/rooms', () => ({
  roomsApi: {
    getRoomGpuPool: getRoomGpuPoolMock,
    getRoomNodes: getRoomNodesMock,
  },
}))

describe('RoomGpuPoolSummary', () => {
  beforeEach(() => {
    getRoomGpuPoolMock.mockResolvedValue(fixtureGpuPool)
    getRoomNodesMock.mockResolvedValue([fixtureRoomNode])
  })

  it('renders pool totals and VRAM', async () => {
    renderWithProviders(<RoomGpuPoolSummary roomId={fixtureRoom.id} />)

    expect(await screen.findByText(/Total GPUs:/)).toBeInTheDocument()
    expect(screen.getByText('4')).toBeInTheDocument()
    expect(screen.getByText(/Available \(usable now\)/)).toBeInTheDocument()
    expect(screen.getByText(/VRAM total:/)).toBeInTheDocument()
    expect(screen.getByText(/VRAM available \(usable now\)/)).toBeInTheDocument()
    expect(screen.getByText(/Online nodes:/)).toBeInTheDocument()
    expect(screen.getByText('nvidia')).toBeInTheDocument()
  })

  it('shows zero available when offline peers excluded', async () => {
    getRoomGpuPoolMock.mockResolvedValue(fixtureGpuPoolOffline)
    renderWithProviders(<RoomGpuPoolSummary roomId={fixtureRoom.id} />)

    expect(await screen.findByText(/Available \(usable now\)/)).toBeInTheDocument()
    const availableRow = screen.getByText(/Available \(usable now\)/).parentElement
    expect(availableRow?.textContent).toContain('0')
  })

  it('shows loading state', () => {
    getRoomGpuPoolMock.mockReturnValue(new Promise(() => {}))
    renderWithProviders(<RoomGpuPoolSummary roomId={fixtureRoom.id} />)
    expect(screen.getByText(/Loading GPU pool/i)).toBeInTheDocument()
  })
})
