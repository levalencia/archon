export type Role = 'user' | 'assistant';

export interface ToolCall { tool: string; parameters?: Record<string, unknown>; result?: unknown; status?: string; elapsed_ms?: number }
export interface Skill { name: string; description?: string }
export interface ThinkingStep { type: string; detail: string; done?: boolean; elapsed_ms?: number }
export interface ContextStats { tokens?: number; budget?: number; utilization_pct?: number; compacted?: boolean; tokens_before?: number; tokens_after?: number; saved_pct?: number }
export interface Artifact { id: string; title: string; type: string; language?: string; content_length: number; version?: number }
export interface Message {
  id: string | number; role: Role; content: string; timestamp: string;
  thinking_steps?: ThinkingStep[]; tool_calls?: ToolCall[]; skills_used?: Skill[];
  sources?: Array<{ title: string; url?: string; score?: number }>; artifacts?: Artifact[];
  iterations?: number; context_stats?: ContextStats;
  startedAt?: number; // performance.now() when the message started
}
export interface RunStats { latency: string; tokens: string; tools: number; iterations: number }
export interface LogEntry { ts?: string; level?: string; event?: string; data?: Record<string, unknown> }
export interface Conversation { id: string; title: string; created_at: string; message_count?: number }
export type InspectorTab = 'run' | 'evidence' | 'context' | 'logs';
