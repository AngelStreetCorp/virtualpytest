import { ExecutionHistoryRow, ExecutionHistoryScriptRow } from '../components/common/ExecutionHistoryTable';
import { CampaignScript, DeploymentExecution } from '../hooks/useDeployment';
import { formatToLocalTimeShort } from './dateUtils';
import { getLogsUrl, getScriptDisplayName } from './executionUtils';

export interface CampaignScriptLike {
  id?: string;
  script_name: string;
  success: boolean;
  execution_order?: number;
  execution_time_ms?: number;
  html_report_r2_url?: string;
  logs_r2_url?: string;
  report_url?: string;
  logs_url?: string;
}

/** Uses server-provided `is_campaign` flag; falls back to `campaign_id` for queued/running rows not yet flattened. */
export const isCampaignDeployment = (campaignId?: string | null, _scriptName?: string, isCampaign?: boolean) =>
  isCampaign ?? Boolean(campaignId);

/** Strip trailing _<timestamp> suffix (e.g. "TP_001 sanity_1774851549400" → "TP_001 sanity") */
export const stripTimestampSuffix = (name: string): string => name.replace(/_\d{10,}$/, '');

export const getCampaignDisplayName = (scriptName?: string, name?: string): string => {
  if (scriptName?.startsWith('campaign:')) {
    const afterPrefix = scriptName.slice('campaign:'.length);
    const pipeIdx = afterPrefix.indexOf('|');
    if (pipeIdx !== -1) return stripTimestampSuffix(afterPrefix.slice(pipeIdx + 1));
    return stripTimestampSuffix(afterPrefix);
  }
  // File campaigns: convert path like "test_campaign/run_gw_web_campaign" to "Run Gw Web Campaign"
  if (scriptName?.startsWith('test_campaign/')) {
    const basename = scriptName.split('/').pop()?.replace(/\.py$/, '') || '';
    return basename.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  }
  return stripTimestampSuffix(name || scriptName || '-');
};

export const mapCampaignScriptsToHistoryRows = (
  scripts: Array<CampaignScriptLike | CampaignScript> | undefined,
): ExecutionHistoryScriptRow[] => (
  (scripts || []).map((script, index) => ({
    id: script.id || `${script.script_name}-${index}`,
    scriptName: script.script_name,
    success: script.success,
    durationLabel: script.execution_time_ms != null ? `${(script.execution_time_ms / 1000).toFixed(1)}s` : '-',
    reportUrl: script.html_report_r2_url || ('report_url' in script ? script.report_url : undefined) || undefined,
    logsUrl:
      script.logs_r2_url ||
      ('logs_url' in script ? script.logs_url : undefined) ||
      (script.html_report_r2_url ? getLogsUrl(script.html_report_r2_url) : undefined) ||
      ('report_url' in script && script.report_url ? getLogsUrl(script.report_url) : undefined) ||
      undefined,
  }))
);

export const mapDeploymentExecutionToHistoryRow = (
  execution: DeploymentExecution,
  getTargetLabel: (hostName?: string, deviceId?: string) => string,
): ExecutionHistoryRow => {
  const isCampaign = isCampaignDeployment(execution.deployments?.campaign_id, execution.deployments?.script_name, execution.is_campaign);
  const campaignSuccess = execution.campaign_success ?? execution.success;

  return {
    id: execution.id,
    targetLabel: getTargetLabel(execution.deployments?.host_name, execution.deployments?.device_id),
    scriptLabel: isCampaign
      ? getCampaignDisplayName(execution.deployments?.script_name, execution.campaign_name || execution.deployments?.name)
      : getScriptDisplayName(execution.deployments?.script_name || execution.deployments?.name || '-'),
    startedLabel: execution.started_at ? formatToLocalTimeShort(execution.started_at) : '-',
    completedLabel: execution.completed_at ? formatToLocalTimeShort(execution.completed_at) : '-',
    status: (execution.status || 'completed') as ExecutionHistoryRow['status'],
    resultSuccess: campaignSuccess ?? null,
    reportUrl: execution.report_url || undefined,
    logsUrl: execution.logs_url || (execution.report_url ? getLogsUrl(execution.report_url) : undefined),
    campaignScripts: mapCampaignScriptsToHistoryRows(execution.campaign_scripts),
    hideTopLevelLogs: isCampaign,
  };
};
