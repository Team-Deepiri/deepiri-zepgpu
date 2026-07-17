import { test, expect } from '@playwright/test'
import { loginAsTestUser } from './helpers/auth'

/** Run with E2E_ROOMS_BACKEND=1 against a live backend with room dispatch enabled. */
const describe = process.env.E2E_ROOMS_BACKEND === '1' ? test.describe : test.describe.skip

const SAMPLE_ROOM_ID = '22222222-2222-4222-8222-222222222222'

describe('Room dispatch', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsTestUser(page)
  })

  test('shows dispatch panel and session activity on room detail', async ({ page }) => {
    await page.goto(`/rooms/${SAMPLE_ROOM_ID}`)
    await expect(page.getByRole('heading', { name: 'Dispatch task' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Session activity' })).toBeVisible()
    await expect(page.getByText(/Dispatched tasks appear here/i)).toBeVisible()
  })

  test('dispatches a room_auto task from the panel', async ({ page }) => {
    await page.goto(`/rooms/${SAMPLE_ROOM_ID}`)
    await page.getByLabel('Task name (optional)').fill('E2E room dispatch')
    await page.getByLabel('Function').fill('random.seed')
    await page.getByRole('button', { name: 'Dispatch to room' }).click()
    await expect(page.getByText(/E2E room dispatch|assigned/i)).toBeVisible({ timeout: 10000 })
  })
})
