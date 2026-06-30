import { test, expect } from '@playwright/test'
import { loginAsTestUser } from './helpers/auth'

/** Run with E2E_ROOMS_BACKEND=1 against a live /api/v1/rooms/* backend. */
const describe = process.env.E2E_ROOMS_BACKEND === '1' ? test.describe : test.describe.skip

const SAMPLE_ROOM_ID = '22222222-2222-4222-8222-222222222222'

describe('Room detail', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsTestUser(page)
  })

  test('shows members and GPU pool', async ({ page }) => {
    await page.goto(`/rooms/${SAMPLE_ROOM_ID}`)
    await expect(page.getByRole('heading', { name: 'Team Alpha' })).toBeVisible()
    await expect(page.getByText('host-user')).toBeVisible()
    await expect(page.getByText('Total GPUs:')).toBeVisible()
  })

  test('creates and copies invite', async ({ page }) => {
    await page.goto(`/rooms/${SAMPLE_ROOM_ID}`)
    await page.getByRole('button', { name: 'Create invite' }).click()
    await expect(page.getByText('New code:')).toBeVisible({ timeout: 5000 })
  })

  test('loads connection config', async ({ page }) => {
    await page.goto(`/rooms/${SAMPLE_ROOM_ID}`)
    await expect(page.getByRole('button', { name: 'Copy config' })).toBeVisible({
      timeout: 5000,
    })
  })

  test('shows not found for invalid room', async ({ page }) => {
    await page.goto('/rooms/00000000-0000-4000-8000-000000000000')
    await expect(page.getByText('Room not found')).toBeVisible()
  })
})
