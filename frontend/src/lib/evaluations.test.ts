import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/auth', () => ({ authenticatedFetch: vi.fn() }));
vi.mock('$lib/runs', () => ({ listRuns: vi.fn() }));

import { authenticatedFetch } from '$lib/auth';
import { listRuns } from '$lib/runs';
import {
  EvaluationApiError,
  compareEvaluations,
  createEvaluation,
  getEvaluation,
  listEvaluations,
  listRecordedRuns,
} from './evaluations';

const fetchMock = vi.mocked(authenticatedFetch);
const runsMock = vi.mocked(listRuns);
const base = {
  id: 'eval/a', project_id: 'project a', dataset_id: 'grounded-v1', dataset_version: '1.0.0',
  dataset_hash: 'hash', status: 'completed', run_ids: ['one', 'two'], threshold: 0.85,
  aggregate_metrics: { average_score: 0.9 }, passed: true, created_at: '2026-08-26T00:00:00Z',
  completed_at: '2026-08-26T00:00:01Z', cases: [],
};

beforeEach(() => {
  fetchMock.mockReset();
  runsMock.mockReset();
});

describe('recorded evaluation client', () => {
  it('lists only completed persisted runs through the runs client', async () => {
    runsMock.mockResolvedValueOnce([
      { run_id: 'done', status: 'completed', completed_at: 'now' },
      { run_id: 'active', status: 'running', completed_at: null },
    ] as never);
    expect((await listRecordedRuns()).map((run) => run.run_id)).toEqual(['done']);
    expect(runsMock).toHaveBeenCalledWith({ limit: 100 });
  });

  it('posts the exact dataset and two case mappings', async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(base), { status: 201 }));
    await createEvaluation({ projectId: 'project-a', threshold: 0.72, groundedCitationRunId: 'run-a', safeAbstentionRunId: 'run-b' });
    expect(fetchMock).toHaveBeenCalledWith('/api/evals/runs', expect.objectContaining({ method: 'POST' }));
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(body).toEqual({
      project_id: 'project-a', dataset_id: 'grounded-v1', threshold: 0.72,
      items: [
        { run_id: 'run-a', case_key: 'grounded-citation' },
        { run_id: 'run-b', case_key: 'safe-abstention' },
      ],
    });
  });

  it('encodes list, get, and compare URLs and normalizes malformed collections', async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ items: [{ ...base, run_ids: null, aggregate_metrics: null, cases: null }] }), { status: 200 }));
    expect((await listEvaluations({ projectId: 'project/a', offset: 2 }))[0]).toEqual(expect.objectContaining({ run_ids: [], aggregate_metrics: {}, cases: [] }));
    expect(fetchMock.mock.calls[0][0]).toBe('/api/evals?project_id=project%2Fa&limit=50&offset=2');

    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(base), { status: 200 }));
    await getEvaluation('eval/a');
    expect(fetchMock.mock.calls[1][0]).toBe('/api/evals/eval%2Fa');

    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ a: base, b: base, delta_b_minus_a: { average_score: 0.1, bad: 'x' } }), { status: 200 }));
    expect((await compareEvaluations('eval a', 'eval/b')).delta_b_minus_a).toEqual({ average_score: 0.1 });
    expect(fetchMock.mock.calls[2][0]).toBe('/api/evals/compare?a=eval+a&b=eval%2Fb');
  });

  it.each([
    [401, 'Sign in required'], [404, 'Recorded run or evaluation not found'],
    [409, 'not terminal'], [422, 'invalid mapping'], [429, 'Too many evaluation requests'],
  ])('surfaces %i errors', async (status, message) => {
    const body = status === 409 ? { detail: 'not terminal' } : status === 422 ? { detail: 'invalid mapping' } : {};
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(body), { status }));
    await expect(listEvaluations()).rejects.toEqual(expect.objectContaining<Partial<EvaluationApiError>>({ status, message: expect.stringContaining(message) }));
  });
});
