// palette: drawn on the video surface, same rule as MonitoringOverlay — saturated hex
// literals stay readable on any frame; do NOT swap them for theme tokens (dark/light),
// because the background here is the stream itself, not the app chrome.

/** Above this age the heartbeat is treated as unusable and the numbers are withheld. */
export const STALE_AFTER_SECONDS = 90; // mirrors STALE_HOST_DISPLAY_SECONDS in server_system_routes.py

export const RESOURCE_WARN_PERCENT = 75;
export const RESOURCE_ERROR_PERCENT = 90; // same threshold the Status page flags a host on

export const OVERLAY_COLORS = {
  ok: '#00ff00',
  warn: '#ffaa00',
  error: '#ff4444',
  text: '#ffffff',
  muted: '#cccccc',
  dim: '#888888',
} as const;

export type ServiceStatus = 'active' | 'stuck' | 'stopped' | 'error' | 'unknown' | 'not_installed';

export const SERVICE_LOOKS: Record<ServiceStatus, { text: string; color: string }> = {
  active: { text: 'ok', color: OVERLAY_COLORS.ok },
  stuck: { text: 'stuck', color: OVERLAY_COLORS.warn },
  stopped: { text: 'down', color: OVERLAY_COLORS.error },
  error: { text: 'down', color: OVERLAY_COLORS.error },
  unknown: { text: '?', color: OVERLAY_COLORS.muted },
  not_installed: { text: 'n/a', color: OVERLAY_COLORS.dim },
};
