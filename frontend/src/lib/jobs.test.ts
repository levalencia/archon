import { beforeEach, describe, expect, it, vi } from 'vitest';
vi.mock('$lib/auth', () => ({ authenticatedFetch: vi.fn() }));
import { authenticatedFetch } from '$lib/auth';
import { cancelJob, createJob, getJob, JobApiError, listJobs, retryJob } from './jobs';

const fetchMock = vi.mocked(authenticatedFetch);
beforeEach(() => fetchMock.mockReset());

describe('durable jobs client', () => {
  it('creates an allowlisted job with idempotency and retry bounds', async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ job_id: 'job-1' }), { status: 201 }));
    await createJob({ kind: 'run_export', projectId: 'project/a', payload: { run_id: 'run-1' }, idempotencyKey: 'export-1', maxAttempts: 4 });
    expect(fetchMock).toHaveBeenCalledWith('/api/tasks', expect.objectContaining({ method: 'POST' }));
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      kind: 'run_export', project_id: 'project/a', payload: { run_id: 'run-1' }, idempotency_key: 'export-1', max_attempts: 4,
    });
  });

  it('encodes owner-scoped list and detail routes', async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ items: [] }), { status: 200 }));
    await listJobs({ projectId: 'project/a', limit: 25, offset: 5 });
    expect(fetchMock.mock.calls[0][0]).toBe('/api/tasks?project_id=project%2Fa&limit=25&offset=5');
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ job_id: 'job/1' }), { status: 200 }));
    await getJob('job/1', 'project/a');
    expect(fetchMock.mock.calls[1][0]).toBe('/api/tasks/job%2F1?project_id=project%2Fa');
  });

  it('posts cancel and retry controls to encoded job routes', async () => {
    fetchMock.mockImplementation(async () => new Response(JSON.stringify({ job_id: 'job/1', status: 'pending' }), { status: 200 }));
    await cancelJob('job/1', 'project/a');
    await retryJob('job/1', 'project/a');
    expect(fetchMock.mock.calls).toEqual([
      ['/api/tasks/job%2F1/cancel?project_id=project%2Fa', { method: 'POST' }],
      ['/api/tasks/job%2F1/retry?project_id=project%2Fa', { method: 'POST' }],
    ]);
  });

  it('surfaces bounded safe API errors and stable fallbacks', async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Retryable job not found' }), { status: 404 }));
    await expect(retryJob('missing', 'project-a')).rejects.toEqual(expect.objectContaining<Partial<JobApiError>>({ status: 404, message: 'Retryable job not found' }));
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'x'.repeat(301) }), { status: 500 }));
    await expect(listJobs()).rejects.toThrow('Job request failed (500)');
  });
});
