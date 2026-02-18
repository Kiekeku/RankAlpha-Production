import { defineConfig, devices } from '@playwright/test'

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000'

const shouldStartWebServer = (() => {
  if (process.env.PLAYWRIGHT_NO_WEB_SERVER) return false
  try {
    const { hostname } = new URL(baseURL)
    return hostname === 'localhost' || hostname === '127.0.0.1'
  } catch {
    return true
  }
})()

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  webServer: shouldStartWebServer
    ? {
        command: 'pnpm dev',
        url: baseURL,
        env: {
          PLAYWRIGHT_MOCKS: '1',
        },
        reuseExistingServer: process.env.PLAYWRIGHT_REUSE_SERVER === '1',
        timeout: 120_000,
      }
    : undefined,
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
