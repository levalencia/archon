import { cleanup, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ArtifactPanel from './components/ArtifactPanel.svelte';

const artifact = {
  id: 'artifact-1',
  title: 'Private preview',
  type: 'html',
  content_length: 10,
};

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('ArtifactPanel', () => {
  it('loads previews with authentication and uses a scriptless sandbox', async () => {
    localStorage.setItem('archon_token', 'secret-token');
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('<p>safe preview</p>', { status: 200 }),
    );

    render(ArtifactPanel, { props: { artifacts: [artifact] } });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/artifacts/artifact-1/render');
    expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer secret-token');

    const frame = screen.getByTitle('Artifact preview');
    expect(frame.getAttribute('sandbox')).toBe('');
    await waitFor(() => expect(frame.getAttribute('srcdoc')).toContain('safe preview'));
  });
});
