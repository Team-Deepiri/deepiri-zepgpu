import '@testing-library/jest-dom/vitest'
import { afterAll, afterEach, beforeAll, vi } from 'vitest'
import { setupServer } from 'msw/node'
import { roomHandlers } from '@/test/handlers/rooms'
import { taskHandlers } from '@/test/handlers/tasks'

export const clipboardWriteTextMock = vi.fn().mockResolvedValue(undefined)

Object.defineProperty(globalThis.navigator, 'clipboard', {
  configurable: true,
  writable: true,
  value: {
    writeText: clipboardWriteTextMock,
  },
})

export const server = setupServer(...roomHandlers, ...taskHandlers)

beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' })
})

afterEach(() => {
  server.resetHandlers()
  localStorage.clear()
  clipboardWriteTextMock.mockClear()
})

afterAll(() => {
  server.close()
})
