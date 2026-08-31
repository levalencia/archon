import { test, expect, type Page } from '@playwright/test';

async function openStudio(page: Page, view?: string) {
  await page.addInitScript(() => localStorage.setItem('archon_token', 'playwright-token'));
  await page.goto(view ? `/learn?view=${view}` : '/learn');
  await expect(page.getByRole('heading', { name: 'Choose the view that matches your question' })).toBeVisible();
}

test('roadmap presents six stable phases and sixteen modules', async ({ page }) => {
  await openStudio(page);
  await expect(page.getByRole('heading', { name: 'A stable path from foundations to operations' })).toBeVisible();
  await expect(page.getByLabel('Visual Learning Studio summary')).toContainText('66');
  await expect(page.getByLabel('Visual Learning Studio summary')).toContainText('16');
  await expect(page.locator('article').filter({ hasText: /Foundations and bounded runtime/ })).toBeVisible();
  await page.getByRole('button', { name: /Typed runtime/ }).click();
  await expect(page.getByLabel('Selected module')).toContainText('Typed runtime');
  await expect(page.locator('g.concept-node')).toHaveCount(0);
});

test('stories use one labeled directional relationship per step', async ({ page }) => {
  await openStudio(page, 'stories');
  await expect(page.getByRole('heading', { name: 'Follow one flow at a time' })).toBeVisible();
  await expect(page.getByText('Step 1 of 8')).toBeVisible();
  await expect(page.getByText('HTTP POST', { exact: true })).toBeVisible();
  await expect(page.getByText('Browser', { exact: true })).toBeVisible();
  await expect(page.getByText('Gateway', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Next story step' }).click();
  await expect(page.getByText('Step 2 of 8')).toBeVisible();
  await expect(page.getByText('AUTHENTICATES WITH', { exact: true })).toBeVisible();
});

test('architecture keeps five layers fixed and exposes typed relations', async ({ page }) => {
  await openStudio(page, 'architecture');
  await expect(page.getByRole('heading', { name: 'Five stable architecture layers' })).toBeVisible();
  await expect(page.getByText(/Layer [1-5]/)).toHaveCount(5);
  await page.getByRole('button', { name: /Policy and approvals/ }).click();
  const details = page.getByLabel('Selected architecture component');
  await expect(details).toContainText('Policy and approvals');
  await expect(details).toContainText('GATES');
  await expect(page.locator('g.concept-node')).toHaveCount(0);
});

test('evidence view preserves status and proof boundaries', async ({ page }) => {
  await openStudio(page, 'evidence');
  await expect(page.getByRole('heading', { name: 'Capability evidence without inflated claims' })).toBeVisible();
  const details = page.getByLabel('Selected evidence details');

  await page.getByRole('combobox', { name: 'Evidence status' }).selectOption('partial');
  await expect(page.getByText('0 of 66 capabilities')).toBeVisible();
  await expect(details).toContainText('No evidence details are available');

  await page.getByRole('combobox', { name: 'Evidence status' }).selectOption('implemented');
  await page.getByRole('searchbox', { name: 'Search evidence' }).fill('embedding');
  await expect(page.getByText('7 of 66 capabilities')).toBeVisible();
  await page.getByRole('button', { name: /Embeddings/ }).click();
  await expect(details).toContainText(/Azure Foundry text-embedding-3-small is live-proven/i);

  await page.getByRole('searchbox', { name: 'Search evidence' }).fill('');
  await page.getByRole('combobox', { name: 'Evidence status' }).selectOption('deferred');
  await expect(page.getByText('8 of 66 capabilities')).toBeVisible();
  await expect(details).not.toContainText('Embeddings');

  await page.getByRole('searchbox', { name: 'Search evidence' }).fill('no-such-capability');
  await expect(page.getByText('0 of 66 capabilities')).toBeVisible();
  await expect(details).toContainText('No evidence details are available');
});

test('Present, Listen, and Study expose prepared NotebookLM recipes', async ({ page }) => {
  await openStudio(page, 'present');
  await expect(page.getByRole('heading', { name: 'Explain Archon visually' })).toBeVisible();
  await expect(page.getByText('Prepared, not yet generated.')).toBeVisible();
  await expect(page.getByText('Slide Deck', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: /Open NotebookLM promptbook/ })).toBeVisible();
  await expect(page.getByRole('link', { name: /Open step-by-step runbook/ })).toBeVisible();

  await page.getByRole('link', { name: /Listen/ }).click();
  await expect(page.getByRole('heading', { name: 'Review Archon through audio' })).toBeVisible();
  await expect(page.getByText('Audio', { exact: true })).toBeVisible();

  await page.getByRole('link', { name: /Study/ }).click();
  await expect(page.getByRole('heading', { name: 'Practice retrieval and comprehension' })).toBeVisible();
  await expect(page.getByText('Flashcards', { exact: true })).toBeVisible();
  await expect(page.getByText('Quiz', { exact: true })).toBeVisible();
  await expect(page.getByText('Report', { exact: true })).toBeVisible();
});

test('browser history restores the previous studio mode', async ({ page }) => {
  await openStudio(page);
  await page.getByRole('link', { name: /Stories/ }).click();
  await expect(page).toHaveURL(/view=stories/);
  await expect(page.getByRole('heading', { name: 'Follow one flow at a time' })).toBeVisible();
  await page.goBack();
  await expect(page.getByRole('heading', { name: 'A stable path from foundations to operations' })).toBeVisible();
});

test('legacy map URL redirects to the structured Stories view', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('archon_token', 'playwright-token'));
  await page.goto('/learn/map');
  await expect(page).toHaveURL(/\/learn\?view=stories$/);
  await expect(page.getByRole('heading', { name: 'Follow one flow at a time' })).toBeVisible();
});

test('all studio modes avoid horizontal overflow on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => localStorage.setItem('archon_token', 'playwright-token'));
  for (const view of ['roadmap', 'stories', 'architecture', 'evidence', 'present', 'listen', 'study']) {
    await page.goto(`/learn?view=${view}`);
    await expect(page.getByRole('heading', { name: 'Choose the view that matches your question' })).toBeVisible();
    await expect.poll(async () => page.evaluate(() => document.body.scrollWidth <= document.body.clientWidth)).toBe(true);
  }
  await expect(page.getByRole('link', { name: 'Learn', exact: true })).toHaveAttribute('aria-current', 'page');
});
