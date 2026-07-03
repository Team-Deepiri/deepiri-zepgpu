import { test, expect } from '@playwright/test'
import { loginAsTestUser } from './helpers/auth'

const describe = process.env.E2E_ROOMS_BACKEND === '1' ? test.describe : test.describe.skip

const SAMPLE_ROOM_ID = '22222222-2222-4222-8222-222222222222'

describe('Room nodes', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsTestUser(page)
  })

  test('shows nodes section and GPU pool on room detail', async ({ page }) => {
    await page.goto(`/rooms/${SAMPLE_ROOM_ID}`)
    await expect(page.getByRole('heading', { name: 'Team Alpha' })).toBeVisible()
    await expect(page.getByRole('heading', { name: /Nodes/i })).toBeVisible()
    await expect(page.getByText(/Total GPUs:/)).toBeVisible()
    await expect(page.getByText(/Available \(usable now\)/)).toBeVisible()
  })
})
