import { test, expect } from '@playwright/test'
import { loginAsTestUser } from './helpers/auth'

/** Run with E2E_ROOMS_BACKEND=1 against a live /api/v1 backend with WS enabled. */
const describe = process.env.E2E_ROOMS_BACKEND === '1' ? test.describe : test.describe.skip

const SAMPLE_ROOM_ID = '22222222-2222-4222-8222-222222222222'

describe('Room WebSocket live updates', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsTestUser(page)
  })

  test('shows live connection status on room detail', async ({ page }) => {
    await page.goto(`/rooms/${SAMPLE_ROOM_ID}`)
    await expect(page.getByText(/Live (connected|connecting)/i)).toBeVisible({
      timeout: 10000,
    })
  })
})
