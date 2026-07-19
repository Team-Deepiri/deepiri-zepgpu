import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, screen } from '@testing-library/react'
import RoomActivityLog from '@/components/rooms/RoomActivityLog'
import { renderWithProviders } from '@/test/test-utils'
import { fixtureCompletedRoomTask, fixtureDispatchedTask } from '@/test/fixtures/tasks'

const { getTaskMock } = vi.hoisted(() => ({
  getTaskMock: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    tasksApi: {
      ...actual.tasksApi,
      get: getTaskMock,
    },
  }
})

vi.mock('@/api/nodeTasks', () => ({
  nodeTasksApi: {
    getResult: vi.fn(),
  },
}))

describe('RoomActivityLog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getTaskMock.mockResolvedValue(fixtureDispatchedTask)
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('shows empty state when no tasks dispatched', () => {
    renderWithProviders(<RoomActivityLog taskIds={[]} />)
    expect(screen.getByText(/Dispatched tasks appear here/i)).toBeInTheDocument()
  })

  it('renders dispatched task status', async () => {
    renderWithProviders(<RoomActivityLog taskIds={[fixtureDispatchedTask.id]} />)

    expect(await screen.findByText(fixtureDispatchedTask.name!)).toBeInTheDocument()
    expect(screen.getAllByText('assigned').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/room_auto/)).toBeInTheDocument()
  })

  it('polls active tasks while fallback polling is enabled', async () => {
    vi.useFakeTimers()
    renderWithProviders(
      <RoomActivityLog taskIds={[fixtureDispatchedTask.id]} enablePolling />,
    )

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
      await vi.advanceTimersByTimeAsync(3000)
    })

    expect(getTaskMock.mock.calls.length).toBeGreaterThan(1)
  })

  it('does not poll active tasks when WebSocket updates are connected', async () => {
    vi.useFakeTimers()
    renderWithProviders(
      <RoomActivityLog taskIds={[fixtureDispatchedTask.id]} enablePolling={false} />,
    )

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
      await vi.advanceTimersByTimeAsync(9000)
    })

    expect(getTaskMock).toHaveBeenCalledTimes(1)
  })

  it('stops fallback polling for terminal tasks', async () => {
    vi.useFakeTimers()
    getTaskMock.mockResolvedValue({
      ...fixtureCompletedRoomTask,
      dispatch_mode: 'local',
    })
    renderWithProviders(
      <RoomActivityLog taskIds={[fixtureCompletedRoomTask.id]} enablePolling />,
    )

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
      await vi.advanceTimersByTimeAsync(9000)
    })

    expect(getTaskMock).toHaveBeenCalledTimes(1)
  })
})
