import { test, expect } from '@playwright/test'
import { mockPipelineHealth, mockRankingsApi } from './api-mocks'

test.describe('frontend UI flows', () => {
  test('saved views drawer opens from rankings', async ({ page }) => {
    await mockRankingsApi(page)
    await page.goto('/rankings')
    await page.getByRole('button', { name: /saved views/i }).click()
    await page.waitForURL(/views=1/)
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole('button', { name: /save current view/i })).toBeVisible()
    await expect(dialog.getByRole('button', { name: /copy link to current view/i })).toBeVisible()
  })

  test('compare shows baseline and deltas helper', async ({ page }) => {
    await page.goto('/compare?symbols=AAPL,MSFT')
    await expect(page.getByText('Baseline (reference)')).toBeVisible()
    const baselineSelect = page.getByLabel('Select baseline ticker')
    await expect(baselineSelect).toBeVisible()
    await expect(baselineSelect).toHaveValue('AAPL')
    const tooltipTrigger = page.getByRole('button', { name: 'Explain deltas' })
    await tooltipTrigger.hover()
    await expect(page.getByText(/Deltas compare each metric against the baseline ticker/i)).toBeVisible()
  })

  test('data status panel opens from nav', async ({ page }) => {
    await mockPipelineHealth(page)
    await page.goto('/rankings')
    const statusButton = page.getByRole('button', { name: /data status/i })
    await expect(statusButton).toBeVisible()
    await statusButton.click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('heading', { name: 'Data Status' })).toBeVisible()
    await expect(dialog.getByText('Affected modules', { exact: true })).toBeVisible()
  })

  test('collapsed filter rail can be expanded', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('rankalpha.rankings.filtersCollapsed.v1')
    })
    await page.goto('/rankings')
    const collapseFilters = page.getByRole('button', { name: 'Collapse filters' })
    const showFilters = page.getByRole('button', { name: 'Show filters' })
    if (await collapseFilters.isVisible()) {
      await collapseFilters.click()
      await expect(showFilters).toBeVisible()
      await showFilters.click()
      await expect(collapseFilters).toBeVisible()
    } else if (await showFilters.isVisible()) {
      await showFilters.click()
      await expect(collapseFilters).toBeVisible()
    } else {
      await expect(collapseFilters).toBeVisible()
    }
  })
})
