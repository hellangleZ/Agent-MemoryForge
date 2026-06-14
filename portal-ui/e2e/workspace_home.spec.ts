import { test, expect } from '@playwright/test';

/**
 * E2E tests for /workspace dashboard buttons (Refresh).
 */
test.describe('Workspace Home', () => {
  let calls: Record<string, number>;

  test.beforeEach(async ({ page }) => {
    // Catch-all to avoid Next rewrites proxying to 127.0.0.1:8080 during tests.
    await page.route('**/portal/v1/**', async (route) => {
      const req = route.request();
      const path = new URL(req.url()).pathname;
      await route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ detail: `mocked: no route for ${path}` }),
      });
    });

    await page.addInitScript(() => {
      localStorage.setItem('portal_auth', '1');
      localStorage.setItem('portal_workspace_id', 'ws_default');
    });

    calls = { config: 0, me: 0, mem: 0, tools: 0, agents: 0 };

    await page.route('**/portal/v1/workspace/config', async (route) => {
      calls.config += 1;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ data: { id: 'ws_default', system_prompt: 'x', mcp: {} } }),
      });
    });

    await page.route('**/portal/v1/me', async (route) => {
      calls.me += 1;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id: 'u', email: 'u@example.com', role: 'user', created_at: new Date().toISOString() }),
      });
    });

    await page.route('**/portal/v1/memory/stats', async (route) => {
      calls.mem += 1;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: {
            stm: { count: 1, size_bytes: 1 },
            wm: { count: 1, size_bytes: 1 },
            ltm: { count: 1, size_bytes: 1 },
            knowledge_graph: { nodes: 0, edges: 0, size_bytes: 0 },
            file_first: { index: { stale: false, mtime_s: 1700000000 } },
          },
        }),
      });
    });

    await page.route('**/portal/v1/tools/status', async (route) => {
      calls.tools += 1;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ tools: [{ name: 't', enabled: true, status: 'active', config: {} }] }),
      });
    });

    await page.route('**/portal/v1/agents', async (route) => {
      calls.agents += 1;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ agents: { a: { id: 'a', name: 'a', custom: false } } }),
      });
    });
  });

  test('refresh button refetches data', async ({ page }) => {
    const isMemStats = (req: any) => {
      if (!req) return false;
      if (req.method?.() !== 'POST') return false;
      try {
        return new URL(req.url()).pathname === '/portal/v1/memory/stats';
      } catch {
        return false;
      }
    };

    // Ensure the initial fetch has started and hit the expected endpoint.
    const firstStatsReq = page.waitForRequest(isMemStats);
    await page.goto('/workspace');
    await firstStatsReq;
    await expect(page.locator('text=/Workspace:/i')).toBeVisible({ timeout: 10000 });
    expect(calls.mem).toBeGreaterThan(0);

    const before = calls.mem;
    const refreshBtn = page.getByRole('button', { name: /^Refresh$/i });
    await expect(refreshBtn).toBeEnabled();

    // Wait for the *next* stats fetch triggered by Refresh.
    const secondStatsReq = page.waitForRequest(isMemStats);
    await refreshBtn.click();
    await secondStatsReq;

    await expect.poll(() => calls.mem).toBeGreaterThan(before);
  });
});


test.describe('Workspace Home - Stale Session', () => {
  test('clears stale auth marker and does not fetch protected dashboard data', async ({ page }) => {
    let memoryStatsCalls = 0;

    await page.route('**/portal/v1/**', async (route) => {
      const req = route.request();
      const path = new URL(req.url()).pathname;
      await route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ detail: `mocked: no route for ${path}` }),
      });
    });

    await page.addInitScript(() => {
      localStorage.setItem('portal_auth', '1');
      localStorage.setItem('portal_workspace_id', 'ws_default');
    });

    await page.route('**/portal/v1/me', async (route) => {
      await route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Not authenticated' }),
      });
    });

    await page.route('**/portal/v1/memory/stats', async (route) => {
      memoryStatsCalls += 1;
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'should not be called without a valid session' }),
      });
    });

    await page.goto('/workspace');

    await expect(page.getByText('Not authenticated', { exact: true })).toBeVisible({ timeout: 10000 });
    await expect(page.getByText('Authenticated', { exact: true })).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => localStorage.getItem('portal_auth'))).toBeNull();
    expect(memoryStatsCalls).toBe(0);
  });
});
