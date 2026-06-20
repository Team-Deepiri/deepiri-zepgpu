import { test, expect } from '@playwright/test'
import { loginAsTestUser } from './helpers/auth'

test.describe('VPN regression', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsTestUser(page)
  })

  test('VPN Pool page still loads', async ({ page }) => {
    await page.goto('/vpn')
    await expect(page.getByRole('heading', { name: /VPN & GPU pool/i })).toBeVisible()
    await expect(page.getByText('My networks')).toBeVisible()
    await expect(page.getByText('Join with code')).toBeVisible()
  })

  test('GPU Rooms nav is separate from VPN Pool', async ({ page }) => {
    await page.goto('/rooms')
    await expect(page.getByRole('heading', { name: 'GPU Rooms' })).toBeVisible()
    await page.goto('/vpn')
    await expect(page.getByRole('heading', { name: /VPN & GPU pool/i })).toBeVisible()
  })
})
