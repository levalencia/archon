import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  listJobs: vi.fn(), getJob: vi.fn(), cancelJob: vi.fn(), retryJob: vi.fn(),
}));
vi.mock('$lib/jobs', () => api);
import JobInspector from './JobInspector.svelte';

const failedJob = {
  job_id: 'job-123456789', owner_id: 'owner-1', project_id: 'project-a', kind: 'run_export', status: 'dead_letter',
  attempts: 3, max_attempts: 3, idempotency_key: 'export-run-42', created_at: '2026-08-28T10:00:00Z',
  updated_at: '2026-08-28T10:01:00Z', completed_at: '2026-08-28T10:01:00Z', error_code: 'handler_failed',
  result: { export_id: 'export-1', payload: { secret: 'never-render-this' } },
} as const;

afterEach(() => {
  cleanup();
  Object.values(api).forEach((mock) => mock.mockReset());
});

describe('JobInspector', () => {
  it('shows lifecycle and safe metadata without rendering raw payloads, then retries', async () => {
    api.listJobs.mockResolvedValueOnce([failedJob]).mockResolvedValue([{ ...failedJob, status: 'pending', attempts: 0, completed_at: null, error_code: null }]);
    api.getJob.mockResolvedValueOnce(failedJob).mockResolvedValueOnce({ ...failedJob, status: 'pending', attempts: 0, completed_at: null, error_code: null });
    api.retryJob.mockResolvedValue({ job_id: failedJob.job_id, status: 'pending' });
    render(JobInspector);

    const row = await screen.findByRole('button', { name: /Inspect run_export job/ });
    await fireEvent.click(row);
    await screen.findByText('Idempotency lineage');
    expect(screen.getByText('export-run-42')).toBeTruthy();
    expect(screen.getByText('handler failed')).toBeTruthy();
    expect(screen.getByText('export-1')).toBeTruthy();
    expect(screen.queryByText('never-render-this')).toBeNull();

    await fireEvent.click(screen.getByRole('button', { name: 'Retry job' }));
    await waitFor(() => expect(api.retryJob).toHaveBeenCalledWith(failedJob.job_id, 'project-a'));
    await waitFor(() => expect(screen.getAllByText('Pending').length).toBeGreaterThan(0));
    await waitFor(() => expect(api.listJobs.mock.calls.length).toBeGreaterThanOrEqual(2));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Refresh durable jobs' }).hasAttribute('disabled')).toBe(false));

    api.listJobs.mockResolvedValue([]);
    await fireEvent.input(screen.getByLabelText('Project scope'), { target: { value: 'project-b' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Apply filter' }));
    await screen.findByText('No durable jobs found');

    api.listJobs.mockRejectedValue(new Error('Jobs are temporarily unavailable'));
    await fireEvent.click(screen.getByRole('button', { name: 'Refresh durable jobs' }));
    await screen.findByRole('alert');
    expect(screen.getByRole('alert').textContent).toContain('Jobs are temporarily unavailable');
    expect(api.listJobs).toHaveBeenLastCalledWith({ projectId: 'project-b', limit: 50 });
  });
});
