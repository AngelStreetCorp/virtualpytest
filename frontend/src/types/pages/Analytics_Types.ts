/**
 * Shapes returned by GET /server/analytics/<section>, plus the build-time
 * project.json the Project tab reads.
 *
 * Kept deliberately loose where the backend passes rows straight through from a view
 * (`AnalyticsDevice`, `AnalyticsHost`): those mirror SQL columns, and a stricter type
 * here would just have to be edited every time the view gains a column.
 */

export const ANALYTICS_SECTIONS = [
  'overview',
  'system',
  'devices',
  'kpi',
  'incidents',
  'alerts',
  'project',
] as const;

export type AnalyticsSection = (typeof ANALYTICS_SECTIONS)[number];

/** Sections served by the API. 'project' is static JSON and has no route. */
export type ApiSection = Exclude<AnalyticsSection, 'project'>;

/**
 * A named value — the shape every ranking, donut slice and treemap cell uses.
 *
 * The index signature is required, not decorative: recharts types its data as
 * `Record<string, unknown>`-ish (`TreemapDataType`), so a closed interface will not
 * pass to <Treemap>. It also lets a row carry extra context (`host`) without a
 * variant type per chart.
 */
export interface Ranked {
  name: string;
  value: number;
  is_others?: boolean;
  host?: string;
  [key: string]: unknown;
}

export type DeviceState = 'up' | 'issue' | 'down';

export interface AnalyticsDevice {
  host_name: string;
  device_id: string;
  device_name: string | null;
  device_model: string | null;
  ffmpeg_status: string | null;
  monitor_status: string | null;
  last_seen: string;
  status: DeviceState;
}

export interface AnalyticsHost {
  host_name: string;
  server_name: string | null;
  cpu_percent: number | null;
  memory_percent: number | null;
  disk_percent: number | null;
  cpu_temperature_celsius: number | null;
  uptime_days: number | null;
  last_seen: string;
  reachability: 'reporting' | 'stale' | 'silent';
}

export interface OverviewSection {
  tiles: {
    hosts_total: number;
    hosts_reporting: number;
    devices_total: number;
    devices_up: number;
    devices_issue: number;
    devices_down: number;
    incidents_open: number;
    alerts_active: number;
    pass_rate: number | null;
  };
  device_counts: Record<DeviceState, number>;
  incidents_timeline: Array<Record<string, string | number>>;
  incident_severities: string[];
  kpi_timeline: Array<{ day: string; passed: number; failed: number }>;
  pass_rate: number | null;
  total_runs: number;
}

export interface SystemSection {
  hosts: AnalyticsHost[];
  total: number;
  reachability: Record<string, number>;
  disk: Ranked[];
  memory: Ranked[];
  cpu: Ranked[];
  uptime_days: Ranked[];
  temperature: Ranked[];
  devices_per_host: Ranked[];
  by_server: Record<string, number>;
}

export interface DevicesSection {
  devices: AnalyticsDevice[];
  counts: Record<DeviceState, number>;
  total: number;
  by_model: Ranked[];
  by_host: Ranked[];
  availability_worst: Ranked[];
  availability_timeline: Array<{ day: string; availability_percent: number | null }>;
  availability_day: string | null;
}

export interface KpiSection {
  timeline: Array<{ day: string; passed: number; failed: number }>;
  total_runs: number;
  passed: number;
  failed: number;
  pass_rate: number | null;
  by_script: Ranked[];
  by_environment: Record<string, number>;
}

export interface IncidentsSection {
  timeline: Array<Record<string, string | number>>;
  severities: string[];
  by_severity: Record<string, number>;
  by_component: Record<string, number>;
  by_device: Ranked[];
  total: number;
  open: number;
  mttr_minutes: number | null;
}

export interface AlertsSection {
  timeline: Array<Record<string, string | number>>;
  types: string[];
  by_type: Record<string, number>;
  by_device: Ranked[];
  total: number;
  active: number;
  review: { checked: number; discarded: number; unreviewed: number };
}

/** frontend/public/analytics/project.json — written by prebuild step 6. */
export interface ProjectMetrics {
  generated_at: string;
  build: string | null;
  build_date: string | null;
  loc: {
    total: number;
    files: number;
    /** 'source' = generated output excluded via the repo ignore rules. */
    method: 'source' | 'working-tree';
    by_area: Array<{ name: string; value: number; files: number }>;
  };
  releases: Array<{
    build: string;
    date: string;
    features: number;
    fixes: number;
    security: number;
    bugs_fixed: number;
  }>;
  bugs: {
    total: number;
    by_severity: Record<string, number>;
    by_status: Record<string, number>;
    fixed_per_build: Record<string, number>;
    unshipped: number;
    internal_only: number;
  };
}

export interface SectionEnvelope<T> {
  success: boolean;
  section: string;
  /** Where the value came from on the server: fresh | stale | cold. */
  cache: 'fresh' | 'stale' | 'cold';
  generated_at: string;
  data: T;
}

export type SectionPayload = {
  overview: OverviewSection;
  system: SystemSection;
  devices: DevicesSection;
  kpi: KpiSection;
  incidents: IncidentsSection;
  alerts: AlertsSection;
};
