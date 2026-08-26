import { beforeEach, describe, expect, it, vi } from 'vitest';
vi.mock('$lib/auth', () => ({ authenticatedFetch: vi.fn() }));
import { authenticatedFetch } from '$lib/auth';
import { RunApiError, compareRuns, getRunEvents, listRuns } from './runs';

const fetchMock = vi.mocked(authenticatedFetch);
beforeEach(() => fetchMock.mockReset());

describe('persisted run client', () => {
  it('encodes filters and normalizes events into sequence order', async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ items: [] }), { status: 200 }));
    await listRuns({ conversationId: 'conversation/a', projectId: 'p', offset: 2 });
    expect(fetchMock.mock.calls[0][0]).toContain('conversation_id=conversation%2Fa');
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ items: [
      { sequence: 2, event_at: '', kind: 'run_stopped', iteration: 1, payload: {} },
      { sequence: 1, event_at: '', kind: 'run_started', iteration: 0, payload: {} },
    ] }), { status: 200 }));
    expect((await getRunEvents('run/1')).map(e => e.sequence)).toEqual([1, 2]);
  });

  it('uses explicit errors for auth/not-found and calls compare endpoint', async () => {
    fetchMock.mockResolvedValueOnce(new Response('', { status: 401 }));
    await expect(listRuns()).rejects.toEqual(expect.objectContaining<Partial<RunApiError>>({ status: 401, message: 'Sign in required' }));
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ a: {}, b: {} }), { status: 200 }));
    await compareRuns('a one', 'b/two');
    expect(fetchMock.mock.calls[1][0]).toBe('/api/runs/compare?a=a+one&b=b%2Ftwo');
  });
});
