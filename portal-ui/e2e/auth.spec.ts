import { test, expect } from '@playwright/test';

/**
 * E2E tests for authentication flow.
 */
test.describe('Authentication', () => {
  test.beforeEach(async ({ page }) => {
    // Start each test from a clean state
    await page.context().clearCookies();
    await page.addInitScript(() => {
      localStorage.clear();
      localStorage.setItem('portal_workspace_id', 'ws_default');
    });
  });

  test('login page loads', async ({ page }) => {
    await page.goto('/login');

    // Check page title
    await expect(page).toHaveTitle(/Agent-MemoryForge Portal/);

    // Check login form elements exist
    await expect(page.locator('#username')).toBeVisible();
    await expect(page.locator('#password')).toBeVisible();
    await expect(page.locator('button[type="submit"]')).toBeVisible();
  });

  test('shows error on invalid credentials', async ({ page }) => {
    await page.route('**/portal/v1/login', async (route) => {
      await route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Invalid credentials' }),
      });
    });
    await page.goto('/login');

    // Fill in invalid credentials
    await page.locator('#username').fill('invalid_user');
    await page.locator('#password').fill('invalid_password');

    // Submit form
    await page.locator('button[type="submit"]').click();

    // Should show error message
    await expect(page.getByText(/Login failed/i)).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=/401/').first()).toBeVisible({ timeout: 5000 });
  });

  test('shows already logged in only when the server session is valid', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('portal_auth', '1');
    });
    await page.route('**/portal/v1/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id: 'u', email: 'u@example.com', role: 'user', created_at: '2026-01-01T00:00:00Z' }),
      });
    });

    await page.goto('/login');

    await expect(page.locator('text=/Already Logged In/i')).toBeVisible();
  });

  test('clears stale login marker when the server session is invalid', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('portal_auth', '1');
    });
    await page.route('**/portal/v1/me', async (route) => {
      await route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Not authenticated' }),
      });
    });

    await page.goto('/login');

    await expect(page.locator('#username')).toBeVisible();
    await expect(page.locator('text=/Already Logged In/i')).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => localStorage.getItem('portal_auth'))).toBeNull();
  });
});

// NOTE: The portal currently does not hard-redirect on most routes when unauthenticated.
// Auth gating is primarily used for API calls; route-level guards can be added later.
