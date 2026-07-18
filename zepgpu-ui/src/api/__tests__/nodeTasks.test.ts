import { describe, expect, it, beforeEach } from 'vitest'
import { nodeTasksApi } from '@/api/nodeTasks'
import { fixtureNodeTaskResult } from '@/test/fixtures/tasks'

describe('nodeTasksApi (MSW)', () => {
  beforeEach(() => {
    localStorage.setItem('token', 'test-token')
  })

  it('getResult returns assignment result for host', async () => {
    const result = await nodeTasksApi.getResult(fixtureNodeTaskResult.assignment_id)
    expect(result.task_id).toBe(fixtureNodeTaskResult.task_id)
    expect(result.assignment_status).toBe('completed')
    expect(result.result_metadata).toEqual({ remote_result: { ok: true } })
  })

  it('getResult throws for unknown assignment', async () => {
    await expect(
      nodeTasksApi.getResult('00000000-0000-4000-8000-000000000000'),
    ).rejects.toThrow()
  })
})
