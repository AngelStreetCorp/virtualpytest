/**
 * Shared one-click rerun.
 *
 * Replays a `RerunPayload` on its original target, dispatching by payload type
 * to the same executor the original launch used. Used by any page that lists
 * past executions — RunTests keeps its own launch path because it also has to
 * insert an optimistic row into its local table, while pages that read results
 * straight from the DB (TestReports) only need the run to start and the next
 * refresh to pick it up.
 *
 * Rerun is run-now only: a locked device surfaces an error instead of silently
 * rerouting through the deployment scheduler, so the user is never left waiting
 * on a queue entry they didn't ask for.
 */
import { useCallback, useState } from 'react';

import { useCampaign } from '../pages/useCampaign';
import { useScript } from './useScript';
import { useTestCaseExecution } from '../testcase/useTestCaseExecution';
import { useTestCaseSave } from '../testcase/useTestCaseSave';
import { stampInputValues } from '../../utils/testcase/scriptInputUtils';
import type { RerunPayload } from '../../types/common/Rerun_Types';

export interface RerunOutcome {
  started: boolean;
  error?: string;
}

export const useRerun = () => {
  const { executeMultipleScripts } = useScript();
  const { executeTestCase } = useTestCaseExecution();
  const { getTestCase } = useTestCaseSave();
  const { executeCampaign } = useCampaign();

  // Payload ids currently in flight, so a caller can disable the icon it
  // clicked without blocking reruns on other rows.
  const [rerunningIds, setRerunningIds] = useState<string[]>([]);

  const runScript = useCallback(async (payload: Extract<RerunPayload, { type: 'script' }>): Promise<RerunOutcome> => {
    const results = await executeMultipleScripts([
      {
        id: `rerun_${Date.now()}_${payload.hostName}_${payload.deviceId}`,
        scriptName: payload.scriptName,
        hostName: payload.hostName,
        deviceId: payload.deviceId,
        parameters: payload.parameters,
        forceUnlock: false,
        // Run-now only — ask the server for the 423 rather than a queue entry.
        queueIfLocked: false,
        // The payload replays an already-resolved row, so there's no selection
        // to read a per-script env from; 'prod' is just the capacity tag.
        environment: 'prod',
        virtualScriptId: payload.virtualScriptId,
      },
    ]);

    const result = Object.values(results)[0] as any;
    if (result?.errorType === 'device_locked') {
      return { started: false, error: `${payload.hostName}:${payload.deviceId} is locked` };
    }
    return { started: true };
  }, [executeMultipleScripts]);

  const runTestcase = useCallback(async (payload: Extract<RerunPayload, { type: 'testcase' }>): Promise<RerunOutcome> => {
    let graph = payload.executionGraph;

    // No embedded graph — the payload came from a stored result, which only
    // carries the testcase id. Fetch the graph now.
    if (!graph) {
      if (!payload.testcaseId) {
        return { started: false, error: 'This testcase run has no saved definition to replay' };
      }
      const response = await getTestCase(payload.testcaseId);
      if (!response.success || !response.testcase?.graph_json) {
        return { started: false, error: response.error || 'Failed to load the testcase definition' };
      }
      graph = response.testcase.graph_json;
    }

    // Protected inputs are resolved per device at run time, exactly as the
    // original launch did; user-supplied values replay verbatim.
    const runValues: Record<string, any> = { ...(payload.inputValues || {}) };
    runValues['device_model_name'] = payload.deviceModel || 'unknown';
    runValues['host_name'] = payload.hostName;
    runValues['device_name'] = payload.deviceId;

    const result = await executeTestCase(
      stampInputValues(graph, runValues),
      payload.deviceId,
      payload.hostName,
      undefined,
      payload.scriptName,
      payload.testcaseVersionNumber
        ? { testcase_id: payload.testcaseId, testcase_version: payload.testcaseVersionNumber }
        : { testcase_id: payload.testcaseId },
    );

    return result.success ? { started: true } : { started: false, error: result.error };
  }, [executeTestCase, getTestCase]);

  const runCampaign = useCallback(async (payload: Extract<RerunPayload, { type: 'campaign' }>): Promise<RerunOutcome> => {
    const result = await executeCampaign(payload.campaignConfig);
    return result?.success === false
      ? { started: false, error: (result as any).error }
      : { started: true };
  }, [executeCampaign]);

  /**
   * Replay `payload`. `trackingId` (the source row's id) marks the row as busy
   * for the duration so the caller can disable just that icon.
   */
  const rerun = useCallback(async (payload: RerunPayload, trackingId?: string): Promise<RerunOutcome> => {
    if (trackingId) setRerunningIds((prev) => [...prev, trackingId]);
    try {
      if (payload.type === 'script') return await runScript(payload);
      if (payload.type === 'testcase') return await runTestcase(payload);
      return await runCampaign(payload);
    } catch (error) {
      return { started: false, error: error instanceof Error ? error.message : String(error) };
    } finally {
      if (trackingId) setRerunningIds((prev) => prev.filter((id) => id !== trackingId));
    }
  }, [runScript, runTestcase, runCampaign]);

  return { rerun, rerunningIds };
};
