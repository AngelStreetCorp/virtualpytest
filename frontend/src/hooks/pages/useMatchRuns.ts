import { useCallback, useEffect, useState } from 'react';

import { api } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';

/** One row from the match_runs table, after the server returns it. */
export interface MatchRun {
  id: string;
  team_id: string;
  server_id: string | null;
  host_name: string;
  device_id: string | null;
  device_name: string | null;
  device_model: string | null;
  userinterface_name: string;
  tree_id: string | null;
  variant: string | null;
  profile?: string | null;
  /** verify | localize_button | monitor_localize | localize_check | nightwatch */
  source: string;
  source_ref: Record<string, unknown> | null;
  started_at: string;
  completed_at: string | null;
  elapsed_ms: number | null;
  /** known_node | unknown | no_signal | low_confidence | overlay | live */
  verdict: string;
  matched_node_id: string | null;
  matched_confidence: number | null;
  runner_up_margin: number | null;
  /** [{node_id, label, score, rank}] top-3 — only present when candidate_floor_hit */
  candidates_top_3: Array<{ node_id: string | null; label: string | null; score: number | null; rank: number }>;
  candidate_threshold: number;
  candidate_floor_hit: boolean;
  dhash: number | null;
  frame_url: string | null;
  previous_event_id: string | null;
  previous_node_id: string | null;
  step_in_session: number | null;
  session_id: string | null;
  created_at: string;
  /** True when the run stored its live fingerprint (the fingerprint itself comes with useDeviceRuns). */
  has_fingerprint?: boolean;
  live_fingerprint?: Record<string, unknown> | null;
}

export interface NodeTransition {
  from_node_id: string;
  to_node_id: string;
  userinterface_name: string;
  occurrences: number;
  uncertain_occurrences: number;
  last_seen_at: string;
}

/** One row from /server/match-runs/summary — the live KPI strip. */
export interface MatchRunSummary {
  total: number;
  matched: number;
  uncertain: number;
  unknown_or_low_conf: number;
  distinct_devices: number;
  distinct_profiles: number;
  distinct_hosts: number;
  avg_confidence: number | null;
  window_started_at: string | null;
}

/** One row per (host, device) — the per-device heatmap + table. */
export interface MatchRunDeviceRow {
  host_name: string;
  device_name: string | null;
  total: number;
  matched: number;
  uncertain: number;
  unknown: number;
  last_match_at: string | null;
}

/** One row from /server/match-runs/distribution — the stacked-bar chart. */
export interface MatchRunDistributionRow {
  bucket: string;
  verdict: string;
  count: number;
}

/** Window keys accepted by the dashboard endpoints. */
export type MatchRunsWindow = '1h' | '6h' | '24h' | '7d';

interface UseMatchRunsFilters {
  teamId: string;
  deviceId?: string;
  deviceName?: string;
  userinterfaceName?: string;
  limit?: number;
  /** KPI window. Defaults to '24h'. */
  window?: MatchRunsWindow;
  /** Auto-refresh interval ms; 0 disables. Defaults to 10s. */
  refreshMs?: number;
}

const DEFAULT_REFRESH_MS = 10_000;

export const useMatchRuns = (filters: UseMatchRunsFilters) => {
  const [recent, setRecent] = useState<MatchRun[]>([]);
  const [transitions, setTransitions] = useState<NodeTransition[]>([]);
  const [uncertain, setUncertain] = useState<MatchRun[]>([]);
  const [summary, setSummary] = useState<MatchRunSummary | null>(null);
  const [previous, setPrevious] = useState<MatchRunSummary | null>(null);
  const [perDevice, setPerDevice] = useState<MatchRunDeviceRow[]>([]);
  const [distribution, setDistribution] = useState<MatchRunDistributionRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastFetchedAt, setLastFetchedAt] = useState<string | null>(null);
  const [lastErrorAt, setLastErrorAt] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    if (!filters.teamId) return;
    setLoading(true);
    // Stale-while-revalidate: do NOT clear `error` here.  If this refetch
    // fails again, the operator sees the prior error + the new timestamp;
    // if it succeeds, both clear together.  Same shape as SWR libraries
    // (stale data stays on screen until the next successful refresh).
    try {
      const basePayload = {
        team_id: filters.teamId,
        device_id: filters.deviceId,
        device_name: filters.deviceName,
        userinterface_name: filters.userinterfaceName,
        window: filters.window ?? '24h',
        limit: filters.limit ?? 50,
      };
      const [r1, r2, r3, r4, r5, r6] = await Promise.all([
        api.post(buildServerUrl('/server/match-runs/recent'), basePayload),
        filters.userinterfaceName
          ? api.post(buildServerUrl('/server/match-runs/transitions'), basePayload)
          : Promise.resolve({ rows: [] }),
        api.post(buildServerUrl('/server/match-runs/uncertain'), basePayload),
        api.post(buildServerUrl('/server/match-runs/summary'), basePayload),
        api.post(buildServerUrl('/server/match-runs/per-device'), basePayload),
        api.post(buildServerUrl('/server/match-runs/distribution'), basePayload),
      ]);
      setRecent((r1 as { rows: MatchRun[] }).rows || []);
      setTransitions((r2 as { rows: NodeTransition[] }).rows || []);
      setUncertain((r3 as { rows: MatchRun[] }).rows || []);
      setSummary((r4 as { row: MatchRunSummary }).row || null);
      setPrevious((r4 as { previous?: MatchRunSummary }).previous || null);
      setPerDevice((r5 as { rows: MatchRunDeviceRow[] }).rows || []);
      setDistribution((r6 as { rows: MatchRunDistributionRow[] }).rows || []);
      setLastFetchedAt(new Date().toISOString());
      setError(null);
      setLastErrorAt(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to load match_runs';
      setError(msg);
      setLastErrorAt(new Date().toISOString());
    } finally {
      setLoading(false);
    }
  }, [filters.teamId, filters.deviceId, filters.deviceName, filters.userinterfaceName, filters.limit, filters.window]);

  useEffect(() => {
    refetch();
  }, [refetch]);

  useEffect(() => {
    const ms = filters.refreshMs ?? DEFAULT_REFRESH_MS;
    if (!ms) return undefined;
    const t = window.setInterval(() => refetch(), ms);
    return () => window.clearInterval(t);
  }, [refetch, filters.refreshMs]);

  return {
    recent,
    transitions,
    uncertain,
    summary,
    previous,
    perDevice,
    distribution,
    loading,
    error,
    lastFetchedAt,
    lastErrorAt,
    refetch,
  };
};

/** The device a drill-down is about: `deviceName` null = the runs of the host that carry no device. */
export interface DeviceRunsFilters {
  teamId: string;
  hostName: string;
  deviceName: string | null;
  limit?: number;
}

/** Last N runs of one host/device (POST /server/match-runs/recent), newest first. */
export const useDeviceRuns = (filters: DeviceRunsFilters | null) => {
  const [rows, setRows] = useState<MatchRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    if (!filters || !filters.teamId || !filters.hostName) {
      setRows([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await api.post(buildServerUrl('/server/match-runs/recent'), {
        team_id: filters.teamId,
        host_name: filters.hostName,
        device_name: filters.deviceName || undefined,
        host_only: !filters.deviceName,
        include_fingerprint: true,
        limit: filters.limit ?? 50,
      });
      setRows((res as { rows: MatchRun[] }).rows || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load runs');
    } finally {
      setLoading(false);
    }
  }, [filters?.teamId, filters?.hostName, filters?.deviceName, filters?.limit]);

  useEffect(() => {
    refetch();
  }, [refetch]);

  return { rows, loading, error, refetch };
};
