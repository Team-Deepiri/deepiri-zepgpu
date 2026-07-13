import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import RoomActivityLog from '@/components/rooms/RoomActivityLog'
import { renderWithProviders } from '@/test/test-utils'
import { fixtureRoom } from '@/test/fixtures/rooms'
import { fixtureDispatchedTask } from '@/test/fixtures/tasks'

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
    getTaskMock.mockResolvedValue(fixtureDispatchedTask)
  })

  it('shows empty state when no tasks dispatched', () => {
    renderWithProviders(<RoomActivityLog roomId={fixtureRoom.id} taskIds={[]} />)
    expect(screen.getByText(/Dispatched tasks appear here/i)).toBeInTheDocument()
  })

  it('renders dispatched task status', async () => {
    renderWithProviders(
      <RoomActivityLog roomId={fixtureRoom.id} taskIds={[fixtureDispatchedTask.id]} />,
    )

    expect(await screen.findByText(fixtureDispatchedTask.name!)).toBeInTheDocument()
    expect(screen.getAllByText('assigned').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/room_auto/)).toBeInTheDocument()
  })
})
