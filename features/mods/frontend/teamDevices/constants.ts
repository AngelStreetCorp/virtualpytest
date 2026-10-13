export const MOD_ID = 'team-devices';
export const WIDGET_ID = 'team-devices';

export const REFRESH_MS = 60_000;
export const RESULTS_PATH = '/server/script-results/getAllScriptResults';
export const ALERTS_PATH = '/server/alerts/getActiveAlerts';

/** What the widget counts as errors (its "Count as errors" setting). */
export const ERRORS_FAILED_24H = 'failed_24h';
export const ERRORS_FAILED_7D = 'failed_7d';
export const ERRORS_OPEN_ALERTS = 'open_alerts';

const DAY_MS = 24 * 60 * 60 * 1000;
/**
 * Failed-run windows, and how many newest results are read for each: a very busy team may
 * count fewer than the real total.
 */
export const FAILURE_WINDOWS = {
  [ERRORS_FAILED_24H]: { windowMs: DAY_MS, limit: 300 },
  [ERRORS_FAILED_7D]: { windowMs: 7 * DAY_MS, limit: 1000 },
} as const;

/** Rows listed before "+N more". */
export const MAX_ROWS = 8;

export const SHOW_ALL = 'all';
export const SHOW_ACTIVE = 'active';
