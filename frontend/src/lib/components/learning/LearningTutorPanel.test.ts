import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ askLearningTutor: vi.fn() }));
vi.mock('$lib/learning-tutor', async () => {
  const actual = await vi.importActual<typeof import('$lib/learning-tutor')>('$lib/learning-tutor');
  return { ...actual, askLearningTutor: api.askLearningTutor };
});

import LearningTutorPanel from './LearningTutorPanel.svelte';

const context = {
  view: 'present' as const,
  artifact_id: 'code-first-video-02',
  playback_seconds: 300,
};

afterEach(() => {
  cleanup();
  localStorage.clear();
  api.askLearningTutor.mockReset();
});

describe('LearningTutorPanel', () => {
  it('opens from an accessible trigger and asks with the current context', async () => {
    api.askLearningTutor.mockResolvedValue({
      run_id: 'run-1',
      session_id: 'session-1',
      answer_markdown: '## Direct answer\nA service slot starts empty. [E1]\n\n```python\napp.state.sandbox_executor = None\n```',
      citations: [{
        id: 'E1', kind: 'code', title: 'main.py — create_app',
        excerpt: 'app.state.sandbox_executor = None', score: 1,
        source_commit: 'a'.repeat(40),
        locator: { path: 'backend/app/main.py', line_start: 418, line_end: 420 },
      }],
      related_questions: ['When is the slot populated?'],
      diagram: null,
      grounded: true,
      unsupported: [],
      metrics: { faithfulness_score: 1 },
    });

    render(LearningTutorPanel, { props: { context, contextTitle: 'Video 2 — Building FastAPI' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Ask about this topic' }));
    expect(screen.getByRole('complementary', { name: 'Learning tutor' })).toBeTruthy();
    await fireEvent.input(screen.getByLabelText('Question about this topic'), {
      target: { value: 'What is a service slot?' },
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Ask Cogentrex tutor' }));

    await waitFor(() => expect(api.askLearningTutor).toHaveBeenCalledWith(
      'What is a service slot?', context,
    ));
    expect(await screen.findByText('A service slot starts empty. [E1]')).toBeTruthy();
    expect(screen.getAllByText('app.state.sandbox_executor = None')).toHaveLength(2);
    expect(screen.getByRole('link', { name: 'Open evidence' }).getAttribute('href')).toMatch(
      /main\.py#L418-L420$/,
    );
  });

  it('closes with the labelled close button', async () => {
    render(LearningTutorPanel, { props: { context, contextTitle: 'Video 2' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Ask about this topic' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Close learning tutor' }));
    expect(screen.queryByRole('complementary', { name: 'Learning tutor' })).toBeNull();
  });
});
