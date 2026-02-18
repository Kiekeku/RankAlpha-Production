import { test, expect } from '@playwright/test'
import { mockPipelineHealth, mockRankingsApi, mockScreenerApi } from './api-mocks'

test.describe('frontend UX flows', () => {
  test('compare tray opens from header and navigates to compare page', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem(
        'rankalpha.compare.v2',
        JSON.stringify({
          v: 2,
          symbols: ['AAA', 'BBB'],
          baseline: 'AAA',
          showDeltas: true,
          deltaMode: 'abs',
        }),
      )
    })
    await mockRankingsApi(page)
    await page.goto('/rankings')

    await page.getByRole('button', { name: /open compare/i }).click()
    const tray = page.getByRole('region', { name: 'Compare tray' })
    await expect(tray).toBeVisible()
    await expect(tray.getByText('Compare 2/3')).toBeVisible()

    const expandButton = tray.getByRole('button', { name: /expand compare tray/i })
    if (await expandButton.isVisible()) {
      await expandButton.click()
    }

    const openCompareLink = tray.getByRole('link', { name: 'Open Compare' })
    await expect(openCompareLink).toHaveAttribute('href', /\/compare/)
  })

  test('saved views can save, load, and delete', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('rankalpha.rankings.saved_views.v1')
    })
    await mockRankingsApi(page)
    await page.goto('/rankings')

    await page.getByRole('button', { name: /saved views/i }).click()
    await page.waitForURL(/views=1/)
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await page.getByLabel('View name').fill('My test view')
    await page.getByRole('button', { name: /save current view/i }).click()

    await expect(dialog.getByText('My test view', { exact: true })).toBeVisible()
    await dialog.getByRole('button', { name: 'Load' }).click()
    await dialog.getByRole('button', { name: 'Delete' }).click()
    await expect(dialog.getByText('Create your first saved view')).toBeVisible()
  })

  test('ai detail uses section nav anchors', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/ai-analysis/TEST?analysis_id=mock')
    const nav = page.getByRole('navigation', { name: 'On this page' })
    await expect(nav).toBeVisible({ timeout: 10_000 })

    await nav.getByRole('link', { name: 'Risks' }).click()
    await expect(page).toHaveURL(/#risks$/)

    await nav.getByRole('link', { name: /back to top/i }).click()
    await expect(page).toHaveURL(/#top$/)
    await expect(page.getByText('External snippets (unverified)')).toBeVisible()
  })

  test('screener columns dialog toggles and persists params', async ({ page }) => {
    await mockScreenerApi(page)
    await page.goto('/screener')

    await page.getByRole('button', { name: 'Columns' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByText('Result columns')).toBeVisible()

    const aiCheckbox = dialog.getByLabel('AI Snapshot')
    await aiCheckbox.click()
    await expect.poll(() => new URL(page.url()).searchParams.get('cols')).not.toBeNull()

    await dialog.getByRole('button', { name: /reset to default/i }).click()
    await dialog.getByRole('button', { name: /done/i }).click()
  })

  test('rankings filters show chips and clear all', async ({ page }) => {
    await mockRankingsApi(page)
    await page.goto('/rankings')

    await page.getByLabel('Search').fill('AAPL')
    await expect.poll(() => new URL(page.url()).searchParams.get('q')).toBe('AAPL')
    await expect(page.getByText('Search: AAPL', { exact: true }).first()).toBeVisible()

    await page.getByRole('button', { name: 'Clear all' }).click()
    await expect(page.getByLabel('Search')).toHaveValue('')
  })

  test('rankings checkbox select does not navigate, row click opens ticker', async ({ page }) => {
    await mockRankingsApi(page)
    await page.goto('/rankings')

    const checkbox = page.getByRole('checkbox', { name: /add aaa to compare/i })
    const startingUrl = page.url()
    await checkbox.click()
    await expect(page).toHaveURL(startingUrl)

    const row = page.getByRole('button', { name: /AAA/ }).first()
    await row.click()
    await expect(page).toHaveURL(/\/ticker\/AAA/i)
  })

  test('data status panel shows cadence and refresh info', async ({ page }) => {
    await mockPipelineHealth(page)
    await page.goto('/rankings')

    const statusButton = page.getByRole('button', { name: /data status/i })
    await expect(statusButton).toBeVisible()
    await statusButton.click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByText('Expected cadence')).toBeVisible()
    await expect(dialog.getByText('Ingestion: nightly after US close.')).toBeVisible()
    await expect(dialog.getByText('Last successful refresh')).toBeVisible()
  })
})
