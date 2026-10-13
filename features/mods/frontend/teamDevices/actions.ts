/** Pure rules of the Team devices widget. */
import { TERMINAL_STATUSES } from '../../../../frontend/src/mods/core/constants';
import type { RunEvent } from '../../../../frontend/src/mods/core/types';

import { SHOW_ACTIVE } from './constants';
import type { AlertRow, DeviceRow, ErrorCounts, FleetTotals, RunningRuns, ScriptResultRow } from './types';

export const failureKey = (hostName: string, deviceName: string) => `${hostName}:${deviceName}`;

/** Keep the devices of running runs; a run leaves when it ends. Runs without a device are skipped. */
export const applyRun = (running: RunningRuns, e: RunEvent): RunningRuns => {
  if (TERMINAL_STATUSES.has(e.status)) {
    if (!(e.id in running)) return running;
    const next = { ...running };
    delete next[e.id];
    return next;
  }
  if (!e.hostName || !e.deviceId || e.id in running) return running;
  return { ...running, [e.id]: { hostName: e.hostName, deviceId: e.deviceId } };
};

/** Failed results started inside the window, counted per host + device name. */
export const countFailures = (results: ScriptResultRow[], now: number, windowMs: number): ErrorCounts => {
  const byName: Record<string, number> = {};
  for (const r of results) {
    if (r.success !== false || !r.host_name || !r.device_name || !r.started_at) continue;
    if (now - Date.parse(r.started_at) > windowMs) continue;
    const key = failureKey(r.host_name, r.device_name);
    byName[key] = (byName[key] ?? 0) + 1;
  }
  return { byName, byId: {} };
};

/** Open alerts of this team (alerts without a team count too), per host + device id. */
export const countAlerts = (alerts: AlertRow[], teamId: string): ErrorCounts => {
  const byId: Record<string, number> = {};
  for (const a of alerts) {
    if (!a.host_name || !a.device_id || (a.team_id && a.team_id !== teamId)) continue;
    const key = `${a.host_name}:${a.device_id}`;
    byId[key] = (byId[key] ?? 0) + 1;
  }
  return { byName: {}, byId };
};

const NO_ERRORS: ErrorCounts = { byName: {}, byId: {} };

interface HostLike {
  host_name: string;
  status?: string;
  devices?: { device_id: string; device_name?: string; device_model?: string }[];
}

/** One row per device, busiest first: failures, then running, then name. */
export const buildRows = (hosts: HostLike[], running: RunningRuns, errors: ErrorCounts | undefined, show: string): DeviceRow[] => {
  const counts = errors ?? NO_ERRORS;
  const runningCount: Record<string, number> = {};
  Object.values(running).forEach((r) => {
    const key = `${r.hostName}:${r.deviceId}`;
    runningCount[key] = (runningCount[key] ?? 0) + 1;
  });
  const rows = hosts.flatMap((h) =>
    (h.devices ?? []).map((d) => ({
      hostName: h.host_name,
      deviceId: d.device_id,
      deviceName: d.device_name || d.device_id,
      deviceModel: d.device_model,
      online: h.status === undefined || h.status === 'online',
      running: runningCount[`${h.host_name}:${d.device_id}`] ?? 0,
      failed:
        (counts.byName[failureKey(h.host_name, d.device_name || d.device_id)] ?? 0) +
        (counts.byId[`${h.host_name}:${d.device_id}`] ?? 0),
    })),
  );
  return rows
    .filter((r) => show !== SHOW_ACTIVE || r.running > 0 || r.failed > 0 || !r.online)
    .sort((a, b) => b.failed - a.failed || b.running - a.running || a.deviceName.localeCompare(b.deviceName));
};

export const totals = (rows: DeviceRow[]): FleetTotals => ({
  devices: rows.length,
  offline: rows.filter((r) => !r.online).length,
  running: rows.reduce((n, r) => n + r.running, 0),
  failed: rows.reduce((n, r) => n + r.failed, 0),
});
