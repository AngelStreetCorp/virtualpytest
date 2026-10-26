// palette: drawn on the video surface, same rule as MonitoringOverlay — saturated hex
// literals stay readable on any frame; do NOT swap them for theme tokens (dark/light),
// because the background here is the stream itself, not the app chrome.

/** Above this age the heartbeat is treated as unusable and the numbers are withheld. */
export const STALE_AFTER_SECONDS = 90; // mirrors STALE_HOST_DISPLAY_SECONDS in server_system_routes.py

export const RESOURCE_WARN_PERCENT = 75;
export const RESOURCE_ERROR_PERCENT = 90; // same threshold the Status page flags a host on

/** One font for the whole box: labels, headers and values used to mix the theme sans with monospace. */
export const OVERLAY_FONT = 'ui-monospace, SFMono-Regular, Menlo, monospace';

/** WebRTC freeze share of the last sample window (percent). Measured 2026-10-14 on a lossy Wi-Fi host: ~45%. */
export const FREEZE_WARN_PERCENT = 1;
export const FREEZE_ERROR_PERCENT = 5;
/** Share of received packets re-requested by NACK (percent). Healthy wired paths sit near 0. */
export const NACK_WARN_PERCENT = 0.5;
export const NACK_ERROR_PERCENT = 2;

/** Image telemetry (TASK-157): p95 age of a frame when the monitor starts on it. Above warn the monitor is behind. */
export const IMG_AGE_WARN_MS = 2000;
export const IMG_AGE_ERROR_MS = 5000;
/** Receiver jitter (ms). */
export const JITTER_WARN_MS = 15;
export const JITTER_ERROR_MS = 30;

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
