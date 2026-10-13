/**
 * Types for Settings → AI (TASK-30 per-usage AI routing).
 * Mirrors backend_server/src/routes/server_ai_routing_routes.py.
 */

export type Capability = 'tools' | 'vision';
export type Thinking = 'auto' | 'on' | 'off';
export type Reach = 'server' | 'host';

export interface AiUsage {
  key: string;
  label: string;
  description: string;
  parent: string | null;
  needs: Capability[];
  output: string;
  thinking: string;
}

export interface AiPreset {
  name: string;
  label: string;
  base_url: string | null;
  needs_key: boolean;
  base_url_required: boolean;
  lists_models: boolean;
  web_search: boolean; // can answer web usages (text.web.*) with a live search
}

export interface AiEndpoint {
  id: string;
  name: string;
  preset: string;
  base_url: string | null;
  secret_name: string | null;
  reach: Reach;
  timeout_s: number;
  max_concurrency: number | null;
  /** Where the provider hosts the data (free text: EU, US, local) — shown on Monitoring → AI usage. */
  region: string | null;
  allowed_team_ids: string[] | null;
  enabled: boolean;
  has_secret: boolean;
  needs_key: boolean;
  /** Seconds the server keeps skipping this endpoint after a connection failure (0 = up). */
  down_for_s: number;
}

export interface AiProfile {
  id: string;
  name: string;
  endpoint_id: string;
  model: string;
  temperature: number | null;
  max_tokens_cap: number | null;
  thinking: Thinking;
  image_max_edge: number | null;
  extra: Record<string, unknown>;
  fallback_profile_id: string | null;
  capabilities: Capability[];
  enabled: boolean;
}

export interface AiRoute {
  id: string;
  team_id: string | null;
  usage_key: string;
  profile_id: string;
  host_name: string | null;
  device_model: string | null;
  userinterface_name: string | null;
  split_profile_id: string | null;
  split_percent: number | null;
  priority: number;
  enabled: boolean;
}

export interface AiHop {
  profile: string;
  endpoint: string;
  preset: string;
  model: string;
  reach: Reach;
  base_url: string | null;
  timeout_s: number;
}

export interface AiResolution {
  usage: string;
  via: string;
  layer: 'team' | 'default';
  split_arm: string | null;
  chain: AiHop[];
}

export type AiEffective = AiResolution | { error: string };

export interface AiConfig {
  is_platform_admin: boolean;
  usages: AiUsage[];
  presets: AiPreset[];
  endpoints: AiEndpoint[];
  profiles: AiProfile[];
  routes: AiRoute[];
  effective: Record<string, AiEffective>;
  /** The team the config is read for ('all' = every team's overrides) and what the dropdowns offer. Absent on older servers. */
  scope?: { team: string | null; options: { team: { key: string; label: string }[]; project: { key: string; label: string }[] } };
}

/** The Settings → AI team / project dropdowns. Empty team = All. */
export interface AiScope {
  team: string;
  project: string;
}

export interface AiUsageStats {
  calls: number;
  errors: number;
  fallbacks: number;
  avg_ms: number;
  error_rate: number;
  tokens_in: number;
  tokens_out: number;
  profiles: Record<string, number>;
}

export interface EndpointTestResult {
  success: boolean;
  endpoint?: string;
  models?: string[];
  reply?: string;
  error?: string;
  note?: string;
}

export interface ProfileTestResult {
  success: boolean;
  kind: 'text' | 'vision' | 'tools' | 'web';
  reply?: string;
  error?: string;
}

export const isResolutionError = (value: AiEffective | undefined): value is { error: string } =>
  !!value && 'error' in value;

/** USD per 1M tokens for an endpoint + model from `valid_from` on (`model = '*'`: every model of the endpoint). */
export interface AiPrice {
  id: string;
  endpoint: string;
  model: string;
  price_in: number;
  price_out: number;
  price_cache_read: number | null;
  price_cache_write: number | null;
  /** USD per web search. */
  price_web_search: number | null;
  valid_from: string;
  note: string | null;
  created_at: string;
  /** Where the price came from (backend `prices.source_of`). */
  source?: 'manual' | 'openrouter' | 'langfuse' | 'plan';
}

/** An endpoint with no per-call price: a flat plan (included) or a local PC (free). */
export interface UnpricedEndpoint {
  endpoint: string;
  kind: 'plan' | 'local';
}

/** GET /server/ai/usage/budget — this month's priced spend of the team and its budget (null = none set). */
export interface BudgetResponse {
  success: boolean;
  spent: number;
  forecast: number;
  budget: {
    limit: number;
    mode: 'warn' | 'block';
    warn_at: number;
    spent: number;
    forecast: number;
    share: number;
    state: 'ok' | 'warn' | 'over';
  } | null;
}
