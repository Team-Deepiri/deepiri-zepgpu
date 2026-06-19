import { test, expect } from '@playwright/test'
import { loginAsTestUser } from './helpers/auth'

/** Run with E2E_ROOMS_BACKEND=1 once Kapill's /api/v1/rooms/* endpoints are live. */
const describe = process.env.E2E_ROOMS_BACKEND === '1' ? test.describe : test.describe.skip

describe('GPU Rooms list', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsTestUser(page)
  })

  test('loads rooms page and shows seed room', async ({ page }) => {
    await page.goto('/rooms')
    await expect(page.getByRole('heading', { name: 'GPU Rooms' })).toBeVisible()
    await expect(page.getByText('Team Alpha')).toBeVisible()
  })

  test('creates a room', async ({ page }) => {
    await page.goto('/rooms')
    await page.getByLabel(/^Name$/).fill('E2E Room')
    await page.getByRole('button', { name: 'Create room' }).click()
    await expect(page.getByText('E2E Room')).toBeVisible()
  })

  test('navigates to room detail', async ({ page }) => {
    await page.goto('/rooms')
    await page.getByRole('link', { name: /Team Alpha/i }).click()
    await expect(page.getByRole('heading', { name: 'Team Alpha' })).toBeVisible()
    await expect(page.getByText('Members')).toBeVisible()
  })
})
