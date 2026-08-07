const { defineConfig, devices } = require('@playwright/test');

const port = Number(process.env.SPEAKCHAIN_E2E_PORT || 4173);
const baseURL = `http://127.0.0.1:${port}`;

module.exports = defineConfig({
  testDir: './e2e',
  testMatch: '**/*.spec.js',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 2,
  timeout: 60_000,
  expect: { timeout: 7_000 },
  reporter: process.env.CI
    ? [['line'], ['html', { outputFolder: 'playwright-report', open: 'never' }]]
    : 'line',
  outputDir: 'test-results',
  use: {
    baseURL,
    locale: 'uk-UA',
    timezoneId: 'Europe/Kyiv',
    serviceWorkers: 'block',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off'
  },
  projects: [
    {
      name: 'chromium-desktop',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1280, height: 900 }
      }
    },
    {
      name: 'chromium-mobile',
      use: {
        ...devices['Pixel 7']
      }
    }
  ],
  webServer: process.env.SPEAKCHAIN_E2E_EXTERNAL_SERVER ? undefined : {
    command: `node e2e/static-server.mjs ${port}`,
    url: `${baseURL}/index_v2.html`,
    reuseExistingServer: !process.env.CI,
    timeout: 15_000,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 1_000 },
    stdout: 'pipe',
    stderr: 'pipe'
  }
});
