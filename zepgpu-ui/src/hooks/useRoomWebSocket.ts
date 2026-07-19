import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { buildRoomWebSocketUrl } from '@/api/roomWs'
import { useAuthStore } from '@/stores/authStore'
import type { RoomWebSocketMessage } from '@/types'

export type RoomWebSocketStatus = 'connecting' | 'connected' | 'disconnected'

const MAX_BACKOFF_MS = 15000

function getAuthToken(): string | null {
  return useAuthStore.getState().token ?? localStorage.getItem('token')
}

function invalidateForEvent(
  queryClient: ReturnType<typeof useQueryClient>,
  roomId: string,
  message: RoomWebSocketMessage,
) {
  const type = message.type
  const payload = message.payload ?? {}

  if (type === 'room_member_joined' || type === 'room_member_left') {
    void queryClient.invalidateQueries({ queryKey: ['room-members', roomId] })
    return
  }

  if (type === 'room_node_online' || type === 'room_node_offline') {
    void queryClient.invalidateQueries({ queryKey: ['room-nodes', roomId] })
    void queryClient.invalidateQueries({ queryKey: ['room-gpu-pool', roomId] })
    void queryClient.invalidateQueries({ queryKey: ['room-members', roomId] })
    return
  }

  if (type === 'room_gpu_update') {
    void queryClient.invalidateQueries({ queryKey: ['room-gpu-pool', roomId] })
    void queryClient.invalidateQueries({ queryKey: ['room-gpus', roomId] })
    const peerId = typeof payload.peer_id === 'string' ? payload.peer_id : undefined
    if (peerId) {
      void queryClient.invalidateQueries({ queryKey: ['room-node-gpus', roomId, peerId] })
    } else {
      void queryClient.invalidateQueries({ queryKey: ['room-node-gpus', roomId] })
    }
    void queryClient.invalidateQueries({ queryKey: ['room-nodes', roomId] })
    return
  }

  if (
    type === 'room_task_assigned' ||
    type === 'room_task_started' ||
    type === 'room_task_completed' ||
    type === 'room_task_failed'
  ) {
    const taskId = typeof payload.task_id === 'string' ? payload.task_id : undefined
    if (taskId) {
      void queryClient.invalidateQueries({ queryKey: ['task', taskId] })
    }
    void queryClient.invalidateQueries({ queryKey: ['room-nodes', roomId] })
    void queryClient.invalidateQueries({ queryKey: ['room-gpu-pool', roomId] })
  }
}

export function useRoomWebSocket(roomId: string | undefined): {
  status: RoomWebSocketStatus
} {
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<RoomWebSocketStatus>('disconnected')
  const wsRef = useRef<WebSocket | null>(null)
  const backoffRef = useRef(1000)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const closedByUsRef = useRef(false)

  useEffect(() => {
    if (!roomId) {
      setStatus('disconnected')
      return
    }

    closedByUsRef.current = false

    const clearReconnect = () => {
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
    }

    const connect = () => {
      const token = getAuthToken()
      if (!token) {
        setStatus('disconnected')
        return
      }

      clearReconnect()
      setStatus('connecting')

      const ws = new WebSocket(buildRoomWebSocketUrl(token))
      wsRef.current = ws

      ws.onopen = () => {
        backoffRef.current = 1000
        ws.send(JSON.stringify({ type: 'subscribe_room', room_id: roomId }))
      }

      ws.onmessage = (event) => {
        let message: RoomWebSocketMessage
        try {
          message = JSON.parse(String(event.data)) as RoomWebSocketMessage
        } catch {
          return
        }

        if (message.type === 'subscribed') {
          setStatus('connected')
          return
        }

        if (message.type === 'room_error') {
          setStatus('disconnected')
          return
        }

        if (message.type === 'pong') {
          return
        }

        invalidateForEvent(queryClient, roomId, message)
      }

      ws.onerror = () => {
        // onclose handles reconnect
      }

      ws.onclose = () => {
        setStatus('disconnected')
        wsRef.current = null
        if (closedByUsRef.current) {
          return
        }
        const delay = backoffRef.current
        backoffRef.current = Math.min(MAX_BACKOFF_MS, delay * 2)
        reconnectTimerRef.current = setTimeout(connect, delay)
      }
    }

    connect()

    return () => {
      closedByUsRef.current = true
      clearReconnect()
      const ws = wsRef.current
      wsRef.current = null
      if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
        try {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'unsubscribe_room', room_id: roomId }))
          }
        } catch {
          // ignore
        }
        ws.close()
      }
      setStatus('disconnected')
    }
  }, [roomId, queryClient])

  return { status }
}
