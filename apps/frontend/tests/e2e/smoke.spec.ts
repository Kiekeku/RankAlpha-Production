import { test, expect } from '@playwright/test'

test.describe('frontend smoke', () => {
  test('redirects home to overview nowcast', async ({ page }) => {
    await page.goto('/')
    const overviewLink = page.getByRole('link', { name: /open overview/i })
    await expect(overviewLink).toBeVisible()
    await expect(overviewLink).toHaveAttribute('href', /\/overview\/nowcast/)
  })

  test('rankings page shows header', async ({ page }) => {
    await page.goto('/rankings')
    await expect(page.getByRole('heading', { name: 'Rankings', level: 1 })).toBeVisible()
  })

  test('screener page shows header', async ({ page }) => {
    await page.goto('/screener')
    await expect(page.getByRole('heading', { name: 'Screener' })).toBeVisible()
  })

  test('ai feed page shows header', async ({ page }) => {
    await page.goto('/ai-analysis')
    await expect(page.getByRole('heading', { name: 'AI Feed' })).toBeVisible()
  })
})
