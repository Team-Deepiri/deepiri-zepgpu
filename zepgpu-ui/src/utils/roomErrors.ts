import axios from 'axios'

/** Used in tests to simulate backend error responses with status + detail. */
export class RoomApiError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'RoomApiError'
    this.status = status
    this.detail = detail
  }
}

export function getRoomErrorMessage(err: unknown, fallback = 'Something went wrong'): string {
  if (err instanceof RoomApiError) {
    return err.detail
  }
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string') {
      return detail
    }
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => (typeof item === 'object' && item && 'msg' in item ? String(item.msg) : null))
        .filter(Boolean)
      if (messages.length > 0) {
        return messages.join(', ')
      }
    }
  }
  if (err instanceof Error && err.message) {
    return err.message
  }
  return fallback
}

export function getRoomErrorStatus(err: unknown): number | null {
  if (err instanceof RoomApiError) return err.status
  if (axios.isAxiosError(err)) return err.response?.status ?? null
  return null
}
