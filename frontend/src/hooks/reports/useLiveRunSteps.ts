/**
 * Steps recorded so far by the script behind one live task, for the live run page.
 * Polls the existing GET /server/script/liveProgress (the same feed the Run Tests dialog
 * snapshots) every 2 s while the run is active and the tab is visible. One last read is
 * made when the run ends so the final steps are shown.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { apiClient } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import type { LiveRunStep } from '../script/useLiveScriptProgress';

const STEPS_POLL_MS = 2000;

export interface LiveRunSteps {
  steps: LiveRunStep[];
  totalSteps: number | null;
  stepNumber: number;
  message: string | null;
  /** Id of the task the steps belong to (the one running on the device when no taskId was given). */
  taskId: string | null;
  /** True once the feed has answered at least once (with or without steps). */
  polled: boolean;
}

const EMPTY: LiveRunSteps = { steps: [], totalSteps: null, stepNumber: 0, message: null, taskId: null, polled: false };

const isVisible = () => typeof document === 'undefined' || document.visibilityState === 'visible';

export const useLiveRunSteps = (
  taskId: string,
  hostName: string | null | undefined,
  deviceId: string | null | undefined,
  active: boolean,
): LiveRunSteps => {
  const [state, setState] = useState<LiveRunSteps>(EMPTY);
  const inflight = useRef(false);

  const load = useCallback(async () => {
    if (!hostName || inflight.current) return;
    inflight.current = true;
    try {
      const qs = new URLSearchParams({ host_name: hostName, device_id: deviceId || '' });
      const response = await apiClient(buildServerUrl(`/server/script/liveProgress?${qs}`), { method: 'GET' });
      if (!response.ok) return;
      const task = (await response.json())?.task;
      setState((prev) => (prev.polled ? prev : { ...prev, polled: true }));
      // The endpoint answers for whatever runs on the device now; only keep this task's steps
      // (an empty taskId takes whatever runs there, for rows that do not know their task id).
      if (!task || (taskId && task.id !== taskId)) return;
      const recorded: any[] = task.progress_steps || [];
      setState({
        steps: recorded.map((s, i) => ({
          number: s.step_number ?? i + 1,
          label: s.label || '',
          success: s.success !== false,
          skipped: s.skipped,
          error: s.error,
          durationMs: s.duration_ms,
          screenshot: s.screenshot ?? null,
          stage: s.stage ?? null,
          at: typeof s.at === 'number' ? s.at * 1000 : null,
        })),
        totalSteps: task.progress?.total_steps ?? null,
        stepNumber: task.progress?.step_number ?? recorded.length,
        message: task.progress?.message ?? null,
        taskId: task.id,
        polled: true,
      });
    } catch {
      // Best effort — the next tick retries.
    } finally {
      inflight.current = false;
    }
  }, [taskId, hostName, deviceId]);

  useEffect(() => {
    if (!hostName) return undefined;
    void load();
    if (!active) return undefined;
    const id = window.setInterval(() => {
      if (isVisible()) void load();
    }, STEPS_POLL_MS);
    return () => window.clearInterval(id);
  }, [load, active, hostName]);

  return state;
};
