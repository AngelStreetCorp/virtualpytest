/**
 * Response shapes of GET /server/dashboard/summary and GET /server/dashboard/system (TASK-123).
 * The only place these shapes are written down on the frontend; the cards read them, never the raw JSON.
 */

export const DASH_RANGES = ['24h', '7d', '30d'] as const;
export type DashRange = (typeof DASH_RANGES)[number];

export interface RunningItem {
  script_name: string;
  device_id: string;
  host_name: string;
  started_at: string;
  result_id: string;
}

export interface TrendBucket {
  bucket_start: string;
  total: number;
  passed: number;
}

export interface FailureItem {
  result_id: string;
  script_name: string;
  host_name: string;
  device_id: string;
  reason: string;
  finished_at: string;
}

export interface FlakyItem {
  script_name: string;
  runs: number;
  failed: number;
}

export interface DeploymentItem {
  name: string;
  next_run_at: string | null;
  state: string;
}

export interface LockedItem {
  host_name: string;
  device_id: string;
  holder: string;
  since: string;
}

export interface FailingItem {
  script_name: string;
  runs: number;
  failed: number;
  last_verdict: 'passed' | 'failed' | 'aborted';
  last_at: string | null;
  last_result_id: string;
}

export interface DownDevice {
  host_name: string;
  device_id: string;
  device_name: string;
}

export interface HostDevices {
  host_name: string;
  total: number;
  down: number;
  locked: number;
}

export interface DashboardSummary {
  success: boolean;
  generated_at: string;
  range: DashRange;
  running: { count: number; queued: number; items: RunningItem[] };
  results: { total: number; passed: number; failed: number; aborted: number; trend: TrendBucket[] };
  failures: FailureItem[];
  failing: FailingItem[];
  flaky: FlakyItem[];
  deployments: { active: number; items: DeploymentItem[] };
  devices: {
    total: number;
    free: number;
    locked: number;
    down: number;
    locked_items: LockedItem[];
    down_items: DownDevice[];
    hosts: HostDevices[];
  };
}

export type VmStatus = 'ok' | 'warning' | 'error' | 'stale';

export interface VmRow {
  id: string;
  name: string;
  cpu: number | null;
  load1: number | null;
  ram: number | null;
  disk: number | null;
  status: VmStatus;
  checked_at: string | null;
}

export interface DashboardSystem {
  success: boolean;
  generated_at: string;
  storage: { disk_pct: number; inode_pct: number } | null;
  vms: VmRow[] | null;
  services: { ok: number; total: number } | null;
  monitoring: { hosts_total: number; hosts_ok: number; problems: Array<{ host_name: string; detail: string; severity?: 'warning' | 'error' }> } | null;
  ai_usage: { cost_7d: number; top_model: string | null; /** Fullest budget bucket this month; null without a budget. */ budget?: { share: number; label: string } | null; /** Last 24 h of calls that gave nothing usable (AI_USAGE.md). */ waste?: { tokens: number; cost: number | null; spend: number | null; share_pct: number; top: { source: string; tokens: number; cost: number | null }[] } | null } | null;
}

/** What the cards receive: each block is null until its endpoint answered (or when it never will). */
export interface DashboardData {
  summary: DashboardSummary | null;
  system: DashboardSystem | null;
  summaryError: boolean;
  systemError: boolean;
  loading: boolean;
}
