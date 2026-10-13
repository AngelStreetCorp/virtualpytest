/** Pure state transitions of the Run Progress mod. */
import { TERMINAL_STATUSES } from '../../../../frontend/src/mods/core/constants';
import type { RunEvent } from '../../../../frontend/src/mods/core/types';

import { FINISHED_TTL_MS, MAX_ROWS, TRACKED_KINDS } from './constants';
import type { RunOutcome, RunProgressState, RunRow, RunSummary } from './types';

export const initialRunProgressState: RunProgressState = { rows: {}, hidden: false };

const clampPct = (n: number) => Math.max(0, Math.min(100, Math.round(n)));

export const outcomeOf = (status: string): RunOutcome =>
  !TERMINAL_STATUSES.has(status) ? 'running' : status === 'completed' ? 'passed' : 'failed';

export const isTracked = (e: RunEvent) => TRACKED_KINDS.has(e.kind);

/** 0–100, or undefined while a running row has reported nothing measurable. */
export const rowPercent = (row: RunRow): number | undefined => {
  if (row.outcome !== 'running') return 100;
  if (row.stepNumber !== undefined && row.totalSteps) return clampPct((row.stepNumber / row.totalSteps) * 100);
  if (row.progress !== undefined) return clampPct(row.progress);
  return undefined;
};

/** Merge one update into its row. An update after the end of a run is ignored. */
export const applyRunEvent = (state: RunProgressState, e: RunEvent): RunProgressState => {
  if (!isTracked(e)) return state;
  const prev = state.rows[e.id];
  if (prev && prev.outcome !== 'running') return state;

  const row: RunRow = {
    id: e.id,
    kind: e.kind,
    status: e.status,
    outcome: outcomeOf(e.status),
    progress: e.progress ?? prev?.progress,
    step: e.step ?? prev?.step,
    stepNumber: e.stepNumber ?? prev?.stepNumber,
    totalSteps: e.totalSteps ?? prev?.totalSteps,
    message: e.message ?? prev?.message,
    hostName: e.hostName ?? prev?.hostName,
    deviceId: e.deviceId ?? prev?.deviceId,
    error: e.error ?? prev?.error,
    startedAt: prev?.startedAt ?? e.timestamp,
    updatedAt: e.timestamp,
  };
  return { rows: { ...state.rows, [e.id]: row }, hidden: prev ? state.hidden : false };
};

/** True when this update ends a run that was still running (or unseen). */
export const endsRun = (state: RunProgressState, e: RunEvent): boolean =>
  isTracked(e) && TERMINAL_STATUSES.has(e.status) && (state.rows[e.id]?.outcome ?? 'running') === 'running';

/** Drop finished rows past their TTL, and the oldest past MAX_ROWS. */
export const pruneRows = (state: RunProgressState, now: number): RunProgressState => {
  const kept = Object.values(state.rows)
    .filter((r) => r.outcome === 'running' || now - r.updatedAt < FINISHED_TTL_MS)
    .sort((a, b) => b.startedAt - a.startedAt)
    .slice(0, MAX_ROWS);
  if (kept.length === Object.keys(state.rows).length) return state;
  return { ...state, rows: Object.fromEntries(kept.map((r) => [r.id, r])) };
};

/** Running first, then newest. */
export const sortedRows = (state: RunProgressState): RunRow[] =>
  Object.values(state.rows).sort((a, b) =>
    a.outcome === b.outcome || (a.outcome !== 'running' && b.outcome !== 'running')
      ? b.startedAt - a.startedAt
      : a.outcome === 'running' ? -1 : 1,
  );

export const summarize = (rows: RunRow[]): RunSummary => {
  const running = rows.filter((r) => r.outcome === 'running').length;
  const passed = rows.filter((r) => r.outcome === 'passed').length;
  const failed = rows.filter((r) => r.outcome === 'failed').length;
  const total = rows.length;
  const percent = total ? clampPct(rows.reduce((sum, r) => sum + (rowPercent(r) ?? 0), 0) / total) : 0;
  return { running, passed, failed, total, percent };
};

export const hideBand = (state: RunProgressState): RunProgressState => ({ ...state, hidden: true });
