import { useCallback, useEffect, useRef, useState } from 'react';

import { apiClient } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import type { MaintenanceScope } from './useMaintenanceWindow';

export type StepState = 'pending' | 'waiting' | 'running' | 'done' | 'failed';
export type RunStatus = 'active' | 'ok' | 'failed' | 'rolled_back';

export interface RunStep {
  index: number;
  key: string;
  title: string;
  state: StepState;
  detail: string | null;
  data: Record<string, any>;
  started_at: string | null;
  finished_at: string | null;
}

export type PhaseName = 'rsync' | 'install' | 'restart' | 'health';
export type PhaseState = 'running' | 'ok' | 'failed' | 'skipped';

export interface DeployPhase {
  state: PhaseState;
  started: string | null;
  ended: string | null;
  duration_s: number | null;
  detail: string;
}

/** One machine of the deployment: server, frontend, a host, a docker target. Keyed by (role, host). */
export interface DeployCard {
  host: string;
  role: string;
  state: 'pending' | 'running' | 'ok' | 'failed' | 'skipped';
  started: string | null;
  ended: string | null;
  duration_s: number | null;
  phases: Partial<Record<PhaseName, DeployPhase>>;
  log: string[];
  error: string;
}

/** Parsed VPT_PROGRESS lines of the run log (server side, same format as deploy_progress.py). */
export interface DeploymentView {
  hosts: DeployCard[];
  state: 'pending' | 'running' | 'ok' | 'failed';
  started: string | null;
  ended: string | null;
  duration_s: number | null;
  phases_done: number;
  phases_total: number;
}

export interface UpdateRun {
  id: string;
  status: RunStatus;
  started_by: string;
  started_at: string;
  window_start: string;
  window_end: string;
  scope: MaintenanceScope;
  device_ids: string[];
  note: string;
  closed_at: string | null;
  close_message: string | null;
  steps: RunStep[];
  log: string[];
  deployment?: DeploymentView | null;
  /** TASK-128 G12: the pause / abort request flags of the deploy (read by the loop between machines). */
  control?: { pause: boolean; abort: boolean; by?: string };
  /** True for a run started before the TASK-109 step change: the server refuses its steps. */
  legacy?: boolean;
}

export interface MigrationsState {
  tracker: 'missing' | 'ready';
  tracker_file: string;
  total: number;
  applied: number;
  pending: string[];
  files: string[];
  can_apply: boolean;
}

const BASE = '/server/platform-update';
const POLL_MS = 4000;

const post = async (path: string, body: Record<string, unknown>) => {
  const response = await apiClient(buildServerUrl(`${BASE}${path}`), { method: 'POST', body: JSON.stringify(body) });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.success === false) {
    throw new Error(data.error || data.message || `HTTP ${response.status}`);
  }
  return data;
};

/** State of the active (or last opened) update run, plus the calls that drive its steps. */
export const usePlatformUpdateRun = () => {
  const [run, setRun] = useState<UpdateRun | null>(null);
  const [migrations, setMigrations] = useState<MigrationsState | null>(null);
  const [busyStep, setBusyStep] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const runIdRef = useRef<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const response = await apiClient(buildServerUrl(`${BASE}/runs/active`));
      const data = await response.json();
      if (response.ok && data.success) {
        if (data.run) {
          runIdRef.current = data.run.id;
          setRun(data.run);
        } else if (runIdRef.current) {
          const closed = await apiClient(buildServerUrl(`${BASE}/runs/${runIdRef.current}`));
          const closedData = await closed.json();
          if (closed.ok && closedData.success) setRun(closedData.run);
        }
      }
    } catch {
      // transient; next poll retries
    } finally {
      setLoaded(true);
    }
  }, []);

  const refreshMigrations = useCallback(async () => {
    try {
      const response = await apiClient(buildServerUrl(`${BASE}/migrations`));
      const data = await response.json();
      if (response.ok && data.success) setMigrations(data);
      else setMigrations(null);
    } catch {
      setMigrations(null);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const guarded = useCallback(
    async <T,>(step: number | null, work: () => Promise<T>): Promise<T | undefined> => {
      setBusyStep(step);
      setError(null);
      try {
        return await work();
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Request failed');
        return undefined;
      } finally {
        setBusyStep(null);
        await refresh();
      }
    },
    [refresh]
  );

  const startRun = useCallback(
    (windowStart: string, windowEnd: string, note: string) =>
      guarded(null, async () => {
        const data = await post('/runs', { window_start: windowStart, window_end: windowEnd, note, scope: 'platform' });
        runIdRef.current = data.run.id;
        setRun(data.run);
      }),
    [guarded]
  );

  const stepCall = useCallback(
    (index: number, body: Record<string, unknown>) =>
      guarded(index, async () => {
        if (!runIdRef.current) throw new Error('No active run');
        const data = await post(`/runs/${runIdRef.current}/steps/${index}`, body);
        setRun(data.run);
        return data.run as UpdateRun;
      }),
    [guarded]
  );

  const closeRun = useCallback(
    (status: 'ok' | 'failed' | 'rolled_back', message: string) =>
      guarded(6, async () => {
        if (!runIdRef.current) throw new Error('No active run');
        const data = await post(`/runs/${runIdRef.current}/close`, { status, message });
        setRun(data.run);
      }),
    [guarded]
  );

  const migrationCall = useCallback(
    (path: string, body: Record<string, unknown>) =>
      guarded(4, async () => {
        await post(`/migrations${path}`, body);
        await refreshMigrations();
      }),
    [guarded, refreshMigrations]
  );

  const leaveRun = useCallback(() => {
    runIdRef.current = null;
    setRun(null);
  }, []);

  return {
    run, migrations, busyStep, error, loaded, setError,
    startRun, stepCall, closeRun, refresh, refreshMigrations, migrationCall, leaveRun,
    logUrl: run ? buildServerUrl(`${BASE}/runs/${run.id}/log`) : null,
  };
};
