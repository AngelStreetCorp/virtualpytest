// Dashboard stats interface
export interface ImageTelemetryStatus {
  bucket_seconds: number;
  frames_arrived: number;
  frames_analyzed: number;
  frames_dropped: number;
  arrived_fps: number | null;
  image_bytes: number;
  estimated_image_throughput_bps: number | null;
  frame_age_p95_ms: number | null;
  queue_depth_max: number;
  process?: {
    cpu_pct_monitor: number | null;
    rss_monitor_bytes: number | null;
    cpu_pct_ffmpeg: number | null;
    rss_ffmpeg_bytes: number | null;
    load_per_core: number | null;
  };
}

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
  // Per-mount usage (TASK-20). Optional — older hosts and the lightweight
  // registration payload may not include it.
  disk_mounts?: Array<{ mount: string; percent: number; used_gb: number; total_gb: number }>;
  // Same units as the rest of the disk block, surfaced in the stream-stats
  // overlay so the user can see "is the host actually writing/reading?".
  disk_used_gb?: number;
  disk_total_gb?: number;
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
  monitor_profiles?: Record<string, string>;  // {device_id: monitor profile} (TASK-90)
  monitor_profile_services?: Record<string, Record<string, boolean>>;  // {profile: {img|audio|subtitle|archiver|kpi|avq: bool}}: what each profile expects
  monitor_profile_params?: Record<string, { delay_s?: number; captions?: boolean }>;  // {device_id: caption_playback params} (TASK-103, written by the host)
  monitoring_off?: string[];  // device ids whose profile runs no monitor and no review buffer (tv_lite, TASK-95)
  monitor_overlay_on?: string[];  // device ids whose profile draws its own overlay (eggs, cars): monitoring opens on
  load_average_1m?: number;
  load_average_5m?: number;
  load_average_15m?: number;
  // Capture I/O throughput, from get_host_system_stats / get_enhanced_system_stats
  // (TASK-20). Read was added alongside write so the stream-stats overlay can
  // show R/W MB/s next to disk_percent; older hosts pre-dating the change will
  // simply omit disk_read_mb_per_sec.
  disk_read_mb_per_sec?: number;
  disk_write_mb_per_sec?: number;
  // Per-device ffmpeg-configured capture rate (BUG-0575). Parsed on the host
  // from the live ffmpeg process cmdline (`-framerate N` in run_ffmpeg.sh).
  // The stream-stats overlay displays this as the "FPS: in" value, distinct
  // from the rate the monitor actually observes (which depends on host load).
  stream_capture_fps?: Record<string, number>;
  // Image telemetry per device (TASK-157), present only when the host runs IMG_TELEMETRY=true.
  // Counted by the img monitor over the last window; null = not measured (never 0).
  image_telemetry?: Record<string, ImageTelemetryStatus>;
  uptime_seconds?: number;
  download_mbps?: number;
  upload_mbps?: number;
  error?: string;
  // How many browser test runs this host carries at the same time, and the cap
  // (TASK-146). A browser-isolated script drives a Chrome of its own, so the host -
  // not the device - is what runs out; the host card shows this.
  browser_runs?: {
    running?: number;
    waiting?: number;
    cap?: number;
  };
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
