import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  const authorized = (headers: Record<string, string>) => headers.authorization === 'Bearer playwright-token';
  await page.addInitScript(() => localStorage.setItem('archon_token', 'playwright-token'));
  await page.route('**/api/conversations', route => {
    if (!authorized(route.request().headers())) return route.fulfill({ status: 401 });
    return route.request().method() === 'POST'
      ? route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ id: 'run-123', title: 'Test run', created_at: new Date().toISOString(), message_count: 0 }) })
      : route.fulfill({ contentType: 'application/json', body: '[]' });
  });
  await page.route('**/api/admin/health', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ llm_model: 'Reliability Model', llm_provider: 'test' }) }));
  await page.route('**/api/chat/stream', async route => authorized(route.request().headers())
    ? route.fulfill({ status: 200, contentType: 'text/event-stream', body: 'event: thinking\ndata: Verifying evidence\n\nevent: token\ndata: Grounded answer\n\nevent: context\ndata: {"tokens":120,"budget":8000,"utilization_pct":1.5}\n\nevent: done\ndata: {"iterations":1,"tools_used":0,"elapsed_ms":42}\n\n' })
    : route.fulfill({ status: 401 }));
  await page.route('**/api/logs/stream', route => authorized(route.request().headers())
    ? route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' })
    : route.fulfill({ status: 401 }));
  await page.route('**/api/chat/history/*', route => authorized(route.request().headers())
    ? route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ messages: [] }) })
    : route.fulfill({ status: 401 }));
});

test('desktop workbench streams an answer and exposes inspector tabs', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 }); await page.goto('/');
  await expect(page.getByRole('heading', { name: /Make every answer/ })).toBeVisible();
  await page.getByRole('textbox', { name: 'Message' }).fill('Is this grounded?'); await page.getByRole('button', { name: 'Send' }).click();
  await expect(page.getByText('Grounded answer')).toBeVisible(); await expect(page).toHaveURL(/\/chat\/run-123/);
});

test('mobile uses navigation drawer and inspector bottom sheet', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 }); await page.goto('/');
  const open = page.getByRole('button', { name: 'Open conversations' }); await expect(open).toBeEnabled(); await open.click(); const drawer = page.locator('aside.sidebar'); await expect(drawer).toHaveAttribute('data-open', 'true'); await expect(drawer).toHaveClass(/open/); await expect.poll(async () => (await drawer.boundingBox())?.x ?? -999).toBeGreaterThanOrEqual(0);
  await drawer.getByRole('button', { name: 'Close conversations' }).click(); await page.getByRole('button', { name: 'Inspect run' }).click();
  await expect(page.getByRole('tab', { name: 'Logs' })).toBeVisible();
});

test('approval decisions include the exact SSE run binding', async ({ page }) => {
  await page.unroute('**/api/chat/stream');
  await page.route('**/api/chat/stream', route => route.fulfill({
    status: 200,
    contentType: 'text/event-stream',
    body: 'event: approval_required\ndata: {"tool":"terminal","tool_call_id":"call-7","run_id":"00000000-0000-4000-8000-000000000007","parameters":{}}\n\nevent: done\ndata: {}\n\n',
  }));
  let decision: unknown;
  await page.route('**/api/chat/approve/call-7', async route => {
    decision = route.request().postDataJSON();
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
  });

  await page.goto('/');
  await page.getByRole('textbox', { name: 'Message' }).fill('run a tool');
  await page.getByRole('button', { name: 'Send' }).click();
  await page.getByRole('button', { name: 'Approve' }).click();

  expect(decision).toEqual({ approved: true, run_id: '00000000-0000-4000-8000-000000000007' });
});

test('approval event without a run binding fails visibly without a decision UI', async ({ page }) => {
  await page.unroute('**/api/chat/stream');
  await page.route('**/api/chat/stream', route => route.fulfill({
    status: 200,
    contentType: 'text/event-stream',
    body: 'event: approval_required\ndata: {"tool":"terminal","tool_call_id":"call-7","parameters":{}}\n\n',
  }));

  await page.goto('/');
  await page.getByRole('textbox', { name: 'Message' }).fill('run a tool');
  await page.getByRole('button', { name: 'Send' }).click();

  await expect(page.getByRole('alert')).toContainText('missing run binding');
  await expect(page.getByRole('dialog', { name: 'Tool approval required' })).toHaveCount(0);
});
