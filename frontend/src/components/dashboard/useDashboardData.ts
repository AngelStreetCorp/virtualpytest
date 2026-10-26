import { useCallback, useEffect, useRef, useState } from 'react';

import { APP_CONFIG } from '../../config/constants';
import { api } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';

import type { DashboardData, DashboardSummary, DashboardSystem, DashRange } from './dashboardTypes';

export const DASHBOARD_POLL_MS = 30_000;

export const EMPTY_DASHBOARD_DATA: DashboardData = {
  summary: null,
  system: null,
  summaryError: false,
  systemError: false,
  loading: true,
};

interface Result {
  data: DashboardData;
  /** generated_at of the newest answer (ms since epoch), or null before the first one. */
  generatedAt: number | null;
  /** Fetch now (manual refresh, kiosk rotation). */
  refresh: () => void;
}

/**
 * The one poll behind every card (TASK-123): summary for all users, system for admins, every 30 s,
 * skipped while the browser tab is hidden, plus `refresh()`. Cards never fetch on their own.
 */
export function useDashboardData(range: DashRange, includeSystem: boolean): Result {
  const [data, setData] = useState<DashboardData>(EMPTY_DASHBOARD_DATA);
  const [generatedAt, setGeneratedAt] = useState<number | null>(null);
  const alive = useRef(true);
  const inFlight = useRef(false);
  const lastFetch = useRef(0);

  const fetchAll = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    lastFetch.current = Date.now();
    const team = encodeURIComponent(APP_CONFIG.DEFAULT_TEAM_ID);
    try {
      const [summary, system] = await Promise.allSettled([
        api.get<DashboardSummary>(buildServerUrl(`/server/dashboard/summary?team_id=${team}&range=${range}`)),
        includeSystem
          ? api.get<DashboardSystem>(buildServerUrl(`/server/dashboard/system?team_id=${team}`))
          : Promise.resolve(null),
      ]);
      if (!alive.current) return;
      const s = summary.status === 'fulfilled' && summary.value?.success !== false ? summary.value : null;
      const sys = system.status === 'fulfilled' && system.value && system.value.success !== false ? system.value : null;
      setData((prev) => ({
        // Keep the last good answer when a poll fails: a blip should not blank the cards.
        summary: s ?? prev.summary,
        system: sys ?? prev.system,
        summaryError: s === null,
        systemError: includeSystem && sys === null,
        loading: false,
      }));
      const stamps = [s?.generated_at, sys?.generated_at]
        .map((g) => (g ? new Date(g).getTime() : NaN))
        .filter((n) => Number.isFinite(n));
      if (stamps.length > 0) setGeneratedAt(Math.max(...stamps));
    } finally {
      inFlight.current = false;
    }
  }, [range, includeSystem]);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  // Range / role change and first mount: fetch at once.
  useEffect(() => {
    void fetchAll();
  }, [fetchAll]);

  useEffect(() => {
    const tick = () => {
      if (typeof document !== 'undefined' && document.hidden) return;
      void fetchAll();
    };
    const id = window.setInterval(tick, DASHBOARD_POLL_MS);
    // Coming back to the tab after a long absence: do not wait for the next tick.
    const onVisible = () => {
      if (!document.hidden && Date.now() - lastFetch.current >= DASHBOARD_POLL_MS) void fetchAll();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      window.clearInterval(id);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [fetchAll]);

  const refresh = useCallback(() => {
    void fetchAll();
  }, [fetchAll]);

  return { data, generatedAt, refresh };
}
