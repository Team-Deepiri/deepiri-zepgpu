import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import toast from 'react-hot-toast'
import InvitePanel from '@/components/rooms/InvitePanel'
import { renderWithProviders } from '@/test/test-utils'
import { fixtureInvite, fixtureRoom } from '@/test/fixtures/rooms'
import { clipboardWriteTextMock } from '@/test/setup'

const { listRoomInvitesMock, createRoomInviteMock, revokeRoomInviteMock } = vi.hoisted(() => ({
  listRoomInvitesMock: vi.fn(),
  createRoomInviteMock: vi.fn(),
  revokeRoomInviteMock: vi.fn(),
}))

vi.mock('@/api/rooms', () => ({
  roomsApi: {
    listRoomInvites: listRoomInvitesMock,
    createRoomInvite: createRoomInviteMock,
    revokeRoomInvite: revokeRoomInviteMock,
  },
}))

vi.mock('react-hot-toast', () => ({
  default: { success: vi.fn(), error: vi.fn() },
}))

describe('InvitePanel', () => {
  beforeEach(() => {
    listRoomInvitesMock.mockResolvedValue([fixtureInvite])
    createRoomInviteMock.mockResolvedValue({ ...fixtureInvite, code: 'FRESHCODE' })
    revokeRoomInviteMock.mockResolvedValue(undefined)
    clipboardWriteTextMock.mockReset()
    clipboardWriteTextMock.mockResolvedValue(undefined)
    vi.mocked(toast.success).mockClear()
    vi.mocked(toast.error).mockClear()
  })

  it('lists active invites', async () => {
    renderWithProviders(<InvitePanel roomId={fixtureRoom.id} />)
    expect(await screen.findByText('TEAMALPHA')).toBeInTheDocument()
    expect(screen.getByText(/Uses 1\/10/)).toBeInTheDocument()
  })

  it('creates invite', async () => {
    const user = userEvent.setup()
    renderWithProviders(<InvitePanel roomId={fixtureRoom.id} />)
    await screen.findByText('TEAMALPHA')

    await user.click(screen.getByRole('button', { name: /create invite/i }))

    await waitFor(() => {
      expect(createRoomInviteMock).toHaveBeenCalledWith(
        fixtureRoom.id,
        expect.objectContaining({ max_uses: 10 }),
      )
      expect(screen.getByText('FRESHCODE')).toBeInTheDocument()
      expect(screen.getByTestId('invite-join-command')).toHaveTextContent('zepgpu-node join')
      expect(screen.getByTestId('invite-join-command')).toHaveTextContent('FRESHCODE')
    })
  })

  it('clears lastCreated when roomId changes', async () => {
    const user = userEvent.setup()
    const { rerender } = renderWithProviders(<InvitePanel roomId={fixtureRoom.id} />)
    await screen.findByText('TEAMALPHA')
    await user.click(screen.getByRole('button', { name: /create invite/i }))
    expect(await screen.findByText('FRESHCODE')).toBeInTheDocument()

    const otherRoomId = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'
    listRoomInvitesMock.mockResolvedValue([])
    rerender(<InvitePanel roomId={otherRoomId} />)

    await waitFor(() => {
      expect(screen.queryByText('FRESHCODE')).not.toBeInTheDocument()
      expect(screen.queryByTestId('invite-join-command')).not.toBeInTheDocument()
    })
  })

  it('copies invite code', async () => {
    const user = userEvent.setup()
    renderWithProviders(<InvitePanel roomId={fixtureRoom.id} />)
    await screen.findByText('TEAMALPHA')

    await user.click(screen.getByTitle('Copy code'))

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith('Invite code copied')
    })
  })

  it('shows error toast when clipboard write fails', async () => {
    const user = userEvent.setup()
    const writeSpy = vi
      .spyOn(navigator.clipboard, 'writeText')
      .mockRejectedValueOnce(new Error('denied'))
    renderWithProviders(<InvitePanel roomId={fixtureRoom.id} />)
    await screen.findByText('TEAMALPHA')

    await user.click(screen.getByTitle('Copy code'))

    await waitFor(() => {
      expect(writeSpy).toHaveBeenCalled()
      expect(toast.error).toHaveBeenCalledWith('Failed to copy to clipboard')
    })
    writeSpy.mockRestore()
  })

  it('copies join command', async () => {
    const user = userEvent.setup()
    createRoomInviteMock.mockResolvedValue({
      ...fixtureInvite,
      code: 'FRESHCODE',
      join_command: 'zepgpu-node join --invite FRESHCODE --coordinator https://coord.example',
    })
    renderWithProviders(<InvitePanel roomId={fixtureRoom.id} />)
    await screen.findByText('TEAMALPHA')
    await user.click(screen.getByRole('button', { name: /create invite/i }))
    await screen.findByTestId('invite-join-command')

    await user.click(screen.getByRole('button', { name: /copy command/i }))

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith('Join command copied')
    })
  })
})
