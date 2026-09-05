export type Role = 'user' | 'assistant';

export interface ToolCall { tool: string; parameters?: Record<string, unknown>; result?: unknown; status?: string; elapsed_ms?: number }
export interface Skill { name: string; description?: string }
export interface ThinkingStep { type: string; detail: string; done?: boolean; elapsed_ms?: number }
export interface ContextStats { tokens?: number; budget?: number; utilization_pct?: number; compacted?: boolean; tokens_before?: number; tokens_after?: number; tokens_saved?: number; saved_pct?: number; messages?: number; messages_before?: number; messages_after?: number }
export type ExecutionMode = 'auto' | 'single' | 'team';
export interface OrchestrationStatus {
  requested_mode: ExecutionMode;
  resolved_mode: Exclude<ExecutionMode, 'auto'>;
  reason_code: string;
  router_version?: string;
  degraded?: boolean;
}
export interface ChildAgentStatus {
  child_id: string;
  parent_run_id?: string;
  profile_id: string;
  specialist_kind: 'fixed' | 'dynamic';
  status: 'running' | 'completed' | 'failed' | 'timed_out' | 'cancelled' | 'denied';
  reason_code?: string | null;
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  tool_count?: number;
}
export interface Artifact { id: string; title: string; type: string; language?: string; content?: string; content_length: number; version?: number }
export interface Message {
  id: string | number; role: Role; content: string; timestamp: string;
  run_id?: string;
  thinking_steps?: ThinkingStep[]; tool_calls?: ToolCall[]; skills_used?: Skill[];
  sources?: Array<{ id?: string; title: string; url?: string; score?: number }>; artifacts?: Artifact[];
  iterations?: number; context_stats?: ContextStats;
  startedAt?: number; // performance.now() when the message started
  evalScores?: { name: string; score: number; reason: string }[];
  verifier?: { status?: string; supported?: boolean; unsupported_claims?: string[]; reason?: string };
  orchestration?: OrchestrationStatus;
  child_agents?: ChildAgentStatus[];
  status?: 'streaming' | 'completed' | 'failed'; elapsed_ms?: number;
}
export interface RunStats { latency: string; tokens: string; tools: number; iterations: number; cost?: string }
export interface LogEntry { ts?: string; level?: string; event?: string; data?: Record<string, unknown> }
export interface Conversation { id: string; title: string; created_at: string; message_count?: number }
export type InspectorTab = 'run' | 'agents' | 'evidence' | 'context' | 'logs';
