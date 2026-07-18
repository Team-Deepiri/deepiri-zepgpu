import { describe, expect, it } from 'vitest'
import { fixtureCompletedRoomTask, fixtureDispatchedTask } from '@/test/fixtures/tasks'
import { isActiveStatus, isTerminalTaskStatus, shouldPollTask } from '@/utils/taskStatus'

describe('task status utilities', () => {
  it('identifies active task statuses', () => {
    expect(isActiveStatus('assigned')).toBe(true)
    expect(isActiveStatus('completed')).toBe(false)
    expect(isActiveStatus(undefined)).toBe(false)
  })

  it('identifies terminal task statuses', () => {
    expect(isTerminalTaskStatus('failed')).toBe(true)
    expect(isTerminalTaskStatus('running')).toBe(false)
    expect(isTerminalTaskStatus(undefined)).toBe(false)
  })

  it('polls missing and active tasks but stops for terminal tasks', () => {
    expect(shouldPollTask(undefined)).toBe(true)
    expect(shouldPollTask(fixtureDispatchedTask)).toBe(true)
    expect(shouldPollTask(fixtureCompletedRoomTask)).toBe(false)
  })
})
