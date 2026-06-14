import { test, expect } from '@playwright/test';

test.describe('Chat', () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await page.addInitScript(() => {
      localStorage.setItem('portal_auth', '1');
      localStorage.setItem('portal_workspace_id', 'ws_default');
    });
  });

  test('blocks sending when the local auth marker is stale', async ({ page }) => {
    let chatCalls = 0;

    await page.route('**/portal/v1/me', async (route) => {
      await route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Not authenticated' }),
      });
    });

    await page.route('**/v1/chat/stream', async (route) => {
      chatCalls += 1;
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'chat should not be called without a valid session' }),
      });
    });

    await page.goto('/chat/code-assistant');

    await expect(page.getByText(/Session expired|Sign in again/i)).toBeVisible({ timeout: 10000 });
    await page.getByPlaceholder(/Type your message/i).fill('hi');
    await expect(page.getByRole('button', { name: /Send message/i })).toBeDisabled();
    expect(chatCalls).toBe(0);
  });
});
