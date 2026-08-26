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
  // A newly-created conversation has no durable run until execution starts. Keep that
  // normal empty state deterministic in tests that are focused on streaming/approval UI.
  await page.route('**/api/runs?**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items: [] }) }));
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

  await expect(page.getByRole('alert').filter({ hasText: 'missing run binding' })).toContainText('missing run binding');
  await expect(page.getByRole('dialog', { name: 'Tool approval required' })).toHaveCount(0);
});

const persistedRuns = [
  {
    run_id: 'run-new', conversation_id: 'persisted-conversation', project_id: 'project',
    provider: 'provider-a', model: 'model-new', status: 'completed',
    started_at: '2026-08-26T12:00:00Z', completed_at: '2026-08-26T12:00:01Z',
    answer_summary: 'Persisted answer from the run ledger', input_tokens: 80,
    output_tokens: 40, total_tokens: 120, cost_usd: 0.0123, latency_ms: 987,
    iterations: 2, stop_reason: 'complete', parent_run_id: null, fork_source_sequence: null,
  },
  {
    run_id: 'run-old', conversation_id: 'persisted-conversation', project_id: 'project',
    provider: 'provider-b', model: 'model-old', status: 'completed',
    started_at: '2026-08-25T12:00:00Z', completed_at: '2026-08-25T12:00:02Z',
    answer_summary: 'Older persisted answer', input_tokens: 150, output_tokens: 50,
    total_tokens: 200, cost_usd: 0.02, latency_ms: 1500, iterations: 4,
    stop_reason: 'max_iterations', parent_run_id: null, fork_source_sequence: null,
  },
];

const persistedEvents = [
  { sequence: 3, event_at: '2026-08-26T12:00:01Z', kind: 'run_stopped', iteration: 2, payload: { reason: 'complete' } },
  { sequence: 1, event_at: '2026-08-26T12:00:00Z', kind: 'run_started', iteration: 0, payload: { source: 'stored' } },
  { sequence: 2, event_at: '2026-08-26T12:00:00.5Z', kind: 'model_completed', iteration: 1, payload: { tokens: 120 } },
];

async function mockPersistedRunApis(page: import('@playwright/test').Page) {
  await page.route('**/api/runs?**', route => route.fulfill({
    contentType: 'application/json', body: JSON.stringify({ items: persistedRuns }),
  }));
  await page.route('**/api/runs/run-new/events?**', route => route.fulfill({
    contentType: 'application/json', body: JSON.stringify({ items: persistedEvents }),
  }));
  await page.route('**/api/runs/run-new', route => route.fulfill({
    contentType: 'application/json', body: JSON.stringify(persistedRuns[0]),
  }));
}

test('desktop reload reconstructs persisted summary and ordered timeline without starting a model run', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockPersistedRunApis(page);
  const forbiddenRequests: string[] = [];
  page.on('request', request => {
    if (request.method() === 'POST' && ['/api/chat/stream', '/api/conversations'].some(path => request.url().endsWith(path))) {
      forbiddenRequests.push(`${request.method()} ${request.url()}`);
    }
  });

  await page.goto('/chat/persisted-conversation');
  await page.reload();

  const summary = page.getByRole('region', { name: 'Persisted run summary' });
  await expect(summary).toContainText('Persisted answer from the run ledger');
  await expect(summary).toContainText('provider-a / model-new');
  await expect(summary).toContainText('120 (80 in / 40 out)');
  await expect(summary).toContainText('$0.0123');
  await expect(summary).toContainText('987ms');
  await expect(summary).toContainText('complete');
  const timeline = page.locator('.timeline ol li');
  await expect(timeline).toHaveCount(3);
  await expect(timeline.nth(0)).toContainText('#1');
  await expect(timeline.nth(1)).toContainText('#2');
  await expect(timeline.nth(2)).toContainText('#3');
  expect(forbiddenRequests).toEqual([]);
});

test('fork posts the exact run and sequence then opens the durable target conversation', async ({ page }) => {
  await mockPersistedRunApis(page);
  let forkRequest: { url: string; body: unknown } | undefined;
  await page.route('**/api/runs/run-new/fork', async route => {
    forkRequest = { url: new URL(route.request().url()).pathname, body: route.request().postDataJSON() };
    await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({
      target_conversation_id: 'fork-target', checkpoint_id: 'checkpoint-1', workspace_restoration: 'none',
    }) });
  });
  await page.route('**/api/chat/history/fork-target', route => route.fulfill({
    contentType: 'application/json', body: JSON.stringify({ messages: [{ role: 'user', content: 'Forked persisted prompt' }] }),
  }));

  await page.goto('/chat/persisted-conversation');
  await page.getByRole('button', { name: 'Fork from latest event' }).click();

  await expect(page).toHaveURL(/\/chat\/fork-target$/);
  await expect(page.getByText('Forked persisted prompt')).toBeVisible();
  expect(forkRequest).toEqual({ url: '/api/runs/run-new/fork', body: { source_sequence: 3 } });
});

test('compare selection renders deterministic stored differences', async ({ page }) => {
  await mockPersistedRunApis(page);
  await page.route('**/api/runs/compare?**', route => route.fulfill({
    contentType: 'application/json', body: JSON.stringify({
      a: { ...persistedRuns[0], tokens: { input: 80, output: 40, total: 120 } },
      b: { ...persistedRuns[1], tokens: { input: 150, output: 50, total: 200 } },
    }),
  }));

  await page.goto('/chat/persisted-conversation');
  await page.getByRole('combobox').filter({ has: page.locator('option', { hasText: 'Compare with…' }) }).selectOption('run-old');
  await page.getByRole('button', { name: 'Compare', exact: true }).click();

  const comparison = page.getByText('Stored run comparison').locator('..');
  await expect(comparison).toContainText('model-new');
  await expect(comparison).toContainText('model-old');
  await expect(comparison).toContainText('120');
  await expect(comparison).toContainText('200');
  await expect(comparison).toContainText('max_iterations');
});

test('mobile persisted-run inspector bottom sheet is usable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockPersistedRunApis(page);
  await page.goto('/chat/persisted-conversation');
  await page.getByRole('button', { name: 'Inspect run' }).click();

  const inspector = page.locator('aside.inspector-shell');
  await expect(inspector).toHaveAttribute('data-open', 'true');
  await expect(inspector.getByRole('region', { name: 'Persisted run summary' })).toBeVisible();
  await expect(inspector.getByRole('button', { name: 'Fork from latest event' })).toBeEnabled();
  await inspector.getByRole('button', { name: 'Reload' }).click();
  await expect(inspector).toContainText('Persisted answer from the run ledger');
  await inspector.getByRole('button', { name: 'Close inspector' }).click();
  await expect(inspector).toHaveAttribute('data-open', 'false');
});

test('run API 401 and 404 failures are visible', async ({ page }) => {
  await page.route('**/api/runs?**', route => route.fulfill({ status: 401, body: '' }));
  await page.goto('/chat/persisted-conversation');
  await expect(page.getByRole('alert')).toContainText('Sign in required');

  await page.unroute('**/api/runs?**');
  await page.route('**/api/runs?**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items: [persistedRuns[0]] }) }));
  await page.route('**/api/runs/run-new', route => route.fulfill({ status: 404, body: '' }));
  await page.route('**/api/runs/run-new/events?**', route => route.fulfill({ status: 404, body: '' }));
  await page.getByRole('button', { name: 'Reload' }).click();
  await expect(page.getByRole('alert')).toContainText('Run not found');
});
