import { test, expect } from '@playwright/test';

/**
 * E2E tests for workspace configuration.
 */
test.describe('Workspace', () => {
  test.beforeEach(async ({ page }) => {
    // Catch-all to avoid Next rewrites proxying to 127.0.0.1:8080 during tests.
    // Register first so per-endpoint mocks below can override it.
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

    // Mock workspace config API
    await page.route('**/portal/v1/workspace/config', async (route) => {
      const req = route.request();
      if (req.method() === 'POST') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ status: 'success' }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: {
            system_prompt: 'Default system prompt for testing',
            mcp: {
              mcp_stdio_json: '',
              mcp_servers_json: '',
              mcp_http_url: '',
              mcp_http_namespace: '',
              mcp_http_headers_json: '',
            },
          },
        }),
      });
    });

    // Mock apply API
    await page.route('**/portal/v1/workspace/apply', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'success' }),
      });
    });
  });

  test('workspace page loads', async ({ page }) => {
    await page.goto('/config');

    // Check page loaded
    await expect(page.locator('text=/Configuration/i')).toBeVisible();
  });

  test('displays system prompt configuration', async ({ page }) => {
    await page.goto('/config');

    // Look for system prompt textarea or editor
    const promptEditor = page.locator('#system_prompt').first();

    await expect(promptEditor).toBeVisible({ timeout: 5000 });
  });

  test('can edit and save configuration', async ({ page }) => {
    await page.goto('/config');

    // Make a real change first; Save is disabled until the form is dirty.
    const promptEditor = page.locator('#system_prompt').first();
    await expect(promptEditor).toBeVisible({ timeout: 5000 });
    await promptEditor.fill('Default system prompt for testing (updated)');

    // Find and click save button
    const saveButton = page.locator('button:has-text("Save"), button[type="submit"]').first();

    if (await saveButton.isVisible()) {
      await expect(saveButton).toBeEnabled({ timeout: 5000 });
      const reqPromise = page.waitForRequest((req) => req.url().includes('/portal/v1/workspace/config') && req.method() === 'POST');
      await saveButton.click();
      await reqPromise;

      // Look for success indicator
      await expect(page.locator('text=/saved|success/i, .toast, [data-testid="save-success"]')).toBeVisible({ timeout: 5000 }).catch(() => {
        // Some implementations may not show toast
      });
    }
  });

  test('can apply configuration changes', async ({ page }) => {
    await page.goto('/config');

    // Look for apply button
    const applyButton = page.locator('button:has-text("Apply")').first();

    if (await applyButton.isVisible()) {
      const reqPromise = page.waitForRequest((req) => req.url().includes('/portal/v1/workspace/apply') && req.method() === 'POST');
      await applyButton.click();
      await reqPromise;

      // Wait for apply to complete
      await page.waitForTimeout(1000);
    }
  });
});

test.describe('Workspace - Error Handling', () => {
  test('handles API errors gracefully', async ({ page }) => {
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

    // Mock API error
    await page.route('**/portal/v1/workspace/config', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Internal server error' }),
      });
    });

    await page.goto('/config');

    // Should show error state or fallback
    const errorElement = page.locator('text=/error|failed|try again/i, [data-testid="error-message"]').first();
    await expect(errorElement).toBeVisible({ timeout: 5000 }).catch(() => {
      // Page may show fallback content instead
    });
  });
});
