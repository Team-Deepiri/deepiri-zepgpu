import { describe, expect, it } from 'vitest'
import { ensureList } from '@/utils/listUtils'

describe('ensureList', () => {
  it('returns bare arrays unchanged', () => {
    expect(ensureList([1, 2, 3])).toEqual([1, 2, 3])
  })

  it('unwraps nested list keys', () => {
    expect(ensureList({ schedules: [{ id: '1' }], total: 1 }, 'schedules')).toEqual([{ id: '1' }])
    expect(ensureList({ namespaces: [], total: 0 }, 'namespaces')).toEqual([])
  })

  it('returns empty array for invalid values', () => {
    expect(ensureList(null)).toEqual([])
    expect(ensureList(undefined)).toEqual([])
    expect(ensureList({ total: 0 }, 'schedules')).toEqual([])
    expect(ensureList({ schedules: [], total: 0 })).toEqual([])
  })
})
