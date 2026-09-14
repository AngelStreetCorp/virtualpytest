import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { io, Socket } from 'socket.io-client';

import { DeploymentExecution, useDeployment } from '../hooks/useDeployment';
import { useWorkspaceContext } from './workspace/WorkspaceContext';

type SystemUpdateHandler = (event: any) => void;

interface RunExecutionsContextValue {
  runningExecutions: DeploymentExecution[];
  queuedExecutions: DeploymentExecution[];
  completedExecutions: DeploymentExecution[];
  refresh: () => Promise<void>;
  subscribeSystemUpdate: (handler: SystemUpdateHandler) => () => void;
}

const RunExecutionsContext = createContext<RunExecutionsContextValue | null>(null);

export const useRunExecutions = (): RunExecutionsContextValue => {
  const ctx = useContext(RunExecutionsContext);
  if (!ctx) {
    throw new Error('useRunExecutions must be used within RunExecutionsProvider');
  }
  return ctx;
};

const dedupe = (executions: DeploymentExecution[]): DeploymentExecution[] => {
  const seen = new Set<string>();
  return executions.filter((execution) => {
    if (seen.has(execution.id)) return false;
    seen.add(execution.id);
    return true;
  });
};

// /system socket events arrive in bursts (deployment_changed, lock_changed,
// deployment_execution_changed, execution_update). Each /executions/recent
// fetch is ~300ms after parallelization, so we still coalesce socket-driven
// reloads to one fetch per RELOAD_DEBOUNCE_MS.
const RELOAD_DEBOUNCE_MS = 3000;
const BACKSTOP_RELOAD_MS = 120000;

export const RunExecutionsProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { getRecentExecutions } = useDeployment();
  const { activeWorkspace } = useWorkspaceContext();
  const [runningExecutions, setRunningExecutions] = useState<DeploymentExecution[]>([]);
  const [queuedExecutions, setQueuedExecutions] = useState<DeploymentExecution[]>([]);
  const [completedExecutions, setCompletedExecutions] = useState<DeploymentExecution[]>([]);

  // Active workspace scope, read live inside refresh() via a ref so switching
  // workspaces doesn't recreate refresh() (which would tear down the socket).
  const scopeRef = useRef<{ deviceFilter?: string[]; scriptFilter?: string[] }>({});
  scopeRef.current = {
    deviceFilter: activeWorkspace?.device_filter,
    scriptFilter: activeWorkspace?.script_filter,
  };

  const inflightRef = useRef<Promise<void> | null>(null);
  // When refresh() is called while another fetch is mid-flight, mark a
  // pending follow-up. Otherwise we'd swallow the state change that arrived
  // *after* the in-flight fetch's data was captured — e.g. report_url being
  // written between the GET going out and the response coming back, leaving
  // the row stuck at "FAILURE / No Report" until the user manually reloads.
  const pendingRefreshRef = useRef(false);
  const reloadTimerRef = useRef<number | null>(null);
  const socketRef = useRef<Socket | null>(null);
  const subscribersRef = useRef<Set<SystemUpdateHandler>>(new Set());

  const refresh = useCallback(async (): Promise<void> => {
    if (inflightRef.current) {
      pendingRefreshRef.current = true;
      return inflightRef.current;
    }
    const promise = (async () => {
      try {
        do {
          pendingRefreshRef.current = false;
          const response = await getRecentExecutions(scopeRef.current);
          if (response?.success) {
            setRunningExecutions(dedupe(response.running_executions || []));
            setQueuedExecutions(dedupe(response.queued_executions || []));
            setCompletedExecutions(dedupe(response.completed_executions || []));
          }
        } while (pendingRefreshRef.current);
      } catch (err) {
        console.warn('[@RunExecutionsContext] refresh failed', err);
      } finally {
        inflightRef.current = null;
      }
    })();
    inflightRef.current = promise;
    return promise;
  }, [getRecentExecutions]);

  const scheduleReload = useCallback(() => {
    if (reloadTimerRef.current !== null) {
      window.clearTimeout(reloadTimerRef.current);
    }
    reloadTimerRef.current = window.setTimeout(() => {
      reloadTimerRef.current = null;
      void refresh();
    }, RELOAD_DEBOUNCE_MS);
  }, [refresh]);

  const subscribeSystemUpdate = useCallback((handler: SystemUpdateHandler) => {
    subscribersRef.current.add(handler);
    return () => {
      subscribersRef.current.delete(handler);
    };
  }, []);

  // Initial fetch on mount, and refetch whenever the active workspace changes
  // so the server-side scope (device/script filter) is reapplied for the new
  // workspace instead of showing the previous workspace's cached rows.
  useEffect(() => {
    void refresh();
  }, [refresh, activeWorkspace?.id]);

  // Backstop poll in case a /system socket event is missed (tab woken from
  // freeze, server restart, transient disconnect).
  useEffect(() => {
    const id = window.setInterval(() => {
      void refresh();
    }, BACKSTOP_RELOAD_MS);
    return () => window.clearInterval(id);
  }, [refresh]);

  // Single /system socket shared by RunTests + MonitorTests.
  useEffect(() => {
    if (socketRef.current) return;

    const socket: Socket = io(`${window.location.origin}/system`, {
      transports: ['websocket'],
      reconnection: true,
    });
    socketRef.current = socket;

    socket.on('system_update', (event: any) => {
      // Terminal-status deployment events carry the just-written report/log
      // URLs — refresh immediately so RunTests' "Last Executions" row doesn't
      // stay stuck on FAILURE / No Report until a manual page reload. The
      // in-flight-follow-up loop in refresh() makes back-to-back fires safe.
      const status = event?.status;
      const isTerminalDeployment = event?.domain === 'deployment' && (
        status === 'completed' || status === 'failed' ||
        status === 'aborted' || status === 'skipped'
      );
      if (isTerminalDeployment) {
        void refresh();
      } else if (event?.domain === 'deployment' || event?.type === 'lock_changed') {
        scheduleReload();
      }
      // Fan out to local subscribers (e.g., RunTests' lock-tooltip refresh).
      subscribersRef.current.forEach((handler) => {
        try {
          handler(event);
        } catch (err) {
          console.warn('[@RunExecutionsContext] subscriber error', err);
        }
      });
    });

    return () => {
      socket.disconnect();
      socketRef.current = null;
      if (reloadTimerRef.current !== null) {
        window.clearTimeout(reloadTimerRef.current);
        reloadTimerRef.current = null;
      }
    };
  }, [refresh, scheduleReload]);

  const value = useMemo<RunExecutionsContextValue>(() => ({
    runningExecutions,
    queuedExecutions,
    completedExecutions,
    refresh,
    subscribeSystemUpdate,
  }), [runningExecutions, queuedExecutions, completedExecutions, refresh, subscribeSystemUpdate]);

  return (
    <RunExecutionsContext.Provider value={value}>
      {children}
    </RunExecutionsContext.Provider>
  );
};
