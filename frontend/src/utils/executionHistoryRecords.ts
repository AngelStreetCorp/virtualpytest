/**
 * Execution history records, shared by Run Tests (Last Executions) and the project page.
 * Pure helpers: map a deployment_execution row to a record, merge/sort records, and turn
 * a record into a table row. No React state in here.
 */
import type { RerunPayload } from '../types/common/Rerun_Types';
import type { ExecutionHistoryRow } from '../components/common/ExecutionHistoryTable';
import { formatExecutionHistoryTimestamp, formatToLocalTimeShort } from './dateUtils';
import { getLogsUrl } from './executionUtils';
import { CampaignScriptLike, mapCampaignScriptsToHistoryRows } from './executionHistoryUtils';

export const RUN_TESTS_HISTORY_LIMIT = 20;

export const getExecutionDeviceId = (deviceId?: string): string => (deviceId && deviceId.trim() ? deviceId : 'host');

export const buildTargetKey = (hostName: string, deviceId?: string): string =>
  `${hostName}:${getExecutionDeviceId(deviceId)}`;

/**
 * The running executions the operator can act on: the ones this browser session
 * started, plus the ones the server still reports as running.
 *
 * The page keeps the two lists apart on purpose — `activeExecutions` is what
 * THIS browser started, the history is what the server knows — but the Last
 * Executions table merges them, so the Run page's Abort button has to read the
 * same merged view. After a reload the local list is empty while the table
 * still shows a run going, and a button that reads only the local list is
 * greyed out exactly when the operator is looking at a run they cannot stop
 * (QA-OPS-20).
 *
 * A target is listed once: a run this session started also has a server row,
 * and aborting it twice would be two requests for one run. Campaign runs are
 * left out — their abort needs an execution_id and its own endpoint, and they
 * keep the row-level stop button in the table.
 *
 * Note on scope: the abort endpoint addresses a TARGET (host_name +
 * device_id), not a single execution, so aborting a target stops whatever is
 * running on it — including a run another operator started on the same
 * target. That is the API's semantics and it was already true before this
 * helper existed; the helper only decides WHICH targets the button offers
 * to stop, so the button now offers the same targets the table shows as
 * running.
 */
export const collectAbortableRunningExecutions = (
  localExecutions: ExecutionRecord[],
  historyExecutions: ExecutionRecord[],
): ExecutionRecord[] => {
  const isAbortable = (exec: ExecutionRecord) =>
    exec.status === 'running' && exec.executionType !== 'campaign';

  const local = localExecutions.filter(isAbortable);
  const seen = new Set(local.map((exec) => buildTargetKey(exec.hostName, exec.deviceId)));
  const fromServer = historyExecutions.filter(
    (exec) => isAbortable(exec) && !seen.has(buildTargetKey(exec.hostName, exec.deviceId)),
  );
  return [...local, ...fromServer];
};

export const formatTargetLabel = (hostName: string, deviceId?: string, deviceDisplayName?: string): string => {
  const normalizedDeviceId = getExecutionDeviceId(deviceId);
  if (normalizedDeviceId === 'host') return hostName;
  // Device first, host after, so the same device_name on two hosts stays distinguishable.
  return `${deviceDisplayName || normalizedDeviceId}:${hostName}`;
};

// Simple execution record interface
export interface ExecutionRecord {
  id: string;
  executionType: 'script' | 'testcase' | 'campaign';
  scriptName: string;
  hostName: string;
  deviceId?: string;
  deploymentId?: string;
  deploymentExecutionId?: string;
  backendTaskId?: string;
  deviceModel?: string; // Add device model field
  startedAtRaw?: string;
  completedAtRaw?: string;
  startTime: string;
  endTime?: string;
  status: 'running' | 'completed' | 'failed' | 'aborted' | 'queued' | 'skipped';
  testResult?: 'success' | 'failure'; // New field for actual test outcome
  parameters?: string;
  reportUrl?: string;
  logsUrl?: string; // Add logs URL field
  campaignSuccess?: boolean;
  campaignScripts?: CampaignScriptLike[];
  // Launch-time config so the row's rerun icon can relaunch without
  // refetching anything (see RerunPayload above).
  rerunPayload?: RerunPayload;
}

const parseExecutionDisplayTimestamp = (value?: string): number => {
  if (!value) return 0;
  const parsed = new Date(value).getTime();
  return Number.isNaN(parsed) ? 0 : parsed;
};

const applyExecutionTimestamps = (record: ExecutionRecord): ExecutionRecord => {
  const next = { ...record };

  if (next.startedAtRaw) {
    next.startTime = formatToLocalTimeShort(next.startedAtRaw);
  } else if (next.startTime) {
    next.startedAtRaw = next.startTime;
  }

  if (next.completedAtRaw) {
    next.endTime = formatToLocalTimeShort(next.completedAtRaw);
  } else if (next.endTime) {
    next.completedAtRaw = next.endTime;
  }

  return next;
};

const getExecutionRecordScore = (record: ExecutionRecord): number => {
  let score = 0;

  if (record.id?.length === 36) score += 4;
  if (record.deploymentExecutionId) score += 4;
  if (record.deploymentId) score += 2;
  if (record.backendTaskId) score += 2;
  if (record.endTime) score += 2;
  if (record.reportUrl) score += 1;
  if (record.logsUrl) score += 1;
  if (record.testResult) score += 1;
  if (record.status === 'completed' || record.status === 'failed' || record.status === 'aborted' || record.status === 'skipped') {
    score += 3;
  } else if (record.status === 'running') {
    score += 1;
  }

  return score;
};

const pickPreferredExecutionRecord = (left: ExecutionRecord, right: ExecutionRecord): ExecutionRecord => {
  const leftScore = getExecutionRecordScore(left);
  const rightScore = getExecutionRecordScore(right);

  if (rightScore > leftScore) {
      return {
        ...right,
      backendTaskId: right.backendTaskId || left.backendTaskId,
      startedAtRaw: right.startedAtRaw || left.startedAtRaw,
      completedAtRaw: right.completedAtRaw || left.completedAtRaw,
      endTime: right.endTime || left.endTime,
      reportUrl: right.reportUrl || left.reportUrl,
      logsUrl: right.logsUrl || left.logsUrl,
        testResult: right.testResult || left.testResult,
        parameters: right.parameters || left.parameters,
        deviceModel: right.deviceModel || left.deviceModel,
        campaignSuccess: right.campaignSuccess ?? left.campaignSuccess,
        campaignScripts: (right.campaignScripts && right.campaignScripts.length > 0) ? right.campaignScripts : left.campaignScripts,
      };
  }

  return {
    ...left,
    backendTaskId: left.backendTaskId || right.backendTaskId,
    startedAtRaw: left.startedAtRaw || right.startedAtRaw,
    completedAtRaw: left.completedAtRaw || right.completedAtRaw,
    endTime: left.endTime || right.endTime,
    reportUrl: left.reportUrl || right.reportUrl,
    logsUrl: left.logsUrl || right.logsUrl,
    testResult: left.testResult || right.testResult,
    parameters: left.parameters || right.parameters,
    deviceModel: left.deviceModel || right.deviceModel,
    campaignSuccess: left.campaignSuccess ?? right.campaignSuccess,
    campaignScripts: (left.campaignScripts && left.campaignScripts.length > 0) ? left.campaignScripts : right.campaignScripts,
  };
};

export const normalizeExecutionHistory = (
  records: ExecutionRecord[],
  limit: number = RUN_TESTS_HISTORY_LIMIT,
): ExecutionRecord[] => {
  const byId = new Map<string, ExecutionRecord>();

  records.forEach((record) => {
    if (!record?.id) {
      return;
    }

    const hydratedRecord = applyExecutionTimestamps(record);

    const current = byId.get(hydratedRecord.id);
    byId.set(
      hydratedRecord.id,
      current ? pickPreferredExecutionRecord(current, hydratedRecord) : hydratedRecord,
    );
  });

  return Array.from(byId.values())
    .sort((left, right) => {
      const timeDiff =
        parseExecutionDisplayTimestamp(right.completedAtRaw || right.endTime || right.startedAtRaw || right.startTime) -
        parseExecutionDisplayTimestamp(left.completedAtRaw || left.endTime || left.startedAtRaw || left.startTime);
      if (timeDiff !== 0) return timeDiff;

      const targetDiff = `${left.hostName}:${left.deviceId || 'host'}`
        .localeCompare(`${right.hostName}:${right.deviceId || 'host'}`);
      if (targetDiff !== 0) return targetDiff;

      const scriptDiff = left.scriptName.localeCompare(right.scriptName);
      if (scriptDiff !== 0) return scriptDiff;

      return left.id.localeCompare(right.id);
    })
    .slice(0, limit);
};

export const mapDeploymentExecutionToRecord = (execution: any): ExecutionRecord | null => {
  const deployment = execution?.deployments;
  const deploymentExecutionId = execution?.id;
  const deploymentId = execution?.deployment_id || deployment?.id;
  const startedAt = execution?.started_at || execution?.scheduled_at;
  const rawStatus = String(execution?.status || '').toLowerCase();
  const status = rawStatus === 'running' || rawStatus === 'completed' || rawStatus === 'failed' || rawStatus === 'aborted' || rawStatus === 'queued' || rawStatus === 'skipped'
    ? rawStatus as ExecutionRecord['status']
    : 'queued';

  if (!deploymentId || !deployment?.host_name || !startedAt) {
    return null;
  }

  const isFileCampaign = !deployment?.campaign_id && (deployment?.script_name || '').toLowerCase().includes('campaign');
  const executionType: ExecutionRecord['executionType'] = (deployment?.campaign_id || isFileCampaign) ? 'campaign' : 'script';
  const reportUrl = execution?.report_url || execution?.reportUrl;
  const rawLogsUrl = execution?.logs_url || execution?.logsUrl;

  // Hoist the launch-time rerun config from the deployment row (written by
  // create_adhoc_execution and the /server/deployment/create route). For
  // script-type rows that predate this column, synthesize one from the
  // existing fields so older entries are still rerunnable.
  let rerunPayload: RerunPayload | undefined;
  if (deployment?.rerun_payload && typeof deployment.rerun_payload === 'object') {
    rerunPayload = deployment.rerun_payload as RerunPayload;
  } else if (executionType === 'script') {
    rerunPayload = {
      type: 'script',
      scriptName: deployment.script_name || '',
      hostName: deployment.host_name,
      deviceId: deployment.device_id || 'host',
      parameters: deployment.parameters || '',
    };
  }

  return {
    id: deploymentExecutionId || deploymentId,
    executionType,
    scriptName: (executionType === 'campaign' ? execution?.campaign_name : null) || deployment?.script_name || deployment?.name || 'Deployment',
    hostName: deployment.host_name,
    deviceId: deployment.device_id || 'host',
    deploymentId,
    deploymentExecutionId: deploymentExecutionId || undefined,
    startedAtRaw: startedAt,
    completedAtRaw: execution?.completed_at || undefined,
    startTime: formatToLocalTimeShort(startedAt),
    endTime: execution?.completed_at ? formatToLocalTimeShort(execution.completed_at) : undefined,
    status,
    testResult: status === 'completed'
      ? (execution?.success ? 'success' : 'failure')
      : status === 'failed'
        ? 'failure'
        : undefined,
    reportUrl: reportUrl || undefined,
    logsUrl: rawLogsUrl ? getLogsUrl(rawLogsUrl) : reportUrl ? getLogsUrl(reportUrl) : undefined,
    campaignSuccess: execution?.campaign_success,
    campaignScripts: Array.isArray(execution?.campaign_scripts) ? execution.campaign_scripts : undefined,
    rerunPayload,
  };
};

/** One table row for a record. `deviceDisplayName` and `scriptLabel` come from the caller's lookups. */
export const executionRecordToHistoryRow = (
  execution: ExecutionRecord,
  deviceDisplayName: string | undefined,
  scriptLabel: string,
): ExecutionHistoryRow => {
  // Parameters this script/device ran with: local rows carry them on the record, DB rows on
  // the rerunPayload. Drop --host/--device (the Target column shows them) and put one flag
  // per line so the hover tooltip stays readable.
  const rawParams = execution.parameters
    || (execution.rerunPayload?.type === 'script' ? execution.rerunPayload.parameters : '');
  const trimmedParams = rawParams
    ? rawParams.replace(/(^|\s)--(host|device)\s+\S+/g, '').trim()
    : '';
  const parametersLabel = trimmedParams
    ? trimmedParams.replace(/\s+--/g, '\n--')
    : undefined;

  return {
    id: execution.id,
    targetLabel: formatTargetLabel(execution.hostName, execution.deviceId, deviceDisplayName),
    scriptLabel,
    parametersLabel,
    startedLabel: formatExecutionHistoryTimestamp(execution.startedAtRaw || execution.startTime),
    completedLabel: formatExecutionHistoryTimestamp(execution.completedAtRaw || execution.endTime),
    status: execution.status,
    resultSuccess: execution.executionType === 'campaign'
      ? (execution.campaignSuccess ?? (execution.testResult === 'success' ? true : execution.testResult === 'failure' ? false : null))
      : (execution.testResult === 'success' ? true : execution.testResult === 'failure' ? false : null),
    reportUrl: execution.reportUrl,
    logsUrl: execution.logsUrl,
    campaignScripts: mapCampaignScriptsToHistoryRows(execution.campaignScripts),
    hideTopLevelLogs: execution.executionType === 'campaign',
    // Rerun only on finished rows: a rerun while the original runs just races it.
    rerunPayload: (execution.status === 'completed' || execution.status === 'failed')
      ? execution.rerunPayload
      : undefined,
    liveKey: execution.status === 'running' && execution.executionType === 'script'
      ? buildTargetKey(execution.hostName, execution.deviceId)
      : undefined,
    startedAtMs: execution.startedAtRaw ? Date.parse(execution.startedAtRaw) || undefined : undefined,
    completedAtMs: execution.completedAtRaw ? Date.parse(execution.completedAtRaw) || undefined : undefined,
    abortPayload: execution.status === 'running'
      ? { hostName: execution.hostName, deviceId: execution.deviceId, executionType: execution.executionType }
      : undefined,
  };
};
