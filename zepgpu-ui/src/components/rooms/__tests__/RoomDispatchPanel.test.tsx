import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import RoomDispatchPanel from '@/components/rooms/RoomDispatchPanel'
import { renderWithProviders } from '@/test/test-utils'
import { fixtureRoom, fixtureRoomNode, fixtureRoomNodeGpu } from '@/test/fixtures/rooms'

const { getRoomNodesMock, getRoomNodeGpusMock, dispatchTaskMock } = vi.hoisted(() => ({
  getRoomNodesMock: vi.fn(),
  getRoomNodeGpusMock: vi.fn(),
  dispatchTaskMock: vi.fn(),
}))

vi.mock('@/api/rooms', () => ({
  roomsApi: {
    getRoomNodes: getRoomNodesMock,
    getRoomNodeGpus: getRoomNodeGpusMock,
    dispatchTask: dispatchTaskMock,
  },
}))

describe('RoomDispatchPanel', () => {
  const onTaskDispatched = vi.fn()

  beforeEach(() => {
    onTaskDispatched.mockClear()
    getRoomNodesMock.mockResolvedValue([fixtureRoomNode])
    getRoomNodeGpusMock.mockResolvedValue([fixtureRoomNodeGpu])
    dispatchTaskMock.mockResolvedValue({
      id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
      status: 'assigned',
    })
  })

  it('renders dispatch form with auto mode', async () => {
    renderWithProviders(
      <RoomDispatchPanel roomId={fixtureRoom.id} onTaskDispatched={onTaskDispatched} />,
    )

    expect(screen.getByRole('heading', { name: /Dispatch task/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Auto-select GPU/i })).toBeInTheDocument()
    expect(screen.getByLabelText(/Function/i)).toHaveValue('')
    expect(screen.getByLabelText(/Function/i)).toHaveAttribute(
      'placeholder',
      'package.module.function',
    )
  })

  it('dispatches room_auto task', async () => {
    const user = userEvent.setup()
    renderWithProviders(
      <RoomDispatchPanel roomId={fixtureRoom.id} onTaskDispatched={onTaskDispatched} />,
    )

    await user.type(screen.getByLabelText(/Function/i), 'random.seed')
    await user.click(screen.getByRole('button', { name: /Dispatch to room/i }))

    await waitFor(() => {
      expect(dispatchTaskMock).toHaveBeenCalledWith(
        expect.objectContaining({
          room_id: fixtureRoom.id,
          dispatch_mode: 'room_auto',
          func_name: 'random.seed',
        }),
      )
    })
    expect(onTaskDispatched).toHaveBeenCalledWith('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb')
  })

  it('requires node selection for room_specific_node', async () => {
    const user = userEvent.setup()
    renderWithProviders(
      <RoomDispatchPanel roomId={fixtureRoom.id} onTaskDispatched={onTaskDispatched} />,
    )

    await user.click(screen.getByRole('button', { name: /Specific node/i }))
    const dispatchButton = screen.getByRole('button', { name: /Dispatch to room/i })
    expect(dispatchButton).toBeDisabled()
  })

  it('validates GPU memory against single-GPU capacity, not node sums', async () => {
    const user = userEvent.setup()
    renderWithProviders(
      <RoomDispatchPanel roomId={fixtureRoom.id} onTaskDispatched={onTaskDispatched} />,
    )

    // Node sum is 24576; single GPU fixture reports 18000.
    expect(
      await screen.findByText(/Max per GPU currently available: 18,000 MB/i),
    ).toBeInTheDocument()
    expect(screen.getByLabelText(/GPU memory/i)).toHaveAttribute('max', '18000')

    await user.clear(screen.getByLabelText(/GPU memory/i))
    await user.type(screen.getByLabelText(/GPU memory/i), '19000')

    await waitFor(() => {
      expect(screen.getByLabelText(/GPU memory/i)).toHaveValue(18000)
    })
  })
})
