/**
 * Live run status by server polling.
 *
 * Polls `GET /server/run-management/live/:task_id` every LIVE_POLL_INTERVAL_MS, one request
 * at a time, only while the page is visible and the run is not terminal. Becoming visible
 * again refetches immediately. An optional `subscribe` (an existing /system event fan-out,
 * e.g. RunExecutionsContext.subscribeSystemUpdate) only makes the next poll happen sooner;
 * this hook never opens a socket of its own.
 *
 * Staleness is explicit: the server's own `stale` flag, or no successful poll for more
 * than three intervals. A failed poll keeps the last known data.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { LIVE_POLL_INTERVAL_MS, isTerminalStatus, toRunStatus, type LiveRunStatus } from '../../types/reports';
import { fetchLiveStatus, isApiError } from './runManagementApi';
import { useReportScope } from './useRunManagement';

export type SystemEventSubscribe = (handler: (event: any) => void) => () => void;

export interface UseLiveRunOptions {
  subscribe?: SystemEventSubscribe;
}

export interface UseLiveRunResult {
  data: LiveRunStatus | null;
  error: unknown;
  stale: boolean;
  isPolling: boolean;
  lastSuccessAt: number | null;
  refetch: () => void;
}

const STALE_AFTER_MS = LIVE_POLL_INTERVAL_MS * 3;

const isVisible = () => typeof document === 'undefined' || document.visibilityState === 'visible';

export const useLiveRun = (taskId: string, options: UseLiveRunOptions = {}): UseLiveRunResult => {
  const { subscribe } = options;
  const scope = useReportScope();
  const scopeRef = useRef(scope);
  scopeRef.current = scope;
  const [data, setData] = useState<LiveRunStatus | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [lastSuccessAt, setLastSuccessAt] = useState<number | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inflightRef = useRef<AbortController | null>(null);
  const terminalRef = useRef(false);
  const unmountedRef = useRef(false);
  const pollRef = useRef<() => void>(() => undefined);

  const clearTimer = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const schedule = useCallback((delay: number) => {
    clearTimer();
    if (unmountedRef.current || terminalRef.current || !isVisible()) {
      setIsPolling(false);
      return;
    }
    setIsPolling(true);
    timerRef.current = setTimeout(() => pollRef.current(), delay);
  }, []);

  const poll = useCallback(async () => {
    clearTimer();
    if (inflightRef.current || unmountedRef.current) return;
    const controller = new AbortController();
    inflightRef.current = controller;
    try {
      const next = await fetchLiveStatus(taskId, controller.signal, scopeRef.current);
      if (unmountedRef.current) return;
      setData(next);
      setError(null);
      const at = Date.now();
      setLastSuccessAt(at);
      setNow(at);
      terminalRef.current = isTerminalStatus(next.status);
    } catch (err) {
      if (unmountedRef.current || controller.signal.aborted) return;
      // 404 still answers with the shape: the task is unknown to this server (or out of
      // scope). Show that honestly instead of an error, and keep polling.
      const body = isApiError(err, 404) ? (err.body as Partial<LiveRunStatus> | null) : null;
      if (body && typeof body === 'object' && body.task_id) {
        setData({ ...(body as LiveRunStatus), status: toRunStatus(body.status) });
        setError(null);
      } else {
        setError(err);
      }
      setNow(Date.now());
    } finally {
      if (inflightRef.current === controller) inflightRef.current = null;
    }
    schedule(LIVE_POLL_INTERVAL_MS);
  }, [taskId, schedule]);

  pollRef.current = () => void poll();

  // Start / restart for a task.
  useEffect(() => {
    unmountedRef.current = false;
    terminalRef.current = false;
    setData(null);
    setError(null);
    setLastSuccessAt(null);
    if (isVisible()) void poll();
    return () => {
      unmountedRef.current = true;
      clearTimer();
      inflightRef.current?.abort();
      inflightRef.current = null;
    };
  }, [taskId, poll]);

  // Pause while hidden; refetch at once when visible again.
  useEffect(() => {
    const onVisibility = () => {
      if (isVisible()) {
        if (!terminalRef.current) void poll();
      } else {
        clearTimer();
        setIsPolling(false);
      }
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
  }, [poll]);

  // Existing /system events may bring the next poll forward.
  useEffect(() => {
    if (!subscribe) return undefined;
    return subscribe((event) => {
      if (event?.type !== 'execution_update' || terminalRef.current || !isVisible()) return;
      void poll();
    });
  }, [subscribe, poll]);

  const refetch = useCallback(() => {
    void poll();
  }, [poll]);

  const stale =
    Boolean(data?.stale) ||
    (lastSuccessAt !== null && now - lastSuccessAt > STALE_AFTER_MS) ||
    (error !== null && data !== null);

  return { data, error, stale, isPolling, lastSuccessAt, refetch };
};
