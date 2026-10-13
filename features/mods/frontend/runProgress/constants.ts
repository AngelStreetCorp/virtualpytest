export const MOD_ID = 'run-progress';
export const PANE_ID = 'run-progress';

/** Run kinds shown; Take Control events (action, navigation, verification) are left out. */
export const TRACKED_KINDS: ReadonlySet<string> = new Set(['script', 'campaign', 'testcase']);

/** A finished run stays listed this long. */
export const FINISHED_TTL_MS = 10 * 60_000;
export const PRUNE_INTERVAL_MS = 30_000;
export const MAX_ROWS = 50;

/** Live page of a running script (RunLive). */
export const liveRunPath = (taskId: string) => `/test-results/live/${encodeURIComponent(taskId)}`;
