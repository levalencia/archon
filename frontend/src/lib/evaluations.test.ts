import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/auth', () => ({ authenticatedFetch: vi.fn() }));
vi.mock('$lib/runs', () => ({ listRuns: vi.fn() }));

import { authenticatedFetch } from '$lib/auth';
import { listRuns } from '$lib/runs';
import {
  EvaluationApiError,
  compareEvaluations,
  createCandidate,
  createDriftReport,
  createEvaluation,
  decideCandidateApproval,
  getDriftReport,
  getEvaluation,
  isInsufficientSample,
  listCandidates,
  listEvaluations,
  listRecordedRuns,
  transitionCandidate,
} from './evaluations';

const fetchMock = vi.mocked(authenticatedFetch);
const runsMock = vi.mocked(listRuns);
const base = {
  id: 'eval/a', project_id: 'project a', dataset_id: 'grounded-v1', dataset_version: '1.0.0',
  dataset_hash: 'hash', status: 'completed', source_run_ids: ['one', 'two'], threshold: 0.85,
  aggregate_metrics: { mean_score: 0.9 }, passed: true, created_at: '2026-08-26T00:00:00Z',
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
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ items: [{ ...base, source_run_ids: null, aggregate_metrics: null, cases: null }] }), { status: 200 }));
    expect((await listEvaluations({ projectId: 'project/a', offset: 2 }))[0]).toEqual(expect.objectContaining({ source_run_ids: [], aggregate_metrics: {}, cases: [] }));
    expect(fetchMock.mock.calls[0][0]).toBe('/api/evals?project_id=project%2Fa&limit=50&offset=2');

    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(base), { status: 200 }));
    await getEvaluation('eval/a');
    expect(fetchMock.mock.calls[1][0]).toBe('/api/evals/eval%2Fa');

    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ a: base, b: base, metric_delta_b_minus_a: { mean_score: 0.1, bad: 'x' } }), { status: 200 }));
    expect((await compareEvaluations('eval a', 'eval/b')).metric_delta_b_minus_a).toEqual({ mean_score: 0.1 });
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

describe('drift and reviewed optimization client', () => {
  const drift = {
    id: 'drift/a', owner_id: 'owner-a', project_id: 'project/a', baseline_eval_id: 'base', candidate_eval_id: 'next',
    baseline_identity: {}, candidate_identity: {}, baseline_summary: { sample_count: 2 }, candidate_summary: { sample_count: 2 },
    deltas: { mean_score: -0.2 }, warnings: [{ metric: 'sample_count', direction: 'insufficient_sample', baseline_count: 2, candidate_count: 2, threshold: 20 }],
    minimum_sample_size: 20, created_at: '2026-08-28T00:00:00Z',
  };
  const candidate = {
    id: 'candidate/a', owner_id: 'owner-a', project_id: 'project/a', candidate_type: 'prompt', change_summary: 'Improve grounding',
    proposal_metadata: {}, rollback_plan: 'Restore rev-1', target_revision: 'rev-2', baseline_eval_id: 'base', candidate_eval_id: 'next',
    drift_report_id: 'drift/a', state: 'proposed', version: 7, approval_id: null, created_at: 'now', updated_at: 'now', promoted_at: null, rolled_back_at: null,
  } as const;

  it('uses project-scoped drift contracts and detects insufficient samples', async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(drift), { status: 201 }));
    const result = await createDriftReport({ projectId: 'project/a', baselineEvalId: 'base', candidateEvalId: 'next', minimumSampleSize: 20 });
    expect(isInsufficientSample(result)).toBe(true);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/evals/drift');
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({ project_id: 'project/a', baseline_eval_id: 'base', candidate_eval_id: 'next', minimum_sample_size: 20 });
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(drift)));
    await getDriftReport('drift/a', 'project/a');
    expect(fetchMock.mock.calls[1][0]).toBe('/api/evals/drift/drift%2Fa?project_id=project%2Fa');
  });

  it('lists and creates project-aware candidates without autonomously promoting', async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ items: [candidate] })));
    expect(await listCandidates('project/a')).toHaveLength(1);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/evals/candidates?project_id=project%2Fa&limit=50');
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(candidate), { status: 201 }));
    await createCandidate({ projectId: 'project/a', candidateType: 'prompt', changeSummary: 'Improve grounding', rollbackPlan: 'Restore rev-1', targetRevision: 'rev-2', baselineEvalId: 'base', candidateEvalId: 'next', driftReportId: 'drift/a' });
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({ project_id: 'project/a', candidate_type: 'prompt', change_summary: 'Improve grounding', proposal_metadata: {}, rollback_plan: 'Restore rev-1', target_revision: 'rev-2', baseline_eval_id: 'base', candidate_eval_id: 'next', drift_report_id: 'drift/a' });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/promote'))).toBe(false);
  });

  it('binds the explicit human decision to the candidate run', async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ approved: true })));
    await decideCandidateApproval('tool/a', 'candidate/a', true);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/chat/approve/tool%2Fa');
    expect(JSON.parse(String(init?.body))).toEqual({ run_id: 'candidate/a', approved: true });
  });

  it('sends exact expected-version snapshots for every review action', async () => {
    const cases = [
      ['approval', {}, '/approval'], ['approve', { approvalId: 'receipt-1' }, '/approve'],
      ['reject', { reasonCode: 'poor_quality' }, '/reject'], ['promote', {}, '/promote'], ['rollback', { reasonCode: 'regression' }, '/rollback'],
    ] as const;
    for (const [action, extra, suffix] of cases) {
      fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(action === 'approval' ? { approval_id: 'receipt-1', tool_call_id: 'tool-1' } : candidate)));
      await transitionCandidate('candidate/a', action, { projectId: 'project/a', expectedVersion: 7, ...extra });
      const [url, init] = fetchMock.mock.calls.at(-1)!;
      expect(url).toBe(`/api/evals/candidates/candidate%2Fa${suffix}`);
      expect(JSON.parse(String(init?.body))).toEqual({ project_id: 'project/a', expected_version: 7, ...(action === 'approve' ? { approval_id: 'receipt-1' } : {}), ...(action === 'reject' ? { reason_code: 'poor_quality' } : {}), ...(action === 'rollback' ? { reason_code: 'regression' } : {}) });
    }
  });

  it('bounds server-controlled error detail', async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'x'.repeat(1000) }), { status: 409 }));
    await expect(listCandidates('p')).rejects.toMatchObject({ status: 409, message: 'x'.repeat(300) });
  });
});
