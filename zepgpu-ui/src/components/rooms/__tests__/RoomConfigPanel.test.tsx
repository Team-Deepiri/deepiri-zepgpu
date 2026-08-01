import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import toast from 'react-hot-toast'
import RoomConfigPanel from '@/components/rooms/RoomConfigPanel'
import { renderWithProviders } from '@/test/test-utils'
import { fixtureConfig, fixtureRoom } from '@/test/fixtures/rooms'
import { RoomApiError } from '@/utils/roomErrors'

const { getRoomConfigMock } = vi.hoisted(() => ({
  getRoomConfigMock: vi.fn(),
}))

vi.mock('@/api/rooms', () => ({
  roomsApi: {
    getRoomConfig: getRoomConfigMock,
  },
}))

vi.mock('react-hot-toast', () => ({
  default: { success: vi.fn(), error: vi.fn() },
}))

describe('RoomConfigPanel', () => {
  beforeEach(() => {
    getRoomConfigMock.mockResolvedValue(fixtureConfig)
  })

  it('shows config actions when loaded', async () => {
    renderWithProviders(
      <RoomConfigPanel roomId={fixtureRoom.id} transportMode="wireguard" />,
    )
    expect(await screen.findByRole('button', { name: /copy config/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /download/i })).toBeInTheDocument()
    expect(screen.getByText(/Transport mode:/i)).toBeInTheDocument()
    expect(screen.getByText('wireguard')).toBeInTheDocument()
  })

  it('copies config to clipboard', async () => {
    const user = userEvent.setup()
    renderWithProviders(
      <RoomConfigPanel roomId={fixtureRoom.id} transportMode="wireguard" />,
    )
    await screen.findByRole('button', { name: /copy config/i })

    await user.click(screen.getByRole('button', { name: /copy config/i }))

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith('Config copied to clipboard')
    })
  })

  it('shows not-available message on 403', async () => {
    getRoomConfigMock.mockRejectedValue(new RoomApiError(403, 'Room config is not available yet'))

    renderWithProviders(
      <RoomConfigPanel roomId={fixtureRoom.id} transportMode="wireguard" />,
    )

    expect(
      await screen.findByText(/Connection config is not available yet/i),
    ).toBeInTheDocument()
  })

  it('shows dial-out guidance without fetching WireGuard config', async () => {
    getRoomConfigMock.mockClear()
    renderWithProviders(
      <RoomConfigPanel
        roomId={fixtureRoom.id}
        transportMode="dialout"
        requiresWireguardUdp={false}
      />,
    )

    expect(await screen.findByText(/No inbound UDP 51820 is required/i)).toBeInTheDocument()
    expect(screen.getByText(/WireGuard config download/i)).toBeInTheDocument()
    expect(getRoomConfigMock).not.toHaveBeenCalled()
  })
})
