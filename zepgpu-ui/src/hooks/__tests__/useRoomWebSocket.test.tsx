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
      ws.emit({ type: 'subscribed', room_id: 'room-1' })
    })

    await waitFor(() => expect(result.current.status).toBe('connected'))
  })

  it('invalidates node queries on room_node_online', async () => {
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
    })
  })
})
