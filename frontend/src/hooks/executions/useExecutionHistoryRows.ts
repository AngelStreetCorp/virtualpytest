/**
 * Last Executions data, shared by Run Tests and the project page.
 *
 * `useExecutionHistoryRecords` reads the running / queued / completed deployment executions
 * from the executions context and returns them as normalised records (newest first, no limit).
 * `useExecutionHistoryRows(filter)` turns them into table rows, optionally narrowed to one
 * project: a row is kept when its script label is one of the project's scripts OR its target
 * is one of the project's devices.
 */
import { useMemo } from 'react';

import type { ExecutionHistoryRow } from '../../components/common/ExecutionHistoryTable';
import { useRunExecutions } from '../../contexts/RunExecutionsContext';
import {
  ExecutionRecord,
  executionRecordToHistoryRow,
  mapDeploymentExecutionToRecord,
  normalizeExecutionHistory,
} from '../../utils/executionHistoryRecords';
import { getScriptDisplayName } from '../../utils/executionUtils';
import { useTargetSelection } from '../useTargetSelection';

export interface ProjectExecutionFilter {
  /** Script / testcase / campaign names in the project. */
  scriptNames: string[];
  /** Devices in the project. */
  devices: Array<{ host_name: string; device_id: string }>;
}

export const useExecutionHistoryRecords = (): ExecutionRecord[] => {
  const { runningExecutions, queuedExecutions, completedExecutions } = useRunExecutions();
  return useMemo(() => {
    const records = [...runningExecutions, ...queuedExecutions, ...completedExecutions]
      .map((execution: unknown) => mapDeploymentExecutionToRecord(execution))
      .filter((record): record is ExecutionRecord => Boolean(record));
    // No slice here: tab/workspace filters and the final limit belong to the caller, or a burst
    // of campaign rows would push every script row out before the tab filter runs.
    return normalizeExecutionHistory(records, Infinity);
  }, [runningExecutions, queuedExecutions, completedExecutions]);
};

/** "vpt/smoke_video_stream.py" and "smoke_video_stream" name the same script. */
const scriptKey = (name: string): string =>
  (name.split('/').pop() || name).replace(/\.py$/i, '').trim().toLowerCase();

export const useExecutionHistoryRows = (filter?: ProjectExecutionFilter, limit = 200): ExecutionHistoryRow[] => {
  const records = useExecutionHistoryRecords();
  const { getDevicesFromHost } = useTargetSelection();

  const scriptKeys = useMemo(() => new Set((filter?.scriptNames ?? []).map(scriptKey)), [filter?.scriptNames]);
  const deviceKeys = useMemo(
    () => new Set((filter?.devices ?? []).map((d) => `${d.host_name}:${d.device_id}`)),
    [filter?.devices],
  );

  return useMemo(() => {
    return records
      .filter((r) => r.status !== 'aborted' && r.status !== 'skipped')
      .filter((r) => {
        if (!filter) return true;
        return scriptKeys.has(scriptKey(r.scriptName))
          || scriptKeys.has(scriptKey(getScriptDisplayName(r.scriptName)))
          || deviceKeys.has(`${r.hostName}:${r.deviceId || 'host'}`);
      })
      .slice(0, limit)
      .map((r) => {
        const device = r.deviceId ? getDevicesFromHost(r.hostName).find((d: any) => d.device_id === r.deviceId) : undefined;
        return executionRecordToHistoryRow(r, device?.device_name || undefined, getScriptDisplayName(r.scriptName));
      });
  }, [records, filter, scriptKeys, deviceKeys, limit, getDevicesFromHost]);
};
