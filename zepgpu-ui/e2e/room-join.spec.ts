import { test, expect } from '@playwright/test'
import { loginAsTestUser } from './helpers/auth'

/** Run with E2E_ROOMS_BACKEND=1 once Kapill's /api/v1/rooms/* endpoints are live. */
const describe = process.env.E2E_ROOMS_BACKEND === '1' ? test.describe : test.describe.skip

describe('Join room', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsTestUser(page)
  })

  test('shows error for expired invite', async ({ page }) => {
    await page.goto('/rooms')
    await page.getByLabel('Invite code').fill('EXPIRED1')
    await page.getByRole('button', { name: 'Join room' }).click()
    await expect(page.getByText('Invite has expired')).toBeVisible()
  })

  test('shows error for revoked invite', async ({ page }) => {
    await page.goto('/rooms')
    await page.getByLabel('Invite code').fill('REVOKED1')
    await page.getByRole('button', { name: 'Join room' }).click()
    await expect(page.getByText('Invite has been revoked')).toBeVisible()
  })
})
