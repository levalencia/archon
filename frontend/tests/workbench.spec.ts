import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.route('**/api/conversations', route => route.request().method() === 'POST'
    ? route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ id: 'run-123', title: 'Test run', created_at: new Date().toISOString(), message_count: 0 }) })
    : route.fulfill({ contentType: 'application/json', body: '[]' }));
  await page.route('**/api/admin/health', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ llm_model: 'Reliability Model', llm_provider: 'test' }) }));
  await page.route('**/api/chat/stream', async route => route.fulfill({ status: 200, contentType: 'text/event-stream', body: 'event: thinking\ndata: Verifying evidence\n\nevent: token\ndata: Grounded answer\n\nevent: context\ndata: {"tokens":120,"budget":8000,"utilization_pct":1.5}\n\nevent: done\ndata: {"iterations":1,"tools_used":0,"elapsed_ms":42}\n\n' }));
});

test('desktop workbench streams an answer and exposes inspector tabs', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 }); await page.goto('/');
  await expect(page.getByRole('heading', { name: /Make every answer/ })).toBeVisible();
  await page.getByRole('textbox', { name: 'Message' }).fill('Is this grounded?'); await page.getByRole('button', { name: 'Send' }).click();
  await expect(page.getByText('Grounded answer')).toBeVisible(); await expect(page).toHaveURL(/\/chat\/run-123/);
  await page.screenshot({ path: 'screenshots/reliability-workbench-desktop.png', fullPage: true });
});

test('mobile uses navigation drawer and inspector bottom sheet', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 }); await page.goto('/');
  const open = page.getByRole('button', { name: 'Open conversations' }); await expect(open).toBeEnabled(); await open.click(); const drawer = page.locator('aside.sidebar'); await expect(drawer).toHaveAttribute('data-open', 'true'); await expect(drawer).toHaveClass(/open/); await expect.poll(async () => (await drawer.boundingBox())?.x ?? -999).toBeGreaterThanOrEqual(0);
  await drawer.getByRole('button', { name: 'Close conversations' }).click(); await page.getByRole('button', { name: 'Inspect run' }).click();
  await expect(page.getByRole('tab', { name: 'Logs' })).toBeVisible(); await page.screenshot({ path: 'screenshots/reliability-workbench-mobile.png', fullPage: true });
});
