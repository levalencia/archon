import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';

import ChatMessages from './ChatMessages.svelte';

const teamMessage = {
  id: 'answer-team',
  role: 'assistant' as const,
  content: 'Team answer',
  timestamp: '',
  status: 'completed' as const,
  iterations: 1,
  tool_calls: [],
  orchestration: {
    requested_mode: 'team' as const,
    resolved_mode: 'team' as const,
    reason_code: 'user_forced_team',
  },
  child_agents: [
    {
      child_id: 'child-researcher',
      profile_id: 'researcher-v1',
      specialist_kind: 'fixed' as const,
      status: 'completed' as const,
      iterations: 2,
      total_tokens: 42,
      tool_count: 3,
    },
    {
      child_id: 'child-analyst',
      profile_id: 'dynamic-analyst-v1',
      specialist_kind: 'dynamic' as const,
      status: 'completed' as const,
      iterations: 2,
      total_tokens: 31,
      tool_count: 3,
    },
  ],
};

afterEach(cleanup);

describe('ChatMessages Team execution', () => {
  it('renders safe child lifecycle evidence inline with aggregate counts', () => {
    render(ChatMessages, { props: { messages: [teamMessage] } });

    const team = screen.getByRole('region', { name: 'Team execution' });
    expect(team.textContent).toContain('team → team');
    expect(team.textContent).toContain('researcher-v1');
    expect(team.textContent).toContain('dynamic-analyst-v1');
    expect(team.textContent).toContain('2 iterations');
    expect(team.textContent).toContain('3 tools');
    const summary = screen.getByRole('region', { name: 'Execution summary' });
    expect(summary.textContent).toContain('6 tools');
    expect(summary.textContent).toContain('5 iterations');
  });

  it('does not render Team evidence for a single-agent message', () => {
    render(ChatMessages, {
      props: {
        messages: [{
          id: 'answer-single', role: 'assistant', content: 'Single answer', timestamp: '',
          status: 'completed', iterations: 1, tool_calls: [],
          orchestration: {
            requested_mode: 'single', resolved_mode: 'single', reason_code: 'user_forced_single',
          },
        }],
      },
    });

    expect(screen.queryByRole('region', { name: 'Team execution' })).toBeNull();
  });
});
