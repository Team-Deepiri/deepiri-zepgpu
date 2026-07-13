/**
 * Host-facing node task API — read assignment results after remote execution.
 */
import api from '@/api/client'
import type { NodeTaskResult } from '@/types'

export const nodeTasksApi = {
  getResult: async (assignmentId: string): Promise<NodeTaskResult> => {
    const { data } = await api.get<NodeTaskResult>(`/node-tasks/${assignmentId}/result`)
    return data
  },
}
