import { expect, test, type Page, type Route } from '@playwright/test';

const server = { id: 's1', project_id: 'default', name: 'Docs', profile_id: 'official-docs', transport: 'stdio', enabled: true, health: 'unknown', last_error_code: null, last_seen: null, created_at: '2026-08-26T10:00:00Z', updated_at: '2026-08-26T10:00:00Z' };
const tool = { id: 't1', server_id: 's1', name: 'search_docs', title: 'Search docs', description: 'Search approved documentation', input_schema: { type: 'object', properties: { query: { type: 'string' } } }, read_only: true, destructive: false, enabled: false, version: '1' };
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

async function mockSettingsBase(page: Page) {
  await page.addInitScript(() => localStorage.setItem('archon_token', 'test-token'));
  await page.route('**/api/projects/default/instructions', route => json(route, []));
  await page.route('**/api/skills/catalog?**', route => json(route, []));
  await page.route('**/api/capabilities/projects/default/effective', route => json(route, { items: [] }));
  await page.route('**/api/mcp/profiles', route => json(route, [{ id: 'official-docs', display_name: 'Official Docs' }]));
}

test('creates, discovers, disables/enables server and tool without execution', async ({ page }) => {
  await mockSettingsBase(page);
  let servers: typeof server[] = [];
  let inventory: typeof tool[] = [];
  const requests: { path: string; method: string; body: unknown }[] = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/mcp/')) requests.push({ path: `${url.pathname}${url.search}`, method: request.method(), body: request.postDataJSON?.() });
  });
  await page.route('**/api/mcp/servers?**', route => json(route, servers));
  await page.route('**/api/mcp/servers', async route => { servers = [server]; await json(route, server, 201); });
  await page.route('**/api/mcp/servers/s1/tools?**', route => json(route, inventory));
  await page.route('**/api/mcp/servers/s1/discover?**', async route => { inventory = [tool]; await json(route, inventory); });
  await page.route('**/api/mcp/servers/s1/tools/search_docs?**', async route => { inventory = [{ ...tool, enabled: true }]; await json(route, inventory[0]); });
  await page.route('**/api/mcp/servers/s1?**', async route => {
    const enabled = route.request().postDataJSON().enabled as boolean;
    servers = [{ ...server, enabled }];
    await json(route, servers[0]);
  });

  await page.goto('/settings');
  await page.getByLabel('Integration name').fill('Docs');
  await page.getByRole('button', { name: 'Add integration' }).click();
  await expect(page.getByTestId('mcp-server')).toContainText('unknown');
  await page.getByRole('button', { name: 'Disable Docs' }).click();
  await expect(page.getByRole('button', { name: 'Enable Docs' })).toBeVisible();
  await page.getByRole('button', { name: 'Enable Docs' }).click();
  await page.getByRole('button', { name: 'Discover tools' }).click();
  await expect(page.getByTestId('mcp-tool')).toContainText('read-only');
  await page.getByTestId('mcp-tool').getByRole('checkbox').check();
  await expect(page.getByTestId('mcp-tool').getByRole('checkbox')).toBeChecked();

  expect(requests.find(request => request.method === 'POST' && request.path === '/api/mcp/servers')?.body).toEqual({ project_id: 'default', name: 'Docs', profile_id: 'official-docs', enabled: true });
  expect(requests.some(request => request.path.startsWith('/api/mcp/request'))).toBe(false);
  expect(requests.some(request => request.path === '/api/mcp/servers/s1/tools/search_docs?project_id=default' && request.method === 'PATCH' && JSON.stringify(request.body) === '{"enabled":true}')).toBe(true);
});

test('shows owner-safe errors and keeps MCP controls touch-safe without overflow', async ({ page }) => {
  await mockSettingsBase(page);
  await page.route('**/api/mcp/servers?**', route => json(route, { detail: { code: 'owner_mismatch' } }, 403));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/settings');
  await expect(page.getByRole('heading', { name: 'MCP integrations' })).toBeVisible();
  await expect(page.getByRole('alert')).toContainText('belongs to another owner');
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  const heights = await page.locator('#mcp button, #mcp input, #mcp select').evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().height));
  expect(heights.length).toBeGreaterThan(0);
  expect(heights.every(height => height >= 44)).toBe(true);
});
