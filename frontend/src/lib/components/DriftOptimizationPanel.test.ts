import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  createCandidate: vi.fn(),
  createDriftReport: vi.fn(),
  decideCandidateApproval: vi.fn(),
  getDriftReport: vi.fn(),
  isInsufficientSample: vi.fn(() => false),
  listCandidates: vi.fn(),
  transitionCandidate: vi.fn(),
}));

vi.mock('$lib/evaluations', () => api);
import DriftOptimizationPanel from './DriftOptimizationPanel.svelte';

const evaluation = (id: string) => ({
  id,
  project_id: 'project-a',
  dataset_id: 'grounded-v1',
  dataset_version: '1',
  dataset_hash: 'a'.repeat(64),
  model_revision: 'model-v1',
  provider_revision: 'provider-v1',
  config_revision: 'config-v1',
  source_run_ids: [],
  threshold: 0.8,
  status: 'completed',
  passed: true,
  aggregate_metrics: { mean_score: 0.9 },
  created_at: '2026-08-28T00:00:00Z',
  updated_at: '2026-08-28T00:00:00Z',
  completed_at: '2026-08-28T00:00:00Z',
  cases: [],
});

const proposed = {
  id: 'candidate-a',
  owner_id: 'owner-a',
  project_id: 'project-a',
  candidate_type: 'prompt',
  change_summary: 'Use template revision p2',
  proposal_metadata: { template_revision: 'p2' },
  rollback_plan: 'Restore p1',
  target_revision: 'p2',
  baseline_eval_id: 'eval-a',
  candidate_eval_id: 'eval-b',
  drift_report_id: 'drift-a',
  state: 'proposed',
  version: 1,
  approval_id: null,
  created_at: 'now',
  updated_at: 'now',
  promoted_at: null,
  rolled_back_at: null,
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('DriftOptimizationPanel approval workflow', () => {
  it('records no approval until the human clicks and binds the exact receipt', async () => {
    api.listCandidates.mockResolvedValue([proposed]);
    api.transitionCandidate
      .mockResolvedValueOnce({ approval_id: 'approval-a', tool_call_id: 'tool-a' })
      .mockResolvedValueOnce({ ...proposed, state: 'approved', version: 2, approval_id: 'approval-a' });
    api.decideCandidateApproval.mockResolvedValue(undefined);

    render(DriftOptimizationPanel, {
      props: { projectId: 'project-a', evaluations: [evaluation('eval-a'), evaluation('eval-b')] },
    });
    const request = await screen.findByRole('button', { name: 'Request human approval' });
    expect(api.decideCandidateApproval).not.toHaveBeenCalled();
    await fireEvent.click(request);
    const approve = await screen.findByRole('button', {
      name: 'Approve request and record decision',
    });
    expect(api.transitionCandidate).toHaveBeenNthCalledWith(1, 'candidate-a', 'approval', {
      projectId: 'project-a',
      expectedVersion: 1,
      approvalId: undefined,
      reasonCode: undefined,
    });
    await fireEvent.click(approve);
    await waitFor(() => {
      expect(api.decideCandidateApproval).toHaveBeenCalledWith('tool-a', 'candidate-a', true);
      expect(api.transitionCandidate).toHaveBeenNthCalledWith(2, 'candidate-a', 'approve', {
        projectId: 'project-a',
        expectedVersion: 1,
        approvalId: 'approval-a',
        reasonCode: undefined,
      });
    });
  });

  it('never attaches a report after the selected cohort pair changes', async () => {
    api.listCandidates.mockResolvedValue([]);
    api.createDriftReport.mockResolvedValue({
      id: 'drift-ab',
      project_id: 'project-a',
      baseline_eval_id: 'eval-a',
      candidate_eval_id: 'eval-b',
      baseline_identity: {}, candidate_identity: {}, baseline_summary: {}, candidate_summary: {},
      deltas: {}, warnings: [], minimum_sample_size: 2, created_at: 'now',
    });
    api.createCandidate.mockResolvedValue({
      ...proposed,
      id: 'candidate-c',
      baseline_eval_id: 'eval-a',
      candidate_eval_id: 'eval-c',
      drift_report_id: null,
    });
    render(DriftOptimizationPanel, {
      props: {
        projectId: 'project-a',
        evaluations: [evaluation('eval-a'), evaluation('eval-b'), evaluation('eval-c')],
      },
    });
    await fireEvent.change(screen.getByLabelText('Drift reference cohort'), {
      target: { value: 'eval-a' },
    });
    await fireEvent.change(screen.getByLabelText('Drift comparison cohort'), {
      target: { value: 'eval-b' },
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Create drift comparison' }));
    await screen.findByText('Drift report');
    await fireEvent.change(screen.getByLabelText('Drift comparison cohort'), {
      target: { value: 'eval-c' },
    });
    await fireEvent.input(screen.getByLabelText('Declared target revision'), {
      target: { value: 'p3' },
    });
    await fireEvent.input(screen.getByLabelText('Change summary'), {
      target: { value: 'Use p3' },
    });
    await fireEvent.input(screen.getByLabelText('Rollback plan'), {
      target: { value: 'Restore p2' },
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Create candidate' }));
    await waitFor(() => {
      expect(api.createCandidate).toHaveBeenCalledWith(expect.objectContaining({
        baselineEvalId: 'eval-a',
        candidateEvalId: 'eval-c',
        driftReportId: undefined,
      }));
    });
  });

  it('releases drift busy state when the selected pair changes mid-request', async () => {
    api.listCandidates.mockResolvedValue([]);
    api.createDriftReport.mockReturnValue(new Promise(() => {}));
    render(DriftOptimizationPanel, {
      props: {
        projectId: 'project-a',
        evaluations: [evaluation('eval-a'), evaluation('eval-b'), evaluation('eval-c')],
      },
    });
    await fireEvent.change(screen.getByLabelText('Drift reference cohort'), {
      target: { value: 'eval-a' },
    });
    await fireEvent.change(screen.getByLabelText('Drift comparison cohort'), {
      target: { value: 'eval-b' },
    });
    const compare = screen.getByRole('button', { name: 'Create drift comparison' });
    await fireEvent.click(compare);
    expect((compare as HTMLButtonElement).disabled).toBe(true);
    await fireEvent.change(screen.getByLabelText('Drift comparison cohort'), {
      target: { value: 'eval-c' },
    });
    await waitFor(() => expect((compare as HTMLButtonElement).disabled).toBe(false));
  });

  it('preserves newer form edits when an older create request completes', async () => {
    api.listCandidates.mockResolvedValue([]);
    let resolve!: (value: typeof proposed) => void;
    api.createCandidate.mockReturnValue(new Promise((done) => { resolve = done; }));
    render(DriftOptimizationPanel, {
      props: { projectId: 'project-a', evaluations: [evaluation('eval-a'), evaluation('eval-b')] },
    });
    const summary = screen.getByLabelText('Change summary');
    await fireEvent.input(screen.getByLabelText('Declared target revision'), {
      target: { value: 'p2' },
    });
    await fireEvent.input(summary, { target: { value: 'Original summary' } });
    await fireEvent.input(screen.getByLabelText('Rollback plan'), {
      target: { value: 'Restore p1' },
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Create candidate' }));
    await fireEvent.input(summary, { target: { value: 'Newer unsent summary' } });
    resolve(proposed);
    await waitFor(() => expect((summary as HTMLTextAreaElement).value).toBe('Newer unsent summary'));
  });
});
