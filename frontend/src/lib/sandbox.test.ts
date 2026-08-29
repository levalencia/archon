import { beforeEach, describe, expect, it, vi } from 'vitest';
vi.mock('$lib/auth', () => ({ authenticatedFetch: vi.fn() }));
import { authenticatedFetch } from '$lib/auth';
import { getSandboxStatus } from './sandbox';

const fetchMock = vi.mocked(authenticatedFetch);

beforeEach(() => fetchMock.mockReset());

describe('sandbox status client', () => {
  it('loads authenticated metadata with a bounded signal', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ enabled: true, available: true }), { status: 200 }));
    await expect(getSandboxStatus()).resolves.toEqual({ enabled: true, available: true });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/sandbox/status',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it('returns a stable status error', async () => {
    fetchMock.mockResolvedValue(new Response('{}', { status: 503 }));
    await expect(getSandboxStatus()).rejects.toThrow('Sandbox status unavailable (503)');
  });
});
