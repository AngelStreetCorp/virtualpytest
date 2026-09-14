import { useEffect, useState, useRef } from 'react';

import { Host } from '../../types/common/Host_Types';
import { buildRunningLogUrl } from '../../utils/buildUrlUtils';
import { isRunningLogStale } from '../../utils/recUtils';

export interface StepInfo {
  step_number: number;
  command: string;
  description?: string;
  params?: Record<string, unknown>;
  status?: 'pending' | 'current' | 'completed' | 'failed';
}

export interface ActionInfo {
  command: string;
  params?: Record<string, unknown>;
  status?: 'pending' | 'current' | 'completed' | 'failed';
}

export interface VerificationInfo {
  command: string;
  verification_type: string;
  params?: Record<string, unknown>;
  status?: 'pending' | 'current' | 'completed' | 'failed';
}

export interface RunningLogData {
  completed_steps?: Array<
    StepInfo & {
      actions?: ActionInfo[];
      verifications?: VerificationInfo[];
    }
  >;
  previous_step?: StepInfo & {
    actions?: ActionInfo[];
    verifications?: VerificationInfo[];
  };
  current_step?: StepInfo & {
    actions?: ActionInfo[];
    verifications?: VerificationInfo[];
    current_action_index?: number;
    current_verification_index?: number;
  };
  next_step?: StepInfo;
  start_time: string;
  estimated_end?: string;
  script_name: string;
  total_steps: number;
  current_step_number: number;
}

const MAX_RUNNING_LOG_FAILURES = 3;
const POLL_INTERVAL_MS = 2000;

/**
 * Centralized polling for running.log. Single source of truth for script execution state.
 * Returns full log data and derived script name.
 */
export const useRunningLog = (
  host: Host,
  deviceId: string | undefined,
  enabled = true
): { logData: RunningLogData | null; scriptName: string | null } => {
  const [logData, setLogData] = useState<RunningLogData | null>(null);
  const failureCountRef = useRef(0);

  useEffect(() => {
    if (!enabled || !deviceId) {
      failureCountRef.current = 0;
      setLogData(null);
      return;
    }

    let isCancelled = false;
    let intervalId: NodeJS.Timeout | null = null;

    const fetchLog = async () => {
      if (failureCountRef.current >= MAX_RUNNING_LOG_FAILURES) {
        return;
      }
      if (document.visibilityState === 'hidden') {
        return;
      }

      try {
        const url = `${buildRunningLogUrl(host, deviceId)}?t=${Date.now()}`;
        const response = await fetch(url);

        if (response.ok) {
          const data = await response.json();
          if (!isCancelled) {
            // Ignore stale logs left over from a finished/dead run (e.g. a deployment
            // whose execution row never flipped out of 'running'). Treat as no data so
            // the overlay never shows a days-old "finishing..." run.
            setLogData(isRunningLogStale(data?.start_time) ? null : data);
            failureCountRef.current = 0;
          }
          return;
        }

        failureCountRef.current += 1;
        if (!isCancelled) {
          setLogData(null);
        }

        if (failureCountRef.current >= MAX_RUNNING_LOG_FAILURES && intervalId) {
          clearInterval(intervalId);
          intervalId = null;
        }
      } catch {
        failureCountRef.current += 1;
        if (!isCancelled) {
          setLogData(null);
        }

        if (failureCountRef.current >= MAX_RUNNING_LOG_FAILURES && intervalId) {
          clearInterval(intervalId);
          intervalId = null;
        }
      }
    };

    fetchLog();
    intervalId = setInterval(fetchLog, POLL_INTERVAL_MS);

    return () => {
      isCancelled = true;
      if (intervalId) {
        clearInterval(intervalId);
      }
    };
  }, [host, deviceId, enabled]);

  const scriptName =
    logData && typeof logData.script_name === 'string' ? logData.script_name : null;

  return { logData, scriptName };
};
