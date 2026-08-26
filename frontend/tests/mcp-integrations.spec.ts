import { expect, test, type Page } from '@playwright/test';

const server = { id: 's1', project_id: 'default', name: 'Docs', profile_id: 'official-docs', transport: 'stdio', enabled: true, health: 'unknown', last_error_code: null, last_seen: null, created_at: '2026-08-26T10:00:00Z', updated_at: '2026-08-26T10:00:00Z' };
const tool = { id: 't1', server_id: 's1', name: 'search_docs', title: 'Search docs', description: 'Search approved documentation', input_schema: { type: 'object', properties: { query: { type: 'string' } } }, read_only: true, destructive: false, enabled: false, version: '1' };

async function mockBase(page: Page) {
  await page.addInitScript(() => localStorage.setItem('archon_token', 'test-token'));
  await page.route('**/api/conversations', route => route.fulfill({ contentType: 'application/json', body: '[]' }));
  await page.route('**/api/admin/health', route => route.fulfill({ contentType: 'application/json', body: '{}' }));
  await page.route('**/api/skills', route => route.fulfill({ contentType: 'application/json', body: '[]' }));
  await page.route('**/api/mcp/profiles', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify([{ id: 'official-docs', display_name: 'Official Docs' }]) }));
}

test('creates, discovers, inventories, and toggles without calling a tool', async ({ page }) => {
  await mockBase(page);
  let servers: typeof server[] = [];
  let inventory: typeof tool[] = [];
  const executionRequests: string[] = [];
  page.on('request', request => {
    if (new URL(request.url()).pathname === '/api/mcp/request') executionRequests.push(request.url());
  });
  await page.route('**/api/mcp/servers?**', async route => {
    if (route.request().method() === 'GET') return route.fulfill({ contentType: 'application/json', body: JSON.stringify(servers) });
    return route.fallback();
  });
  await page.route('**/api/mcp/servers', async route => {
    servers = [server];
    await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(server) });
  });
  await page.route('**/api/mcp/servers/s1/tools', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify(inventory) }));
  await page.route('**/api/mcp/servers/s1/discover?**', async route => { inventory = [tool]; await route.fulfill({ contentType: 'application/json', body: JSON.stringify(inventory) }); });
  await page.route('**/api/mcp/servers/s1/tools/search_docs?**', async route => { inventory = [{ ...tool, enabled: true }]; await route.fulfill({ contentType: 'application/json', body: JSON.stringify(inventory[0]) }); });

  await page.goto('/settings');
  await page.getByLabel('Integration name').fill('Docs');
  await page.getByRole('button', { name: 'Add integration' }).click();
  await expect(page.getByTestId('mcp-server')).toContainText('unknown');
  await page.getByRole('button', { name: 'Discover tools' }).click();
  await expect(page.getByTestId('mcp-tool')).toContainText('read-only');
  await page.getByTestId('mcp-tool').getByRole('checkbox').check();
  await expect(page.getByTestId('mcp-tool').getByRole('checkbox')).toBeChecked();
  expect(executionRequests).toEqual([]);
});

test('shows owner-safe API errors and remains usable on mobile', async ({ page }) => {
  await mockBase(page);
  await page.route('**/api/mcp/servers?**', route => route.fulfill({ status: 403, contentType: 'application/json', body: JSON.stringify({ detail: { code: 'owner_mismatch' } }) }));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/settings');
  await expect(page.getByRole('heading', { name: 'Skills & Integrations' })).toBeVisible();
  await expect(page.getByRole('alert')).toContainText('belongs to another owner');
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});
