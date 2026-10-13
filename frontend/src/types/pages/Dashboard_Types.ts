// Dashboard stats interface
export interface DashboardStats {
  testCases: number;
  campaigns: number;
  trees: number;
  recentActivity: RecentActivity[];
}

// System stats structure as returned by the server (flat structure)
// Used for dashboard display of device resource usage
export interface SystemStats {
  cpu_percent: number;
  memory_percent: number;
  disk_percent: number;
  // The fullest monitored mount, not necessarily `/` — hosts keep captures,
  // references and reports on their own filesystem, which is the one that fills.
  disk_worst_mount?: string | null;
  platform: string;
  architecture: string;
  // What the vpt-host process is actually running on vs the machine underneath.
  // A Windows PC running vpt-host in Docker Desktop reports platform 'Linux'
  // (the container kernel), so the card shows `physical_platform` + a Docker
  // badge instead of the misleading bare "Linux". Absent on hosts that predate
  // the detection — the card falls back to `platform` alone.
  physical_platform?: string;
  in_container?: boolean;
  container_runtime?: string | null;
  is_wsl?: boolean;
  os_mismatch?: boolean;
  python_version?: string;
  cpu_temperature_celsius?: number;  // CPU temperature (optional, only on supported hardware)
  hardware_encode?: boolean;  // VAAPI H.264 hardware encode available → enables the HD+ stream tier
  archive_video?: boolean;  // host keeps the 24h review buffer (ARCHIVE_VIDEO); false disables Last 24h
  load_average_1m?: number;
  load_average_5m?: number;
  load_average_15m?: number;
  // Capture write throughput, from get_host_system_stats / get_enhanced_system_stats.
  // The backend has always sent this; it was simply never declared here.
  disk_write_mb_per_sec?: number;
  uptime_seconds?: number;
  download_mbps?: number;
  upload_mbps?: number;
  error?: string;
  // Service health summary
  service_health?: {
    overall_status?: 'online' | 'degraded' | 'error' | 'unknown';
    services?: Array<{
      name: string;
      label: string;
      status: 'active' | 'stuck' | 'stopped' | 'error' | 'unknown' | 'not_installed';
      critical: boolean;
      optional: boolean;
      controllable?: boolean;
      description?: string;
      detail?: string; // Why the status is what it is (e.g. heatmap output freshness)
      runtime?: 'service' | 'task';
      resolved_name?: string;
    }>;
  };
  operational_status?: 'online' | 'degraded' | 'error' | 'unknown';
}

// Recent activity interface (separate from LogEntry)
export interface RecentActivity {
  id: string;
  type: 'test' | 'campaign';
  name: string;
  status: 'success' | 'error' | 'pending';
  timestamp: string;
}

// Log entry interface for debug logs
export interface LogEntry {
  timestamp: string;
  level: 'info' | 'warn' | 'error' | 'debug';
  source: 'frontend' | 'backend';
  message: string;
  details?: any;
}

export type ViewMode = 'grid' | 'table';

export type LogLevel = 'all' | 'info' | 'warn' | 'error' | 'debug';
export type LogSource = 'all' | 'frontend' | 'backend';
