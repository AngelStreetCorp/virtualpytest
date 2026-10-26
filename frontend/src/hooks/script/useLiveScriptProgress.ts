import { useCallback, useEffect, useRef, useState } from 'react';

import { useRunExecutions } from '../../contexts/RunExecutionsContext';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { apiClient } from '../../utils/apiClient';

export interface LiveRunStep {
  number: number;
  label: string;
  success: boolean;
  skipped?: boolean;
  error?: string | null;
  durationMs?: number | null;
  /** Browser-reachable screenshot URL, when the step carried one. */
  screenshot?: string | null;
  /** Optional stage the step belongs to (script-defined). */
  stage?: string | null;
  /** Epoch ms the step was recorded. */
  at?: number | null;
}

export interface LiveRunProgress {
  taskId?: string;
  steps: LiveRunStep[];
  stepNumber: number;
  totalSteps: number | null;
  message?: string;
  updatedAt: number;
}

/**
 * Latest live progress of the script running on each target, from the `execution_update`
 * events (status "running") the server fans out for /script/progress. Keyed by the caller's
 * target key; a new execution_id on the same target starts a fresh list.
 */
export const useLiveScriptProgress = (keyOf: (hostName: string, deviceId?: string) => string) => {
  const { subscribeSystemUpdate } = useRunExecutions();
  const [byTarget, setByTarget] = useState<Record<string, LiveRunProgress>>({});
  const keyOfRef = useRef(keyOf);
  keyOfRef.current = keyOf;

  useEffect(() => subscribeSystemUpdate((event: any) => {
    if (event?.type !== 'execution_update' || event?.execution_type !== 'script') return;
    const key = keyOfRef.current(event.host_name || '', event.device_id);
    if (event.status !== 'running') {
      setByTarget((prev) => {
        if (!(key in prev)) return prev;
        const next = { ...prev };
        delete next[key];
        return next;
      });
      return;
    }
    const step = event.result?.step;
    setByTarget((prev) => {
      const current = prev[key];
      const base = current && current.taskId === event.execution_id
        ? current
        : { taskId: event.execution_id, steps: [], stepNumber: 0, totalSteps: null, updatedAt: 0 } as LiveRunProgress;
      const steps = step
        ? [...base.steps, {
            number: event.result?.step_number ?? base.steps.length + 1,
            label: step.label || step.message || step.to_node || '',
            success: step.success !== false,
            skipped: step.skipped,
            error: step.error,
            durationMs: step.duration_ms,
            screenshot: step.screenshot ?? null,
            stage: step.stage ?? null,
            at: Date.now(),
          }]
        : base.steps;
      return {
        ...prev,
        [key]: {
          ...base,
          steps,
          stepNumber: event.result?.step_number ?? base.stepNumber,
          totalSteps: event.result?.total_steps ?? base.totalSteps,
          message: event.message || base.message,
          updatedAt: Date.now(),
        },
      };
    });
  }), [subscribeSystemUpdate]);

  /** Snapshot of the run now on a target (steps recorded so far), for a run this page did not see start. */
  const loadSnapshot = useCallback(async (key: string, hostName: string, deviceId: string) => {
    try {
      const qs = new URLSearchParams({ host_name: hostName, device_id: deviceId });
      const response = await apiClient(buildServerUrl(`/server/script/liveProgress?${qs}`), { method: 'GET' });
      if (!response.ok) return;
      const task = (await response.json())?.task;
      if (!task) return;
      const taskId: string = task.id;
      const recorded: any[] = task?.progress_steps || [];
      if (!recorded.length && !task?.progress) return;
      setByTarget((prev) => {
        if (prev[key]?.steps.length) return prev;
        return {
          ...prev,
          [key]: {
            taskId,
            steps: recorded.map((s) => ({
              number: s.step_number, label: s.label || '', success: s.success !== false,
              skipped: s.skipped, error: s.error, durationMs: s.duration_ms,
              screenshot: s.screenshot ?? null, stage: s.stage ?? null,
              at: typeof s.at === 'number' ? s.at * 1000 : null,
            })),
            stepNumber: task.progress?.step_number ?? recorded.length,
            totalSteps: task.progress?.total_steps ?? null,
            message: task.progress?.message,
            updatedAt: Date.now(),
          },
        };
      });
    } catch {
      // Best effort — live events fill the list in.
    }
  }, []);

  return { byTarget, loadSnapshot };
};
