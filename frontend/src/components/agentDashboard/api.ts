// Typed fetchers for the Agent Dashboard (TASK-54 §8). Auth headers come from apiClient.
import { apiClient } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';

export type Health = 'ok' | 'warn' | 'error' | 'idle';
export type Level = 'ok' | 'error' | 'fallback' | 'running';

export interface AgentLink { label: string; to: string }
export interface NowItem {
  part: string;
  summary: string;
  started_at: string;
  link?: { kind: string; id: string; url: string | null } | null;
}
export interface AgentStats {
  calls: number; errors: number; fallbacks: number; tokens_in: number; tokens_out: number; avg_ms: number;
}
export interface AgentPart { key: string; label: string; calls: number; errors: number }
export interface RecentError { ts: string; part: string; summary: string; count: number }
export interface AgentOverview {
  id: string; name: string; role?: string; description?: string; version?: string; model?: string | null;
  health: Health;
  last_activity: string | null;
  now: NowItem[];
  stats: AgentStats;
  parts: AgentPart[];
  recent_errors: RecentError[];
  links: AgentLink[];
  feedback?: { rating?: number | null; count?: number; comment?: string | null; up?: number; down?: number } | null;
}
export interface Overview { window_hours: number; agents: AgentOverview[] }

export interface LogRow {
  id: string; ts: string; part: string; level: Level; summary: string;
  tokens_in: number; tokens_out: number; duration_ms: number;
  links: { report?: string | null; alert?: string | null; chat_session?: string | null; trace?: string | null; testprompt?: string | null };
  detail?: { question?: string; answer?: string } | null;
}
export interface LogsPage { rows: LogRow[]; next_before: string | null }
export interface Turn {
  ts: string; role: 'user' | 'agent' | 'tool'; content: string; tool_calls?: unknown[];
  tokens_in?: number; tokens_out?: number; trace_url?: string | null;
}
export interface UsageKey {
  usage_key: string; agent: string; calls: number; errors: number; fallbacks: number;
  tokens_in: number; tokens_out: number; avg_ms: number;
}
export interface Usage {
  days: number;
  by_agent_day: { agent: string; day: string; tokens_in: number; tokens_out: number; calls: number }[];
  by_key: UsageKey[];
  decisions: { usage_key: string; ok: number; fail: number; outcome_known: number }[];
  openrouter?: Record<string, unknown> | null;
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await apiClient(buildServerUrl(path), { signal });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try { const b = await res.json(); msg = b?.error || b?.message || msg; } catch { /* keep status */ }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

export const fetchOverview = (hours: number, signal?: AbortSignal) =>
  getJson<Overview>(`/server/agents/overview?hours=${hours}`, signal);

export interface LogQuery { part?: string; level?: string; hours: number; q?: string; limit?: number; before?: string | null }
export const fetchLogs = (agentId: string, f: LogQuery, signal?: AbortSignal) => {
  const p = new URLSearchParams({ hours: String(f.hours), limit: String(f.limit ?? 50) });
  if (f.part) p.set('part', f.part);
  if (f.level) p.set('level', f.level);
  if (f.q) p.set('q', f.q);
  if (f.before) p.set('before', f.before);
  return getJson<LogsPage>(`/server/agents/${encodeURIComponent(agentId)}/logs?${p}`, signal);
};

export const fetchTurns = (agentId: string, sessionId: string, signal?: AbortSignal) =>
  getJson<{ turns: Turn[] }>(`/server/agents/${encodeURIComponent(agentId)}/turns/${encodeURIComponent(sessionId)}`, signal);

export const fetchUsage = (days: number, signal?: AbortSignal) =>
  getJson<Usage>(`/server/agents/usage?days=${Math.max(1, days)}`, signal);

export const fmtTokens = (n: number): string => {
  if (!n) return '0';
  if (n >= 1e6) return `${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1)} M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(n >= 1e4 ? 0 : 1)} k`;
  return String(n);
};

export const fmtAgo = (iso?: string | null): string => {
  if (!iso) return 'never';
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
};

export const fmtDuration = (ms: number): string => (ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`);
