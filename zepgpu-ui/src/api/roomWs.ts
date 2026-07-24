/**
 * Build the room WebSocket URL using the current page origin and JWT.
 */
export function buildRoomWebSocketUrl(token: string): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  return `${protocol}//${host}/api/v1/ws/rooms?token=${encodeURIComponent(token)}`
}
