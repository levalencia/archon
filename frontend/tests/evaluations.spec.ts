import { expect, test, type Page } from '@playwright/test';

const runs = [
  { run_id: 'run-grounded', conversation_id: 'c1', project_id: 'project-a', provider: 'test', model: 'grounded-model', status: 'completed', started_at: '2026-08-26T10:00:00Z', completed_at: '2026-08-26T10:00:01Z', answer_summary: 'Answer with citations', input_tokens: 10, output_tokens: 20, total_tokens: 30, cost_usd: 0, latency_ms: 100, iterations: 1, stop_reason: 'complete', parent_run_id: null, fork_source_sequence: null },
  { run_id: 'run-abstain', conversation_id: 'c2', project_id: 'project-a', provider: 'test', model: 'safe-model', status: 'completed', started_at: '2026-08-26T09:00:00Z', completed_at: '2026-08-26T09:00:01Z', answer_summary: 'Safe abstention', input_tokens: 11, output_tokens: 12, total_tokens: 23, cost_usd: 0, latency_ms: 90, iterations: 1, stop_reason: 'complete', parent_run_id: null, fork_source_sequence: null },
];

const evaluation = (id: string, score: number, includeCases = false) => ({
  id, project_id: 'project-a', dataset_id: 'grounded-v1', dataset_version: '1.0.0', dataset_hash: 'hash', status: 'completed', source_run_ids: ['run-grounded', 'run-abstain'], threshold: 0.85,
  aggregate_metrics: { mean_score: score, pass_rate: score, total_tokens: 53, total_cost_usd: 0, mean_latency_ms: 95 }, passed: score >= 0.85,
  created_at: id === 'eval-new' ? '2026-08-26T12:00:00Z' : '2026-08-25T12:00:00Z', completed_at: '2026-08-26T12:00:01Z',
  cases: includeCases ? [
    { source_run_id: 'run-grounded', case_key: 'grounded-citation', metrics: { score: 1, citation_coverage: 0.9 }, checks: [{ name: 'has_citation', passed: true }], passed: true },
    { source_run_id: 'run-abstain', case_key: 'safe-abstention', metrics: { score: 0.8 }, checks: [{ name: 'abstained_safely', passed: true }], passed: true },
  ] : [],
});

async function mockEvaluationApis(page: Page, options: { empty?: boolean; listStatus?: number } = {}) {
  await page.addInitScript(() => localStorage.setItem('archon_token', 'playwright-token'));
  const forbidden: string[] = [];
  page.on('request', request => {
    if (/\/api\/(chat|models?|llm|completions?)/.test(new URL(request.url()).pathname)) forbidden.push(`${request.method()} ${request.url()}`);
  });
  await page.route('**/api/conversations', route => route.fulfill({ contentType: 'application/json', body: '[]' }));
  await page.route('**/api/admin/health', route => route.fulfill({ contentType: 'application/json', body: '{}' }));
  await page.route('**/api/runs?**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items: options.empty ? [] : runs }) }));
  await page.route('**/api/evals?**', route => route.fulfill(options.listStatus ? { status: options.listStatus, contentType: 'application/json', body: JSON.stringify({ detail: options.listStatus === 429 ? 'Rate limit reached' : 'Sign in required' }) } : { contentType: 'application/json', body: JSON.stringify({ items: options.empty ? [] : [evaluation('eval-old', 0.7)] }) }));
  return forbidden;
}

test('desktop creates a recorded evaluation, opens its report, and compares history', async ({ page }) => {
  const forbidden = await mockEvaluationApis(page);
  let posted: unknown;
  await page.route('**/api/evals/runs', async route => {
    posted = route.request().postDataJSON();
    await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(evaluation('eval-new', 0.9, true)) });
  });
  await page.route('**/api/evals/eval-old', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify(evaluation('eval-old', 0.7, true)) }));
  await page.route('**/api/evals/compare?**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ a: evaluation('eval-new', 0.9), b: evaluation('eval-old', 0.7), metric_delta_b_minus_a: { mean_score: -0.2, pass_rate: -0.2, total_tokens: 0 } }) }));

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/eval');
  await expect(page.getByRole('heading', { name: 'Recorded Run Evaluations' })).toBeVisible();
  await page.getByRole('button', { name: 'Run recorded evaluation' }).click();
  await expect(page.getByRole('heading', { name: /project-a/ }).last()).toBeVisible();
  await expect(page.getByLabel('project-a eval-new').getByText('grounded-citation', { exact: true })).toBeVisible();
  expect(posted).toEqual({ project_id: 'project-a', dataset_id: 'grounded-v1', threshold: 0.85, items: [{ run_id: 'run-grounded', case_key: 'grounded-citation' }, { run_id: 'run-abstain', case_key: 'safe-abstention' }] });

  await page.getByLabel('Candidate evaluation').selectOption('eval-old');
  await page.getByRole('button', { name: 'Compare', exact: true }).click();
  await expect(page.getByLabel('Evaluation deltas')).toContainText('-0.2');
  expect(forbidden).toEqual([]);
});

test('mobile creation controls, history, and report remain usable', async ({ page }) => {
  const forbidden = await mockEvaluationApis(page);
  await page.route('**/api/evals/eval-old', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify(evaluation('eval-old', 0.7, true)) }));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/eval');
  await expect(page.getByLabel('Grounded citation run')).toBeVisible();
  const card = page.getByRole('button', { name: /Open evaluation eval-old/ });
  await expect(card).toBeVisible();
  await card.click();
  await expect(page.getByLabel('project-a eval-old').getByText('safe-abstention', { exact: true })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  expect(forbidden).toEqual([]);
});

test('empty and API error states are visible', async ({ page }) => {
  await mockEvaluationApis(page, { empty: true });
  await page.goto('/eval');
  await expect(page.getByText('No completed recorded runs')).toBeVisible();
  await expect(page.getByText('No evaluation history yet')).toBeVisible();

  await page.unroute('**/api/evals?**');
  await page.route('**/api/evals?**', route => route.fulfill({ status: 429, contentType: 'application/json', body: JSON.stringify({ detail: 'Rate limit reached' }) }));
  await page.getByRole('button', { name: 'Reload evaluations' }).click();
  await expect(page.getByRole('alert')).toContainText('Rate limit reached');
});
