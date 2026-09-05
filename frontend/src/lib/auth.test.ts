import { beforeEach, describe, expect, it, vi } from 'vitest';
import { authenticatedFetch } from './auth';

describe('authenticatedFetch', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('clears stale authentication after a 401 response', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    localStorage.setItem('archon_token', 'stale-token');
    localStorage.setItem('archon_user', JSON.stringify({ user_id: 'u1', username: 'luis' }));
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 401 })));

    const response = await authenticatedFetch('/api/learning-media/catalog');

    expect(response.status).toBe(401);
    expect(localStorage.getItem('archon_token')).toBeNull();
    expect(localStorage.getItem('archon_user')).toBeNull();
  });

  it('keeps valid authentication and sends the bearer token', async () => {
    localStorage.setItem('archon_token', 'valid-token');
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    await authenticatedFetch('/api/learning-media/catalog');

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get('Authorization')).toBe('Bearer valid-token');
    expect(localStorage.getItem('archon_token')).toBe('valid-token');
  });
});
