import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason?: unknown) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}

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

const pendingJob = {
  ...failedJob,
  job_id: 'job-987654321',
  project_id: 'project-b',
  kind: 'echo',
  status: 'pending',
  attempts: 0,
  completed_at: null,
  error_code: null,
  result: null,
} as const;

afterEach(() => {
  vi.useRealTimers();
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

  it('ignores stale detail responses after selecting another job', async () => {
    const first = deferred<typeof failedJob>();
    const second = deferred<typeof pendingJob>();
    api.listJobs.mockResolvedValue([failedJob, pendingJob]);
    api.getJob.mockImplementation((jobId: string) => jobId === failedJob.job_id ? first.promise : second.promise);
    render(JobInspector);

    const firstRow = await screen.findByRole('button', { name: `Inspect run_export job ${failedJob.job_id}` });
    const secondRow = screen.getByRole('button', { name: `Inspect echo job ${pendingJob.job_id}` });
    await fireEvent.click(firstRow);
    await fireEvent.click(secondRow);
    second.resolve(pendingJob);
    await waitFor(() => expect(secondRow.classList.contains('selected')).toBe(true));

    first.resolve(failedJob);
    await Promise.resolve();
    await waitFor(() => {
      expect(secondRow.classList.contains('selected')).toBe(true);
      expect(firstRow.classList.contains('selected')).toBe(false);
    });
  });

  it('invalidates pending detail when the project filter changes', async () => {
    const detail = deferred<typeof failedJob>();
    api.listJobs.mockResolvedValueOnce([failedJob]).mockResolvedValueOnce([]);
    api.getJob.mockReturnValue(detail.promise);
    render(JobInspector);

    await fireEvent.click(await screen.findByRole('button', { name: /Inspect run_export job/ }));
    await fireEvent.input(screen.getByLabelText('Project scope'), { target: { value: 'project-b' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Apply filter' }));
    await screen.findByText('No durable jobs found');
    detail.resolve(failedJob);
    await Promise.resolve();
    expect(screen.queryByText('Idempotency lineage')).toBeNull();
  });

  it('snapshots the action target and disables selection while retry is pending', async () => {
    const retry = deferred<{ job_id: string; status: 'pending' }>();
    api.listJobs.mockResolvedValue([failedJob, pendingJob]);
    api.getJob.mockResolvedValueOnce(failedJob).mockResolvedValueOnce({ ...failedJob, status: 'pending', attempts: 0, completed_at: null, error_code: null });
    api.retryJob.mockReturnValue(retry.promise);
    render(JobInspector);

    const firstRow = await screen.findByRole('button', { name: `Inspect run_export job ${failedJob.job_id}` });
    const secondRow = screen.getByRole('button', { name: `Inspect echo job ${pendingJob.job_id}` });
    await fireEvent.click(firstRow);
    await screen.findByText('Idempotency lineage');
    await fireEvent.click(screen.getByRole('button', { name: 'Retry job' }));
    expect(firstRow.hasAttribute('disabled')).toBe(true);
    expect(secondRow.hasAttribute('disabled')).toBe(true);
    await fireEvent.click(secondRow);
    expect(api.getJob).toHaveBeenCalledTimes(1);
    expect(api.retryJob).toHaveBeenCalledWith(failedJob.job_id, failedJob.project_id);

    retry.resolve({ job_id: failedJob.job_id, status: 'pending' });
    await waitFor(() => expect(api.getJob).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(firstRow.classList.contains('selected')).toBe(true));
  });

  it('never lets a stale list response overwrite fresh job detail', async () => {
    const staleList = deferred<(typeof failedJob)[]>();
    const freshDetail = { ...failedJob, idempotency_key: 'fresh-detail-lineage', attempts: 2 };
    api.listJobs.mockResolvedValueOnce([failedJob]).mockReturnValueOnce(staleList.promise);
    api.getJob.mockResolvedValue(freshDetail);
    render(JobInspector);

    await fireEvent.click(await screen.findByRole('button', { name: /Inspect run_export job/ }));
    await screen.findByText('fresh-detail-lineage');
    await fireEvent.click(screen.getByRole('button', { name: 'Refresh durable jobs' }));
    expect(api.listJobs).toHaveBeenCalledTimes(2);

    staleList.resolve([failedJob]);
    await waitFor(() => expect(screen.getByText('fresh-detail-lineage')).toBeTruthy());
    expect(screen.queryByText('export-run-42')).toBeNull();
  });

  it('serializes polling while the initial list request is unresolved', async () => {
    vi.useFakeTimers();
    const initial = deferred<(typeof failedJob)[]>();
    api.listJobs.mockReturnValue(initial.promise);
    render(JobInspector);

    await vi.advanceTimersByTimeAsync(24_000);
    expect(api.listJobs).toHaveBeenCalledTimes(1);
    initial.resolve([failedJob]);
    await vi.runAllTicks();
    await Promise.resolve();
    expect(api.listJobs).toHaveBeenCalledTimes(1);
  });
});
