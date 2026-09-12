import { describe, expect, it, vi } from 'vitest';
import { getLearningArtifact, getMediaAccess, loadLearningLibrary } from './learning-artifacts';

const catalog = {
  schema: 'cogentrex.learning-library',
  version: 1,
  generated_at: '2026-09-04T12:00:00Z',
  source_commit: 'a'.repeat(40),
  packs: [{
    id: 'request-lifecycle',
    title: 'Request Lifecycle',
    purpose: 'Follow a governed request end to end.',
    artifacts: [{
      id: 'request-deck', type: 'deck', title: 'Request Lifecycle Deck',
      status: 'published', language: 'en', media_type: 'application/json',
      sha256: 'b'.repeat(64), source_commit: 'a'.repeat(40),
      limitations: ['Derived learning material.'],
    }],
  }],
};

describe('learning artifact client', () => {
  it('loads and validates an English published catalog', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(catalog), { status: 200 }));
    await expect(loadLearningLibrary(fetcher)).resolves.toEqual(catalog);
    expect(fetcher).toHaveBeenCalledWith('/api/learning-media/catalog');
  });

  it('rejects malformed or non-English catalogs', async () => {
    const malformed = structuredClone(catalog);
    malformed.packs[0].artifacts[0].language = 'es';
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(malformed), { status: 200 }));
    await expect(loadLearningLibrary(fetcher)).rejects.toThrow('catalog');
  });

  it('loads structured artifact content', async () => {
    const detail = { ...catalog.packs[0].artifacts[0], content: { slides: [] } };
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(detail), { status: 200 }));
    await expect(getLearningArtifact('request-deck', fetcher)).resolves.toEqual(detail);
  });

  it('gets a short-lived media URL', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ url: '/media/x', expires_at: 10 }), { status: 200 }));
    await expect(getMediaAccess('request-audio', fetcher)).resolves.toEqual({ url: '/media/x', expires_at: 10 });
  });
});
