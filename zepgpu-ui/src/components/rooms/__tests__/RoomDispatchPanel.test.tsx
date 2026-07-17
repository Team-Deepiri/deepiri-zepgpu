import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import RoomDispatchPanel from '@/components/rooms/RoomDispatchPanel'
import { renderWithProviders } from '@/test/test-utils'
import { fixtureRoom, fixtureRoomNode } from '@/test/fixtures/rooms'

const { getRoomNodesMock, dispatchTaskMock } = vi.hoisted(() => ({
  getRoomNodesMock: vi.fn(),
  dispatchTaskMock: vi.fn(),
}))

vi.mock('@/api/rooms', () => ({
  roomsApi: {
    getRoomNodes: getRoomNodesMock,
    getRoomNodeGpus: vi.fn().mockResolvedValue([]),
    dispatchTask: dispatchTaskMock,
  },
}))

describe('RoomDispatchPanel', () => {
  const onTaskDispatched = vi.fn()

  beforeEach(() => {
    onTaskDispatched.mockClear()
    getRoomNodesMock.mockResolvedValue([fixtureRoomNode])
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
    expect(screen.getByLabelText(/Function/i)).toHaveValue('random.seed')
  })

  it('dispatches room_auto task', async () => {
    const user = userEvent.setup()
    renderWithProviders(
      <RoomDispatchPanel roomId={fixtureRoom.id} onTaskDispatched={onTaskDispatched} />,
    )

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

  it('validates GPU memory against reported room capacity', async () => {
    const user = userEvent.setup()
    renderWithProviders(
      <RoomDispatchPanel roomId={fixtureRoom.id} onTaskDispatched={onTaskDispatched} />,
    )

    const gpuMemoryInput = screen.getByLabelText(/GPU memory/i)
    expect(await screen.findByText(/Maximum currently available: 24,576 MB/i)).toBeInTheDocument()
    expect(gpuMemoryInput).toHaveAttribute('max', '24576')

    await user.clear(gpuMemoryInput)
    await user.type(gpuMemoryInput, '25000')

    expect(gpuMemoryInput).toHaveValue(25000)
    expect(screen.getByText(/exceeds currently available GPU memory/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Dispatch to room/i })).toBeDisabled()
  })
})
