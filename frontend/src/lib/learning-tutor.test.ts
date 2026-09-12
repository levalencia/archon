import { describe, expect, it, vi } from 'vitest';

import {
  askLearningTutor,
  citationHref,
  streamLearningTutor,
  type LearningTutorContext,
  type TutorCitation,
  type TutorStreamCallbacks,
} from './learning-tutor';
import { SSEParser } from './sse';

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

  it('streams verified tutor answer via SSE', async () => {
    const ssePayload = [
      'event: status\ndata: {"run_id":"r1","phase":"started","message":"Retrieving…"}\n\n',
      'event: progress\ndata: {"run_id":"r1","phase":"retrieving","message":"Searching…"}\n\n',
      ': heartbeat\n\n',
      'event: progress\ndata: {"run_id":"r1","phase":"verified","message":"Verified."}\n\n',
      'event: answer_delta\ndata: {"run_id":"r1","index":0,"delta":"A service slot "}\n\n',
      'event: answer_delta\ndata: {"run_id":"r1","index":1,"delta":"starts empty. [E1]"}\n\n',
      `event: result\ndata: ${JSON.stringify({
        run_id: 'r1', session_id: 's1', answer_markdown: 'A service slot starts empty. [E1]',
        citations: [codeCitation], related_questions: [], diagram: null,
        grounded: true, unsupported: [], metrics: { faithfulness_score: 1 },
      })}\n\n`,
      'event: done\ndata: {"run_id":"r1"}\n\n',
    ].join('');

    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode(ssePayload));
        controller.close();
      },
    });

    const fetcher = vi.fn(async () => new Response(stream, {
      status: 200,
      headers: { 'content-type': 'text/event-stream' },
    }));

    const collected: string[] = [];
    const deltas: string[] = [];
    let finalResult: any;

    await streamLearningTutor('What is a service slot?', context, {
      onStatus(d) { collected.push(`status:${d.phase}`); },
      onProgress(d) { collected.push(`progress:${d.phase}`); },
      onAnswerDelta(d) { deltas.push(d.delta); },
      onResult(d) { finalResult = d; collected.push('result'); },
      onDone() { collected.push('done'); },
    }, fetcher);

    expect(collected).toEqual(['status:started', 'progress:retrieving', 'progress:verified', 'result', 'done']);
    expect(deltas.join('')).toBe('A service slot starts empty. [E1]');
    expect(finalResult.grounded).toBe(true);
    expect(finalResult.citations[0].locator.line_start).toBe(418);
  });

  it('throws on non-ok SSE response', async () => {
    const fetcher = vi.fn(async () => new Response('Unauthorized', { status: 401 }));
    await expect(streamLearningTutor('test', context, {}, fetcher)).rejects.toThrow('401');
  });

  it('builds web citation href for allowlisted HTTPS domains', () => {
    const webCitation: TutorCitation = {
      id: 'W1',
      kind: 'web',
      title: 'Shared services - Wikipedia',
      excerpt: 'A shared service is...',
      score: 0,
      source_commit: '',
      locator: {
        url: 'https://en.wikipedia.org/wiki/Shared_services',
        domain: 'en.wikipedia.org',
        retrieved_at: 1000,
        search_source: 'brave',
      },
    };
    expect(citationHref(webCitation)).toBe('https://en.wikipedia.org/wiki/Shared_services');
  });

  it('rejects web citations from non-allowlisted domains', () => {
    const webCitation: TutorCitation = {
      id: 'W2',
      kind: 'web',
      title: 'Evil page',
      excerpt: 'Nefarious content',
      score: 0,
      source_commit: '',
      locator: {
        url: 'https://evil.example.com/page',
        domain: 'evil.example.com',
      },
    };
    expect(citationHref(webCitation)).toBeUndefined();
  });

  it('rejects web citations with HTTP (non-HTTPS) URLs', () => {
    const webCitation: TutorCitation = {
      id: 'W3',
      kind: 'web',
      title: 'Python docs',
      excerpt: 'asyncio',
      score: 0,
      source_commit: '',
      locator: {
        url: 'http://docs.python.org/3/library/asyncio.html',
        domain: 'docs.python.org',
      },
    };
    expect(citationHref(webCitation)).toBeUndefined();
  });
});
