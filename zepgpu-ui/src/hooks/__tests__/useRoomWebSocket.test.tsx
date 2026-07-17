import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useRoomWebSocket } from '@/hooks/useRoomWebSocket'

class MockWebSocket {
  static OPEN = 1
  static CONNECTING = 0
  static instances: MockWebSocket[] = []

  readyState = MockWebSocket.CONNECTING
  onopen: ((ev?: Event) => void) | null = null
  onmessage: ((ev: MessageEvent) => void) | null = null
  onerror: ((ev?: Event) => void) | null = null
  onclose: ((ev?: CloseEvent) => void) | null = null
  sent: string[] = []

  constructor(public url: string) {
    MockWebSocket.instances.push(this)
    queueMicrotask(() => {
      this.readyState = MockWebSocket.OPEN
      this.onopen?.(new Event('open'))
    })
  }

  send(data: string) {
    this.sent.push(data)
  }

  close() {
    this.readyState = 3
    this.onclose?.(new CloseEvent('close'))
  }

  emit(data: unknown) {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(data) }))
  }
}

function wrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('useRoomWebSocket', () => {
  beforeEach(() => {
    MockWebSocket.instances = []
    vi.stubGlobal('WebSocket', MockWebSocket as unknown as typeof WebSocket)
    localStorage.setItem('token', 'test-jwt')
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('connects with token and sends subscribe_room', async () => {
    const client = new QueryClient()
    const { result } = renderHook(() => useRoomWebSocket('room-1'), {
      wrapper: wrapper(client),
    })

    await waitFor(() => expect(MockWebSocket.instances.length).toBe(1))
    const ws = MockWebSocket.instances[0]
    expect(ws.url).toContain('/api/v1/ws/rooms?token=test-jwt')

    await waitFor(() => {
      expect(ws.sent.some((s) => s.includes('subscribe_room'))).toBe(true)
    })

    act(() => {
      ws.emit({ type: 'connected', user_id: 'u1' })
    })
    expect(result.current.status).toBe('connecting')

    act(() => {
      ws.emit({ type: 'subscribed', room_id: 'room-1' })
    })

    await waitFor(() => expect(result.current.status).toBe('connected'))
  })

  it('invalidates node, pool, and member queries on node status events', async () => {
    const client = new QueryClient()
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries')
    renderHook(() => useRoomWebSocket('room-1'), { wrapper: wrapper(client) })

    await waitFor(() => expect(MockWebSocket.instances.length).toBe(1))
    const ws = MockWebSocket.instances[0]
    act(() => {
      ws.emit({ type: 'subscribed', room_id: 'room-1' })
      ws.emit({
        type: 'room_node_online',
        room_id: 'room-1',
        payload: { peer_id: 'peer-1' },
      })
    })

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({ queryKey: ['room-nodes', 'room-1'] }),
      )
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({ queryKey: ['room-gpu-pool', 'room-1'] }),
      )
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({ queryKey: ['room-members', 'room-1'] }),
      )
    })
  })

  it('invalidates room and node GPU queries on room_gpu_update', async () => {
    const client = new QueryClient()
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries')
    renderHook(() => useRoomWebSocket('room-1'), { wrapper: wrapper(client) })

    await waitFor(() => expect(MockWebSocket.instances.length).toBe(1))
    act(() => {
      MockWebSocket.instances[0].emit({
        type: 'room_gpu_update',
        room_id: 'room-1',
        payload: { peer_id: 'peer-1' },
      })
    })

    await waitFor(() => {
      for (const queryKey of [
        ['room-gpu-pool', 'room-1'],
        ['room-gpus', 'room-1'],
        ['room-node-gpus', 'room-1', 'peer-1'],
        ['room-nodes', 'room-1'],
      ]) {
        expect(invalidateSpy).toHaveBeenCalledWith(expect.objectContaining({ queryKey }))
      }
    })
  })

  it.each(['room_member_joined', 'room_member_left'])(
    'invalidates members on %s',
    async (type) => {
      const client = new QueryClient()
      const invalidateSpy = vi.spyOn(client, 'invalidateQueries')
      renderHook(() => useRoomWebSocket('room-1'), { wrapper: wrapper(client) })

      await waitFor(() => expect(MockWebSocket.instances.length).toBe(1))
      act(() => {
        MockWebSocket.instances[0].emit({ type, room_id: 'room-1' })
      })

      await waitFor(() => {
        expect(invalidateSpy).toHaveBeenCalledWith(
          expect.objectContaining({ queryKey: ['room-members', 'room-1'] }),
        )
      })
    },
  )

  it.each([
    'room_task_assigned',
    'room_task_started',
    'room_task_completed',
    'room_task_failed',
  ])('invalidates task and capacity queries on %s', async (type) => {
    const client = new QueryClient()
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries')
    renderHook(() => useRoomWebSocket('room-1'), { wrapper: wrapper(client) })

    await waitFor(() => expect(MockWebSocket.instances.length).toBe(1))
    act(() => {
      MockWebSocket.instances[0].emit({
        type,
        room_id: 'room-1',
        payload: { task_id: 'task-1' },
      })
    })

    await waitFor(() => {
      for (const queryKey of [
        ['task', 'task-1'],
        ['room-nodes', 'room-1'],
        ['room-gpu-pool', 'room-1'],
      ]) {
        expect(invalidateSpy).toHaveBeenCalledWith(expect.objectContaining({ queryKey }))
      }
    })
  })

  it('ignores malformed and unknown messages', async () => {
    const client = new QueryClient()
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries')
    renderHook(() => useRoomWebSocket('room-1'), { wrapper: wrapper(client) })

    await waitFor(() => expect(MockWebSocket.instances.length).toBe(1))
    const ws = MockWebSocket.instances[0]
    act(() => {
      ws.onmessage?.(new MessageEvent('message', { data: '{invalid' }))
      ws.emit({ type: 'unknown_event', room_id: 'room-1' })
    })

    expect(invalidateSpy).not.toHaveBeenCalled()
  })

  it('unsubscribes and closes on unmount', async () => {
    const client = new QueryClient()
    const { unmount } = renderHook(() => useRoomWebSocket('room-1'), {
      wrapper: wrapper(client),
    })

    await waitFor(() => expect(MockWebSocket.instances.length).toBe(1))
    const ws = MockWebSocket.instances[0]
    await waitFor(() => expect(ws.readyState).toBe(MockWebSocket.OPEN))

    unmount()

    expect(ws.sent.some((message) => message.includes('unsubscribe_room'))).toBe(true)
    expect(ws.readyState).toBe(3)
  })

  it('reconnects after an unexpected close', async () => {
    vi.useFakeTimers()
    const client = new QueryClient()
    renderHook(() => useRoomWebSocket('room-1'), { wrapper: wrapper(client) })
    await act(async () => {
      await Promise.resolve()
    })
    expect(MockWebSocket.instances).toHaveLength(1)

    act(() => {
      MockWebSocket.instances[0].onclose?.(new CloseEvent('close'))
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })

    expect(MockWebSocket.instances).toHaveLength(2)
  })

  it('does not open a socket without a JWT', () => {
    localStorage.removeItem('token')
    const client = new QueryClient()
    const { result } = renderHook(() => useRoomWebSocket('room-1'), {
      wrapper: wrapper(client),
    })

    expect(MockWebSocket.instances).toHaveLength(0)
    expect(result.current.status).toBe('disconnected')
  })
})
