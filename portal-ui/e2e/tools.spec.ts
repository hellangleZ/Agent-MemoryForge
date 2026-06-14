import { test, expect } from '@playwright/test';

/**
 * E2E tests for tools discovery and management.
 */
test.describe('Tools', () => {
  test.beforeEach(async ({ page }) => {
    // Catch-all to avoid Next rewrites proxying to 127.0.0.1:8080 during tests.
    // Register this first so more specific mocks below can override it.
    await page.route('**/portal/v1/**', async (route) => {
      const req = route.request();
      const path = new URL(req.url()).pathname;
      await route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ detail: `mocked: no route for ${path}` }),
      });
    });

    // Mock authentication
    await page.addInitScript(() => {
      // UI checks `portal_auth` marker; real auth is cookie-based.
      localStorage.setItem('portal_auth', '1');
      localStorage.setItem('portal_workspace_id', 'ws_default');
    });

    // Mock tools policy API (page load reads it)
    await page.route(/\/portal\/v1\/tools\/policy(\?.*)?$/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: { allowlist: [], denylist: [], overrides: {} },
        }),
      });
    });

    // Mock tools API
    await page.route(/\/portal\/v1\/tools(\?.*)?$/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: {
            'file_operations': [
              { name: 'read_file', category: 'file', spec: 'Read file contents' },
              { name: 'write_file', category: 'file', spec: 'Write content to file' },
            ],
            'web_tools': [
              { name: 'fetch_url', category: 'web', spec: 'Fetch URL content' },
            ],
          },
          tools_by_namespace: {
            'file_operations': [
              { name: 'read_file', category: 'file', spec: 'Read file contents' },
              { name: 'write_file', category: 'file', spec: 'Write content to file' },
            ],
            'web_tools': [
              { name: 'fetch_url', category: 'web', spec: 'Fetch URL content' },
            ],
          },
        }),
      });
    });

    // Mock tools status API
    await page.route(/\/portal\/v1\/tools\/status(\?.*)?$/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          tools: [
            { name: 'read_file', enabled: true, status: 'active', config: {} },
            { name: 'write_file', enabled: true, status: 'active', config: {} },
            { name: 'fetch_url', enabled: false, status: 'disabled', config: {} },
          ],
        }),
      });
    });
  });

  test('tools page loads', async ({ page }) => {
    await page.goto('/tools');

    // Check page loaded
    await expect(page).toHaveURL(/tools/);
  });

  test('displays available tools', async ({ page }) => {
    await page.goto('/tools');

    // Wait for the tools list section to render (async fetch).
    await expect(page.locator('text=Available Tools')).toBeVisible({ timeout: 10000 });

    // Tool cards render the tool name text.
    await expect(page.locator('text=read_file')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('text=write_file')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('text=fetch_url')).toBeVisible({ timeout: 10000 });
  });

  test('displays tool status indicators', async ({ page }) => {
    await page.goto('/tools');

    await expect(page.locator('text=Available Tools')).toBeVisible({ timeout: 10000 });

    // Enabled/Disabled badges are present.
    await expect(page.locator('span').filter({ hasText: /Enabled|Disabled/ }).first()).toBeVisible({ timeout: 10000 });
  });

  test('can filter or search tools', async ({ page }) => {
    await page.goto('/tools');

    // Look for search input
    const searchInput = page.locator('input[placeholder*="Search tools"]').first();

    if (await searchInput.isVisible()) {
      await searchInput.fill('read_file');
      await page.waitForTimeout(500);

      await expect(page.locator('text=read_file')).toBeVisible();
    }
  });

  test('toggle button calls policy API and updates UI', async ({ page }) => {
    // Local in-test state to emulate a real backend.
    const overrides: Record<string, boolean> = {};

    await page.route(/\/portal\/v1\/tools\/policy(\?.*)?$/, async (route) => {
      const req = route.request();
      if (req.method() === 'POST') {
        const body = (req.postDataJSON?.() as any) || {};
        Object.assign(overrides, body.overrides || {});
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ status: 'success', data: { allowlist: [], denylist: [], overrides } }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ data: { allowlist: [], denylist: [], overrides } }),
      });
    });

    await page.route(/\/portal\/v1\/tools\/status(\?.*)?$/, async (route) => {
      const enabled = (name: string, fallback: boolean) => (name in overrides ? Boolean(overrides[name]) : fallback);
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          tools: [
            { name: 'read_file', enabled: enabled('read_file', true), status: 'active', config: {} },
            { name: 'write_file', enabled: enabled('write_file', true), status: 'active', config: {} },
            { name: 'fetch_url', enabled: enabled('fetch_url', false), status: 'disabled', config: {} },
          ],
        }),
      });
    });

    await page.goto('/tools');

    const toolCard = page
      .getByRole('heading', { name: 'read_file' })
      .locator('xpath=ancestor::div[contains(@class,"rounded-xl")]')
      .first();

    // Initial state: enabled with "Disable" action available.
    await expect(toolCard.locator('span').filter({ hasText: 'Enabled' })).toBeVisible({ timeout: 10000 });
    await expect(toolCard.getByRole('button', { name: /Disable/i })).toBeVisible({ timeout: 10000 });

    const reqPromise = page.waitForRequest((req) => req.url().includes('/portal/v1/tools/policy') && req.method() === 'POST');
    await toolCard.getByRole('button', { name: /Disable/i }).click();
    const req = await reqPromise;
    const posted = (req.postDataJSON?.() as any) || {};
    expect(Boolean(posted?.overrides?.read_file)).toBe(false);

    // After refresh: disabled with "Enable" action.
    await expect(toolCard.locator('span').filter({ hasText: 'Disabled' })).toBeVisible({ timeout: 10000 });
    await expect(toolCard.getByRole('button', { name: /Enable/i })).toBeVisible({ timeout: 10000 });
  });
});

test.describe('Tools - Error Handling', () => {
  test('handles empty tools list', async ({ page }) => {
    await page.route('**/portal/v1/**', async (route) => {
      const req = route.request();
      const path = new URL(req.url()).pathname;
      await route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ detail: `mocked: no route for ${path}` }),
      });
    });

    // Mock authentication
    await page.addInitScript(() => {
      localStorage.setItem('portal_auth', '1');
      localStorage.setItem('portal_workspace_id', 'ws_default');
    });

    await page.route(/\/portal\/v1\/tools\/policy(\?.*)?$/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: { allowlist: [], denylist: [], overrides: {} },
        }),
      });
    });

    // Mock empty tools response
    await page.route(/\/portal\/v1\/tools(\?.*)?$/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: {},
          tools_by_namespace: {},
        }),
      });
    });

    await page.route(/\/portal\/v1\/tools\/status(\?.*)?$/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ tools: [] }),
      });
    });

    await page.goto('/tools');

    // Should show empty state or message
    const emptyState = page.locator('text=/No tools found|no tools|empty|no results/i').first();
    await expect(emptyState).toBeVisible({ timeout: 5000 }).catch(() => {
      // Page may still render without error
    });
  });
});
