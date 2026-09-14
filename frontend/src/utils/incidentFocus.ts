/**
 * Deep link from the Heatmap analysis table to one incident on the Alerts page.
 *
 * The heatmap JSON carries no incident id, only host / device / analysis flags per
 * frame, so the link identifies the incident by (host, device, type) plus the frame
 * time. The Alerts page resolves that to the alert whose start..end brackets the
 * frame time (the capture monitor keeps one open alert per device+type, so this is
 * unambiguous). Query params:
 *
 *   /monitoring/incidents?host=<host_name>&device=<device_id>&type=<incident_type>&at=<ISO>
 */

import { Alert } from '../types/pages/Monitoring_Types';

/** Incident types the capture monitor raises, as stored in alerts.incident_type. */
export type IncidentFocusType = 'freeze' | 'blackscreen' | 'no_audio';

export interface IncidentFocus {
  host: string;
  device: string;
  type: IncidentFocusType;
  /** ISO timestamp of the heatmap frame the user clicked. */
  at: string;
}

export const INCIDENTS_ROUTE = '/monitoring/incidents';

export function buildIncidentFocusUrl(focus: IncidentFocus): string {
  const params = new URLSearchParams({
    host: focus.host,
    device: focus.device,
    type: focus.type,
    at: focus.at,
  });
  return `${INCIDENTS_ROUTE}?${params.toString()}`;
}

/** Read the focus params back; null when the page was opened without them. */
export function parseIncidentFocus(searchParams: URLSearchParams): IncidentFocus | null {
  const host = searchParams.get('host');
  const device = searchParams.get('device');
  const type = searchParams.get('type') as IncidentFocusType | null;
  const at = searchParams.get('at');
  if (!host || !device || !type || !at) return null;
  return { host, device, type, at };
}

/**
 * Pick the alert the focus points at. Prefers an alert whose [start_time, end_time]
 * contains `at` (end_time missing = still open). Falls back to the alert with the
 * closest start_time for that host/device/type, within a 10-minute window, which
 * covers the heatmap minute rounding and clock drift between host and server.
 */
export function findFocusedAlert(alerts: Alert[], focus: IncidentFocus): Alert | null {
  const candidates = alerts.filter(
    (a) => a.host_name === focus.host && a.device_id === focus.device && a.incident_type === focus.type,
  );
  if (candidates.length === 0) return null;

  const atMs = new Date(focus.at).getTime();
  if (Number.isNaN(atMs)) return candidates[0];

  const bracketing = candidates.filter((a) => {
    const start = new Date(a.start_time).getTime();
    const end = a.end_time ? new Date(a.end_time).getTime() : Number.POSITIVE_INFINITY;
    return start <= atMs && atMs <= end;
  });
  if (bracketing.length > 0) {
    // Newest start wins if several overlap (should not happen, but be deterministic).
    return bracketing.sort((a, b) => new Date(b.start_time).getTime() - new Date(a.start_time).getTime())[0];
  }

  const TEN_MINUTES = 10 * 60 * 1000;
  const nearest = candidates
    .map((a) => ({ a, d: Math.abs(new Date(a.start_time).getTime() - atMs) }))
    .filter(({ d }) => d <= TEN_MINUTES)
    .sort((x, y) => x.d - y.d)[0];
  return nearest ? nearest.a : null;
}
