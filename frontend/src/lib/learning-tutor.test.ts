import { describe, expect, it, vi } from 'vitest';

import {
  askLearningTutor,
  citationHref,
  type LearningTutorContext,
  type TutorCitation,
} from './learning-tutor';

const context: LearningTutorContext = {
  view: 'present',
  artifact_id: 'code-first-video-02',
  playback_seconds: 300,
};

const codeCitation: TutorCitation = {
  id: 'E1',
  kind: 'code',
  title: 'main.py — create_app',
  excerpt: 'app.state.sandbox_executor = None',
  score: 1,
  source_commit: 'a'.repeat(40),
  locator: { path: 'backend/app/main.py', line_start: 418, line_end: 420 },
};

describe('learning tutor client', () => {
  it('submits only typed context identifiers', async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body));
      expect(body).toEqual({
        question: 'What is a service slot?',
        project_id: 'default',
        context,
      });
      return new Response(JSON.stringify({
        run_id: 'run-1', session_id: 'session-1', answer_markdown: 'Answer [E1]',
        citations: [codeCitation], related_questions: [], diagram: null,
        grounded: true, unsupported: [], metrics: { faithfulness_score: 1 },
      }), { status: 200, headers: { 'content-type': 'application/json' } });
    });

    const response = await askLearningTutor('What is a service slot?', context, fetcher);
    expect(response.grounded).toBe(true);
    expect(response.citations[0].locator.line_start).toBe(418);
  });

  it('builds commit-pinned code links and timestamped video links', () => {
    expect(citationHref(codeCitation)).toBe(
      `https://github.com/levalencia/cogentrex/blob/${'a'.repeat(40)}/backend/app/main.py#L418-L420`,
    );
    expect(citationHref({
      ...codeCitation,
      kind: 'video',
      locator: { artifact_id: 'code-first-video-02', start_seconds: 286.94 },
    })).toBe('/learn?view=present&pack=code-first-series&artifact=code-first-video-02&t=286.94');
  });

  it('refuses unpinned and traversal citation links', () => {
    expect(citationHref({ ...codeCitation, source_commit: 'working-tree:abc' })).toBeUndefined();
    expect(citationHref({
      ...codeCitation,
      locator: { path: '../private.txt', line_start: 1, line_end: 1 },
    })).toBeUndefined();
  });
});
