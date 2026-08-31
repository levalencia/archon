import { test, expect, type Page } from '@playwright/test';

async function openMap(page: Page) {
  await page.addInitScript(() => localStorage.setItem('archon_token', 'playwright-token'));
  await page.goto('/learn/map');
  await expect(page.getByRole('heading', { name: 'Explore Archon as a living concept map' })).toBeVisible();
  await expect(page.locator('g.concept-node')).toHaveCount(66);
}

test('renders all canonical concepts and evidence details', async ({ page }) => {
  await openMap(page);
  await expect(page.getByLabel('Learning graph summary')).toContainText('66');
  await expect(page.getByLabel('Learning graph summary')).toContainText('46');
  await expect(page.getByLabel('Learning graph summary')).toContainText('14');
  await expect(page.getByLabel('Learning graph summary')).toContainText('6');

  const embeddings = page.locator('g.concept-node[aria-label^="Embeddings,"]');
  await embeddings.focus();
  await embeddings.press('Enter');
  await expect(page.getByRole('heading', { name: 'Embeddings', exact: true })).toBeVisible();
  await expect(page.getByRole('complementary', { name: 'Selected concept details' })).toContainText(/mock embeddings/i);
  await expect(page.getByRole('link', { name: /Open concept page|Open module fallback/ })).toHaveAttribute('href', /github\.com\/levalencia\/archon/);
});

test('filters by status and text without losing the canonical graph', async ({ page }) => {
  await openMap(page);
  await expect(page.locator('g.concept-node[tabindex="0"]')).toHaveCount(10);

  await page.getByRole('button', { name: 'partial', exact: true }).click();
  await expect(page.getByText('14 concepts visible')).toBeVisible();
  await expect(page.locator('g.concept-node[tabindex="0"]')).toHaveCount(14);

  await page.getByRole('button', { name: 'all', exact: true }).click();
  await page.getByRole('searchbox', { name: 'Search concepts' }).fill('bounded react');
  await expect(page.getByText('1 concepts visible')).toBeVisible();
  await expect(page.locator('g.concept-node[tabindex="0"]')).toHaveCount(1);
  await expect(page.locator('g.concept-node')).toHaveCount(66);
});

test('guided journey advances across concepts', async ({ page }) => {
  await openMap(page);

  await page.getByRole('button', { name: /Agent lifecycle/ }).click();
  await expect(page.getByText('Step 1 of 10')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Agent anatomy and trust boundaries' })).toBeVisible();

  const typedRuntime = page.locator('g.concept-node[aria-label^="Typed provider-neutral runtime,"]');
  await typedRuntime.focus();
  await typedRuntime.press('Enter');
  await expect(page.getByText('Step 3 of 10')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Typed provider-neutral runtime' })).toBeVisible();

  await page.getByRole('button', { name: 'Previous journey step' }).click();
  await expect(page.getByText('Step 2 of 10')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Python OOP, Protocols, and dependency injection' })).toBeVisible();
});

test('mobile map remains within viewport and exposes navigation', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openMap(page);

  await expect(page.getByRole('link', { name: 'Learn' })).toHaveAttribute('aria-current', 'page');
  await expect(page.getByRole('button', { name: 'Zoom in' })).toBeVisible();
  await expect(page.getByLabel('Selected concept details')).toBeVisible();
  await expect.poll(async () => page.evaluate(() => document.body.scrollWidth <= document.body.clientWidth)).toBe(true);
});
