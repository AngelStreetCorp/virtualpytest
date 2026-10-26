/**
 * Monitoring → AI usage API (TASK-87). Mirrors backend_server/src/routes/server_ai_routing_routes.py
 * (GET /server/ai/usage, /usage/calls, /usage/export, /usage/training, /usage/credits).
 */
import { api, apiClient } from '../../utils/apiClient';
import { buildServerUrl, buildServerUrlWithParams } from '../../utils/buildUrlUtils';

export type GroupBy =
  | 'usage' | 'model' | 'endpoint' | 'team' | 'origin' | 'host' | 'device' | 'script' | 'campaign' | 'user' | 'server'
  | 'arm' | 'error' | 'client' | 'category' | 'caller' | 'result' | 'incident';
export type RangeHours = 1 | 24 | 168 | 720;

export interface ChainHop {
  role: 'main' | 'backup';
  profile: string;
  endpoint: string;
  endpoint_label: string;
  tried: number;
  answered: number;
  failed: number;
  reason: string | null;
  preset: string;
  model: string;
  effort: string;
  reach: string;
  region?: string | null;
  down_for_s: number;
  share: number | null;
}

export interface UsageRow {
  key: string;
  label?: string;
  /** One value per grouping level (`group_by=a,b`) and the backend's name for each (null = the page translates it). */
  parts?: string[];
  labels?: (string | null)[];
  /** Human model name per profile id (`minimax-vlm-minimax-vlm` -> "MiniMax VLM"). */
  profile_labels?: Record<string, string>;
  family?: string;
  first_ts: string | null;
  last_ts: string | null;
  last_error_ts: string | null;
  last_ok_ts: string | null;
  main_error: string | null;
  error_types: Record<string, number>;
  failed_series?: number[];
  profile_last?: Record<string, string>;
  profile_errors: Record<string, number>;
  profile_causes: Record<string, Record<string, number>>;
  calls: number;
  errors: number;
  fallbacks: number;
  total_ms: number;
  tokens_in: number;
  tokens_out: number;
  tokens_cache_read: number;
  tokens_cache_write: number;
  avg_ms: number;
  error_rate: number;
  fallback_rate: number;
  tokens_per_s: number;
  cost: number | null;
  priced_calls: number;
  cost_partial: boolean;
  /** USD saved by prompt-cache reads (not the mixed `saved_cost`). */
  cache_saved?: number;
  avoided: number;
  saved_cost: number | null;
  parse_rate: number | null;
  truncated: number;
  truncated_rate: number;
  images: number;
  image_bytes: number;
  series: number[];
  /** USD per bucket, same buckets as `series` (servers before 2026-10-21 do not send it). */
  cost_series?: number[];
  tokens_in_series: number[];
  profiles: Record<string, number>;
  endpoints: Record<string, number>;
  usages: Record<string, number>;
  routing?: { via: string; layer: string; chain: ChainHop[] } | null;
}

export interface ProviderView {
  endpoint: string;
  name: string;
  type: 'cloud' | 'local';
  /** Flat subscription (MiniMax coding plan): calls cost nothing extra. */
  plan?: boolean;
  preset: string;
  region: string | null;
  reach: string | null;
  enabled: boolean;
  /** Models this provider serves (enabled profiles) and what they can do. */
  models?: { model: string; capabilities: string[] }[];
  /** Answered calls but no token count: show "not reported", never 0. */
  tokens_unreported?: boolean;
  status: 'down' | 'degraded' | 'ok' | 'unused';
  down_for_s: number;
  calls: number;
  errors: number;
  answered: number;
  error_rate: number;
  answered_series: number[];
  failed_series: number[];
  reason: string | null;
  since: string | null;
  last: string | null;
  skipped: number;
}

export interface PreviousTotals {
  calls: number;
  errors: number;
  cost: number | null;
  priced_calls: number;
  tokens_in: number;
  tokens_out: number;
}

/** Useful (answered) / wasted (failed or empty) / saved (avoided by memory or a rule), per metric. */
export interface Split {
  calls: number;
  useful: number;
  wasted: number;
  saved: number;
  tokens: number;
  tokens_useful: number;
  tokens_wasted: number;
  tokens_saved: number;
  cost: number | null;
  cost_useful: number | null;
  cost_wasted: number | null;
  cost_saved: number | null;
}
export interface SourceSplit extends Split { key: string }
export interface IncidentSplit extends Split { host: string; device: string; kind: string }
export interface CategorySplit extends Split { key: string; label?: string; sources?: SourceSplit[]; incidents?: IncidentSplit[] }
export interface CallerSplit extends Split { key: string; categories: Record<string, number> }
export interface Overview {
  totals: Split;
  categories: CategorySplit[];
  callers: CallerSplit[];
  /** Names of the `usage:<key>` categories (a usage with no named category); named ones are translated by the page. */
  category_labels?: Record<string, string>;
}

export interface ErrorCause {
  endpoint: string;
  provider: string;
  type: 'cloud' | 'local';
  preset: string | null;
  reason: string;
  severity: 'error' | 'warning';
  errors: number;
  since: string;
  last: string;
  skipped: number;
  categories: string[];
  category_labels?: Record<string, string>;
  by_category?: { category: string; errors: number; last: string }[];
  features: { usage: string; label: string; errors: number }[];
}

export interface FilterOption { key: string; label?: string; calls?: number }
export interface FilterOptions {
  team: FilterOption[];
  project: FilterOption[];
  user: FilterOption[];
  provider: FilterOption[];
  model: FilterOption[];
}

/** The /server/ai/usage answer. Servers run different code versions: every field added after round 1 is optional. */
export interface UsageReport {
  success: boolean;
  group_by: string;
  hours: RangeHours;
  scope: 'team' | 'all';
  source: 'calls' | 'rollup';
  groups: GroupBy[];
  /** Dimensions with no data in the period (or meaningless: no split route, no public Ask calls): not offered. */
  hidden_groups?: GroupBy[];
  can_view_all: boolean;
  restricted_to_self: boolean;
  totals: UsageRow;
  rows: UsageRow[];
  providers: ProviderView[];
  previous?: PreviousTotals;
  chart_hours?: number;
  step_s?: number;
  series_start?: string;
  series_len?: number;
  overview?: Overview;
  options?: Partial<FilterOptions>;
  errors?: { count: number; causes: ErrorCause[] };
}

/** The filter bar, kept in the page URL. Empty string = no filter ("All"). */
export interface UsageQuery {
  hours: RangeHours;
  team: string;
  project: string;
  user: string;
  provider: string;
  model: string;
  /** success = useful calls, failed = wasted; saved is not a column (the Calls tab lists memory answers). */
  result: '' | 'success' | 'failed' | 'saved';
  /** Set by a click on a category / caller row of the Overview. */
  category: string;
  caller: string;
  /** Error reason (filter_error), set by a click on an error cause. */
  reason: string;
  /** Host name (filter_host): the host group of the page. */
  host?: string;
}

export const EMPTY_QUERY: UsageQuery = { hours: 24, team: '', project: '', user: '', provider: '', model: '', result: '', category: '', caller: '', reason: '' };

/** The server does not have the AI usage API (older code): the page says so instead of failing. */
export class AiUsageMissingError extends Error {}

/** Group dimensions the dedicated filters map to (filter_<group>). */
const FILTER_GROUPS: [keyof UsageQuery, GroupBy][] = [
  ['user', 'user'], ['provider', 'endpoint'], ['model', 'model'], ['result', 'result'], ['category', 'category'], ['caller', 'caller'], ['reason', 'error'], ['host', 'host'],
];

export const queryParams = (q: UsageQuery): Record<string, string> => {
  const params: Record<string, string> = { hours: String(q.hours) };
  if (q.team) params.team_ids = q.team;
  else params.scope = 'all';
  if (q.project) params.project = q.project;
  FILTER_GROUPS.forEach(([field, group]) => {
    if (q[field] && !(field === 'result' && q.result === 'saved')) params[`filter_${group}`] = String(q[field]);
  });
  return params;
};

export type UsageFilters = Partial<Record<GroupBy, string>>;

export interface AiCall {
  id: number;
  ts: string;
  request_id: string | null;
  usage_key: string;
  usage_label?: string;
  category?: string;
  category_label?: string | null;
  ref_type?: string | null;
  ref_id?: string | null;
  ref_kind?: string | null;
  caller?: string;
  user_id: string | null;
  origin: string;
  script_name: string | null;
  script_result_id: string | null;
  host_name: string | null;
  device_id: string | null;
  profile: string;
  endpoint: string;
  model: string | null;
  effort_sent: string | null;
  fallback_used: boolean;
  ok: boolean;
  outcome: string;
  error_type: string | null;
  tokens_in: number;
  tokens_out: number;
  turn_index: number | null;
  tool_calls: number | null;
  stop_reason: string | null;
  latency_ms: number;
  cost: number | null;
  cost_source?: string;
  trace_url: string | null;
  images?: number;
  image_bytes?: number;
  attempt_index?: number;
}

export interface CallsReport {
  success: boolean;
  calls: AiCall[];
  sampled: number;
  latency: { p50: number | null; p95: number | null; n: number };
}

export interface TrainingReport {
  success: boolean;
  scope: 'team' | 'all';
  opted_in_teams: number;
  totals: { samples: number; labelled: number; failures: number; conflicts: number; linked: number };
  groups: {
    family: string;
    device_model: string;
    samples: number;
    labelled: number;
    failures: number;
    conflicts: number;
    linked: number;
    by_source: Record<string, number>;
  }[];
  accuracy: {
    usage: string;
    label: string;
    profile: string;
    model: string;
    labelled: number;
    failures: number;
    accuracy: number;
    avg_cost: number | null;
  }[];
}

export interface CreditRow {
  endpoint: string;
  has_key: boolean;
  total_credits?: number;
  total_usage?: number;
  balance?: number;
  credits_error?: string;
}

export const fetchAiUsage = async (q: UsageQuery, groupBy: string): Promise<UsageReport> => {
  const response = await apiClient(buildServerUrlWithParams('/server/ai/usage', { ...queryParams(q), group_by: groupBy }));
  if (response.status === 404) {
    const body = await response.json().catch(() => null);
    if (!body || body.success !== false) throw new AiUsageMissingError('no AI usage API');
    throw new Error(body.error || 'usage request failed');
  }
  const body = await response.json().catch(() => null);
  if (!response.ok || !body || body.success === false) throw new Error(body?.error || `HTTP ${response.status}`);
  return body as UsageReport;
};

export const usageExportUrl = (q: UsageQuery, groupBy: string) =>
  buildServerUrlWithParams('/server/ai/usage/export', { ...queryParams(q), group_by: groupBy });

export const fetchAiCalls = (q: UsageQuery, limit = 200, withSaved = false) =>
  api.get<CallsReport>(buildServerUrlWithParams('/server/ai/usage/calls', { ...queryParams(q), group_by: 'usage', limit: String(limit), ...(withSaved ? { saved: '1' } : {}) }));

/** One call by its request id (the call view of the page); avoided calls included. */
export const fetchAiCall = (q: UsageQuery, requestId: string) =>
  api.get<CallsReport>(buildServerUrlWithParams('/server/ai/usage/calls', { ...queryParams({ ...q, provider: '', category: '', caller: '', reason: '', result: '' }), request_id: requestId, limit: '1', saved: '1' }));

export interface TraceStep { name: string | null; model: string | null; level: string | null; status: string | null; input: unknown; output: unknown; start: string | null }
export interface CallTrace { id: string; name: string | null; timestamp: string | null; input: unknown; output: unknown; steps: TraceStep[] }

/** One call's conversation; null when nothing was recorded for it (yet), or tracing is off (the route's 404). */
export const fetchCallTrace = async (traceId: string): Promise<CallTrace | null> => {
  const response = await apiClient(buildServerUrl(`/server/ai/usage/trace/${encodeURIComponent(traceId)}`));
  if (response.status === 404) return null;
  const body = await response.json().catch(() => null);
  if (!response.ok || !body || body.success === false) throw new Error(body?.error || `HTTP ${response.status}`);
  return body.trace as CallTrace;
};

export const fetchTrainingReport = (q: UsageQuery) =>
  api.get<TrainingReport>(buildServerUrlWithParams('/server/ai/usage/training', { hours: String(q.hours), ...(q.team ? { team_ids: q.team } : { scope: 'all' }) }));

export const fetchCredits = () =>
  api.get<{ success: boolean; endpoints: CreditRow[] }>(buildServerUrlWithParams('/server/ai/usage/credits', {}));

export interface RunCost {
  success: boolean;
  calls: number;
  errors: number;
  tokens_in: number;
  tokens_out: number;
  cost: number | null;
  priced_calls: number;
}

export const fetchRunCost = (scriptResultIds: string[]) =>
  api.get<RunCost>(buildServerUrlWithParams('/server/ai/usage/run', { script_result_ids: scriptResultIds.join(',') }));

export interface HealthCause {
  endpoint: string;
  provider: string;
  type: 'cloud' | 'local';
  preset: string | null;
  reason: string;
  severity: 'error' | 'warning';
  errors: number;
  since: string;
  last: string;
  skipped: number;
  features: { usage: string; label: string; errors: number }[];
}

export interface BackupAlert {
  usage: string;
  label: string;
  calls: number;
  fallbacks: number;
  share: number;
}

export interface HealthReport {
  success: boolean;
  causes: HealthCause[];
  backup: BackupAlert[];
}

export const fetchAiAlerts = (scopeAll: boolean) =>
  api.get<HealthReport>(buildServerUrlWithParams('/server/ai/usage/alerts', scopeAll ? { scope: 'all' } : {}));

export interface BudgetStatus {
  bucket_type: 'team' | 'user' | 'model' | 'endpoint' | 'usage' | 'project';
  bucket_id: string;
  team_scope: string;
  label: string | null;
  limit: number;
  mode: 'warn' | 'block';
  warn_at: number;
  spent: number;
  forecast: number;
  share: number;
  state: 'ok' | 'warn' | 'over';
  updated_by?: string | null;
  updated_at?: string | null;
}

export interface BudgetReport {
  success: boolean;
  spent: number;
  forecast: number;
  budget: BudgetStatus | null;
}

export interface BudgetBucketsReport {
  success: boolean;
  team_id: string;
  buckets: BudgetStatus[];
  month?: { spent: number; forecast: number };
  team_budgeted?: boolean;
  unbudgeted?: { endpoint: string; name: string; spent: number }[];
}

export interface BudgetDecision {
  statuses: BudgetStatus[];
  blocked: boolean;
}

export const BUCKET_TYPES: BudgetStatus['bucket_type'][] = ['team', 'user', 'model', 'endpoint', 'usage', 'project'];

export const fetchBudget = (teamId?: string) =>
  teamId
    ? api.get<BudgetBucketsReport>(buildServerUrlWithParams('/server/ai/usage/budget', { team_id: teamId }))
    : api.get<BudgetReport>(buildServerUrlWithParams('/server/ai/usage/budget', {}));

export const evaluateBudget = (input: { team_id: string; usage_key?: string; model?: string; endpoint?: string; user_id?: string; project_id?: string }) =>
  api.post<BudgetDecision>(buildServerUrl('/server/ai/usage/budget/evaluate'), input);

export interface BucketUpsertInput {
  bucket_type: BudgetStatus['bucket_type'];
  bucket_id: string;
  team_scope: string;
  month_limit_usd: number;
  mode: 'warn' | 'block';
  warn_at: number;
  label?: string | null;
}

export const upsertBucket = (input: BucketUpsertInput) =>
  api.put<{ success: boolean }>(buildServerUrl('/server/ai/budget'), input);

export const deleteBucket = (bucket_type: BudgetStatus['bucket_type'], bucket_id: string, team_scope?: string) =>
  api.delete<{ success: boolean }>(buildServerUrlWithParams('/server/ai/budget',
    team_scope ? { bucket_type, bucket_id, team_scope } : { bucket_type, bucket_id }));

// ---------------------------------------------------------------- TASK-143: benchmarks
export interface BenchmarkCase {
  id: number;
  ts: string;
  run_id: string;
  team_id: string | null;
  uc: string;
  usage_key: string;
  profile: string;
  model: string | null;
  endpoint: string | null;
  case_id: string;
  kind: string | null;
  ok: boolean;
  scored: boolean;
  score: number | null;
  error: string | null;
  ms: number;
  tokens_in: number;
  tokens_out: number;
  cost: number | null;
  request_id: string | null;
}

export interface BenchmarkRun {
  run_id: string;
  ts: string | null;
  team_id: string | null;
  uc: string;
  usage_key: string;
  /** The feature (usage page category) the usage key belongs to. */
  category?: string;
  profile: string;
  model: string | null;
  endpoint: string | null;
  cases: number;
  scored: number;
  passed: number;
  score: number;
  pass_rate: number;
  ms: number;
  tokens_in: number;
  tokens_out: number;
  cost: number;
}

export interface BenchmarksReport {
  success: boolean;
  runs: BenchmarkRun[];
  cases: BenchmarkCase[];
  usage_keys: string[];
  /** Human name of each usage key (the raw key stays in a tooltip). */
  usage_labels?: Record<string, string>;
  models: string[];
  scope: 'team' | 'all';
  team_id: string | null;
}

export const fetchBenchmarks = (params: { usage_key?: string; model?: string; category?: string; hours?: number; limit?: number } = {}) =>
  api.get<BenchmarksReport>(buildServerUrlWithParams('/server/ai/benchmarks', {
    ...(params.usage_key ? { usage_key: params.usage_key } : {}),
    ...(params.model ? { model: params.model } : {}),
    ...(params.category ? { category: params.category } : {}),
    ...(params.hours ? { hours: String(params.hours) } : {}),
    ...(params.limit ? { limit: String(params.limit) } : {}),
  }));
