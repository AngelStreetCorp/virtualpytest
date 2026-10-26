import { useCallback, useEffect, useRef, useState } from 'react';

import { api } from '../../../utils/apiClient';
import { buildServerUrl } from '../../../utils/buildUrlUtils';
import type { MonitorProfileInfo, MonitorProfileStatus, MonitorUnits } from './plan';

const POLL_MS = 2000;
const POLL_GIVE_UP_MS = 90_000;

export interface UseMonitorProfiles {
  profiles: MonitorProfileInfo[];
  hostDefault: string;
  units: MonitorUnits | null;
  status: MonitorProfileStatus | null;
  /** true while a save is still being applied on the host */
  applying: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  /** call right after a successful save: polls the status until the host says the apply is done */
  watchApply: () => void;
}

const base = '/server/settings/host-monitor-profiles';

export function useMonitorProfiles(hostName: string): UseMonitorProfiles {
  const [profiles, setProfiles] = useState<MonitorProfileInfo[]>([]);
  const [hostDefault, setHostDefault] = useState('tv_app');
  const [units, setUnits] = useState<MonitorUnits | null>(null);
  const [status, setStatus] = useState<MonitorProfileStatus | null>(null);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const host = useRef(hostName);
  host.current = hostName;

  const stop = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  };

  const loadStatus = useCallback(async (): Promise<MonitorProfileStatus | null> => {
    const q = `?host_name=${encodeURIComponent(host.current)}`;
    const data = await api.get(buildServerUrl(`${base}/status${q}`));
    const next = data as MonitorProfileStatus;
    setStatus(next);
    if (next.units) setUnits(next.units);
    return next;
  }, []);

  const refresh = useCallback(async () => {
    if (!host.current) return;
    setError(null);
    try {
      const data = await api.get(buildServerUrl(`${base}?host_name=${encodeURIComponent(host.current)}`));
      setProfiles(data.profiles ?? []);
      setHostDefault(data.default ?? 'tv_app');
      setUnits(data.units ?? null);
      await loadStatus();
    } catch (err) {
      // An older host without the route: the picker is hidden, the rest of Settings keeps working.
      setProfiles([]);
      setStatus(null);
      setError(err instanceof Error ? err.message : 'Monitoring profiles are not available on this host');
    }
  }, [loadStatus]);

  const watchApply = useCallback(() => {
    stop();
    setApplying(true);
    const startedAt = Date.now();
    const tick = async () => {
      try {
        const s = await loadStatus();
        if (s?.result?.state === 'done') {
          setApplying(false);
          return;
        }
      } catch {
        /* keep trying until the give-up time */
      }
      if (Date.now() - startedAt > POLL_GIVE_UP_MS) {
        setApplying(false);
        return;
      }
      timer.current = setTimeout(tick, POLL_MS);
    };
    timer.current = setTimeout(tick, 500);
  }, [loadStatus]);

  useEffect(() => {
    stop();
    setApplying(false);
    setStatus(null);
    setProfiles([]);
    if (hostName) void refresh();
    return stop;
  }, [hostName, refresh]);

  return { profiles, hostDefault, units, status, applying, error, refresh, watchApply };
}
