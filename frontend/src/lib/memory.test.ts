import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/auth', () => ({ authenticatedFetch: vi.fn() }));

import { authenticatedFetch } from '$lib/auth';
import { getMemoryRotation, rotateMemoryKeys } from './memory';

const fetchMock = vi.mocked(authenticatedFetch);

beforeEach(() => fetchMock.mockReset());

describe('memory rotation client', () => {
  it('encodes project scope and posts a bounded batch', async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          project_id: 'project/a',
          active_version: 2,
          version_counts: { '1': 1, '2': 3 },
          remaining: 1,
          complete: false,
          retirement_requires_legacy_writer_drain: true,
        }),
        { status: 200 },
      ),
    );

    await getMemoryRotation('project/a');
    await rotateMemoryKeys('project/a', 25);

    expect(fetchMock.mock.calls[0][0]).toBe('/api/memory/rotation?project_id=project%2Fa');
    expect(fetchMock.mock.calls[1]).toEqual([
      '/api/memory/rotation?project_id=project%2Fa',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ batch_size: 25 }) }),
    ]);
  });

  it('raises a safe status-only error', async () => {
    fetchMock.mockResolvedValueOnce(new Response('', { status: 429 }));
    await expect(getMemoryRotation()).rejects.toThrow('Memory rotation request failed (429)');
  });
});
