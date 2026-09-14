import { useCallback, useEffect, useMemo, useState } from 'react';

import { api } from '../../../../frontend/src/utils/apiClient';
import { buildServerUrl } from '../../../../frontend/src/utils/buildUrlUtils';

export interface TimelineIncident {
  id: string;
  type: string; // blackscreen | freeze | audio_loss | macroblocks
  start: number; // epoch ms
  end: number; // epoch ms (now if still active)
  active: boolean;
}

export interface TimelineScript {
  id: string;
  name: string;
  start: number;
  end: number;
  success: boolean | null;
  device_name?: string;
}

export interface TimelineZap {
  id: string;
  t: number; // epoch ms (execution_date)
  key: string | null; // triggering remote key
  transition: string | null; // 'freeze' | 'blackscreen'
  durationMs: number | null;
  channel: string | null;
  reportUrl: string | null; // per-event zap report (R2)
}

interface UseDeviceTimelineResult {
  incidents: TimelineIncident[];
  scripts: TimelineScript[];
  zaps: TimelineZap[];
  refresh: () => void;
}

/**
 * Device incidents (alerts) + script runs over the last `hours` for the L2 timeline.
 *
 * PERF: alerts are filtered server-side by device_id (was: pull ~200 unfiltered);
 * scripts are fetched ONCE per host (small limit) and filtered to the device
 * IN MEMORY — so resolving device_name no longer triggers a second heavy refetch.
 */
export function useDeviceTimeline(
  hostName: string | undefined,
  deviceId: string | undefined,
  deviceName: string | undefined,
  hours = 24,
): UseDeviceTimelineResult {
  const [incidents, setIncidents] = useState<TimelineIncident[]>([]);
  const [rawScripts, setRawScripts] = useState<TimelineScript[]>([]);
  const [zaps, setZaps] = useState<TimelineZap[]>([]);

  // Alerts — depend on host+device only; server-side device filter keeps it tiny.
  const fetchIncidents = useCallback(async () => {
    if (!hostName || !deviceId) return;
    const cutoff = Date.now() - hours * 3600_000;
    const now = Date.now();
    try {
      const res = await api.get(
        buildServerUrl(
          `/server/alerts/getAllAlerts?device_id=${encodeURIComponent(deviceId)}` +
            `&host_name=${encodeURIComponent(hostName)}&active_limit=50&resolved_limit=100`,
        ),
      );
      const rows: any[] = Array.isArray(res) ? res : res?.alerts || [];
      setIncidents(
        rows
          .map((a) => {
            const start = new Date(a.start_time).getTime();
            const end = a.end_time ? new Date(a.end_time).getTime() : now;
            return { id: a.id, type: a.incident_type, start, end, active: !a.end_time };
          })
          .filter((i) => i.end >= cutoff),
      );
    } catch {
      setIncidents([]);
    }
  }, [hostName, deviceId, hours]);

  // Scripts — depend on HOST only (not device_name): fetch once, filter in memory.
  const fetchScripts = useCallback(async () => {
    if (!hostName) return;
    const cutoff = Date.now() - hours * 3600_000;
    try {
      const res = await api.get(
        buildServerUrl(`/server/script-results/getAllScriptResults?host_name=${encodeURIComponent(hostName)}&limit=80`),
      );
      const rows: any[] = Array.isArray(res) ? res : res?.script_results || res?.results || [];
      setRawScripts(
        rows
          .map((s) => {
            const start = new Date(s.started_at).getTime();
            const end = s.completed_at ? new Date(s.completed_at).getTime() : start;
            return { id: s.id, name: s.script_name, start, end, success: s.success ?? null, device_name: s.device_name };
          })
          .filter((s) => s.end >= cutoff),
      );
    } catch {
      setRawScripts([]);
    }
  }, [hostName, hours]);

  useEffect(() => {
    fetchIncidents();
    const id = setInterval(fetchIncidents, 60_000);
    return () => clearInterval(id);
  }, [fetchIncidents]);

  useEffect(() => {
    fetchScripts();
    const id = setInterval(fetchScripts, 120_000);
    return () => clearInterval(id);
  }, [fetchScripts]);

  // Zaps — by host + device_name (zap_results keys on device_name).
  const fetchZaps = useCallback(async () => {
    if (!hostName || !deviceName) return;
    try {
      const res = await api.get(
        buildServerUrl(
          `/server/monitoring/zaps?device_name=${encodeURIComponent(deviceName)}` +
            `&host_name=${encodeURIComponent(hostName)}&hours=${hours}`,
        ),
      );
      const rows: any[] = Array.isArray(res?.zaps) ? res.zaps : [];
      setZaps(
        rows.map((z) => ({
          id: z.id,
          t: new Date(z.execution_date || z.started_at).getTime(),
          key: z.action_params?.key ?? null,
          transition: z.transition_type ?? null,
          durationMs: z.total_zap_duration_ms ?? null,
          channel: z.channel_name || z.channel_number || null,
          reportUrl: z.report_url ?? null,
        })),
      );
    } catch {
      setZaps([]);
    }
  }, [hostName, deviceName, hours]);

  useEffect(() => {
    fetchZaps();
    const id = setInterval(fetchZaps, 120_000);
    return () => clearInterval(id);
  }, [fetchZaps]);

  const scripts = useMemo(
    () => (deviceName ? rawScripts.filter((s) => s.device_name === deviceName) : rawScripts),
    [rawScripts, deviceName],
  );

  const refresh = useCallback(() => {
    fetchIncidents();
    fetchScripts();
    fetchZaps();
  }, [fetchIncidents, fetchScripts, fetchZaps]);

  return { incidents, scripts, zaps, refresh };
}
