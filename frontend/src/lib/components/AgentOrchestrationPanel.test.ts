import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  listRunChildren: vi.fn(),
  getRunEvents: vi.fn(),
}));
vi.mock('$lib/runs', () => api);

import AgentOrchestrationPanel from './AgentOrchestrationPanel.svelte';

afterEach(cleanup);
beforeEach(() => {
  api.listRunChildren.mockReset().mockResolvedValue([]);
  api.getRunEvents.mockReset().mockResolvedValue([]);
});

describe('AgentOrchestrationPanel', () => {
  it('shows the routed mode and bounded child evidence', () => {
    render(AgentOrchestrationPanel, {
      props: {
        message: {
          id: 'answer-1',
          role: 'assistant',
          content: 'answer',
          timestamp: '',
          orchestration: {
            requested_mode: 'auto',
            resolved_mode: 'team',
            reason_code: 'cross_domain_task',
          },
          child_agents: [
            {
              child_id: 'child-1',
              profile_id: 'researcher-v1',
              specialist_kind: 'fixed',
              status: 'completed',
              total_tokens: 42,
              tool_count: 1,
            },
            {
              child_id: 'child-2',
              profile_id: 'dynamic-analyst-v1',
              specialist_kind: 'dynamic',
              status: 'failed',
              reason_code: 'provider_error',
            },
          ],
        },
      },
    });

    expect(screen.getByText('auto → team')).toBeTruthy();
    expect(screen.getByText('researcher-v1')).toBeTruthy();
    expect(screen.getByText('dynamic-analyst-v1')).toBeTruthy();
    expect(screen.getByText('provider error')).toBeTruthy();
  });

  it('explains a single-agent run without inventing children', () => {
    render(AgentOrchestrationPanel, {
      props: {
        message: {
          id: 'answer-2',
          role: 'assistant',
          content: 'answer',
          timestamp: '',
          orchestration: {
            requested_mode: 'single',
            resolved_mode: 'single',
            reason_code: 'user_forced_single',
          },
        },
      },
    });

    expect(screen.getByText('This run stayed on the single-agent path.')).toBeTruthy();
  });

  it('reconstructs orchestration evidence from the durable run ledger', async () => {
    api.listRunChildren.mockResolvedValue([
      {
        run_id: 'child-1', conversation_id: 'parent-1', project_id: 'default', provider: 'mock',
        model: 'mock', status: 'completed', started_at: '', completed_at: '', answer_summary: null,
        input_tokens: 4, output_tokens: 6, total_tokens: 10, cost_usd: null, latency_ms: 12,
        iterations: 1, stop_reason: 'completed', parent_run_id: 'parent-1', fork_source_sequence: null,
      },
    ]);
    api.getRunEvents.mockResolvedValue([
      { sequence: 1, event_at: '', kind: 'orchestration_routed', iteration: 0, payload: { requested_mode: 'auto', resolved_mode: 'team', reason_code: 'cross_domain_task' } },
      { sequence: 2, event_at: '', kind: 'delegation_completed', iteration: 0, payload: { child_id: 'child-1', profile_id: 'researcher-v1', specialist_kind: 'fixed', status: 'completed', total_tokens: 10, tool_count: 1 } },
    ]);

    render(AgentOrchestrationPanel, { props: { runId: 'parent-1' } });

    expect(await screen.findByText('auto → team')).toBeTruthy();
    expect(await screen.findByText('researcher-v1')).toBeTruthy();
  });

  it('shows a loading state while durable evidence is being fetched', async () => {
    let resolveRuns!: (value: unknown[]) => void;
    let resolveEvents!: (value: unknown[]) => void;
    api.listRunChildren.mockImplementation(() => new Promise((resolve) => { resolveRuns = resolve; }));
    api.getRunEvents.mockImplementation(() => new Promise((resolve) => { resolveEvents = resolve; }));

    render(AgentOrchestrationPanel, { props: { runId: 'parent-loading' } });

    expect(await screen.findByText('Loading persisted agent evidence…')).toBeTruthy();
    resolveRuns([]);
    resolveEvents([]);
    expect(await screen.findByText('No orchestration evidence is available for this run.')).toBeTruthy();
  });
});
