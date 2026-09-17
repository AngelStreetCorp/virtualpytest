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
  platform: string;
  architecture: string;
  python_version?: string;
  cpu_temperature_celsius?: number;  // CPU temperature (optional, only on supported hardware)
  hardware_encode?: boolean;  // VAAPI H.264 hardware encode available → enables the HD+ stream tier
  load_average_1m?: number;
  load_average_5m?: number;
  load_average_15m?: number;
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
