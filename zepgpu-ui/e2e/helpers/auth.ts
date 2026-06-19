import { Page } from '@playwright/test'

export async function loginAsTestUser(page: Page) {
  await page.route('**/api/v1/auth/login', async (route) => {
    await route.fulfill({
      json: { access_token: 'e2e-test-token', token_type: 'bearer' },
    })
  })

  await page.route('**/api/v1/users/me', async (route) => {
    await route.fulfill({
      json: {
        id: '11111111-1111-4111-8111-111111111111',
        username: 'e2e-user',
        email: 'e2e@test.com',
        role: 'user',
        is_active: true,
        created_at: '2026-01-01T00:00:00.000Z',
        last_login: null,
        namespace_ids: [],
        total_tasks: 0,
        total_gpu_hours: 0,
      },
    })
  })

  await page.goto('/login')
  await page.getByPlaceholder('Enter your username').fill('e2e-user')
  await page.getByPlaceholder('Enter your password').fill('password')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.waitForURL('/')
}
