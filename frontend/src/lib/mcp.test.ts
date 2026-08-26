import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  createServer, deleteServer, discoverTools, listProfiles, listServers,
  listTools, toggleTool, updateServer,
} from './mcp';
import { authenticatedFetch } from './auth';

vi.mock('./auth', () => ({ authenticatedFetch: vi.fn() }));
const api = vi.mocked(authenticatedFetch);
const ok = (body: unknown, status = 200) => new Response(status === 204 ? null : JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json' },
});

describe('MCP API contracts', () => {
  beforeEach(() => api.mockReset());

  it('uses the safe profiles and project-scoped inventory routes', async () => {
    api.mockResolvedValueOnce(ok([{ id: 'docs', display_name: 'Docs' }]))
      .mockResolvedValueOnce(ok([]));
    await expect(listProfiles()).resolves.toEqual([{ id: 'docs', display_name: 'Docs' }]);
    await listServers('team/a');
    expect(api).toHaveBeenNthCalledWith(1, '/api/mcp/profiles', undefined);
    expect(api).toHaveBeenNthCalledWith(2, '/api/mcp/servers?project_id=team%2Fa', undefined);
  });

  it('creates, edits, discovers, inventories, toggles, and deletes without an execution endpoint', async () => {
    api.mockImplementation(async () => ok({}, 200));
    await createServer('default', 'Docs', 'docs');
    await updateServer('default', 'server/1', { enabled: false });
    await discoverTools('default', 'server/1');
    await listTools('default', 'server/1');
    await toggleTool('default', 'server/1', 'search/docs', true);
    api.mockResolvedValueOnce(ok(null, 204));
    await deleteServer('default', 'server/1');

    const calls = api.mock.calls.map(([url, init]) => [url, init?.method]);
    expect(calls).toEqual([
      ['/api/mcp/servers', 'POST'],
      ['/api/mcp/servers/server%2F1?project_id=default', 'PATCH'],
      ['/api/mcp/servers/server%2F1/discover?project_id=default', 'POST'],
      ['/api/mcp/servers/server%2F1/tools?project_id=default', undefined],
      ['/api/mcp/servers/server%2F1/tools/search%2Fdocs?project_id=default', 'PATCH'],
      ['/api/mcp/servers/server%2F1?project_id=default', 'DELETE'],
    ]);
    expect(JSON.parse(String(api.mock.calls[0][1]?.body))).toEqual({ project_id: 'default', name: 'Docs', profile_id: 'docs', enabled: true });
    expect(calls.some(([url]) => String(url).includes('/request'))).toBe(false);
  });

  it('normalizes authentication and structured API errors', async () => {
    api.mockResolvedValueOnce(ok({ detail: { code: 'owner_mismatch' } }, 403));
    await expect(listProfiles()).rejects.toMatchObject({ status: 403, code: 'owner_mismatch' });
    api.mockResolvedValueOnce(new Response('', { status: 401 }));
    await expect(listProfiles()).rejects.toMatchObject({ status: 401, code: 'unauthorized' });
  });
});
