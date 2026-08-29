import { beforeEach, describe, expect, it, vi } from 'vitest';
vi.mock('$lib/auth', () => ({ authenticatedFetch: vi.fn() }));
import { authenticatedFetch } from '$lib/auth';
import {
  RunApiError,
  compareRuns,
  createRunExport,
  createShareGrant,
  getRunContext,
  getRunEvents,
  listRunExports,
  listRuns,
  listShareGrants,
  revokeShareGrant,
} from './runs';

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
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ run_id: 'run/1' }), { status: 200 }));
    await getRunContext('run/1');
    expect(fetchMock.mock.calls[2][0]).toBe('/api/runs/run%2F1/context');
  });

  it('uses typed owner-scoped export and grant endpoints', async () => {
    fetchMock.mockImplementation(async (url, init) => {
      if (init?.method === 'DELETE') return new Response(null, { status: 204 });
      if (init?.method === 'POST' && String(url).endsWith('/exports')) {
        return new Response(JSON.stringify({ export_id: 'export-1', run_id: 'run/1' }), { status: 201 });
      }
      if (init?.method === 'POST') {
        return new Response(JSON.stringify({ grant_id: 'grant-1', token: 'one-time-token' }), { status: 201 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    });

    await createRunExport('run/1');
    await listRunExports('run/1');
    await createShareGrant('run/1', 'export/1', 'recipient', 'audit', 3600);
    await listShareGrants('run/1', 'export/1');
    await revokeShareGrant('grant/1');

    expect(fetchMock.mock.calls[0][0]).toBe('/api/runs/run%2F1/exports');
    expect(fetchMock.mock.calls[2][0]).toBe('/api/runs/run%2F1/exports/export%2F1/shares');
    expect(JSON.parse(String(fetchMock.mock.calls[2][1]?.body))).toEqual({
      recipient_user_id: 'recipient', purpose: 'audit', expires_in_seconds: 3600,
    });
    expect(fetchMock.mock.calls[4]).toEqual([
      '/api/shares/grant%2F1', { method: 'DELETE' },
    ]);
  });

  it('uses explicit errors for auth/not-found and calls compare endpoint', async () => {
    fetchMock.mockResolvedValueOnce(new Response('', { status: 401 }));
    await expect(listRuns()).rejects.toEqual(expect.objectContaining<Partial<RunApiError>>({ status: 401, message: 'Sign in required' }));
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ a: {}, b: {} }), { status: 200 }));
    await compareRuns('a one', 'b/two');
    expect(fetchMock.mock.calls[1][0]).toBe('/api/runs/compare?a=a+one&b=b%2Ftwo');
  });
});
