import { defineConfig, devices } from '@playwright/test';

const e2eHost = process.env.E2E_HOST || '127.0.0.1';
const e2ePort = process.env.E2E_PORT || '3000';
const baseURL = process.env.E2E_BASE_URL || `http://${e2eHost}:${e2ePort}`;
const reuseExistingServer = process.env.E2E_REUSE_EXISTING_SERVER === '1';
const skipWebServer = process.env.E2E_SKIP_WEB_SERVER === '1';

/**
 * Playwright configuration for Agent-MemoryForge Portal E2E tests.
 * @see https://playwright.dev/docs/test-configuration
 */
export default defineConfig({
  // Test directory
  testDir: './e2e',

  // Run tests in parallel
  fullyParallel: true,

  // Fail build on CI if you accidentally left test.only in source code
  forbidOnly: !!process.env.CI,

  // Retry on CI only
  retries: process.env.CI ? 2 : 0,

  // Parallel workers (limit on CI)
  workers: process.env.CI ? 1 : undefined,

  // Reporter configuration
  reporter: [
    ['html', { outputFolder: 'playwright-report' }],
    ['list'],
  ],

  // Shared settings for all tests
  use: {
    // Base URL for tests
    baseURL,

    // Collect trace on failure
    trace: 'on-first-retry',

    // Screenshot on failure
    screenshot: 'only-on-failure',

    // Video on failure
    video: 'on-first-retry',
  },

  // Configure projects for major browsers
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
    },
    {
      name: 'webkit',
      use: { ...devices['Desktop Safari'] },
    },

    // Mobile viewports
    {
      name: 'mobile-chrome',
      use: { ...devices['Pixel 5'] },
    },
    {
      name: 'mobile-safari',
      use: { ...devices['iPhone 12'] },
    },
  ],

  // Run a fresh dev server before tests unless explicitly disabled.
  webServer: skipWebServer ? undefined : {
    command: `HOST=${e2eHost} PORT=${e2ePort} npm run dev:custom`,
    url: baseURL,
    reuseExistingServer,
    timeout: 120 * 1000,
  },
});
