import { Terminal as ScriptIcon, ExpandMore as ExpandMoreIcon, ExpandLess as ExpandLessIcon, DeleteOutline as DeleteOutlineIcon, ChevronRight as ChevronRightIcon, Lock as LockIcon, ContentCopy as ContentCopyIcon } from '@mui/icons-material';
import {
  Box,
  Typography,
  Card,
  CardContent,
  Button,
  Grid,
  Chip,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  IconButton,
  Collapse,
  TextField,
  Stack,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Popover,
  Tooltip,
} from '@mui/material';
import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useLocation, useSearchParams } from 'react-router-dom';
import { useResponsiveMode } from '../hooks/useResponsiveMode';
import { UnifiedExecutableSelector, ExecutableItem } from '../components/common/UnifiedExecutableSelector';
import { DeviceInfoModal, DeviceInfoMap } from '../components/run/DeviceInfoModal';
import { ExecutableTypeToggle } from '../components/common/ExecutableTypeToggle';
import { CompactVersionSelector, CompactVersionOption } from '../components/common/CompactVersionSelector';
import { TargetPanel } from '../components/common/TargetPanel';
import { useTargetSelection } from '../hooks/useTargetSelection';
import { useWorkspaceContext } from '../contexts/workspace/WorkspaceContext';

import { useScript } from '../hooks/script/useScript';
import { useToast } from '../hooks/useToast';
import { useRun } from '../hooks/useRun';
import { useDeployment } from '../hooks/useDeployment';
import { useRunExecutions } from '../contexts/RunExecutionsContext';
import { isDeploymentsEnabled, isRunVersionSelectorEnabled } from '../config/featureFlags';
import { useResizableColumns } from '../hooks/useResizableColumns';
import { getScriptDisplayName, getLogsUrl, ensureScriptIdentityMap } from '../utils/executionUtils';
import { useTestCaseExecution } from '../hooks/testcase/useTestCaseExecution';
import { useTestCaseSave } from '../hooks/testcase/useTestCaseSave';
import { useCampaign } from '../hooks/pages/useCampaign';

import { DeviceStreamGrid } from '../components/common/DeviceStreaming/DeviceStreamGrid';
import { ScriptParameterRow } from '../components/common/ParameterInput/ScriptParameterRow';



import { buildServerUrl } from '../utils/buildUrlUtils';
import { api } from '../utils/apiClient';
import { getCampaignBadge } from '../config/constants';
import { getCachedCampaignExecutableList, getCachedExecutableList } from '../utils/executionListCache';
import { openR2Url } from '../utils/infrastructure/cloudflareUtils';
import {
  isTargetKeyCompatibleWithRules,
  isHostCompatibleWithRules,
  isDeviceCompatibleWithRules,
  normalizeTargetRules,
  TargetRules,
} from '../utils/targetCompatibility';
import { CampaignConfig, ScriptConfiguration } from '../types/pages/Campaign_Types';
import type { RerunPayload } from '../types/pages/RunTests_Types';
import { RunWithInputsDialog } from '../components/testcase/RunWithInputsDialog';
import { stampInputValues } from '../utils/testcase/scriptInputUtils';
import { validateCronExpression } from '../utils/cronUtils';
import { formatToLocalTimeShort } from '../utils/dateUtils';
import { CronHelper } from '../components/common/CronHelper';
import { ExecutionHistoryRow } from '../components/common/ExecutionHistoryTable';
import ExecutionHistorySection from '../components/common/ExecutionHistorySection';
import { CampaignScriptLike, mapCampaignScriptsToHistoryRows } from '../utils/executionHistoryUtils';

const RUN_VERSION_SELECTOR_ENABLED = isRunVersionSelectorEnabled();

// Simple execution record interface
interface ExecutionRecord {
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

const normalizeExecutionHistory = (
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

type SelectedExecutableInstance = ExecutableItem & { instanceId: string };

const newInstanceId = (): string => (
  typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `inst_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`
);

interface CampaignExecutableItem {
  id: string;
  source: 'db' | 'file';
  campaign_id?: string;
  name: string;
  description?: string;
  script_name?: string;
  userinterface_name?: string;
  compatibility_rules?: TargetRules[];
  contained_scripts?: Array<{
    script_name: string;
    script_type?: string;
    description?: string;
  }>;
}

interface VersionSnapshotRecord {
  version_number: number;
  snapshot_timestamp?: string | null;
  graph_json?: any;
  campaign_data?: Partial<CampaignConfig> & {
    campaign_name?: string;
    script_configurations?: CampaignConfig['script_configurations'];
  };
}

interface ScriptParameter {
  name: string;
  type: 'positional' | 'optional';
  required: boolean;
  help: string;
  default?: string;
  choices?: string[];
  dataType?: string;
  description?: string;
}

interface ScriptAnalysis {
  success: boolean;
  parameters: ScriptParameter[];
  script_name: string;
  has_parameters: boolean;
  error?: string;
  has_userinterface_param?: boolean;
  userinterface_param?: string;
}

const RUN_TESTS_STATE_KEY = 'run_tests_ui_state_v1';
const RUN_TESTS_PARAMETER_CACHE_KEY = 'run_tests_parameter_cache_v1';
const RUN_TESTS_HISTORY_LIMIT = 20;
const ENVIRONMENT_LABELS: Record<'dev' | 'test' | 'prod', string> = { dev: 'Dev', test: 'Test', prod: 'Prod' };

const normalizeLoadedCampaign = (campaign: any): Omit<CampaignConfig, 'host' | 'device'> => ({
  campaign_id: campaign?.campaign_id || '',
  name: campaign?.name || campaign?.campaign_name || campaign?.campaign_id || 'Campaign',
  description: campaign?.description || '',
  userinterface_name: campaign?.userinterface_name || '',
  callback_url: campaign?.callback_url || '',
  callback_on_script_complete: campaign?.callback_on_script_complete ?? false,
  callback_on_campaign_complete: campaign?.callback_on_campaign_complete ?? true,
  execution_config: {
    continue_on_failure: campaign?.execution_config?.continue_on_failure ?? true,
    timeout_minutes: campaign?.execution_config?.timeout_minutes ?? 120,
    parallel: campaign?.execution_config?.parallel ?? false,
  },
  script_configurations: Array.isArray(campaign?.script_configurations)
    ? campaign.script_configurations
    : [],
});




const RunTests: React.FC = () => {
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const { isMobile, isTablet } = useResponsiveMode();
  const isCompact = isMobile || isTablet;
  const execColumns = useResizableColumns([
    { key: 'target', initialWidth: 160, minWidth: 80 },
    { key: 'script', initialWidth: 240, minWidth: 100 },
    { key: 'start', initialWidth: 120, minWidth: 70 },
    { key: 'end', initialWidth: 120, minWidth: 70 },
    { key: 'status', initialWidth: 120, minWidth: 80 },
    { key: 'report', initialWidth: 120, minWidth: 80 },
    { key: 'logs', initialWidth: 120, minWidth: 80 },
    { key: 'rerun', initialWidth: 70, minWidth: 50 },
  ]);
  const { executeMultipleScripts, isExecuting, executingIds } = useScript();
  const { executeCampaign } = useCampaign();
  const { createDeployment, runDeploymentNow } = useDeployment();
  const {
    runningExecutions: ctxRunningExecutions,
    queuedExecutions: ctxQueuedExecutions,
    completedExecutions: ctxCompletedExecutions,
    refresh: refreshExecutions,
    subscribeSystemUpdate,
  } = useRunExecutions();
  const { executeTestCase } = useTestCaseExecution();
  const { getTestCase } = useTestCaseSave();
  const { showInfo, showSuccess, showError } = useToast();
  
  const [browserTab, setBrowserTab] = useState<'tests' | 'campaigns'>(
    searchParams.get('tab') === 'campaigns' ? 'campaigns' : 'tests',
  );
  


  const [selectedExecutable, setSelectedExecutable] = useState<SelectedExecutableInstance | null>(null);
  // Pending parameterized-testcase launch awaiting input values from the
  // Run-with-inputs dialog (null = no prompt open).
  const [testcaseRunPrompt, setTestcaseRunPrompt] = useState<{
    inputs: any[];
    testcaseName: string;
    pending: {
      allDevices: Array<{ hostName: string; deviceId: string; deviceModel: string }>;
      testcaseVersionNumber: number | null;
      preloaded: {
        executionGraph: any;
        scriptInputs: any[];
        scriptVariables: any[];
        scriptConfigForExecution: { inputs: any[]; variables: any[] };
        versionNumber: number | null;
        testcaseName: string;
        testcaseId: string;
      };
    };
  } | null>(null);
  const [expandedItemId, setExpandedItemId] = useState<string | null>(null);
  // Per-device manual device info (Selected Items → Device Info), applied to
  // metadata.info of every script run on that device. Keyed by resolved device key.
  const [deviceInfoByDevice, setDeviceInfoByDevice] = useState<DeviceInfoMap>({});
  const [deviceInfoModalOpen, setDeviceInfoModalOpen] = useState(false);
  const [selectedExecutableItems, setSelectedExecutableItems] = useState<SelectedExecutableInstance[]>([]);
  const [selectorTypeFilter, setSelectorTypeFilter] = useState<string | null>(isCompact ? null : 'script');
  const [campaignExecutables, setCampaignExecutables] = useState<CampaignExecutableItem[]>([]);
  const [loadingCampaignExecutables, setLoadingCampaignExecutables] = useState(false);
  const [campaignLoadError, setCampaignLoadError] = useState<string | null>(null);
  const [selectedCampaignExecutable, setSelectedCampaignExecutable] = useState<CampaignExecutableItem | null>(null);
  const [selectedCampaignExecutableItems, setSelectedCampaignExecutableItems] = useState<CampaignExecutableItem[]>([]);
  const [selectedCampaignConfig, setSelectedCampaignConfig] = useState<Omit<CampaignConfig, 'host' | 'device'> | null>(null);
  const [testcaseVersionOptions, setTestcaseVersionOptions] = useState<CompactVersionOption[]>([{ key: 'latest', label: 'Latest', versionNumber: null }]);
  const [selectedTestcaseVersionKey, setSelectedTestcaseVersionKey] = useState('latest');
  const [testcaseVersionSnapshots, setTestcaseVersionSnapshots] = useState<Record<string, VersionSnapshotRecord>>({});
  const [campaignVersionOptions, setCampaignVersionOptions] = useState<CompactVersionOption[]>([{ key: 'latest', label: 'Latest', versionNumber: null }]);
  const [selectedCampaignVersionKey, setSelectedCampaignVersionKey] = useState('latest');
  const [campaignVersionSnapshots, setCampaignVersionSnapshots] = useState<Record<string, VersionSnapshotRecord>>({});
  const [selectedScript, setSelectedScript] = useState<string>(''); // Keep for backward compatibility
  const [availableScripts, setAvailableScripts] = useState<string[]>([]);
  const [aiTestCasesInfo, setAiTestCasesInfo] = useState<any[]>([]);

  // Target selection via shared hook
  const {
    selectedDevices,
    toggleTarget,
    updateDeviceUserinterface,
    reconcileTargets,
    filterTargetKeys,
    firstSelectedDevice,
    allHosts,
    getDevicesFromHost,
  } = useTargetSelection();
  const previouslyRunningTargetsRef = useRef<Set<string>>(new Set());
  const { isDeviceAllowed, isScriptAllowed } = useWorkspaceContext();
  
  // Cache for loaded test case graphs (testcase_id -> graph)
  const [testCaseGraphCache, setTestCaseGraphCache] = useState<Record<string, any>>({});

  const [loadingScripts, setLoadingScripts] = useState<boolean>(false);
  const [activeExecutions, setActiveExecutions] = useState<ExecutionRecord[]>([]);
  const executions = activeExecutions;
  const setExecutions = setActiveExecutions;
  const [scriptCallbackUrl, setScriptCallbackUrl] = useState<string>('');
  // Which dev/test/prod DB row a virtual script instance runs (per selected
  // item, keyed by instanceId — a plain disk script has no rows to pick
  // between and never reads this). Unset = derived default in
  // getItemEnvironment (prefers 'prod', else whichever row actually exists).
  const [itemEnvironment, setItemEnvironment] = useState<Record<string, 'dev' | 'test' | 'prod'>>({});
  const [showAdvancedConfig, setShowAdvancedConfig] = useState(false);
  const [startDateOption, setStartDateOption] = useState<'now' | '1hour' | '6hours' | 'tomorrow' | 'nextMonday' | 'custom'>('now');
  const [startDateCustom, setStartDateCustom] = useState<string>('');
  const [scheduleRepeatMode, setScheduleRepeatMode] = useState<'none' | 'periodic'>('none');
  const [scheduleRepeat, setScheduleRepeat] = useState<string>('');
  const [endDateOption, setEndDateOption] = useState<'never' | '1day' | '7days' | '30days' | '90days' | 'custom'>('never');
  const [endDateCustom, setEndDateCustom] = useState<string>('');
  const [scheduleMaxIterations, setScheduleMaxIterations] = useState<string>('');
  const [startDatePopoverAnchor, setStartDatePopoverAnchor] = useState<HTMLElement | null>(null);
  const [endDatePopoverAnchor, setEndDatePopoverAnchor] = useState<HTMLElement | null>(null);
  const [selectedExecutionLockedTargets, setSelectedExecutionLockedTargets] = useState<string[]>([]);
  const [lockTooltips, setLockTooltips] = useState<Record<string, string>>({});
  const [streamsExpanded, setStreamsExpanded] = useState(false);
  const restoredUiStateRef = useRef(false);
  const restoredParamsForScriptRef = useRef<string | null>(null);
  const pendingRestoredParamsRef = useRef<Record<string, string> | null>(null);
  const restoredParameterCacheRef = useRef(false);
  const executionAbortControllers = useRef<Map<string, AbortController>>(new Map());
  const runningTargetKeys = useMemo(() => {
    const keys = new Set<string>();
    activeExecutions.forEach((exec) => {
      if (exec.status !== 'running') {
        return;
      }
      const normalizedDeviceId = exec.deviceId && exec.deviceId.trim() ? exec.deviceId : 'host';
      const key = `${exec.hostName}:${normalizedDeviceId}`;
      keys.add(key);
    });
    return keys;
  }, [activeExecutions]);

  const isTargetLocked = useMemo(() => {
    const lockedSet = new Set(selectedExecutionLockedTargets);
    return (key: string) => {
      if (lockedSet.has(key)) return true;
      // Check has_running_deployment from host data (available for all targets, no extra API call)
      const [hostName, deviceId] = key.split(':');
      if (!hostName) return false;
      const devices = getDevicesFromHost(hostName);
      const device = devices.find((d: any) => d.device_id === (deviceId || 'host'));
      return Boolean(device?.has_running_deployment);
    };
  }, [selectedExecutionLockedTargets, getDevicesFromHost]);

  const selectedRunnableTargetKeys = useMemo(
    () => Array.from(selectedDevices.keys()).filter(
      (key) => !runningTargetKeys.has(key) && !isTargetLocked(key),
    ),
    [selectedDevices, runningTargetKeys, isTargetLocked],
  );
  const selectedRunnableTargetCount = selectedRunnableTargetKeys.length;

  // When a target finishes running, drop it from the target selection so the
  // checkbox, "N targets selected" counter, and Selected Items panel all agree
  // (otherwise the just-finished target stays force-checked + disabled and the
  // user can't unselect it).
  useEffect(() => {
    const previous = previouslyRunningTargetsRef.current;
    const finished: string[] = [];
    previous.forEach((key) => {
      if (!runningTargetKeys.has(key)) {
        finished.push(key);
      }
    });
    previouslyRunningTargetsRef.current = new Set(runningTargetKeys);
    if (finished.length === 0) return;
    filterTargetKeys((key) => !finished.includes(key));
  }, [runningTargetKeys, filterTargetKeys]);

  const scheduleRepeatError = useMemo(() => {
    if (scheduleRepeatMode !== 'periodic' || !scheduleRepeat.trim()) {
      return '';
    }
    const { valid, error } = validateCronExpression(scheduleRepeat.trim());
    return valid ? '' : (error || 'Invalid cron expression');
  }, [scheduleRepeat, scheduleRepeatMode]);

  useEffect(() => {
    setBrowserTab(searchParams.get('tab') === 'campaigns' ? 'campaigns' : 'tests');
  }, [searchParams]);

  useEffect(() => {
    if (isCompact) {
      setSelectorTypeFilter(null);
      return;
    }
    setSelectorTypeFilter(browserTab === 'campaigns' ? null : 'script');
  }, [browserTab, isCompact]);

  function getExecutionDeviceId(deviceId?: string) {
    if (deviceId && deviceId.trim()) {
      return deviceId;
    }
    return 'host';
  }

  function buildTargetKey(hostName: string, deviceId?: string) {
    return `${hostName}:${getExecutionDeviceId(deviceId)}`;
  }

  function formatTargetLabel(hostName: string, deviceId?: string, deviceDisplayName?: string) {
    const normalizedDeviceId = getExecutionDeviceId(deviceId);
    if (normalizedDeviceId === 'host') {
      return hostName;
    }
    // Show the target device in front of the host so the device is the primary
    // identifier, while the host stays visible to disambiguate the same
    // device_name across hosts (e.g. "example-v1:host-1").
    return `${deviceDisplayName || normalizedDeviceId}:${hostName}`;
  }

  const mapDeploymentExecutionToRecord = useCallback((execution: any): ExecutionRecord | null => {
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
  }, []);

  const historyExecutions = useMemo<ExecutionRecord[]>(() => {
    const combined = [
      ...ctxRunningExecutions,
      ...ctxQueuedExecutions,
      ...ctxCompletedExecutions,
    ];
    const records = combined
      .map((execution: any) => mapDeploymentExecutionToRecord(execution))
      .filter((record): record is ExecutionRecord => Boolean(record));
    // Keep every record (scripts + campaigns) here — the tab/workspace filters
    // and the final RUN_TESTS_HISTORY_LIMIT slice happen in visibleExecutions.
    // Slicing to 20 now would drop all script rows whenever the 20 most recent
    // executions are campaigns (e.g. an hourly campaign deployment).
    return normalizeExecutionHistory(records, Infinity);
  }, [ctxRunningExecutions, ctxQueuedExecutions, ctxCompletedExecutions, mapDeploymentExecutionToRecord]);

  const getPlannedStartDate = useCallback((): string | null => {
    if (startDateOption === 'now') return null;
    if (startDateOption === 'custom') return startDateCustom ? new Date(startDateCustom).toISOString() : null;

    const now = new Date();
    switch (startDateOption) {
      case '1hour':
        now.setHours(now.getHours() + 1);
        break;
      case '6hours':
        now.setHours(now.getHours() + 6);
        break;
      case 'tomorrow':
        now.setDate(now.getDate() + 1);
        now.setHours(0, 0, 0, 0);
        break;
      case 'nextMonday': {
        const daysUntilMonday = (8 - now.getDay()) % 7 || 7;
        now.setDate(now.getDate() + daysUntilMonday);
        now.setHours(0, 0, 0, 0);
        break;
      }
    }
    return now.toISOString();
  }, [startDateCustom, startDateOption]);

  const getPlannedEndDate = useCallback((): string | null => {
    if (endDateOption === 'never') return null;
    if (endDateOption === 'custom') return endDateCustom ? new Date(endDateCustom).toISOString() : null;

    const now = new Date();
    switch (endDateOption) {
      case '1day':
        now.setDate(now.getDate() + 1);
        break;
      case '7days':
        now.setDate(now.getDate() + 7);
        break;
      case '30days':
        now.setDate(now.getDate() + 30);
        break;
      case '90days':
        now.setDate(now.getDate() + 90);
        break;
    }
    return now.toISOString();
  }, [endDateCustom, endDateOption]);

  // Ref to prevent duplicate API calls in React Strict Mode
  const isLoadingScriptsRef = useRef<boolean>(false);

  const loadCampaignExecutables = useCallback(async () => {
    setLoadingCampaignExecutables(true);
    setCampaignLoadError(null);
    try {
      const payload = await getCachedCampaignExecutableList(buildServerUrl('/server/campaigns/listExecutables'));
      if (!payload?.success) {
        throw new Error(payload?.error || 'Failed to load campaigns');
      }
      setCampaignExecutables(payload.executables || []);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to load campaigns';
      setCampaignLoadError(message);
    } finally {
      setLoadingCampaignExecutables(false);
    }
  }, []);

  const loadDbCampaign = useCallback(async (campaignId: string) => {
    const response = await fetch(buildServerUrl(`/server/campaigns/${campaignId}/history`));
    const payload = await response.json();

    if (payload?.success && Array.isArray(payload?.versions) && payload.versions.length > 0) {
      const versions = payload.versions as VersionSnapshotRecord[];
      const nextSnapshots: Record<string, VersionSnapshotRecord> = {};
      const nextOptions: CompactVersionOption[] = [];
      versions.slice(0, 4).forEach((version, index) => {
        const key = index === 0 ? 'latest' : `v${version.version_number}`;
        nextSnapshots[key] = version;
        nextOptions.push({
          key,
          label: index === 0 ? 'Latest' : `v${version.version_number}`,
          versionNumber: index === 0 ? null : version.version_number,
        });
      });

      setCampaignVersionSnapshots(nextSnapshots);
      setCampaignVersionOptions(nextOptions);
      setSelectedCampaignVersionKey('latest');
      const latest = versions[0];
      setSelectedCampaignConfig(normalizeLoadedCampaign({
        ...(latest.campaign_data || {}),
        campaign_id: campaignId,
        version_number: latest.version_number,
      }));
      return;
    }

    // Fallback: no version history — load campaign directly
    const fallbackResponse = await fetch(buildServerUrl(`/server/campaigns/getCampaign/${campaignId}`));
    const fallbackPayload = await fallbackResponse.json();
    if (!fallbackPayload?.success || !fallbackPayload?.campaign) {
      throw new Error(fallbackPayload?.error || 'Failed to load campaign');
    }

    setCampaignVersionSnapshots({});
    setCampaignVersionOptions([{ key: 'latest', label: 'Latest', versionNumber: null }]);
    setSelectedCampaignVersionKey('latest');
    setSelectedCampaignConfig(normalizeLoadedCampaign({
      ...fallbackPayload.campaign,
      campaign_id: campaignId,
    }));
  }, []);

  const selectorMaxListHeight = 320;

  const campaignSelectorItems = useMemo<ExecutableItem[]>(() => (
    campaignExecutables.map((item) => ({
      id: item.id,
      type: item.source === 'db' ? 'testcase' : 'script',
      name: item.name,
      description: item.description,
      folder: 'All',
      tags: [],
      badgeLabel: getCampaignBadge(item.source).label,
      badgeColor: getCampaignBadge(item.source).color,
      target_rules: normalizeTargetRules(item.compatibility_rules?.[0] || {
        target_type: 'device',
        host_os: 'all',
        device_model: 'all',
      }),
    }))
  ), [campaignExecutables]);

  const selectedCampaignSelectorItem = useMemo<ExecutableItem | null>(() => {
    if (!selectedCampaignExecutable) {
      return null;
    }
    return campaignSelectorItems.find((item) => item.id === selectedCampaignExecutable.id) || null;
  }, [campaignSelectorItems, selectedCampaignExecutable]);

  const selectedCampaignSelectorItems = useMemo<ExecutableItem[]>(() => (
    selectedCampaignExecutableItems
      .map((selectedItem) => campaignSelectorItems.find((item) => item.id === selectedItem.id) || null)
      .filter((item): item is ExecutableItem => item !== null)
  ), [campaignSelectorItems, selectedCampaignExecutableItems]);

  const handleSelectCampaignExecutable = useCallback(async (item: CampaignExecutableItem | null) => {
    setSelectedCampaignExecutable(item);
    setSelectedCampaignConfig(null);
    setCampaignVersionOptions([{ key: 'latest', label: 'Latest', versionNumber: null }]);
    setSelectedCampaignVersionKey('latest');
    setCampaignVersionSnapshots({});
    if (item?.source === 'db' && item.campaign_id) {
      try {
        await loadDbCampaign(item.campaign_id);
      } catch (error) {
        setCampaignLoadError(error instanceof Error ? error.message : 'Failed to load campaign');
      }
    }
  }, [loadDbCampaign]);

  const handleSelectCampaignVersion = useCallback((option: CompactVersionOption) => {
    if (!selectedCampaignExecutable?.campaign_id) {
      return;
    }
    setSelectedCampaignVersionKey(option.key);
    const snapshot = campaignVersionSnapshots[option.key];
    if (!snapshot) {
      return;
    }
    setSelectedCampaignConfig(normalizeLoadedCampaign({
      ...(snapshot.campaign_data || {}),
      campaign_id: selectedCampaignExecutable.campaign_id,
      version_number: snapshot.version_number,
    }));
  }, [campaignVersionSnapshots, selectedCampaignExecutable]);

  const clearExecutableSelections = useCallback(() => {
    setSelectedExecutable(null);
    setSelectedExecutableItems([]);
    setSelectedScript('');
    setExpandedItemId(null);

    setSelectedCampaignExecutable(null);
    setSelectedCampaignExecutableItems([]);
    setSelectedCampaignConfig(null);
    setCampaignVersionOptions([{ key: 'latest', label: 'Latest', versionNumber: null }]);
    setSelectedCampaignVersionKey('latest');
    setCampaignVersionSnapshots({});
  }, []);

  const handleBrowserTabChange = useCallback((tab: 'tests' | 'campaigns') => {
    clearExecutableSelections();
    setBrowserTab(tab);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set('tab', tab);
      return next;
    });
  }, [clearExecutableSelections, setSearchParams]);

  const addTestSelection = useCallback((item: ExecutableItem) => {
    const instance: SelectedExecutableInstance = { ...item, instanceId: newInstanceId() };
    setSelectedExecutable(instance);
    setSelectedExecutableItems((prev) => [...prev, instance]);
  }, []);

  const removeTestSelection = useCallback((instanceId: string) => {
    const next = selectedExecutableItems.filter((entry) => entry.instanceId !== instanceId);
    setSelectedExecutableItems(next);
    if (next.length === 0) {
      setSelectedExecutable(null);
      // Clear the derived script in the same batched render. If we left it for
      // the forward-sync effect, there'd be one render where selectedExecutable
      // is null but selectedScript is still set — the reverse-sync effect would
      // fire on that gap and resurrect selectedExecutable, re-highlighting the
      // row even though nothing is selected.
      setSelectedScript('');
    } else if (selectedExecutable?.instanceId === instanceId) {
      setSelectedExecutable(next[next.length - 1] || null);
    }
  }, [selectedExecutable, selectedExecutableItems]);

  const addCampaignSelection = useCallback(async (item: CampaignExecutableItem) => {
    await handleSelectCampaignExecutable(item);
    setSelectedCampaignExecutableItems((prev) => (
      prev.some((entry) => entry.id === item.id) ? prev : [...prev, item]
    ));
  }, [handleSelectCampaignExecutable]);

  const removeCampaignSelection = useCallback((itemId: string) => {
    setSelectedCampaignExecutableItems((prev) => {
      const next = prev.filter((entry) => entry.id !== itemId);
      if (next.length === 0) {
        setSelectedCampaignExecutable(null);
        setSelectedCampaignConfig(null);
      } else if (selectedCampaignExecutable?.id === itemId) {
        void handleSelectCampaignExecutable(next[next.length - 1] || null);
      }
      return next;
    });
  }, [handleSelectCampaignExecutable, selectedCampaignExecutable]);

  const getCampaignScriptKey = useCallback((campaignId: string, scriptName: string) =>
    `campaign:${campaignId}:${scriptName}`, []);

  const getCampaignScopeId = useCallback((item: CampaignExecutableItem) => (
    item.campaign_id || item.id
  ), []);

  const getContainedScriptsForCampaign = useCallback((item: CampaignExecutableItem) => {
    if (
      item.source === 'db' &&
      selectedCampaignExecutable?.id === item.id &&
      selectedCampaignConfig?.script_configurations?.length
    ) {
      return selectedCampaignConfig.script_configurations.map((script, index) => ({
        script_name: script.script_name || script.testcase_id || `item_${index + 1}`,
        script_type: script.script_type || (script.testcase_id ? 'testcase' : 'script'),
        description: script.description || '',
      }));
    }
    if (item.contained_scripts?.length) {
      return item.contained_scripts;
    }
    if (item.source === 'file') {
      return [{
        script_name: item.script_name || item.id,
        script_type: 'script',
        description: item.description || '',
      }];
    }
    return [];
  }, [selectedCampaignConfig, selectedCampaignExecutable]);

  const formatLockTooltip = (lockInfo: any): string => {
    if (!lockInfo) return 'Locked';
    const reason = lockInfo.lock_reason || '';
    let label = 'Locked';
    if (reason.startsWith('script_execute:')) label = reason.slice('script_execute:'.length).split('/').pop() || 'script';
    else if (reason.startsWith('deployment_execute:')) label = 'deployment';
    else if (reason.startsWith('deployment:')) label = reason.slice('deployment:'.length) || 'deployment';
    else if (reason === 'manual_take_control' || lockInfo.owner_type === 'manual_control') label = 'manual control';
    else if (reason.startsWith('campaign_execute:')) label = 'campaign';
    else label = lockInfo.owner_type || 'locked';
    const age = Math.round(Number(lockInfo.lock_age_seconds || 0));
    const ageStr = age < 60 ? `${age}s ago` : `${Math.floor(age / 60)}min ago`;
    return `${label} (${ageStr})`;
  };

  const refreshSelectedExecutionLocks = useCallback(async () => {
    const selectedKeys = Array.from(selectedDevices.keys());
    if (selectedKeys.length === 0) {
      setSelectedExecutionLockedTargets([]);
      setLockTooltips({});
      return;
    }

    const tooltips: Record<string, string> = {};
    const checks = await Promise.all(
      selectedKeys.map(async (deviceKey) => {
        const [hostName, deviceId] = deviceKey.split(':');
        const effectiveDeviceId = getExecutionDeviceId(deviceId);
        try {
          const response = await fetch(buildServerUrl('/server/control/checkLock'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ host_name: hostName, device_id: effectiveDeviceId }),
          });
          const data = await response.json();
          const lockInfo = data?.lock_info;
          const ownerType = lockInfo?.owner_type;
          const isExecutionLock =
            Boolean(data?.is_locked) &&
            (ownerType === 'script_execution' || ownerType === 'deployment_execution');
          if (isExecutionLock) {
            tooltips[deviceKey] = formatLockTooltip(lockInfo);
          }
          return isExecutionLock ? deviceKey : null;
        } catch {
          return null;
        }
      }),
    );

    setSelectedExecutionLockedTargets(checks.filter(Boolean) as string[]);
    setLockTooltips(tooltips);
  }, [selectedDevices]);

  useEffect(() => {
    refreshSelectedExecutionLocks();
    const intervalId = window.setInterval(() => {
      refreshSelectedExecutionLocks();
    }, 4000);
    return () => {
      window.clearInterval(intervalId);
    };
  }, [refreshSelectedExecutionLocks]);


  // Sync selectedScript from selectedExecutable for backward compatibility
  useEffect(() => {
    if (browserTab !== 'tests') {
      setSelectedScript('');
      return;
    }
    if (selectedExecutable && selectedExecutable.type === 'script') {
      setSelectedScript(selectedExecutable.id);
    } else {
      setSelectedScript('');
    }
  }, [browserTab, selectedExecutable]);

  // Reverse sync: When selectedScript has a value but selectedExecutable is null,
  // fetch the executable details from the backend (happens on page load with saved state)
  useEffect(() => {
    // Guard against a stale resurrection: when the user unselects the last
    // script, selectedExecutable is cleared and selectedScript follows via the
    // forward-sync effect above. This effect's previous render still captured
    // the old selectedScript and may have an in-flight fetch; the cleanup flag
    // stops it from setting selectedExecutable back (which would re-highlight
    // the row even though nothing is selected).
    let cancelled = false;
    const syncExecutableFromScript = async () => {
      // Only sync if we have a script selected but no executable object
      if (browserTab === 'tests' && selectedScript && !selectedExecutable) {
        try {
          const data = await getCachedExecutableList(buildServerUrl('/server/executable/list'));
          if (cancelled) return;

          if (data.success && data.folders) {
            let found = false;
            for (const folder of data.folders) {
              // Try exact match first
              let foundItem = folder.items.find((item: any) => item.id === selectedScript);

              // If not found and selectedScript doesn't have an extension, try adding .py
              if (!foundItem && !selectedScript.includes('.')) {
                foundItem = folder.items.find((item: any) => item.id === `${selectedScript}.py`);
              }

              // If still not found, try removing extension from selectedScript
              if (!foundItem && selectedScript.includes('.')) {
                const scriptWithoutExt = selectedScript.split('.')[0];
                foundItem = folder.items.find((item: any) => item.id === scriptWithoutExt);
              }

              if (foundItem) {
                if (!cancelled) setSelectedExecutable(foundItem);
                found = true;
                break;
              }
            }
            if (!found) {
              console.warn('[@RunTests] No matching executable found for:', selectedScript);
            }
          }
        } catch (error) {
          console.error('[@RunTests] ❌ Failed to sync executable from script:', error);
        }
      }
    };

    syncExecutableFromScript();
    return () => {
      cancelled = true;
    };
  }, [browserTab, selectedScript, selectedExecutable]);

  type VirtualScriptEnvSource = {
    is_virtual?: boolean;
    virtual_script_id?: string;
    virtual_script_env_ids?: { dev: string | null; test: string | null; prod: string | null };
  };

  // Environments a virtual script actually has a promoted row for. A plain
  // disk script has none — its per-item env control stays hidden. Falls back
  // to ['dev'] for the (should-never-happen) case where a virtual item has no
  // env ids at all, mirroring the backend's own fallback shape.
  const getAvailableEnvironments = useCallback((exec: VirtualScriptEnvSource | null | undefined): Array<'dev' | 'test' | 'prod'> => {
    if (!exec?.is_virtual) return [];
    const envIds = exec.virtual_script_env_ids;
    const available = (['dev', 'test', 'prod'] as const).filter((env) => Boolean(envIds?.[env]));
    return available.length > 0 ? available : ['dev'];
  }, []);

  // Per-item environment (dev/test/prod), keyed by instanceId. Prefers the
  // user's explicit pick when it's still a row that exists for this item,
  // else 'prod', else whichever row the script actually has — so a prod-only
  // script just shows/uses "Prod" instead of silently falling back.
  const getItemEnvironment = useCallback((item: (VirtualScriptEnvSource & { instanceId: string }) | null | undefined): 'dev' | 'test' | 'prod' => {
    const available = getAvailableEnvironments(item);
    if (available.length === 0) return 'prod';
    const stored = item ? itemEnvironment[item.instanceId] : undefined;
    if (stored && available.includes(stored)) return stored;
    return available.includes('prod') ? 'prod' : available[0];
  }, [getAvailableEnvironments, itemEnvironment]);

  // Resolve which virtual-script row (dev/test/prod) a run targets. A virtual
  // script name fans out to up to 3 rows; the executable carries their ids in
  // virtual_script_env_ids. Falls back to virtual_script_id when the chosen
  // env has no promoted row yet. This is what lets a dev run and a prod run
  // of the same script go in parallel (each resolves to a different row id)
  // — device locking keeps them on separate devices.
  const resolveVirtualScriptId = useCallback(
    (exec: VirtualScriptEnvSource | null | undefined, env: 'dev' | 'test' | 'prod'): string | undefined => {
      if (!exec?.is_virtual) return undefined;
      const byEnv = exec.virtual_script_env_ids?.[env];
      return byEnv || exec.virtual_script_id;
    },
    [],
  );

  // Use run hook for script analysis and parameter management
  const {
    scriptAnalysis,
    parameterValues,
    analyzingScript,
    handleParameterChange,
    validateParameters
  } = useRun({
    selectedScript,
    selectedDevice: firstSelectedDevice.deviceId,
    selectedHost: firstSelectedDevice.hostName,
    showWizard: true,
    virtualScriptId: resolveVirtualScriptId(selectedExecutable, getItemEnvironment(selectedExecutable)),
  });

  const [scriptAnalysisCache, setScriptAnalysisCache] = useState<Record<string, ScriptAnalysis>>({});
  const [scriptParameterCache, setScriptParameterCache] = useState<Record<string, Record<string, string>>>({});
  const [perDeviceParams, setPerDeviceParams] = useState<
    Record<string, Record<string, Record<string, string>>>
  >({});
  const analysisRequestsRef = useRef<Set<string>>(new Set());
  const appliedCachedParamsRef = useRef<string | null>(null);

  const getDefaultParameterValue = useCallback((param: ScriptParameter, hostName?: string, deviceId?: string): string => {
    // For framework params (host, device): only use the framework value (VM hostname / device ID)
    // if the script doesn't define its own default. A script with --host defaulting to
    // "imap.example.com" means something different than the VM hostname.
    if (param.name === 'device' && !param.default) {
      return deviceId || '';
    }
    if (param.name === 'host' && !param.default) {
      return hostName || '';
    }
    if (param.name === 'goto_live') {
      return 'true';
    }
    if (param.default !== undefined) {
      return param.default;
    }
    return '';
  }, []);

  const buildInitialParameterValues = useCallback((
    analysis: ScriptAnalysis,
    hostName?: string,
    deviceId?: string,
  ): Record<string, string> => {
    const initialValues: Record<string, string> = {};
    analysis.parameters.forEach((param) => {
      initialValues[param.name] = getDefaultParameterValue(param, hostName, deviceId);
    });
    return initialValues;
  }, [getDefaultParameterValue]);

  const getScriptAnalysisFor = useCallback((scriptId: string) => {
    if (scriptId === selectedScript && scriptAnalysis) {
      return scriptAnalysis;
    }
    return scriptAnalysisCache[scriptId] || null;
  }, [scriptAnalysis, scriptAnalysisCache, selectedScript]);

  const getBaseParamsForScript = useCallback((scriptId: string) => {
    if (scriptId === selectedScript) {
      return parameterValues;
    }
    return scriptParameterCache[scriptId] || {};
  }, [parameterValues, scriptParameterCache, selectedScript]);

  const resolveSelectedTargetKey = useCallback((hostName?: string, deviceId?: string) => {
    const normalizedHost = hostName || firstSelectedDevice.hostName;
    const normalizedDeviceId = getExecutionDeviceId(deviceId);

    for (const key of selectedDevices.keys()) {
      const [selectedHost, selectedDeviceId] = key.split(':');
      if (
        selectedHost === normalizedHost &&
        getExecutionDeviceId(selectedDeviceId) === normalizedDeviceId
      ) {
        return key;
      }
    }

    return `${normalizedHost}:${normalizedDeviceId}`;
  }, [firstSelectedDevice.hostName, selectedDevices]);

  const getEffectiveParamValue = useCallback((
    scriptId: string,
    deviceKey: string | undefined,
    paramName: string,
  ): string => {
    const targetAnalysis = getScriptAnalysisFor(scriptId);
    const baseParams = getBaseParamsForScript(scriptId);
    const normalizedDeviceKey = deviceKey
      ? resolveSelectedTargetKey(deviceKey.split(':')[0], deviceKey.split(':')[1])
      : undefined;
    const deviceOverrides = deviceKey
      ? perDeviceParams[scriptId]?.[normalizedDeviceKey || deviceKey]
      : undefined;
    const overrideValue = deviceOverrides?.[paramName];

    if (typeof overrideValue === 'string' && overrideValue.trim() !== '') {
      return overrideValue;
    }

    // An explicit empty-string override is meaningful for `variant`: it means
    // the user picked "base" and must win over the device's preferred_variant
    // default resolved below. Without this, selecting base on a device whose
    // DEVICE{i}_VARIANT is set (e.g. "stb") silently reverted to that variant.
    // handlePerDeviceParamChange only writes on user action, so the key being
    // present in the overrides bag means the user explicitly chose it.
    if (
      paramName === 'variant' &&
      deviceOverrides &&
      Object.prototype.hasOwnProperty.call(deviceOverrides, 'variant')
    ) {
      return '';
    }

    // Per-device preferred userinterface/variant from the host .env
    // (DEVICE{i}_USERINTERFACE / _VARIANT). Beats the script's declared
    // default; an explicit user override (handled above) still wins.
    if (
      paramName === 'userinterface' ||
      paramName === 'userinterface_name' ||
      paramName === 'variant'
    ) {
      const [hn, di] = normalizedDeviceKey
        ? normalizedDeviceKey.split(':')
        : [firstSelectedDevice.hostName, firstSelectedDevice.deviceId];
      const device = hn
        ? getDevicesFromHost(hn)?.find((d) => d.device_id === di)
        : undefined;
      if (device?.preferred_userinterface) {
        if (paramName === 'userinterface' || paramName === 'userinterface_name') {
          return device.preferred_userinterface;
        }
        if (paramName === 'variant' && device.preferred_variant) {
          // Variant is coupled to the UI: only apply the device's default
          // variant while the effective userinterface is still the device's
          // preferred one. Overriding the UI resets the variant to base.
          const paramsKey = normalizedDeviceKey || deviceKey || '';
          const uiOverride =
            perDeviceParams[scriptId]?.[paramsKey]?.['userinterface'] ??
            perDeviceParams[scriptId]?.[paramsKey]?.['userinterface_name'];
          const effectiveUi =
            typeof uiOverride === 'string' && uiOverride.trim() !== ''
              ? uiOverride.trim()
              : device.preferred_userinterface;
          return effectiveUi === device.preferred_userinterface
            ? device.preferred_variant
            : '';
        }
      }
    }

    const baseValue = baseParams[paramName];
    if (typeof baseValue === 'string' && baseValue.trim() !== '') {
      return baseValue;
    }

    const param = targetAnalysis?.parameters.find((entry) => entry.name === paramName);
    if (!param) {
      return '';
    }

    const [hostName, deviceId] = normalizedDeviceKey
      ? normalizedDeviceKey.split(':')
      : [firstSelectedDevice.hostName, firstSelectedDevice.deviceId];
    return getDefaultParameterValue(param, hostName, deviceId);
  }, [firstSelectedDevice.deviceId, firstSelectedDevice.hostName, getBaseParamsForScript, getDefaultParameterValue, getDevicesFromHost, getScriptAnalysisFor, perDeviceParams, resolveSelectedTargetKey]);

  const handlePerDeviceParamChange = useCallback((scriptId: string, deviceKey: string, paramName: string, value: string) => {
    const resolvedDeviceKey = resolveSelectedTargetKey(deviceKey.split(':')[0], deviceKey.split(':')[1]);
    setPerDeviceParams((prev) => ({
      ...prev,
      [scriptId]: {
        ...(prev[scriptId] || {}),
        [resolvedDeviceKey]: { ...((prev[scriptId] || {})[resolvedDeviceKey] || {}), [paramName]: value },
      },
    }));
  }, [resolveSelectedTargetKey]);

  const ensureScriptAnalysisLoaded = useCallback(async (scriptId: string) => {
    if (!scriptId || scriptId === selectedScript || scriptAnalysisCache[scriptId] || analysisRequestsRef.current.has(scriptId)) {
      return;
    }

    analysisRequestsRef.current.add(scriptId);
    try {
      const analysis = await api.post(buildServerUrl('/server/script/analyze'), {
        script_name: scriptId,
      }) as ScriptAnalysis;

      if (!analysis?.success) {
        return;
      }

      setScriptAnalysisCache((prev) => ({ ...prev, [scriptId]: analysis }));
      setScriptParameterCache((prev) => (
        prev[scriptId]
          ? prev
          : { ...prev, [scriptId]: buildInitialParameterValues(analysis) }
      ));
    } catch (error) {
      console.error('[@RunTests] Failed to analyze script for selected items:', scriptId, error);
    } finally {
      analysisRequestsRef.current.delete(scriptId);
    }
  }, [buildInitialParameterValues, scriptAnalysisCache, selectedScript]);

  const selectedExecutableRules = useMemo<TargetRules>(() => {
    if (browserTab === 'campaigns') {
      const rules = selectedCampaignExecutable?.compatibility_rules || [];
      return normalizeTargetRules(rules[0] || { target_type: 'device', host_os: 'all', device_model: 'all' });
    }
    if (selectedExecutable?.type === 'testcase') {
      return selectedExecutable.target_rules || {
        target_type: 'device',
        host_os: 'all',
        device_model: 'all',
      };
    }

    return selectedExecutable?.target_rules || {
      target_type: 'device',
      host_os: 'all',
      device_model: 'all',
    };
  }, [browserTab, selectedCampaignExecutable, selectedExecutable]);
  const isHostSelectionMode = selectedExecutableRules.target_type === 'host';


  const getScriptValidation = useCallback(() => {
    if (!selectedScript) {
      return { valid: false, errors: ['Please select a script'] };
    }

    if (analyzingScript) {
      return { valid: false, errors: ['Script parameter analysis is still in progress'] };
    }

    if (!scriptAnalysis) {
      return {
        valid: false,
        errors: ['Unable to validate required parameters. Please re-select the script'],
      };
    }

    return validateParameters();
  }, [selectedScript, analyzingScript, scriptAnalysis, validateParameters]);

  const scriptValidation =
    browserTab === 'tests' && selectedExecutable?.type === 'script'
      ? getScriptValidation()
      : { valid: true, errors: [] as string[] };

  useEffect(() => {
    if (!selectedScript || !scriptAnalysis) {
      return;
    }
    setScriptAnalysisCache((prev) => ({ ...prev, [selectedScript]: scriptAnalysis }));
  }, [scriptAnalysis, selectedScript]);

  useEffect(() => {
    if (!selectedScript || !scriptAnalysis) {
      return;
    }
    setScriptParameterCache((prev) => ({ ...prev, [selectedScript]: parameterValues }));
  }, [parameterValues, scriptAnalysis, selectedScript]);

  useEffect(() => {
    if (restoredParameterCacheRef.current) {
      return;
    }
    restoredParameterCacheRef.current = true;

    try {
      const raw = localStorage.getItem(RUN_TESTS_PARAMETER_CACHE_KEY);
      if (!raw) {
        return;
      }

      const saved = JSON.parse(raw) as {
        scriptParameterCache?: Record<string, Record<string, string>>;
        perDeviceParams?: Record<string, Record<string, Record<string, string>>>;
      };

      if (saved.scriptParameterCache && typeof saved.scriptParameterCache === 'object') {
        setScriptParameterCache(saved.scriptParameterCache);
      }

      if (saved.perDeviceParams && typeof saved.perDeviceParams === 'object') {
        setPerDeviceParams(saved.perDeviceParams);
      }
    } catch (e) {
      console.warn('[@RunTests] Failed to restore parameter cache:', e);
    }
  }, []);

  useEffect(() => {
    appliedCachedParamsRef.current = null;
  }, [selectedScript]);

  useEffect(() => {
    if (!selectedScript || !scriptAnalysis) {
      return;
    }
    if (appliedCachedParamsRef.current === selectedScript) {
      return;
    }

    const cachedValues = scriptParameterCache[selectedScript];
    if (!cachedValues) {
      appliedCachedParamsRef.current = selectedScript;
      return;
    }

    scriptAnalysis.parameters.forEach((param) => {
      const nextValue = cachedValues[param.name];
      if (typeof nextValue === 'string' && parameterValues[param.name] !== nextValue) {
        handleParameterChange(param.name, nextValue);
      }
    });

    appliedCachedParamsRef.current = selectedScript;
  }, [handleParameterChange, parameterValues, scriptAnalysis, scriptParameterCache, selectedScript]);

  // Restore UI state after remount (e.g., focus/inactivity recovery)
  useEffect(() => {
    if (restoredUiStateRef.current) return;
    restoredUiStateRef.current = true;

    try {
      const raw = sessionStorage.getItem(RUN_TESTS_STATE_KEY);
      if (!raw) return;
      const saved = JSON.parse(raw) as {
        selectedTargetKeys?: string[];
        parameterValues?: Record<string, string>;
        scriptCallbackUrl?: string;
        streamsExpanded?: boolean;
        browserTab?: 'tests' | 'campaigns';
        deviceInfoByDevice?: DeviceInfoMap;
      };

      if (typeof saved.scriptCallbackUrl === 'string') {
        setScriptCallbackUrl(saved.scriptCallbackUrl);
      }
      if (typeof saved.streamsExpanded === 'boolean') {
        setStreamsExpanded(saved.streamsExpanded);
      }
      if (saved.browserTab && !searchParams.get('tab')) {
        setBrowserTab(saved.browserTab);
        setSearchParams((prev) => { const next = new URLSearchParams(prev); next.set('tab', saved.browserTab!); return next; }, { replace: true });
      }
      if (saved.parameterValues && typeof saved.parameterValues === 'object') {
        pendingRestoredParamsRef.current = saved.parameterValues;
      }
      if (saved.deviceInfoByDevice && typeof saved.deviceInfoByDevice === 'object') {
        setDeviceInfoByDevice(saved.deviceInfoByDevice);
      }
      if (Array.isArray(saved.selectedTargetKeys)) {
        saved.selectedTargetKeys.forEach((key) => {
          if (key && !selectedDevices.has(key)) {
            toggleTarget(key);
          }
        });
      }
    } catch (e) {
      console.warn('[@RunTests] Failed to restore UI state:', e);
    }
  }, [toggleTarget, searchParams, setSearchParams]);

  // Restore parameter values once script analysis is available for the selected script.
  useEffect(() => {
    const pendingParams = pendingRestoredParamsRef.current;
    if (!pendingParams || !selectedScript || !scriptAnalysis) return;
    if (restoredParamsForScriptRef.current === selectedScript) return;

    Object.entries(pendingParams).forEach(([name, value]) => {
      if (typeof value === 'string') {
        handleParameterChange(name, value);
      }
    });

    restoredParamsForScriptRef.current = selectedScript;
    pendingRestoredParamsRef.current = null;
  }, [selectedScript, scriptAnalysis, handleParameterChange]);

  // Persist UI state so returning to the tab doesn't wipe selections and the
  // currently edited script-level values.
  useEffect(() => {
    try {
      const payload = {
        selectedTargetKeys: Array.from(selectedDevices.keys()),
        parameterValues,
        scriptCallbackUrl,
        streamsExpanded,
        browserTab,
        deviceInfoByDevice,
      };
      sessionStorage.setItem(RUN_TESTS_STATE_KEY, JSON.stringify(payload));
    } catch (e) {
      console.warn('[@RunTests] Failed to persist UI state:', e);
    }
  }, [selectedDevices, parameterValues, scriptCallbackUrl, streamsExpanded, browserTab, deviceInfoByDevice]);

  // Persist reusable parameter caches, including sensitive values, because
  // operators expect per-target script settings like passwords to be remembered.
  useEffect(() => {
    try {
      localStorage.setItem(
        RUN_TESTS_PARAMETER_CACHE_KEY,
        JSON.stringify({
          scriptParameterCache,
          perDeviceParams,
        }),
      );
    } catch (e) {
      console.warn('[@RunTests] Failed to persist parameter cache:', e);
    }
  }, [perDeviceParams, scriptParameterCache]);

  // RunTests-specific lock-tooltip refresh. /executions/recent reloads + the
  // shared /system socket live in RunExecutionsContext; here we only need to
  // refresh the lock state of the currently selected targets when an event
  // tells us something about them changed.
  useEffect(() => {
    return subscribeSystemUpdate((event: any) => {
      if (event?.type === 'lock_changed') {
        const hostName = event?.host_name;
        const deviceId = getExecutionDeviceId(event?.device_id);
        const affectsSelectedTarget = Array.from(selectedDevices.keys()).some((key) => {
          const [selectedHost, selectedDeviceId] = key.split(':');
          return selectedHost === hostName && getExecutionDeviceId(selectedDeviceId) === deviceId;
        });
        if (affectsSelectedTarget) {
          void refreshSelectedExecutionLocks();
        }
        return;
      }

      if (event?.domain !== 'deployment') return;
      if (!event?.deployment_id && !event?.execution_id) return;
      if (event.status === 'completed' || event.status === 'failed' || event.status === 'aborted' || event.status === 'skipped' || event.status === 'running') {
        void refreshSelectedExecutionLocks();
      }
    });
  }, [subscribeSystemUpdate, refreshSelectedExecutionLocks, selectedDevices]);

  useEffect(() => {
    selectedExecutableItems.forEach((item) => {
      if (item.type === 'script' && item.id !== selectedScript) {
        void ensureScriptAnalysisLoaded(item.id);
      }
    });
  }, [ensureScriptAnalysisLoaded, selectedExecutableItems, selectedScript]);

  // Load script analysis for each script exposed by the selected campaign items.
  useEffect(() => {
    const itemsToInspect = selectedCampaignExecutableItems.length > 0
      ? selectedCampaignExecutableItems
      : (selectedCampaignExecutable ? [selectedCampaignExecutable] : []);

    itemsToInspect.forEach((item) => {
      getContainedScriptsForCampaign(item).forEach((sc) => {
        if (sc.script_name) {
          void ensureScriptAnalysisLoaded(sc.script_name);
        }
      });
    });
  }, [
    ensureScriptAnalysisLoaded,
    getContainedScriptsForCampaign,
    selectedCampaignExecutable,
    selectedCampaignExecutableItems,
  ]);

  // Alias analysis cache under each selected test instance's instanceId so
  // getEffectiveParamValue (which uses the instanceId as its params key) can
  // resolve the script's parameter signature.
  useEffect(() => {
    const updates: Record<string, ScriptAnalysis> = {};
    selectedExecutableItems.forEach((item) => {
      if (item.type !== 'script') return;
      const analysis = scriptAnalysisCache[item.id];
      if (analysis && scriptAnalysisCache[item.instanceId] !== analysis) {
        updates[item.instanceId] = analysis;
      }
    });
    if (Object.keys(updates).length) {
      setScriptAnalysisCache((prev) => ({ ...prev, ...updates }));
    }
  }, [selectedExecutableItems, scriptAnalysisCache]);

  // Alias analysis/param caches under campaign-prefixed keys so getEffectiveParamValue works
  useEffect(() => {
    const analysisUpdates: Record<string, ScriptAnalysis> = {};
    const paramUpdates: Record<string, Record<string, string>> = {};
    const itemsToInspect = selectedCampaignExecutableItems.length > 0
      ? selectedCampaignExecutableItems
      : (selectedCampaignExecutable ? [selectedCampaignExecutable] : []);

    itemsToInspect.forEach((item) => {
      const campaignScopeId = getCampaignScopeId(item);
      const dbScriptConfigByName = item.source === 'db' && selectedCampaignExecutable?.id === item.id
        ? new Map(
            (selectedCampaignConfig?.script_configurations || [])
              .filter((sc) => sc.script_name)
              .map((sc) => [sc.script_name, sc]),
          )
        : new Map();

      getContainedScriptsForCampaign(item).forEach((sc) => {
        if (!sc.script_name) {
          return;
        }
        const key = getCampaignScriptKey(campaignScopeId, sc.script_name);
        if (!scriptAnalysisCache[key] && scriptAnalysisCache[sc.script_name]) {
          analysisUpdates[key] = scriptAnalysisCache[sc.script_name];
        }
        if (!scriptParameterCache[key]) {
          // Stringify the DB-stored parameters so they round-trip cleanly through
          // the renderer (TextField/Select/Switch all expect string values).
          const dbConfig = dbScriptConfigByName.get(sc.script_name);
          const dbParams: Record<string, string> = {};
          if (dbConfig?.parameters) {
            for (const [k, v] of Object.entries(dbConfig.parameters)) {
              dbParams[k] = v == null ? '' : String(v);
            }
          }
          const baseParams = scriptParameterCache[sc.script_name] || {};
          // DB-saved parameters win over the user's prior in-session edits of
          // the standalone script — opening a campaign should show the
          // campaign's configured values, not whatever the user happened to
          // last type in the script-only view.
          const merged = { ...baseParams, ...dbParams };
          if (Object.keys(merged).length > 0) {
            paramUpdates[key] = merged;
          }
        }
      });
    });

    if (Object.keys(analysisUpdates).length) setScriptAnalysisCache(prev => ({ ...prev, ...analysisUpdates }));
    if (Object.keys(paramUpdates).length) setScriptParameterCache(prev => ({ ...prev, ...paramUpdates }));
  }, [
    getCampaignScopeId,
    getCampaignScriptKey,
    getContainedScriptsForCampaign,
    scriptAnalysisCache,
    scriptParameterCache,
    selectedCampaignConfig,
    selectedCampaignExecutable,
    selectedCampaignExecutableItems,
  ]);

  const isExecutableCompatibleWithCurrentSelection = useCallback((item: ExecutableItem) => {
    if (selectedDevices.size === 0) {
      return true;
    }

    // When a script/testcase doesn't declare target_rules, treat it as
    // compatible with everything (host- or device-selection) instead of
    // hiding it — otherwise legacy scripts silently disappear from the
    // executable list.
    const rules = item.target_rules || { target_type: 'all', host_os: 'all', device_model: 'all' };

    return Array.from(selectedDevices.keys()).some((key) =>
      isTargetKeyCompatibleWithRules(key, allHosts, rules),
    );
  }, [selectedDevices, allHosts]);

  const isCampaignCompatibleWithCurrentSelection = useCallback((item: CampaignExecutableItem) => {
    if (selectedDevices.size === 0) {
      return true;
    }
    const rules = item.compatibility_rules || [];
    if (rules.length === 0) {
      return true;
    }
    return Array.from(selectedDevices.keys()).some((key) =>
      rules.some((rule) => isTargetKeyCompatibleWithRules(key, allHosts, rule)),
    );
  }, [selectedDevices, allHosts]);

  // Prune selected targets when the executable changes to something incompatible.
  useEffect(() => {
    if (browserTab === 'tests' && !selectedExecutable) {
      return;
    }
    if (browserTab === 'campaigns') {
      if (!selectedCampaignExecutable) return;
      const rules = selectedCampaignExecutable?.compatibility_rules || [];
      // No rules = compatible with all targets, skip filtering
      if (rules.length === 0) return;
      filterTargetKeys((key) => rules.some((rule) => isTargetKeyCompatibleWithRules(key, allHosts, rule)));
      return;
    }
    filterTargetKeys((key) => isTargetKeyCompatibleWithRules(key, allHosts, selectedExecutableRules));
  }, [browserTab, selectedExecutable, selectedCampaignExecutable, selectedExecutableRules, allHosts, filterTargetKeys]);

  // Normalize the selected target key shape to match the current panel mode so
  // the target panel, selected-items panel, and execution logic all read the
  // same source of truth.
  // Skip in campaign mode — campaigns accept any target; the filter effect above handles pruning.
  useEffect(() => {
    if (browserTab === 'campaigns') return;

    reconcileTargets((prev) => {
      const next = new Map<string, string>();

      prev.forEach((ui, key) => {
        const [hostName, rawDeviceId] = key.split(':');
        if (!hostName) {
          return;
        }

        if (isHostSelectionMode) {
          const normalizedHostKey = `${hostName}:`;
          if (
            !next.has(normalizedHostKey) &&
            isTargetKeyCompatibleWithRules(normalizedHostKey, allHosts, selectedExecutableRules)
          ) {
            next.set(normalizedHostKey, ui);
          }
          return;
        }

        const normalizedDeviceId = getExecutionDeviceId(rawDeviceId);
        const normalizedDeviceKey = `${hostName}:${normalizedDeviceId}`;
        if (
          normalizedDeviceId !== 'host' &&
          isTargetKeyCompatibleWithRules(normalizedDeviceKey, allHosts, selectedExecutableRules)
        ) {
          next.set(normalizedDeviceKey, ui);
        }
      });

      return next;
    });
  }, [allHosts, browserTab, isHostSelectionMode, reconcileTargets, selectedExecutableRules]);

  // Clear the selected executable if the current target selection makes it impossible to run.
  useEffect(() => {
    if (browserTab === 'campaigns') {
      if (!selectedCampaignExecutable) {
        return;
      }
      if (isCampaignCompatibleWithCurrentSelection(selectedCampaignExecutable)) {
        return;
      }
      setSelectedCampaignExecutable(null);
      setSelectedCampaignConfig(null);
      return;
    }
    if (!selectedExecutable) {
      return;
    }
    if (isExecutableCompatibleWithCurrentSelection(selectedExecutable)) {
      return;
    }
    setSelectedExecutable(null);
    setSelectedScript('');
  }, [browserTab, selectedExecutable, selectedCampaignExecutable, isExecutableCompatibleWithCurrentSelection, isCampaignCompatibleWithCurrentSelection]);


  // Get selected + running targets for stream display
  const visibleStreamTargets = useMemo(() => {
    const dedupedByTarget = new Map<
      string,
      { hostName: string; deviceId: string; userinterface?: string }
    >();

    const addTarget = (deviceKey: string) => {
      const [hostName, rawDeviceId] = deviceKey.split(':');
      if (!hostName) return;

      const normalizedDeviceId = getExecutionDeviceId(rawDeviceId);
      const normalizedKey = `${hostName}:${normalizedDeviceId}`;
      const existing = dedupedByTarget.get(normalizedKey);
      const selectedUi = selectedDevices.get(deviceKey) || '';

      // Keep one stream per normalized host:device key, but preserve any selected UI value if present.
      dedupedByTarget.set(normalizedKey, {
        hostName,
        deviceId: normalizedDeviceId,
        userinterface: selectedUi || existing?.userinterface || '',
      });
    };

    selectedDevices.forEach((_ui, deviceKey) => addTarget(deviceKey));
    runningTargetKeys.forEach((deviceKey) => addTarget(deviceKey));

    return Array.from(dedupedByTarget.values());
  }, [selectedDevices, runningTargetKeys]);

  // Auto stream visibility behavior:
  // - Collapse when there are no visible stream targets
  // - Never force-open on execution start; respect the user's manual choice
  useEffect(() => {
    if (visibleStreamTargets.length === 0) {
      setStreamsExpanded(false);
    }
  }, [visibleStreamTargets.length]);


  const handleAbortRunningTargets = async () => {
    const runningExecutions = executions.filter((exec) => exec.status === 'running');
    if (runningExecutions.length === 0) {
      showInfo('No running targets to abort');
      return;
    }

    const uniqueTargets = new Set<string>();
    runningExecutions.forEach((exec) => {
      uniqueTargets.add(buildTargetKey(exec.hostName, exec.deviceId));
    });

    const targets = Array.from(uniqueTargets);
    showInfo(`Abort requested for ${targets.length} running target(s)`);

    const abortResults = await Promise.all(
      targets.map(async (targetKey) => {
        const [hostName, deviceId] = targetKey.split(':');
        const effectiveDeviceId = getExecutionDeviceId(deviceId);
        const hasTestcaseExecution = runningExecutions.some(
          (exec) =>
            buildTargetKey(exec.hostName, exec.deviceId) === targetKey &&
            exec.executionType === 'testcase',
        );
        const abortEndpoint = hasTestcaseExecution
          ? '/server/testcase/abortRunning'
          : '/server/script/abortRunning';
        try {
          const response = await fetch(buildServerUrl(abortEndpoint), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ host_name: hostName, device_id: effectiveDeviceId }),
          });
          const payload = await response.json();
          return Boolean(response.ok && payload?.success);
        } catch {
          return false;
        }
      }),
    );

    setExecutions((prev) => prev.map((exec) => {
      const key = buildTargetKey(exec.hostName, exec.deviceId);
      if (exec.status === 'running' && targets.includes(key)) {
        // Cancel the background promise so polling/socket wait stops immediately.
        const controller = executionAbortControllers.current.get(exec.id);
        if (controller) {
          controller.abort();
          executionAbortControllers.current.delete(exec.id);
        }
        const completedAtRaw = new Date().toISOString();
        return {
          ...exec,
          status: 'aborted',
          completedAtRaw,
          endTime: formatToLocalTimeShort(completedAtRaw),
        };
      }
      return exec;
    }));

    const successCount = abortResults.filter(Boolean).length;
    if (successCount === targets.length) {
      showSuccess(`Aborted ${successCount} running target(s)`);
    } else {
      showError(`Abort partial: ${successCount}/${targets.length} target(s)`);
    }
  };

  // Load available scripts from virtualpytest/scripts folder
  useEffect(() => {
    const loadScripts = async () => {
      // Prevent duplicate calls in React Strict Mode
      if (isLoadingScriptsRef.current) {
        console.log('[@RunTests] Script loading already in progress, skipping duplicate call');
        return;
      }
      
      isLoadingScriptsRef.current = true;
      setLoadingScripts(true);
      
      try {
        // Pre-load the identity map so getScriptDisplayName can resolve prefix + display names
        ensureScriptIdentityMap();

        console.log('[@RunTests] Loading scripts from API...');
        const response = await fetch(buildServerUrl('/server/script/list'));
        
        if (!response.ok) {
          throw new Error(`API returned ${response.status}`);
        }
        
        const data = await response.json();

        if (data.success) {
          setAvailableScripts(data.scripts || []);
          
          // Store AI test case metadata for display
          if (data.ai_test_cases_info) {
            setAiTestCasesInfo(data.ai_test_cases_info);
          }

          console.log('[@RunTests] Scripts loaded successfully:', (data.scripts || []).length);
        } else {
          // API returned success: false - this is an actual error
          throw new Error(data.error || 'API returned success: false');
        }
      } catch (error) {
        showError('Failed to load available scripts');
        console.error('Error loading scripts:', error);
      } finally {
        setLoadingScripts(false);
        isLoadingScriptsRef.current = false;
      }
    };

    loadScripts();
  }, [showError]); // Remove selectedScript dependency - no need to reload scripts when selection changes

  useEffect(() => {
    loadCampaignExecutables();
  }, [loadCampaignExecutables]);

  useEffect(() => {
    if (browserTab === 'campaigns') {
      loadCampaignExecutables();
    }
  }, [browserTab, loadCampaignExecutables]);

  useEffect(() => {
    const isRunView = (
      location.pathname.startsWith('/run/tests') ||
      location.pathname.startsWith('/test-execution/run-tests')
    );
    if (isRunView && browserTab === 'campaigns') {
      loadCampaignExecutables();
    }
  }, [browserTab, loadCampaignExecutables, location.pathname]);

  // Handle pre-selection from TestCase page
  useEffect(() => {
    const handlePreSelection = () => {
      const preselectedScript = localStorage.getItem('preselected_script');
      const fromTestCase = localStorage.getItem('preselected_from_testcase');
      
      if (fromTestCase === 'true' && preselectedScript && availableScripts.includes(preselectedScript)) {
        // Set the script and open the wizard to show pre-selection
        setSelectedScript(preselectedScript);
        
        // TODO: Auto-select compatible device/host based on userinterface
        // For now, user still needs to select device manually
        
        // Clear the localStorage flags
        localStorage.removeItem('preselected_script');
        localStorage.removeItem('preselected_userinterface');
        localStorage.removeItem('preselected_from_testcase');
        
        // Show toast to inform user
        showSuccess(`Pre-selected AI test case: ${getScriptDisplayName(preselectedScript, aiTestCasesInfo)}`);
      }
    };

    // Only run after scripts are loaded
    if (availableScripts.length > 0) {
      handlePreSelection();
    }
  }, [availableScripts, showSuccess]);

  // Cleanup streams when component unmounts
  useEffect(() => {
    return () => {
      console.log('[@RunTests] Component unmounting, stopping all streams');
    };
  }, []);





  // Helper function to quote parameter values that need it (contain spaces or special chars)
  const quoteIfNeeded = (value: string): string => {
    // If value contains spaces, quotes, or special shell characters, wrap it in double quotes
    if (/[\s"'`$\\()&|;<>]/.test(value)) {
      // Escape any existing double quotes and backslashes
      const escaped = value.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
      return `"${escaped}"`;
    }
    return value;
  };

  // Open R2 URL with automatic signed URL generation (handles both public and private modes)
  const handleOpenR2Url = async (url: string) => {
    try {
      await openR2Url(url);
    } catch (error) {
      console.error('[@RunTests] Failed to open R2 URL:', error);
      showError('Failed to open file. Please try again.');
    }
  };

  const getConfiguredUserinterface = () =>
    (parameterValues.userinterface || parameterValues.userinterface_name || '').trim();

  const buildParameterString = (scriptId: string, deviceHost?: string, deviceId?: string, deviceKey?: string) => {
    const paramStrings: string[] = [];

    // Use provided device info or fall back to first selected device
    const targetHost = deviceHost || firstSelectedDevice.hostName;
    const targetDevice = deviceId || firstSelectedDevice.deviceId;
    const resolvedDeviceKey = resolveSelectedTargetKey(targetHost, targetDevice || undefined);
    const targetAnalysis = getScriptAnalysisFor(scriptId);

    // Add parameters from script analysis
    // ✅ SKIP framework params: host, device (added at the end)
    if (targetAnalysis) {
      targetAnalysis.parameters.forEach((param) => {
        const value = getEffectiveParamValue(scriptId, resolvedDeviceKey || deviceKey, param.name).trim();

        // Skip framework parameters - they're added at the end
        if (param.name === 'host' || param.name === 'device') {
          return;
        }
        
        if (value) {
          if (param.type === 'positional') {
            paramStrings.push(quoteIfNeeded(value));
          } else {
            paramStrings.push(`--${param.name} ${quoteIfNeeded(value)}`);
          }
        }
      });
    }

    // ✅ Always add framework parameters at the end: --host, --device
    if (targetHost) {
      paramStrings.push(`--host ${quoteIfNeeded(targetHost)}`);
    }
    if (targetDevice) {
      paramStrings.push(`--device ${quoteIfNeeded(targetDevice)}`);
    }
    // Dev/prod userinterface targeting (framework arg, not a script param —
    // like --host/--device). Only emitted when a prod entry was picked.
    const uiModeValue = getEffectiveParamValue(scriptId, resolvedDeviceKey || deviceKey, 'ui_mode').trim();
    if (uiModeValue === 'prod') {
      paramStrings.push('--ui-mode prod');
    }

    return paramStrings.join(' ');
  };



  // Helper function to determine test result from script output
  const determineTestResult = (result: any): 'success' | 'failure' | undefined => {
    // Use the script_success field provided by the host - this is the authoritative result
    if (result.script_success !== undefined && result.script_success !== null) {
      return result.script_success ? 'success' : 'failure';
    }
    
    // If no script_success field, script execution likely failed at system level
    if (result.exit_code !== undefined && result.exit_code !== 0) {
      return 'failure';
    }
    
    // If script completed but no script_success field, leave undefined
    return undefined;
  };

  useEffect(() => {
    const loadTestcaseVersions = async () => {
      if (browserTab !== 'tests' || selectedExecutable?.type !== 'testcase' || !selectedExecutable.id) {
        setTestcaseVersionOptions([{ key: 'latest', label: 'Latest', versionNumber: null }]);
        setSelectedTestcaseVersionKey('latest');
        setTestcaseVersionSnapshots({});
        return;
      }

      try {
        const response = await api.get<{ success: boolean; versions: VersionSnapshotRecord[] }>(
          buildServerUrl(`/server/testcase/${selectedExecutable.id}/versions`),
        );
        if (!response?.success || !Array.isArray(response.versions) || response.versions.length === 0) {
          throw new Error('Failed to load testcase versions');
        }

        const nextSnapshots: Record<string, VersionSnapshotRecord> = {};
        const nextOptions: CompactVersionOption[] = [];
        response.versions.slice(0, 4).forEach((version, index) => {
          const key = index === 0 ? 'latest' : `v${version.version_number}`;
          nextSnapshots[key] = version;
          nextOptions.push({
            key,
            label: index === 0 ? 'Latest' : `v${version.version_number}`,
            versionNumber: index === 0 ? null : version.version_number,
          });
        });

        setTestcaseVersionSnapshots(nextSnapshots);
        setTestcaseVersionOptions(nextOptions);
        setSelectedTestcaseVersionKey('latest');
      } catch (error) {
        console.warn('[@RunTests] Failed to load testcase versions:', error);
        setTestcaseVersionOptions([{ key: 'latest', label: 'Latest', versionNumber: null }]);
        setSelectedTestcaseVersionKey('latest');
        setTestcaseVersionSnapshots({});
      }
    };

    void loadTestcaseVersions();
  }, [api, browserTab, selectedExecutable]);

  // Load test case graph from database (with caching) - returns full testcase data
  const loadTestCaseGraph = async (
    testcaseId: string,
    versionKey: string = 'latest',
  ): Promise<{ graph: any; scriptConfig: any; versionNumber: number | null } | null> => {
    const cacheKey = `${testcaseId}@${versionKey}`;
    // Check cache first
    if (testCaseGraphCache[cacheKey]) {
      console.log(`[@RunTests] Using cached graph for test case: ${cacheKey}`);
      return testCaseGraphCache[cacheKey];
    }
    
    console.log(`[@RunTests] Loading graph for test case: ${cacheKey}`);
    
    try {
      let graph: any;
      let versionNumber: number | null = null;

      if (versionKey !== 'latest') {
        const snapshot = testcaseVersionSnapshots[versionKey];
        if (!snapshot?.graph_json) {
          showError('Selected testcase version is unavailable');
          return null;
        }
        graph = snapshot.graph_json;
        versionNumber = snapshot.version_number ?? null;
      } else {
        const response = await getTestCase(testcaseId);
        if (!response.success || !response.testcase) {
          showError(`Failed to load test case: ${response.error || 'Unknown error'}`);
          return null;
        }
        graph = response.testcase.graph_json;
        versionNumber = testcaseVersionSnapshots.latest?.version_number ?? null;
      }
      
      // Extract script config (inputs, outputs, variables) from graph
      const scriptConfig = graph.scriptConfig || {
        inputs: [],
        outputs: [],
        variables: []
      };
      
      const cacheData = { graph, scriptConfig, versionNumber };
      
      // Cache the data
      setTestCaseGraphCache(prev => ({ ...prev, [cacheKey]: cacheData }));
      
      return cacheData;
    } catch (error) {
      console.error('[@RunTests] Error loading test case graph:', error);
      showError(`Failed to load test case: ${error}`);
      return null;
    }
  };

  const splitDevicesByLockState = async <T extends { hostName: string; deviceId: string }>(devices: T[]) => {
    const lockChecks = await Promise.all(
      devices.map(async (device) => {
        try {
          const effectiveDeviceId = getExecutionDeviceId(device.deviceId);
          const response = await fetch(buildServerUrl('/server/control/checkLock'), {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({
              host_name: device.hostName,
              device_id: effectiveDeviceId,
            }),
          });
          const data = await response.json();
          return {
            device,
            locked: Boolean(data?.is_locked),
            lockInfo: data?.lock_info,
          };
        } catch {
          // Fail-open on transient network issues; backend lock acquisition still arbitrates.
          return { device, locked: false, lockInfo: null };
        }
      }),
    );

    const runnable: T[] = [];
    const blocked: Array<{ device: T; lockInfo: any }> = [];
    lockChecks.forEach((entry) => {
      if (entry.locked) {
        blocked.push({ device: entry.device, lockInfo: entry.lockInfo });
      } else {
        runnable.push(entry.device);
      }
    });

    return { runnable, blocked };
  };

  const createOneShotScriptDeployment = useCallback(async ({
    scriptName,
    hostName,
    deviceId,
    parameters,
    virtualScriptId,
    environment,
  }: {
    scriptName: string;
    hostName: string;
    deviceId: string;
    parameters: string;
    // Virtual-script deployments: which dev/test/prod row to run. Absent for
    // disk scripts — the deployment scheduler treats that as unchanged.
    virtualScriptId?: string;
    environment?: 'dev' | 'test' | 'prod';
  }) => {
    const deviceKey = resolveSelectedTargetKey(hostName, deviceId);
    return createDeployment({
      name: `${scriptName}_${hostName}_${deviceId}_${Date.now()}`,
      host_name: hostName,
      device_id: deviceId,
      script_name: scriptName,
      userinterface_name: selectedDevices.get(deviceKey) || '',
      parameters,
      device_info: deviceInfoByDevice[deviceKey],
      cron_expression: '0 0 1 1 *',
      max_executions: 1,
      virtual_script_id: virtualScriptId,
      environment,
    });
  }, [createDeployment, selectedDevices, deviceInfoByDevice]);

  const queueScriptExecutionFallback = useCallback(async ({
    executionId,
    scriptName,
    hostName,
    deviceId,
    parameters,
    virtualScriptId,
    environment,
  }: {
    executionId: string;
    scriptName: string;
    hostName: string;
    deviceId: string;
    parameters: string;
    virtualScriptId?: string;
    environment?: 'dev' | 'test' | 'prod';
  }) => {
    const completedAtRaw = new Date().toISOString();
    const endTime = formatToLocalTimeShort(completedAtRaw);

    setExecutions((prev) => prev.map((item) => item.id === executionId ? {
      ...item,
      endTime: undefined,
      completedAtRaw: undefined,
      status: 'queued',
      testResult: undefined,
      reportUrl: undefined,
      logsUrl: undefined,
    } : item));

    const deploymentResult = await createOneShotScriptDeployment({
      scriptName,
      hostName,
      deviceId,
      parameters,
      virtualScriptId,
      environment,
    });

    const hostDevices = getDevicesFromHost(hostName);
    const deviceObject = hostDevices.find((device) => device.device_id === deviceId);
    const deviceDisplayName = deviceObject?.device_name || deviceId;
    const targetLabel = formatTargetLabel(hostName, deviceId, deviceDisplayName);

    if (deploymentResult?.success) {
      setExecutions((prev) => prev.filter((item) => item.id !== executionId));
      void refreshExecutions();
      showInfo(`${targetLabel} : device locked, queued to run when free`);
      return true;
    }

    setExecutions((prev) => prev.map((item) => item.id === executionId ? {
      ...item,
      completedAtRaw,
      endTime,
      status: 'skipped',
      testResult: undefined,
      reportUrl: undefined,
      logsUrl: undefined,
    } : item));

    showError(`${targetLabel} : device locked, queue fallback failed`);
    return false;
  }, [createOneShotScriptDeployment, getDevicesFromHost, showError, showInfo]);


  const handleExecuteScript = async () => {
    // Determine if this is a script or test case execution
    const isTestCase = selectedExecutable?.type === 'testcase';
    
    console.log(`[@RunTests] Starting execution - Type: ${isTestCase ? 'TESTCASE' : 'SCRIPT'}`);
    
    if (isTestCase) {
      // Route to test case execution
      await handleExecuteTestCase();
    } else {
      // Route to script execution (existing logic)
      await handleExecuteScriptLegacy();
    }
  };
  
  // Test case execution handler (reusing useTestCaseExecution)
  const handleExecuteTestCase = async () => {
    if (!selectedExecutable || !selectedScript) {
      showError('Please select a test case');
      return;
    }

    const selectedPinnedTestcaseVersion =
      selectedTestcaseVersionKey === 'latest'
        ? testcaseVersionSnapshots.latest?.version_number ?? null
        : testcaseVersionSnapshots[selectedTestcaseVersionKey]?.version_number ?? null;

    // Build complete device list from selectedDevices Map
    interface DeviceExecution {
      hostName: string;
      deviceId: string;
      deviceModel: string;  // Add deviceModel
    }
    const allDevices: DeviceExecution[] = [];

    // Iterate over selected runnable devices (running/execution-locked targets are skipped)
    selectedRunnableTargetKeys.forEach((deviceKey) => {
      const [hostName, deviceId] = deviceKey.split(':');

      // Get device model
      const hostDevices = getDevicesFromHost(hostName);
      const deviceObject = hostDevices.find(d => d.device_id === deviceId);
      const deviceModel = deviceObject?.device_model || 'unknown';

      allDevices.push({
        hostName,
        deviceId,
        deviceModel: deviceModel
      });
    });

    if (allDevices.length === 0) {
      showError('No runnable target selected (current selections are running or execution-locked)');
      return;
    }

    const lockSplit = await splitDevicesByLockState(allDevices);

    // Queue locked devices via deployment scheduler
    if (lockSplit.blocked.length > 0 && selectedExecutable) {
      if (selectedTestcaseVersionKey !== 'latest') {
        showError('Historical testcase versions only support immediate runs on currently available devices');
      } else {
      let queuedCount = 0;
      for (const { device } of lockSplit.blocked) {
        const deviceId = device.deviceId || 'host';
        const deviceKey = resolveSelectedTargetKey(device.hostName, deviceId);
        const result = await createDeployment({
          name: `${selectedExecutable.name}_${device.hostName}_${deviceId}_${Date.now()}`,
          host_name: device.hostName,
          device_id: deviceId,
          script_name: selectedScript,
          userinterface_name: selectedDevices.get(deviceKey) || '',
          parameters: '',
          device_info: deviceInfoByDevice[deviceKey],
          cron_expression: '0 0 1 1 *',
          max_executions: 1,
        });
        if (result?.success) {
          queuedCount++;
        }
      }
      if (queuedCount > 0) {
        void refreshExecutions();
        showSuccess(`Queued ${queuedCount} locked device(s) — will run when free`);
      }
      }
    }

    // Run unlocked devices directly
    if (lockSplit.runnable.length > 0) {
      await executeTestCaseOnDevices(lockSplit.runnable, selectedPinnedTestcaseVersion);
    }
  };

  const executeTestCaseOnDevices = async (
    allDevices: Array<{ hostName: string; deviceId: string; deviceModel: string }>,
    testcaseVersionNumber: number | null,
    // Optional preloaded testcase config so rerun can skip loadTestCaseGraph
    // and use the cached graph/inputs/vars captured at first launch.
    preloaded?: {
      executionGraph: any;
      scriptInputs: any[];
      scriptVariables: any[];
      scriptConfigForExecution: { inputs: any[]; variables: any[] };
      versionNumber: number | null;
      testcaseName: string;
      testcaseId: string;
    },
    // User-supplied values for non-protected scriptConfig inputs (from the
    // Run-with-inputs dialog, or replayed from a rerunPayload). undefined =
    // not collected yet — if the testcase declares such inputs, the dialog
    // opens and re-invokes this function with the values.
    testcaseInputValues?: Record<string, any>,
  ) => {
    if (!preloaded && (!selectedExecutable || !selectedScript)) return;

    let executionGraph: any;
    let scriptInputs: any[];
    let scriptVariables: any[];
    let scriptConfigForExecution: { inputs: any[]; variables: any[] };
    let versionNumber: number | null;
    let testcaseName: string;
    let testcaseId: string;

    if (preloaded) {
      executionGraph = preloaded.executionGraph;
      scriptInputs = preloaded.scriptInputs;
      scriptVariables = preloaded.scriptVariables;
      scriptConfigForExecution = preloaded.scriptConfigForExecution;
      versionNumber = preloaded.versionNumber;
      testcaseName = preloaded.testcaseName;
      testcaseId = preloaded.testcaseId;
    } else {
      // Load test case graph
      const testCaseData = await loadTestCaseGraph(selectedScript, selectedTestcaseVersionKey);
      if (!testCaseData) {
        return; // Error already shown in loadTestCaseGraph
      }
      const { graph, scriptConfig, versionNumber: loadedVersion } = testCaseData;

      // Extract script inputs and variables for variable resolution
      scriptInputs = scriptConfig.inputs || [];
      scriptVariables = scriptConfig.variables || [];
      scriptConfigForExecution = { inputs: scriptConfig.inputs, variables: scriptConfig.variables };

      // ✅ CRITICAL: Rebuild graph with scriptConfig (EXACT SAME as TestCaseBuilder line 496-520)
      // TestCaseBuilder doesn't use graph from DB directly - it rebuilds it!
      executionGraph = {
        nodes: graph.nodes,
        edges: graph.edges,
        scriptConfig: {
          inputs: scriptInputs,
          outputs: scriptConfig.outputs || [],
          variables: scriptVariables,
          metadata: {
            mode: 'append',
            fields: scriptConfig.metadata?.fields || scriptConfig.metadata || []
          }
        }
      };
      versionNumber = loadedVersion ?? null;
      testcaseName = selectedExecutable!.name;
      testcaseId = selectedScript;
    }

    // Parameterized testcase: non-protected scriptConfig inputs need values
    // before launch. Open the Run-with-inputs dialog (defaults pre-filled) and
    // re-enter with the chosen values.
    const promptableInputs = (scriptConfigForExecution.inputs || []).filter(
      (input: any) => input && !input.protected,
    );
    if (promptableInputs.length > 0 && testcaseInputValues === undefined) {
      setTestcaseRunPrompt({
        inputs: promptableInputs,
        testcaseName,
        pending: {
          allDevices,
          testcaseVersionNumber,
          preloaded: {
            executionGraph,
            scriptInputs,
            scriptVariables,
            scriptConfigForExecution,
            versionNumber,
            testcaseName,
            testcaseId,
          },
        },
      });
      return;
    }

    // Create execution records upfront
    const executions = allDevices.map((device) => {
      const hostDevices = getDevicesFromHost(device.hostName);
      const deviceObject = hostDevices.find(d => d.device_id === device.deviceId);
      const deviceModel = deviceObject?.device_model || 'unknown';
      const startedAtRaw = new Date().toISOString();

      return {
        id: `exec_${Date.now()}_${device.hostName}_${device.deviceId}`,
        executionType: 'testcase' as const,
        scriptName: testcaseName,
        hostName: device.hostName,
        deviceId: device.deviceId,
        deviceModel: deviceModel,
        startedAtRaw,
        startTime: formatToLocalTimeShort(startedAtRaw),
        status: 'running' as const,
        parameters: '', // Test cases don't have CLI parameters
        // Capture launch-time config so this row's rerun icon replays the
        // exact same graph/inputs/variables without refetching.
        rerunPayload: {
          type: 'testcase' as const,
          scriptName: testcaseName,
          hostName: device.hostName,
          deviceId: device.deviceId,
          deviceModel,
          executionGraph,
          scriptInputs,
          scriptVariables,
          testcaseVersionNumber: versionNumber ?? testcaseVersionNumber,
          inputValues: testcaseInputValues,
        },
      };
    });

    setExecutions(prev => [...executions, ...prev]);

    if (allDevices.length === 1) {
      const hostDevices = getDevicesFromHost(allDevices[0].hostName);
      const deviceObject = hostDevices.find(dev => dev.device_id === allDevices[0].deviceId);
      const deviceDisplayName = deviceObject?.device_name || allDevices[0].deviceId;
      const targetLabel = formatTargetLabel(allDevices[0].hostName, allDevices[0].deviceId, deviceDisplayName);
      showInfo(`Test case "${testcaseName}" started on ${targetLabel}`);
    } else {
      showInfo(`Test case "${testcaseName}" started on ${allDevices.length} devices`);
    }

    try {
      // Execute on all devices concurrently
      const executionPromises = executions.map(async (exec, index) => {
        const device = allDevices[index];
        const configuredUserinterface = getConfiguredUserinterface();

        try {
          console.log(`[@RunTests] Executing test case on ${device.hostName}:${device.deviceId}`);
          console.log(`[@RunTests] 🔍 DEBUG - Graph structure:`);
          console.log('  • Graph has scriptConfig?', !!executionGraph?.scriptConfig);
          console.log('  • Graph.scriptConfig:', JSON.stringify(executionGraph?.scriptConfig, null, 2));
          console.log('  • Passing scriptInputs:', scriptInputs.length, 'items');
          console.log('  • Passing scriptVariables:', scriptVariables.length, 'items');
          console.log('  • Passing userinterface:', configuredUserinterface);

          // Stamp run-time input values onto the graph copy: protected inputs are
          // filled from the execution environment per device; user-supplied values
          // (Run-with-inputs dialog) override defaults. The backend resolves
          // {placeholders} from these — no client-side graph resolution.
          const runValues: Record<string, any> = { ...(testcaseInputValues || {}) };
          runValues['device_model_name'] = device.deviceModel || 'unknown';
          runValues['host_name'] = device.hostName;
          runValues['device_name'] = device.deviceId;
          runValues['userinterface_name'] = configuredUserinterface;
          const stampedGraph = stampInputValues(executionGraph, runValues);

          const result = await executeTestCase(
            stampedGraph,
            device.deviceId,
            device.hostName,
            configuredUserinterface,
            testcaseName,
            (versionNumber ?? testcaseVersionNumber)
              ? {
                  testcase_id: testcaseId,
                  testcase_version: versionNumber ?? testcaseVersionNumber,
                }
              : {
                  testcase_id: testcaseId,
                },
          );
          
          // Determine result
          const executionStatus = result.success ? 'completed' : 'failed';
          const testResult = result.result_type === 'success' ? 'success' : 
                           result.result_type === 'failure' ? 'failure' : undefined;
          
          // Update execution record
          const completedAtRaw = new Date().toISOString();
          setExecutions(prev => prev.map(e => 
            e.id === exec.id ? {
              ...e,
              completedAtRaw,
              endTime: formatToLocalTimeShort(completedAtRaw),
              status: executionStatus,
              testResult: testResult,
              reportUrl: result.report_url,
              logsUrl: result.logs_url,
              deviceModel: e.deviceModel,
            } : e
          ));
          
          // Show completion toast
          const hostDevices = getDevicesFromHost(device.hostName);
          const deviceObject = hostDevices.find(dev => dev.device_id === device.deviceId);
          const deviceDisplayName = deviceObject?.device_name || device.deviceId;
          const deviceLabel = formatTargetLabel(device.hostName, device.deviceId, deviceDisplayName);
          
          if (result.success) {
            if (testResult === 'success') {
              showSuccess(`${deviceLabel} : script PASSED`);
            } else if (testResult === 'failure') {
              showError(`${deviceLabel} : script FAILED`);
            } else {
              showSuccess(`${deviceLabel} : script PASSED`);
            }
          } else {
            showError(`${deviceLabel} : script FAILED`);
          }
          
          return result;
        } catch (error) {
          console.error(`[@RunTests] Error executing test case on ${device.hostName}:${device.deviceId}:`, error);
          
          // Update execution record as failed
          const completedAtRaw = new Date().toISOString();
          setExecutions(prev => prev.map(e => 
            e.id === exec.id ? {
              ...e,
              completedAtRaw,
              endTime: formatToLocalTimeShort(completedAtRaw),
              status: 'failed',
              deviceModel: e.deviceModel,
            } : e
          ));
          
          return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
        }
      });
      
      // Wait for all executions to complete
      const results = await Promise.all(executionPromises);
      
      // Final summary
      const successCount = results.filter((r: any) => r.success).length;
      
      if (allDevices.length === 1) {
        // Single device summary already shown
      } else {
        // Multi-device final summary
        if (successCount === allDevices.length) {
          showSuccess(`🎉 All ${allDevices.length} devices completed successfully!`);
        } else if (successCount > 0) {
          showInfo(`📊 Final: ${successCount}/${allDevices.length} devices successful`);
        } else {
          showError(`💥 All ${allDevices.length} devices failed`);
        }
      }
      
    } catch (error) {
      showError(`Execution failed: ${error}`);
      // Mark remaining as aborted
      executions.forEach(exec => {
        const completedAtRaw = new Date().toISOString();
        setExecutions(prev => prev.map(e => 
          e.id === exec.id && e.status === 'running' ? { 
            ...e, 
            status: 'aborted', 
            completedAtRaw,
            endTime: formatToLocalTimeShort(completedAtRaw),
            deviceModel: e.deviceModel,
          } : e
        ));
      });
    }
  };

  // Script execution handler (existing logic renamed)
  const handleExecuteScriptLegacy = async () => {
    const validation = getScriptValidation();
    if (!validation.valid) {
      showError(`Missing required parameters: ${validation.errors.join(', ')}`);
      return;
    }

    // Build complete device list from selectedDevices Map
    interface DeviceExecution {
      hostName: string;
      deviceId: string;
    }
    const allDevices: DeviceExecution[] = [];

    // Iterate over selected runnable devices (running/execution-locked targets are skipped)
    selectedRunnableTargetKeys.forEach((deviceKey) => {
      const [hostName, deviceId] = deviceKey.split(':');

      allDevices.push({
        hostName,
        deviceId,
      });
    });

    if (allDevices.length === 0 || !selectedScript) {
      showError('Please select a script and at least one runnable target');
      return;
    }

    const lockSplit = await splitDevicesByLockState(allDevices);

    // Queue locked devices via deployment scheduler (same mechanism as multi-script runs)
    if (lockSplit.blocked.length > 0) {
      let queuedCount = 0;
      const itemEnv = getItemEnvironment(selectedExecutable);
      for (const { device } of lockSplit.blocked) {
        const deviceId = device.deviceId || 'host';
        const deviceKey = resolveSelectedTargetKey(device.hostName, deviceId);
        const paramsKey = selectedExecutable?.instanceId || selectedScript;
        const parameters = buildParameterString(paramsKey, device.hostName, deviceId, deviceKey);
        const result = await createOneShotScriptDeployment({
          scriptName: selectedScript,
          hostName: device.hostName,
          deviceId,
          parameters,
          virtualScriptId: resolveVirtualScriptId(selectedExecutable, itemEnv),
          environment: itemEnv,
        });
        if (result?.success) {
          queuedCount++;
        }
      }
      if (queuedCount > 0) {
        void refreshExecutions();
        showSuccess(`Queued ${queuedCount} locked device(s) — will run when free`);
      }
    }

    // Run unlocked devices directly
    if (lockSplit.runnable.length > 0) {
      await executeScriptOnDevices(lockSplit.runnable);
    }
  };

  const executeScriptOnDevices = async (
    allDevices: Array<{ hostName: string; deviceId: string }>,
    options?: {
      // Rerun path supplies pre-resolved per-device script + parameters,
      // skipping selectedScript / getScriptValidation / buildParameterString.
      // virtualScriptId replays a virtual script's exact DB row (dev/test/prod).
      overrides?: Array<{ scriptName: string; hostName: string; deviceId: string; parameters: string; virtualScriptId?: string }>;
      // Rerun is run-now only: if the device is locked, surface an error
      // toast instead of silently rerouting through the deployment scheduler.
      disableQueueFallback?: boolean;
    },
  ) => {
    const useOverrides = !!options?.overrides;
    if (!useOverrides && !selectedScript) return;

    // Validate parameters only when running from current selection. The
    // rerun path's overrides are already a valid resolved CLI string.
    if (!useOverrides) {
      const validation = getScriptValidation();
      if (!validation.valid) {
        showError(`Parameter validation failed: ${validation.errors.join(', ')}`);
        return;
      }
    }

    // Prepare executions for concurrent processing - build parameters per device
    const executions = useOverrides
      ? options!.overrides!.map((override) => {
          const executionDeviceId = getExecutionDeviceId(override.deviceId);
          return {
            id: `exec_${Date.now()}_${override.hostName}_${executionDeviceId}`,
            scriptName: override.scriptName,
            hostName: override.hostName,
            deviceId: executionDeviceId,
            parameters: override.parameters,
            callbackUrl: scriptCallbackUrl.trim() || undefined,
            forceUnlock: false,
            // Rerun replays an already-resolved row id, so there's no "item" to
            // read a per-script env from — 'prod' here is just the capacity tag.
            environment: 'prod' as const,
            virtualScriptId: override.virtualScriptId,
          };
        })
      : allDevices.map((hostDevice) => {
          const executionDeviceId = getExecutionDeviceId(hostDevice.deviceId);
          const paramsKey = selectedExecutable?.instanceId || selectedScript;
          const itemEnv = getItemEnvironment(selectedExecutable);
          return {
            id: `exec_${Date.now()}_${hostDevice.hostName}_${executionDeviceId}`,
            scriptName: selectedScript,
            hostName: hostDevice.hostName,
            deviceId: executionDeviceId,
            parameters: buildParameterString(
              paramsKey,
              hostDevice.hostName,
              executionDeviceId,
              `${hostDevice.hostName}:${executionDeviceId}`,
            ),
            callbackUrl: scriptCallbackUrl.trim() || undefined,
            forceUnlock: false,
            environment: itemEnv,
            virtualScriptId: resolveVirtualScriptId(selectedExecutable, itemEnv),
          };
        });

    // Create execution records upfront
    const newExecutions: ExecutionRecord[] = executions.map(exec => {
      // Get device model for this execution
      const hostDevices = getDevicesFromHost(exec.hostName);
      const deviceObject = hostDevices.find(device => device.device_id === exec.deviceId);
      const deviceModel = deviceObject?.device_model || 'unknown';
      const startedAtRaw = new Date().toISOString();
      
      return {
        id: exec.id,
        executionType: 'script',
        scriptName: exec.scriptName,
        hostName: exec.hostName,
        deviceId: exec.deviceId,
        deviceModel: deviceModel,
        startedAtRaw,
        startTime: formatToLocalTimeShort(startedAtRaw),
        status: 'running',
        parameters: exec.parameters,
        rerunPayload: {
          type: 'script',
          scriptName: exec.scriptName,
          hostName: exec.hostName,
          deviceId: exec.deviceId,
          parameters: exec.parameters,
          // Replay the exact virtual-script row (dev/test/prod) that ran; absent
          // for disk scripts. Without this a virtual-script rerun would look for a
          // disk file named after the virtual script and fail.
          virtualScriptId: exec.virtualScriptId,
        },
      };
    });

    setExecutions(prev => [...newExecutions, ...prev]);

    // Use the script name actually being executed (not current selection) so
    // rerun toasts name the right script.
    const startedScriptName = executions[0]?.scriptName || selectedScript;

    if (allDevices.length === 1) {
      // Get device name for single device execution toast
      const hostDevices = getDevicesFromHost(allDevices[0].hostName);
      const deviceObject = hostDevices.find(dev => dev.device_id === allDevices[0].deviceId);
      const deviceDisplayName = deviceObject?.device_name || allDevices[0].deviceId;
      const targetLabel = formatTargetLabel(allDevices[0].hostName, allDevices[0].deviceId, deviceDisplayName);
      showInfo(`Script "${startedScriptName}" started on ${targetLabel}`);
    } else {
      showInfo(`Script "${startedScriptName}" started on ${allDevices.length} devices`);
    }

    try {
      const isDeviceLockedConflict = (result: any) => result?.errorType === 'device_locked';
      const didScriptStart = (result: any) =>
        !isDeviceLockedConflict(result) &&
        (Boolean(result.stdout) || Boolean(result.stderr) || result.exit_code !== undefined);

      // LIVE UPDATES: Define callback for real-time completion updates
      const onExecutionComplete = (executionId: string, result: any) => {
        console.log(`[@RunTests] Execution ${executionId} completed with exit_code: ${result.exit_code}`);
        console.log(`[@RunTests] Result details:`, {
          exit_code: result.exit_code,
          report_url: result.report_url,
          logs_url: result.logs_url,
          has_stdout: !!result.stdout,
          stdout_length: result.stdout?.length || 0,
          script_success: result.script_success,
        });
        console.log(`[@RunTests] FULL RESULT OBJECT:`, result);

        const batchExecution = executions.find((exec) => exec.id === executionId);
        if (result?.errorType === 'device_locked' && batchExecution) {
          if (options?.disableQueueFallback) {
            // Rerun path: never queue silently. Mark the row as failed and
            // tell the user the target is locked.
            const completedAtRaw = new Date().toISOString();
            setExecutions((prev) => prev.map((exec) => exec.id === executionId ? {
              ...exec,
              completedAtRaw,
              endTime: formatToLocalTimeShort(completedAtRaw),
              status: 'failed' as const,
              testResult: 'failure' as const,
            } : exec));
            const targetLabel = formatTargetLabel(batchExecution.hostName, batchExecution.deviceId);
            showError(`${targetLabel} : device locked, cannot rerun`);
            return;
          }
          // Replay the exact virtual-script row (dev/test/prod) this run
          // already resolved to — the deployment scheduler resolves
          // virtual_script_id to the right DB row on its own.
          void queueScriptExecutionFallback({
            executionId,
            scriptName: batchExecution.scriptName,
            hostName: batchExecution.hostName,
            deviceId: batchExecution.deviceId,
            parameters: batchExecution.parameters || '',
            virtualScriptId: batchExecution.virtualScriptId,
            environment: batchExecution.environment,
          });
          return;
        }
        
        // Update execution record immediately
        // Determine if script execution completed (vs system error)
        const scriptCompleted = didScriptStart(result);
        const executionStatus = scriptCompleted ? 'completed' : 'failed';
        const testResult = determineTestResult(result);

        console.log(`[@RunTests] Determined status: ${executionStatus}, testResult: ${testResult}, reportUrl: ${result.report_url}`);

        // IMMEDIATE UI UPDATE
        const completedAtRaw = new Date().toISOString();
        setExecutions(prev => prev.map(exec => 
          exec.id === executionId ? {
            ...exec,
            completedAtRaw,
            endTime: formatToLocalTimeShort(completedAtRaw),
            status: executionStatus,
            testResult: testResult,
            reportUrl: result.report_url,
            logsUrl: result.logs_url || (result.report_url ? getLogsUrl(result.report_url) : undefined),
            // Preserve deviceModel when updating
            deviceModel: exec.deviceModel,
          } : exec
        ));


        // Show individual completion toast
        const device = allDevices.find(d => executionId.includes(`${d.hostName}_${d.deviceId}`));
        if (device) {
          // Get device name for display in toast
          const hostDevices = getDevicesFromHost(device.hostName);
          const deviceObject = hostDevices.find(dev => dev.device_id === device.deviceId);
          const deviceDisplayName = deviceObject?.device_name || device.deviceId;
          const deviceLabel = formatTargetLabel(device.hostName, device.deviceId, deviceDisplayName);
          
          if (scriptCompleted) {
            if (testResult === 'success') {
              showSuccess(`${deviceLabel} : script PASSED`);
            } else if (testResult === 'failure') {
              showError(`${deviceLabel} : script FAILED`);
            } else {
              showSuccess(`${deviceLabel} : script PASSED`);
            }
          } else {
            showError(`${deviceLabel} : script FAILED`);
          }
        }
      };

      // Execute with live callback - this waits for ALL to complete before returning
      const results = await executeMultipleScripts(
        executions,
        onExecutionComplete,
        (executionId, taskId) => {
          setExecutions((prev) => prev.map((exec) =>
            exec.id === executionId
              ? { ...exec, backendTaskId: taskId }
              : exec,
          ));
        },
      );

      // Final reconciliation: ensure every execution in this batch is transitioned out of
      // "running" even if a live callback was missed.
      setExecutions(prev =>
        prev.map((exec) => {
          if (!executions.some((batchExec) => batchExec.id === exec.id)) {
            return exec;
          }

          const result = results[exec.id];
          if (!result) {
            return exec;
          }

          if (isDeviceLockedConflict(result)) {
            return exec.status === 'running'
              ? {
                ...exec,
                completedAtRaw: undefined,
                endTime: undefined,
                status: 'queued',
                testResult: undefined,
                reportUrl: undefined,
                logsUrl: undefined,
                deviceModel: exec.deviceModel,
              }
              : exec;
          }

          const scriptCompleted = didScriptStart(result);
          const executionStatus = scriptCompleted ? 'completed' : 'failed';
          const testResult = determineTestResult(result);
          const reportUrl = (result as any).report_url;
          const logsUrl =
            (result as any).logs_url || (reportUrl ? getLogsUrl(reportUrl) : undefined);

          const completedAtRaw = exec.completedAtRaw || new Date().toISOString();
          return {
            ...exec,
            completedAtRaw,
            endTime: exec.endTime || formatToLocalTimeShort(completedAtRaw),
            status: exec.status === 'running' ? executionStatus : exec.status,
            testResult: exec.testResult || testResult,
            reportUrl: exec.reportUrl || reportUrl,
            logsUrl: exec.logsUrl || logsUrl,
            deviceModel: exec.deviceModel,
          };
        }),
      );

      // Final summary (all executions are now complete)
      // Use same logic as individual completion callbacks - count script completions (not system errors)
      const successCount = Object.values(results).filter((r: any) => {
        // Script completed if it actually started and reached a terminal script result
        const scriptCompleted = didScriptStart(r);
        return scriptCompleted;
      }).length;
      
      if (allDevices.length === 1) {
        // Single device summary already shown in callback
      } else {
        // Multi-device final summary
        if (successCount === allDevices.length) {
          showSuccess(`🎉 All ${allDevices.length} devices completed successfully!`);
        } else if (successCount > 0) {
          showInfo(`📊 Final: ${successCount}/${allDevices.length} devices successful`);
        } else {
          showError(`💥 All ${allDevices.length} devices failed`);
        }
      }

    } catch (error) {
      showError(`Execution failed: ${error}`);
      // Mark remaining as aborted
      executions.forEach(exec => {
        const completedAtRaw = new Date().toISOString();
        setExecutions(prev => prev.map(e => 
          e.id === exec.id && e.status === 'running' ? { 
            ...e, 
            status: 'aborted', 
            completedAtRaw,
            endTime: formatToLocalTimeShort(completedAtRaw),
            // Preserve deviceModel when updating
            deviceModel: e.deviceModel,
          } : e
        ));
      });
    }
  };

  // Build the per-device script_configurations snapshot for the currently
  // selected campaign. This is the single source of truth used by both
  // "Run Now" (executeCampaignOnDevices) and "Schedule"
  // (handleConvertToScheduledDeployment) so that scheduled deployments
  // execute with exactly the same configuration the user sees on screen.
  const buildCampaignScriptConfigurationsForDevice = useCallback((
    deviceKey: string,
  ): ScriptConfiguration[] | null => {
    if (!selectedCampaignExecutable) return null;

    if (selectedCampaignExecutable.source === 'db') {
      if (!selectedCampaignConfig) return null;
      return selectedCampaignConfig.script_configurations.map((sc) => {
        const key = getCampaignScriptKey(selectedCampaignConfig.campaign_id, sc.script_name);
        const analysis = getScriptAnalysisFor(key);
        const params: Record<string, string> = { ...(sc.parameters || {}) };
        if (analysis) {
          for (const p of analysis.parameters) {
            if (FRAMEWORK_PARAMS.includes(p.name)) continue;
            const val = getEffectiveParamValue(key, deviceKey, p.name).trim();
            if (val) params[p.name] = val;
          }
        }
        const deviceOverrides = perDeviceParams[key]?.[deviceKey];
        if (deviceOverrides) {
          for (const [paramName, paramValue] of Object.entries(deviceOverrides)) {
            if (FRAMEWORK_PARAMS.includes(paramName)) continue;
            const trimmed = paramValue.trim();
            if (trimmed) params[paramName] = trimmed;
          }
        }
        return { ...sc, parameters: params };
      });
    }

    // File campaigns: build configs from contained scripts
    const scopeId = getCampaignScopeId(selectedCampaignExecutable);
    const containedScripts = getContainedScriptsForCampaign(selectedCampaignExecutable);
    return containedScripts.map((sc, index) => {
      const key = getCampaignScriptKey(scopeId, sc.script_name);
      const analysis = getScriptAnalysisFor(key);
      const params: Record<string, string> = {};
      if (analysis) {
        for (const p of analysis.parameters) {
          if (FRAMEWORK_PARAMS.includes(p.name)) continue;
          const val = getEffectiveParamValue(key, deviceKey, p.name).trim();
          if (val) params[p.name] = val;
        }
      }
      const deviceOverrides = perDeviceParams[key]?.[deviceKey];
      if (deviceOverrides) {
        for (const [paramName, paramValue] of Object.entries(deviceOverrides)) {
          if (FRAMEWORK_PARAMS.includes(paramName)) continue;
          const trimmed = paramValue.trim();
          if (trimmed) params[paramName] = trimmed;
        }
      }
      return {
        script_name: sc.script_name,
        script_type: sc.script_type || 'script',
        description: sc.description || '',
        parameters: params,
        order: index,
      };
    });
  }, [
    selectedCampaignExecutable,
    selectedCampaignConfig,
    getCampaignScriptKey,
    getScriptAnalysisFor,
    perDeviceParams,
    getEffectiveParamValue,
    getCampaignScopeId,
    getContainedScriptsForCampaign,
  ]);

  const executeCampaignOnDevices = async (
    allDevices: Array<{ hostName: string; deviceId: string }>,
    // Optional rerun override: a resolved CampaignConfig + display name +
    // source. When provided, skips the selectedCampaignExecutable /
    // selectedCampaignConfig / buildCampaignScriptConfigurationsForDevice
    // rebuild so a rerun replays the exact config captured at launch.
    rerunOverride?: {
      campaignName: string;
      campaignSource: 'db' | 'file';
      campaignConfig: CampaignConfig;
    },
  ) => {
    if (!rerunOverride && !selectedCampaignExecutable) {
      return;
    }

    const effectiveSource = rerunOverride?.campaignSource ?? selectedCampaignExecutable!.source;
    const effectiveName = rerunOverride?.campaignName ?? selectedCampaignExecutable!.name;

    if (effectiveSource === 'db') {
      if (!rerunOverride && !selectedCampaignConfig) {
        showError('Select a campaign first');
        return;
      }
      const campaignBatchId = `campaign-batch-${Date.now()}`;
      const runResults = await Promise.all(
        allDevices.map(async ({ hostName, deviceId }) => {
          const executionId = `campaign-${Date.now()}-${hostName}-${deviceId}`;
          const startedAtRaw = new Date().toISOString();

          // Resolve the full campaign config now so we can both run it and
          // stash it on the execution record's rerunPayload.
          const campaignConfig: CampaignConfig = rerunOverride
            ? {
                ...rerunOverride.campaignConfig,
                host: hostName,
                device: deviceId || 'host',
                campaign_batch_id: campaignBatchId,
              } as CampaignConfig
            : (() => {
                const deviceKey = resolveSelectedTargetKey(hostName, deviceId || 'host');
                const overriddenScriptConfigs = buildCampaignScriptConfigurationsForDevice(deviceKey) || [];
                return {
                  ...selectedCampaignConfig!,
                  script_configurations: overriddenScriptConfigs,
                  host: hostName,
                  device: deviceId || 'host',
                  campaign_batch_id: campaignBatchId,
                } as CampaignConfig;
              })();

          setExecutions((prev) => [{
            id: executionId,
            executionType: 'campaign' as const,
            scriptName: effectiveName,
            hostName,
            deviceId,
            startedAtRaw,
            startTime: formatToLocalTimeShort(startedAtRaw),
            status: 'running' as const,
            rerunPayload: {
              type: 'campaign' as const,
              campaignName: effectiveName,
              hostName,
              deviceId: deviceId || 'host',
              campaignSource: 'db' as const,
              campaignConfig,
            },
          }, ...prev].slice(0, RUN_TESTS_HISTORY_LIMIT));

          try {
            const result = await executeCampaign(campaignConfig);

            const completedAtRaw = new Date().toISOString();
            const finalStatus = result.status === 'completed' || result.status === 'aborted' || result.status === 'failed'
              ? result.status
              : 'completed';
            const overallSuccess = result.result?.overall_success ?? result.success ?? false;
            setExecutions((prev) => prev.map((item) => item.id === executionId ? {
              ...item,
              completedAtRaw,
              endTime: formatToLocalTimeShort(completedAtRaw),
              status: finalStatus,
              testResult: overallSuccess ? 'success' : 'failure',
              reportUrl: result.result?.orchestrator_report_url || undefined,
              logsUrl: (() => {
                const rawLogsUrl = result.result?.orchestrator_logs_url;
                return rawLogsUrl ? getLogsUrl(rawLogsUrl) : undefined;
              })(),
              campaignSuccess: overallSuccess,
              campaignScripts: result.result?.script_executions || [],
          } : item));
        } catch {
            const completedAtRaw = new Date().toISOString();
            setExecutions((prev) => prev.map((item) => item.id === executionId ? {
              ...item,
              completedAtRaw,
              endTime: formatToLocalTimeShort(completedAtRaw),
              status: 'failed',
              testResult: 'failure',
            } : item));
          }
        }),
      );
      void refreshExecutions();
      return runResults;
    }

    // File campaigns: use the same executeCampaign() path as DB campaigns
    // so each script gets its own per-device parameters (no flattening).
    const campaignBatchId = `campaign-batch-${Date.now()}`;
    const scopeId = rerunOverride ? undefined : getCampaignScopeId(selectedCampaignExecutable!);

    const runResults = await Promise.all(
      allDevices.map(async ({ hostName, deviceId }) => {
        const executionId = `campaign-${Date.now()}-${hostName}-${deviceId}`;
        const startedAtRaw = new Date().toISOString();

        // Resolve the full campaign config now so the run and the rerunPayload
        // both see the same shape.
        const campaignConfig: CampaignConfig = rerunOverride
          ? {
              ...rerunOverride.campaignConfig,
              host: hostName,
              device: deviceId || 'host',
              campaign_batch_id: campaignBatchId,
            } as CampaignConfig
          : (() => {
              const deviceKey = resolveSelectedTargetKey(hostName, deviceId || 'host');
              const scriptConfigurations = buildCampaignScriptConfigurationsForDevice(deviceKey) || [];
              return {
                campaign_id: scopeId,
                name: effectiveName,
                userinterface_name: selectedDevices.get(deviceKey) || '',
                execution_config: {
                  continue_on_failure: true,
                  timeout_minutes: 120,
                  parallel: false,
                },
                script_configurations: scriptConfigurations,
                host: hostName,
                device: deviceId || 'host',
                campaign_batch_id: campaignBatchId,
              } as CampaignConfig;
            })();

        setExecutions((prev) => [{
          id: executionId,
          executionType: 'campaign' as const,
          scriptName: effectiveName,
          hostName,
          deviceId,
          startedAtRaw,
          startTime: formatToLocalTimeShort(startedAtRaw),
          status: 'running' as const,
          rerunPayload: {
            type: 'campaign' as const,
            campaignName: effectiveName,
            hostName,
            deviceId: deviceId || 'host',
            campaignSource: 'file' as const,
            campaignConfig,
          },
        }, ...prev].slice(0, RUN_TESTS_HISTORY_LIMIT));

        try {
          const result = await executeCampaign(campaignConfig);

          const completedAtRaw = new Date().toISOString();
          const finalStatus = result.status === 'completed' || result.status === 'aborted' || result.status === 'failed'
            ? result.status
            : 'completed';
          const overallSuccess = result.result?.overall_success ?? result.success ?? false;
          setExecutions((prev) => prev.map((item) => item.id === executionId ? {
            ...item,
            completedAtRaw,
            endTime: formatToLocalTimeShort(completedAtRaw),
            status: finalStatus,
            testResult: overallSuccess ? 'success' : 'failure',
            reportUrl: result.result?.orchestrator_report_url || undefined,
            logsUrl: (() => {
              const rawLogsUrl = result.result?.orchestrator_logs_url;
              return rawLogsUrl ? getLogsUrl(rawLogsUrl) : undefined;
            })(),
            campaignSuccess: overallSuccess,
            campaignScripts: result.result?.script_executions || [],
          } : item));
        } catch {
          const completedAtRaw = new Date().toISOString();
          setExecutions((prev) => prev.map((item) => item.id === executionId ? {
            ...item,
            completedAtRaw,
            endTime: formatToLocalTimeShort(completedAtRaw),
            status: 'failed',
            testResult: 'failure',
          } : item));
        }
      }),
    );
    void refreshExecutions();
    return runResults;
  };

  const scheduleModeLabel = useMemo(() => {
    if (scheduleRepeatMode === 'periodic' && scheduleRepeat.trim()) {
      return 'Periodically';
    }
    if (startDateOption !== 'now') {
      return 'Later';
    }
    return 'Now';
  }, [scheduleRepeat, scheduleRepeatMode, startDateOption]);

  const createScheduledRuns = async () => {
    const activeItemName = browserTab === 'campaigns'
      ? selectedCampaignExecutable?.name
      : selectedExecutable?.name;
    const activeItemRef = browserTab === 'campaigns'
      ? (
        selectedCampaignExecutable?.source === 'db'
          ? (selectedCampaignExecutable?.name || '')
          : (selectedCampaignExecutable?.script_name || selectedCampaignExecutable?.id || '')
      )
      : selectedScript;

    if (!activeItemName || !activeItemRef || selectedRunnableTargetKeys.length === 0) {
      showError('Select one item and at least one target');
      return;
    }

    const startDate = getPlannedStartDate() || undefined;
    let cronExpression = '';
    let maxExecutions: number | null = scheduleMaxIterations ? parseInt(scheduleMaxIterations, 10) : null;

    if (scheduleRepeatMode === 'periodic') {
      cronExpression = scheduleRepeat.trim();
      const { valid, error } = validateCronExpression(cronExpression);
      if (!valid) {
        showError(`Invalid cron expression: ${error || 'Unknown error'}`);
        return;
      }
    } else if (startDate) {
      // One-time runs are scheduled from start_date and must not rely on a yearly cron match.
      cronExpression = '0 0 1 1 *';
      maxExecutions = 1;
    }
    if (!cronExpression) {
      showError('Choose a later start time or enable periodic repeat to create a plan');
      return;
    }

    const shouldRunImmediately = scheduleRepeatMode === 'periodic' && startDateOption === 'now';
    // Campaigns have no virtual-script concept; getItemEnvironment/resolveVirtualScriptId
    // both no-op (return 'prod'/undefined) for a non-virtual or null item.
    const scheduledExecutable = browserTab === 'tests' ? selectedExecutable : null;
    const scheduledEnv = getItemEnvironment(scheduledExecutable);
    const scheduledVirtualScriptId = resolveVirtualScriptId(scheduledExecutable, scheduledEnv);
    let successCount = 0;
    let immediateRunCount = 0;
    let immediateRunFailedCount = 0;
    for (const deviceKey of selectedRunnableTargetKeys) {
      const [hostName, deviceIdRaw] = deviceKey.split(':');
      const deviceId = deviceIdRaw || 'host';
      const resolvedDeviceKey = resolveSelectedTargetKey(hostName, deviceId);

      // For tests: parameters is a CLI string consumed by ScriptExecutor.
      // For campaigns: parameters is a JSON-encoded script_configurations
      // snapshot (per-device overrides captured from the form). The scheduler
      // detects the JSON shape and feeds it to CampaignExecutor — same
      // payload as "Run Now".
      let deploymentParameters = '';
      if (browserTab === 'tests' && selectedScript) {
        const paramsKey = selectedExecutable?.instanceId || selectedScript;
        deploymentParameters = buildParameterString(paramsKey, hostName, deviceId, resolvedDeviceKey);
      } else if (browserTab === 'campaigns') {
        const snapshot = buildCampaignScriptConfigurationsForDevice(resolvedDeviceKey);
        if (snapshot && snapshot.length > 0) {
          deploymentParameters = JSON.stringify(snapshot);
        }
      }

      const result = await createDeployment({
        name: `${activeItemName}_${Date.now()}`,
        host_name: hostName,
        device_id: deviceId,
        script_name: activeItemRef,
        userinterface_name: browserTab === 'tests' ? (selectedDevices.get(resolvedDeviceKey) || '') : '',
        parameters: deploymentParameters,
        device_info: deviceInfoByDevice[resolvedDeviceKey],
        campaign_id: browserTab === 'campaigns' ? (selectedCampaignExecutable?.campaign_id || null) : null,
        cron_expression: cronExpression,
        start_date: startDate || null,
        end_date: getPlannedEndDate(),
        max_executions: maxExecutions,
        virtual_script_id: scheduledVirtualScriptId,
        environment: scheduledEnv,
      });
      if (result?.success) {
        successCount += 1;
        const deploymentId = result.deployment?.id;
        if (shouldRunImmediately && deploymentId) {
          try {
            await runDeploymentNow(deploymentId);
            immediateRunCount += 1;
          } catch (error) {
            immediateRunFailedCount += 1;
            console.error('[@RunTests] Failed to trigger immediate scheduled execution:', deploymentId, error);
          }
        }
      }
    }

    if (successCount > 0) {
      void refreshExecutions();

      if (shouldRunImmediately) {
        if (immediateRunFailedCount === 0) {
          showSuccess(`Created ${successCount} planned run(s) and started ${immediateRunCount} immediate run(s)`);
        } else {
          showInfo(`Created ${successCount} planned run(s); started ${immediateRunCount} now, ${immediateRunFailedCount} will wait for the schedule`);
        }
      } else {
        showSuccess(`Created ${successCount} planned run(s)`);
      }
    } else {
      showError('Failed to create planned runs');
    }
  };

  const handleMultiScriptDeployment = async () => {
    if (selectedExecutableItems.length < 2 || selectedRunnableTargetKeys.length === 0) {
      showError('Select at least 2 scripts and 1 target');
      return;
    }

    let successCount = 0;
    const totalExpected = selectedExecutableItems.length * selectedRunnableTargetKeys.length;
    const immediateDeploymentIds: string[] = [];

    for (const item of selectedExecutableItems) {
      // Per-item env (Selected Items row selector) so a batch of virtual
      // scripts each resolve to their own dev/test/prod row.
      const itemEnv = getItemEnvironment(item);
      const itemVirtualScriptId = resolveVirtualScriptId(item, itemEnv);
      for (const deviceKey of selectedRunnableTargetKeys) {
        const [hostName, deviceIdRaw] = deviceKey.split(':');
        const deviceId = deviceIdRaw || 'host';
        const resolvedDeviceKey = resolveSelectedTargetKey(hostName, deviceId);

        const result = await createDeployment({
          name: `${item.name}_${hostName}_${deviceId}_${Date.now()}`,
          host_name: hostName,
          device_id: deviceId,
          script_name: item.id,
          userinterface_name: selectedDevices.get(resolvedDeviceKey) || '',
          parameters: buildParameterString(item.instanceId, hostName, deviceId, resolvedDeviceKey),
          device_info: deviceInfoByDevice[resolvedDeviceKey],
          cron_expression: '0 0 1 1 *',
          max_executions: 1,
          virtual_script_id: itemVirtualScriptId,
          environment: itemEnv,
        });

        if (result?.success) {
          successCount++;
          const deploymentId = result.deployment?.id;
          if (deploymentId) {
            immediateDeploymentIds.push(deploymentId);
          }
        }
      }
    }

    if (successCount > 0) {
      void refreshExecutions();

      for (const deploymentId of immediateDeploymentIds) {
        try {
          console.log('[@RunTests] Triggering immediate deployment run', { deploymentId });
          await runDeploymentNow(deploymentId);
        } catch (error) {
          console.error('[@RunTests] Failed to trigger immediate run:', deploymentId, error);
        }
      }

      showSuccess(`Queued ${successCount}/${totalExpected} script run(s)`);
    } else {
      showError('Failed to create deployment runs');
    }
  };

  const handleRunAction = async () => {
    if (scheduleModeLabel !== 'Now') {
      await createScheduledRuns();
      return;
    }

    if (browserTab === 'campaigns') {
      const devices = selectedRunnableTargetKeys.map((deviceKey) => {
        const [hostName, deviceId] = deviceKey.split(':');
        return { hostName, deviceId };
      });
      if (devices.length === 0) {
        showError('Please select at least one runnable target');
        return;
      }
      await executeCampaignOnDevices(devices);
      return;
    }

    // Multi-script: 2+ items selected → deploy via scheduler with queuing
    if (selectedExecutableItems.length >= 2) {
      await handleMultiScriptDeployment();
      return;
    }

    await handleExecuteScript();
  };

  // One-click rerun from the "Last Executions" table. Dispatches by payload
  // type to the matching executor on a single target. Does NOT touch
  // selectedDevices/selectedExecutable/perDeviceParams — the user's current
  // selection is preserved. Rerun is run-now only: if the target is locked,
  // the executor surfaces an error toast (no scheduler fallback).
  const handleRerun = useCallback(async (payload: RerunPayload) => {
    if (payload.type === 'script') {
      await executeScriptOnDevices(
        [{ hostName: payload.hostName, deviceId: payload.deviceId }],
        {
          overrides: [{
            scriptName: payload.scriptName,
            hostName: payload.hostName,
            deviceId: payload.deviceId,
            parameters: payload.parameters,
            virtualScriptId: payload.virtualScriptId,
          }],
          disableQueueFallback: true,
        },
      );
      return;
    }
    if (payload.type === 'testcase') {
      await executeTestCaseOnDevices(
        [{ hostName: payload.hostName, deviceId: payload.deviceId, deviceModel: payload.deviceModel }],
        payload.testcaseVersionNumber,
        {
          executionGraph: payload.executionGraph,
          scriptInputs: payload.scriptInputs,
          scriptVariables: payload.scriptVariables,
          scriptConfigForExecution: {
            inputs: payload.scriptInputs,
            variables: payload.scriptVariables,
          },
          versionNumber: payload.testcaseVersionNumber,
          testcaseName: payload.scriptName,
          testcaseId: payload.scriptName,
        },
        // Replay the original run's input values verbatim — no dialog re-prompt.
        // {} (not undefined) when none were collected, so the prompt is skipped.
        payload.inputValues ?? {},
      );
      return;
    }
    if (payload.type === 'campaign') {
      await executeCampaignOnDevices(
        [{ hostName: payload.hostName, deviceId: payload.deviceId }],
        {
          campaignName: payload.campaignName,
          campaignSource: payload.campaignSource,
          campaignConfig: payload.campaignConfig,
        },
      );
      return;
    }
  }, []);




  // Framework parameters with dedicated selectors at the top (host, device)
  // All other parameters show inline in Section 3
  // ✅ Scripts should NEVER declare host/device - they're framework-level infrastructure
  const FRAMEWORK_PARAMS = ['host', 'device'];

  // Thin wrapper around the shared <ScriptParameterRow>. Resolves the
  // effective value for this (script, device, param) cell and builds a small
  // sibling-values bag so cascading selectors (variant ↔ userinterface,
  // edge/node ↔ ui+variant) can self-consult without knowing about
  // perDeviceParams or per-device defaults.
  //
  // `scriptKey` is the param-bag key — instanceId for selected items (so the
  // same script can be added multiple times with different params) or
  // `campaign:<id>:<scriptName>` for campaign rows. The script's actual name
  // (used to gate kpi_measurement/--edge and goto/--node) comes from the
  // analysis, since instanceId UUIDs would never match.
  const renderParamControl = (scriptKey: string, deviceKey: string, param: { name: string; dataType?: string; default?: string; choices?: string[]; required?: boolean }) => {
    const val = getEffectiveParamValue(scriptKey, deviceKey, param.name);
    const [hostName, deviceId] = deviceKey.split(':');
    const device = getDevicesFromHost(hostName).find((d) => d.device_id === deviceId);
    const allValues: Record<string, string> = {
      userinterface: getEffectiveParamValue(scriptKey, deviceKey, 'userinterface'),
      userinterface_name: getEffectiveParamValue(scriptKey, deviceKey, 'userinterface_name'),
      variant: getEffectiveParamValue(scriptKey, deviceKey, 'variant'),
    };
    const analysisScriptName = getScriptAnalysisFor(scriptKey)?.script_name;
    const fallbackSegment = scriptKey.includes(':') ? scriptKey.split(':').pop() || scriptKey : scriptKey;
    const scriptBase = (analysisScriptName || fallbackSegment).replace(/\.py$/, '');
    return (
      <ScriptParameterRow
        key={param.name}
        param={param}
        value={val}
        onChange={(v) => handlePerDeviceParamChange(scriptKey, deviceKey, param.name, v)}
        allValues={allValues}
        scriptName={scriptBase}
        deviceModel={device?.device_model}
        // Dev/prod targeting: the selection's mode rides the same per-device
        // param bag as everything else ('' = dev so nothing is emitted).
        uiMode={getEffectiveParamValue(scriptKey, deviceKey, 'ui_mode') === 'prod' ? 'prod' : 'dev'}
        onUiModeChange={(m) =>
          handlePerDeviceParamChange(scriptKey, deviceKey, 'ui_mode', m === 'prod' ? 'prod' : '')
        }
      />
    );
  };
  
  const selectedTargetEntries = useMemo(
    () => {
      // Skip locked/running devices — their checkbox is force-checked and the
      // user can't uncheck them, but the row only applies to whatever script
      // already owns the lock. Don't carry it into a newly-selected script's
      // Selected Items panel (the run also skips them — see selectedRunnableTargetKeys).
      const entries = Array.from(selectedDevices.keys())
        .filter((deviceKey) => !runningTargetKeys.has(deviceKey) && !isTargetLocked(deviceKey))
        .map((deviceKey) => {
          const [hostName, deviceId] = deviceKey.split(':');
          // Resolve the live device_name so the chip label matches the rest of
          // the page (history table + execution panel) instead of falling back
          // to "<host>:<device_id>".
          const deviceDisplayName = deviceId
            ? getDevicesFromHost(hostName)?.find((d: any) => d.device_id === deviceId)?.device_name
            : undefined;
          return {
            deviceKey,
            hostName,
            deviceId,
            label: formatTargetLabel(hostName, deviceId, deviceDisplayName),
          };
        });
      // Deduplicate by label — two different keys can resolve to the same device display name
      const seen = new Set<string>();
      return entries.filter((entry) => {
        if (seen.has(entry.label)) return false;
        seen.add(entry.label);
        return true;
      });
    },
    [selectedDevices, getDevicesFromHost, runningTargetKeys, isTargetLocked],
  );

  // Copy a source target's per-device params to every other selected target,
  // skipping the UI-bound params (userinterface/variant) that are legitimately
  // per-device. Lets the user fill one row (edge, iterations, …) and fan it out
  // to all targets instead of editing each row by hand.
  const COPY_EXCLUDED_PARAMS = ['userinterface', 'userinterface_name', 'variant'];
  const copyParamsToAllTargets = useCallback((
    scriptKey: string,
    sourceDeviceKey: string,
    displayParameters: { name: string }[],
  ) => {
    const otherKeys = selectedTargetEntries
      .map((entry) => entry.deviceKey)
      .filter((deviceKey) => deviceKey !== sourceDeviceKey);
    if (otherKeys.length === 0) return;

    const copyable = displayParameters.filter((param) => !COPY_EXCLUDED_PARAMS.includes(param.name));
    copyable.forEach((param) => {
      const value = getEffectiveParamValue(scriptKey, sourceDeviceKey, param.name);
      otherKeys.forEach((deviceKey) => {
        handlePerDeviceParamChange(scriptKey, deviceKey, param.name, value);
      });
    });

    showSuccess(`Copied parameters to ${otherKeys.length} target${otherKeys.length === 1 ? '' : 's'}`);
  }, [selectedTargetEntries, getEffectiveParamValue, handlePerDeviceParamChange, showSuccess]);

  const getExecutableBadge = useCallback((item: ExecutableItem) => {
    if (item.is_virtual) {
      return { label: 'VS', color: 'success' as const };
    }
    if (item.type === 'testcase') {
      return { label: 'TC', color: 'secondary' as const };
    }
    return { label: 'S', color: 'primary' as const };
  }, []);

  const visibleExecutions = useMemo(
    () => {
      // Drop local entries that have a matching DB entry on the same
      // host+device+type within 60 seconds (scriptName may differ between
      // local display name and DB deployment name, so it's not compared).
      // Exception: keep the local row when it has a terminal status while the
      // DB row is still 'running' — the DB-side reconciliation may not have
      // run yet (host post-processing can die silently and leave the row stale).
      const TERMINAL_STATUSES = new Set(['completed', 'failed', 'aborted', 'skipped']);
      const droppedDbIds = new Set<string>();
      const dedupedLocal = activeExecutions.filter((local) => {
        const localStart = local.startedAtRaw ? new Date(local.startedAtRaw).getTime() : 0;
        const dbMatch = historyExecutions.find((h) =>
          h.hostName === local.hostName && h.deviceId === local.deviceId
          && h.executionType === local.executionType
          && Math.abs((h.startedAtRaw ? new Date(h.startedAtRaw).getTime() : 0) - localStart) < 60_000
        );
        if (!dbMatch) return true;
        if (TERMINAL_STATUSES.has(local.status) && dbMatch.status === 'running') {
          droppedDbIds.add(dbMatch.id);
          return true;
        }
        return false;
      });
      const filteredHistory = historyExecutions.filter((h) => !droppedDbIds.has(h.id));
      // Normalize without slicing, run every filter, THEN take the top N — so a
      // burst of recent campaign rows can't crowd the script rows out of the
      // tests tab (and vice versa) before the tab filter even runs.
      return normalizeExecutionHistory([...dedupedLocal, ...filteredHistory], Infinity)
        .filter((execution) => execution.status !== 'aborted' && execution.status !== 'skipped')
        .filter((execution) =>
          browserTab === 'campaigns'
            ? execution.executionType === 'campaign'
            : execution.executionType === 'script' || execution.executionType === 'testcase'
        )
        // Workspace scope: hide rows whose device isn't allowed, and hide
        // script-type rows whose script isn't in script_filter. Campaigns and
        // testcases aren't filtered by script_filter (a campaign contains many
        // scripts; filtering by its display name would be arbitrary).
        .filter((execution) => {
          if (execution.deviceId && !isDeviceAllowed(execution.hostName, execution.deviceId)) {
            return false;
          }
          if (execution.executionType === 'script' && !isScriptAllowed(execution.scriptName)) {
            return false;
          }
          return true;
        })
        .slice(0, RUN_TESTS_HISTORY_LIMIT);
    },
    [activeExecutions, browserTab, historyExecutions, isDeviceAllowed, isScriptAllowed],
  );

  const executionHistoryRows = useMemo<ExecutionHistoryRow[]>(
    () => visibleExecutions.map((execution) => {
      const hostDevices = getDevicesFromHost(execution.hostName);
      const deviceObject = execution.deviceId ? hostDevices.find((d) => d.device_id === execution.deviceId) : undefined;
      const deviceDisplayName = deviceObject?.device_name || undefined;

      // Parameters this script/device ran with — local rows carry them on the
      // record, DB rows carry them on the script rerunPayload. Drop --host and
      // --device (the Target column already shows them), then break the CLI
      // string onto one line per flag so the hover tooltip stays readable.
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
        scriptLabel: getScriptDisplayName(execution.scriptName, aiTestCasesInfo),
        parametersLabel,
        startedLabel: execution.startTime || '-',
        completedLabel: execution.endTime || '-',
        status: execution.status,
        resultSuccess: execution.executionType === 'campaign'
          ? (execution.campaignSuccess ?? (execution.testResult === 'success' ? true : execution.testResult === 'failure' ? false : null))
          : (execution.testResult === 'success' ? true : execution.testResult === 'failure' ? false : null),
        reportUrl: execution.reportUrl,
        logsUrl: execution.logsUrl,
        campaignScripts: mapCampaignScriptsToHistoryRows(execution.campaignScripts),
        hideTopLevelLogs: execution.executionType === 'campaign',
        // Only show the rerun icon on completed rows — reruns while the
        // original is still running/queued just race the original.
        rerunPayload: (execution.status === 'completed' || execution.status === 'failed')
          ? execution.rerunPayload
          : undefined,
      };
    }),
    [aiTestCasesInfo, getDevicesFromHost, visibleExecutions],
  );

  return (
    <Box sx={{ px: isMobile ? 0.25 : isTablet ? 0.75 : 1, pt: isMobile ? 0.25 : 0.5, pb: isMobile ? 0.25 : isTablet ? 0.75 : 1 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2, gap: 1, flexWrap: 'wrap' }}>
        <Typography variant="h4">
          Run Tests
        </Typography>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Chip
            label="Tests"
            clickable
            color={browserTab === 'tests' ? 'primary' : 'default'}
            variant={browserTab === 'tests' ? 'filled' : 'outlined'}
            onClick={() => handleBrowserTabChange('tests')}
          />
          <Chip
            label="Campaigns"
            clickable
            color={browserTab === 'campaigns' ? 'primary' : 'default'}
            variant={browserTab === 'campaigns' ? 'filled' : 'outlined'}
            onClick={() => handleBrowserTabChange('campaigns')}
          />
        </Box>
      </Box>
      {isCompact ? (
        <Card variant="outlined" sx={{ mb: 1 }}>
          <CardContent sx={{ py: 1 }}>
            <Typography variant="caption" color="text.secondary">
              {selectedRunnableTargetCount} target{selectedRunnableTargetCount !== 1 ? 's' : ''} selected
              {selectedExecutable ? ` • ${selectedExecutable.name}` : ' • no script selected'}
              {(runningTargetKeys.size > 0 || isExecuting) ? ` • ${Math.max(runningTargetKeys.size, executingIds.length)} running` : ''}
            </Typography>
          </CardContent>
        </Card>
      ) : null}

      <Grid container spacing={2}>
        <Grid item xs={12}>
          <Card sx={{ '& .MuiCardContent-root': { p: 2, '&:last-child': { pb: 2 } } }}>
            <CardContent>
              <Box sx={{ display: 'flex', gap: 2, flexDirection: isCompact ? 'column' : 'row' }}>
                <Box
                  sx={{
                    width: isCompact ? '100%' : 420,
                    flexShrink: 0,
                    borderRight: isCompact ? 'none' : '1px solid',
                    borderColor: 'divider',
                    pr: isCompact ? 0 : 2,
                    minHeight: 0,
                  }}
                >
                  <TargetPanel
                    selectedDevices={selectedDevices}
                    onToggle={toggleTarget}
                    onUpdateUserinterface={updateDeviceUserinterface}
                    allHosts={allHosts}
                    getDevicesFromHost={getDevicesFromHost}
                    isTargetDisabled={(key) => runningTargetKeys.has(key)}
                    isTargetForceChecked={(key) => runningTargetKeys.has(key)}
                    isTargetLocked={isTargetLocked}
                    getLockTooltip={(key) => lockTooltips[key] || 'Locked'}
                    hostOnly={selectedExecutableRules.target_type === 'host'}
                    disableInternalScroll={isCompact}
                    isHostVisible={(hostName) => {
                      const host = allHosts.find((h: any) => h.host_name === hostName);
                      return host ? isHostCompatibleWithRules(host, selectedExecutableRules) : false;
                    }}
                    isDeviceVisible={(hostName, deviceId) => {
                      const host = allHosts.find((h: any) => h.host_name === hostName);
                      if (!host) return false;
                      const device = (host.devices || []).find((d: any) => d.device_id === deviceId);
                      return device ? isDeviceCompatibleWithRules(host, device, selectedExecutableRules) : false;
                    }}
                    showUserinterfaceSelector={false}
                    selectionCountLabel={`${selectedRunnableTargetCount} target${selectedRunnableTargetCount !== 1 ? 's' : ''} selected`}
                  />
                </Box>

                <Box sx={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 1 }}>
                  <UnifiedExecutableSelector
                    dataKey={browserTab}
                    value={browserTab === 'tests' ? null : selectedCampaignSelectorItem}
                    selectedItems={browserTab === 'tests' ? selectedExecutableItems : selectedCampaignSelectorItems}
                    onChange={(item) => {
                      if (browserTab === 'tests') {
                        return;
                      }
                      const matchedCampaign = campaignExecutables.find((entry) => entry.id === item.id) || null;
                      if (matchedCampaign) {
                        void handleSelectCampaignExecutable(matchedCampaign);
                      }
                    }}
                    onItemClick={(item) => {
                      if (browserTab === 'tests') {
                        addTestSelection(item);
                        return;
                      }
                      const matchedCampaign = campaignExecutables.find((entry) => entry.id === item.id);
                      if (matchedCampaign) {
                        if (selectedCampaignExecutableItems.some((entry) => entry.id === matchedCampaign.id)) {
                          removeCampaignSelection(matchedCampaign.id);
                        } else {
                          void addCampaignSelection(matchedCampaign);
                        }
                      }
                    }}
                    onSelectAllVisible={(items) => {
                      if (browserTab === 'tests') {
                        items.forEach((item) => addTestSelection(item));
                        return;
                      }
                      items.forEach((item) => {
                        const matchedCampaign = campaignExecutables.find((entry) => entry.id === item.id);
                        if (matchedCampaign) {
                          void addCampaignSelection(matchedCampaign);
                        }
                      });
                    }}
                    onUnselectAllVisible={browserTab === 'campaigns' ? () => {
                      setSelectedCampaignExecutable(null);
                      setSelectedCampaignConfig(null);
                      setSelectedCampaignExecutableItems([]);
                    } : () => {
                      setSelectedExecutable(null);
                      setSelectedExecutableItems([]);
                      setSelectedScript('');
                      setExpandedItemId(null);
                    }}
                    compatibilityFilter={browserTab === 'tests'
                      ? isExecutableCompatibleWithCurrentSelection
                      : (item) => {
                        const matchedCampaign = campaignExecutables.find((entry) => entry.id === item.id);
                        return matchedCampaign ? isCampaignCompatibleWithCurrentSelection(matchedCampaign) : false;
                      }}
                    itemFilter={browserTab === 'tests'
                      ? (item) => {
                        if (item.folder === 'test_campaign') return false;
                        // Workspace scope: hide scripts not in script_filter.
                        // Testcases aren't script-filtered (they're a separate type).
                        if (item.type === 'script' && !isScriptAllowed(item.id)) return false;
                        if (!selectorTypeFilter) return true;
                        // VS/S are mutually exclusive: a virtual script has
                        // type 'script' too, so "S" must explicitly carve it
                        // out to mean "disk scripts only".
                        if (selectorTypeFilter === 'vs') return Boolean(item.is_virtual);
                        if (selectorTypeFilter === 'script') return item.type === 'script' && !item.is_virtual;
                        return item.type === selectorTypeFilter;
                      }
                      : selectorTypeFilter
                        ? (item) => (
                          selectorTypeFilter === 'tp' || selectorTypeFilter === 'campaign-script'
                            ? item.badgeLabel === (selectorTypeFilter === 'tp' ? 'TP' : 'S')
                            : item.type === selectorTypeFilter
                        )
                        : undefined}
                    placeholder="Search by name..."
                    filters={{ folders: true, tags: true, search: true }}
                    collapseIcon={!isCompact ? (
                      <ExecutableTypeToggle
                        value={selectorTypeFilter}
                        onChange={setSelectorTypeFilter}
                        options={browserTab === 'campaigns'
                          ? [
                            { id: 'campaign-script', label: 'S', color: 'primary' },
                            { id: 'tp', label: 'TP', color: 'secondary' },
                          ]
                          : [
                            { id: 'vs', label: 'VS', color: 'success' },
                            { id: 'script', label: 'S', color: 'primary' },
                            { id: 'testcase', label: 'TC', color: 'secondary' },
                          ]}
                      />
                    ) : undefined}
                    utilityLabel={
                      browserTab === 'tests'
                        ? `${selectedExecutableItems.length} item${selectedExecutableItems.length !== 1 ? 's' : ''} selected`
                        : `${selectedCampaignExecutableItems.length} item${selectedCampaignExecutableItems.length !== 1 ? 's' : ''} selected`
                    }
                    maxListHeight={selectorMaxListHeight}
                    items={browserTab === 'campaigns' ? campaignSelectorItems : undefined}
                    loading={browserTab === 'campaigns' ? loadingCampaignExecutables : undefined}
                    error={browserTab === 'campaigns' ? campaignLoadError : undefined}
                    folderOptions={browserTab === 'campaigns' ? [] : undefined}
                    tagOptions={browserTab === 'campaigns' ? [] : undefined}
                    emptyStateText={browserTab === 'campaigns' ? 'No campaigns found' : 'No executables found'}
                    disableInternalScroll={isCompact}
                  />
                  {RUN_VERSION_SELECTOR_ENABLED && browserTab === 'tests' && selectedExecutable?.type === 'testcase' && selectedExecutableItems.length <= 1 ? (
                    <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
                      <CompactVersionSelector
                        valueKey={selectedTestcaseVersionKey}
                        options={testcaseVersionOptions}
                        disabled={testcaseVersionOptions.length <= 1}
                        onChange={(option) => setSelectedTestcaseVersionKey(option.key)}
                      />
                    </Box>
                  ) : null}
                  {RUN_VERSION_SELECTOR_ENABLED && browserTab === 'campaigns' && selectedCampaignExecutable?.source === 'db' && selectedCampaignExecutableItems.length <= 1 ? (
                    <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
                      <CompactVersionSelector
                        valueKey={selectedCampaignVersionKey}
                        options={campaignVersionOptions}
                        disabled={campaignVersionOptions.length <= 1}
                        onChange={handleSelectCampaignVersion}
                      />
                    </Box>
                  ) : null}
                </Box>
              </Box>
            </CardContent>
          </Card>
        </Grid>


        <Grid item xs={12}>
          <Card>
            <CardContent>
              <Box sx={{ display: 'flex', gap: 1, flexDirection: 'row', alignItems: 'center', flexWrap: 'nowrap' }}>
                {/* Run + Abort */}
                <Button
                  variant="contained"
                  startIcon={<ScriptIcon />}
                  onClick={handleRunAction}
                  disabled={
                    selectedRunnableTargetKeys.length === 0 ||
                    (browserTab === 'tests'
                      // Gate on "an executable is selected", not "a script is
                      // selected" — selectedScript is empty for testcases, which
                      // otherwise kept Run permanently disabled for them.
                      // scriptValidation is {valid:true} for non-scripts.
                      ? (!selectedExecutable || loadingScripts || !scriptValidation.valid)
                      : !selectedCampaignExecutable)
                  }
                >
                  Run
                </Button>
                <Button
                  variant="outlined"
                  onClick={handleAbortRunningTargets}
                  disabled={browserTab === 'campaigns' || runningTargetKeys.size === 0}
                >
                  Abort
                </Button>

                {/* Start */}
                <FormControl size="small" sx={{ minWidth: 120 }}>
                  <InputLabel>Start</InputLabel>
                  <Select
                    value={startDateOption}
                    label="Start"
                    onChange={(e) => {
                      const val = e.target.value as typeof startDateOption;
                      setStartDateOption(val);
                      if (val === 'custom') {
                        setStartDatePopoverAnchor(e.target as unknown as HTMLElement);
                      }
                    }}
                  >
                    <MenuItem value="now">Now</MenuItem>
                    <MenuItem value="1hour">In 1 hour</MenuItem>
                    <MenuItem value="6hours">In 6 hours</MenuItem>
                    <MenuItem value="tomorrow">Tomorrow 00:00</MenuItem>
                    <MenuItem value="nextMonday">Next Monday</MenuItem>
                    <MenuItem value="custom">{startDateOption === 'custom' && startDateCustom ? startDateCustom.replace('T', ' ') : 'Pick date...'}</MenuItem>
                  </Select>
                </FormControl>
                <Popover
                  open={Boolean(startDatePopoverAnchor)}
                  anchorEl={startDatePopoverAnchor}
                  onClose={() => setStartDatePopoverAnchor(null)}
                  anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
                >
                  <Box sx={{ p: 1.5 }}>
                    <TextField
                      type="datetime-local"
                      size="small"
                      value={startDateCustom}
                      onChange={(e) => setStartDateCustom(e.target.value)}
                      autoFocus
                      sx={{ width: 220 }}
                    />
                  </Box>
                </Popover>

                {/* Repeat */}
                {isDeploymentsEnabled() && (<>
                <FormControl size="small" sx={{ minWidth: 130 }}>
                  <InputLabel>Repeat</InputLabel>
                  <Select
                    value={scheduleRepeatMode === 'none' ? 'none' : (scheduleRepeat || 'none')}
                    label="Repeat"
                    onChange={(e) => {
                      const val = e.target.value as string;
                      if (val === 'none') {
                        setScheduleRepeatMode('none');
                        setScheduleRepeat('');
                      } else if (val === 'custom') {
                        setScheduleRepeatMode('periodic');
                        if (!scheduleRepeat.trim()) setScheduleRepeat('0 * * * *');
                      } else {
                        setScheduleRepeatMode('periodic');
                        setScheduleRepeat(val);
                      }
                    }}
                  >
                    <MenuItem value="none">No repeat</MenuItem>
                    <MenuItem value="*/10 * * * *">Every 10 min</MenuItem>
                    <MenuItem value="0 * * * *">Every hour</MenuItem>
                    <MenuItem value="0 */6 * * *">Every 6 hours</MenuItem>
                    <MenuItem value="0 0 * * *">Every day</MenuItem>
                    <MenuItem value="0 0 * * 1">Every week</MenuItem>
                    <MenuItem value="custom">
                      {scheduleRepeatMode === 'periodic' && scheduleRepeat && !['*/10 * * * *','0 * * * *','0 */6 * * *','0 0 * * *','0 0 * * 1'].includes(scheduleRepeat)
                        ? scheduleRepeat
                        : 'Custom cron...'}
                    </MenuItem>
                  </Select>
                </FormControl>
                </>)}

                {/* End */}
                <FormControl size="small" sx={{ minWidth: 110 }}>
                  <InputLabel>End</InputLabel>
                  <Select
                    value={endDateOption}
                    label="End"
                    onChange={(e) => {
                      const val = e.target.value as typeof endDateOption;
                      setEndDateOption(val);
                      if (val === 'custom') {
                        setEndDatePopoverAnchor(e.target as unknown as HTMLElement);
                      }
                    }}
                  >
                    <MenuItem value="never">No end</MenuItem>
                    <MenuItem value="1day">+1 day</MenuItem>
                    <MenuItem value="7days">+7 days</MenuItem>
                    <MenuItem value="30days">+30 days</MenuItem>
                    <MenuItem value="90days">+90 days</MenuItem>
                    <MenuItem value="custom">{endDateOption === 'custom' && endDateCustom ? endDateCustom.replace('T', ' ') : 'Pick date...'}</MenuItem>
                  </Select>
                </FormControl>
                <Popover
                  open={Boolean(endDatePopoverAnchor)}
                  anchorEl={endDatePopoverAnchor}
                  onClose={() => setEndDatePopoverAnchor(null)}
                  anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
                >
                  <Box sx={{ p: 1.5 }}>
                    <TextField
                      type="datetime-local"
                      size="small"
                      value={endDateCustom}
                      onChange={(e) => setEndDateCustom(e.target.value)}
                      autoFocus
                      sx={{ width: 220 }}
                    />
                  </Box>
                </Popover>

                {/* Max Iterations + Callback — inline on desktop, collapsed on mobile */}
                {isCompact ? (
                  <>
                    <Box
                      component="span"
                      onClick={() => setShowAdvancedConfig(!showAdvancedConfig)}
                      sx={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 0.5,
                        cursor: 'pointer',
                        color: 'text.secondary',
                        typography: 'caption',
                        userSelect: 'none',
                        '&:hover': { color: 'text.primary' }
                      }}
                    >
                      {showAdvancedConfig ? <ExpandMoreIcon sx={{ fontSize: 14 }} /> : <ChevronRightIcon sx={{ fontSize: 14 }} />}
                      More
                    </Box>
                    <Collapse in={showAdvancedConfig} sx={{ width: '100%' }}>
                      <Box sx={{ display: 'flex', gap: 1.5, flexDirection: 'column', width: '100%' }}>
                        <TextField
                          size="small"
                          label="Max Iterations"
                          value={scheduleMaxIterations}
                          onChange={(e) => setScheduleMaxIterations(e.target.value)}
                          placeholder="None"
                          sx={{ width: '100%' }}
                        />
                        <TextField
                          label="Callback URL"
                          value={scriptCallbackUrl}
                          onChange={(e) => setScriptCallbackUrl(e.target.value)}
                          placeholder="/hooks/script-complete"
                          size="small"
                          sx={{ width: '100%' }}
                        />
                      </Box>
                    </Collapse>
                  </>
                ) : (
                  <>
                    <TextField
                      size="small"
                      label="Max Iter."
                      value={scheduleMaxIterations}
                      onChange={(e) => setScheduleMaxIterations(e.target.value)}
                      placeholder="None"
                      sx={{ width: 100 }}
                    />
                    <TextField
                      label="Callback URL"
                      value={scriptCallbackUrl}
                      onChange={(e) => setScriptCallbackUrl(e.target.value)}
                      placeholder="/hooks/script-complete"
                      size="small"
                      sx={{ flex: 1, minWidth: 120 }}
                    />
                  </>
                )}
              </Box>
              {isDeploymentsEnabled() && scheduleRepeatMode === 'periodic' ? (
                <Box sx={{ mt: 1.25 }}>
                  <CronHelper
                    value={scheduleRepeat}
                    onChange={setScheduleRepeat}
                    error={scheduleRepeatError}
                  />
                </Box>
              ) : null}
            </CardContent>
          </Card>
        </Grid>

        {(selectedExecutableItems.length > 0 || selectedCampaignExecutableItems.length > 0) ? (
          <Grid item xs={12}>
            <Card>
              <CardContent>
                <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                  <Typography variant="h6">
                    Selected Items
                  </Typography>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                    {selectedTargetEntries.length > 0 && (
                      <Button
                        size="small"
                        variant="outlined"
                        onClick={() => setDeviceInfoModalOpen(true)}
                        sx={{ textTransform: 'none' }}
                      >
                        Device Info
                        {Object.keys(deviceInfoByDevice).length > 0 ? ` (${Object.keys(deviceInfoByDevice).length})` : ''}
                      </Button>
                    )}
                    <IconButton
                      size="small"
                      color="error"
                      onClick={clearExecutableSelections}
                      title="Clear all selected items"
                    >
                      <DeleteOutlineIcon fontSize="small" />
                    </IconButton>
                  </Box>
                </Box>
                <Stack spacing={0.5}>
                  {selectedExecutableItems.map((item) => (
                    <Accordion
                      key={`test-${item.instanceId}`}
                      expanded={expandedItemId === `test-${item.instanceId}`}
                      onChange={(_, isExpanded) => {
                        setExpandedItemId(isExpanded ? `test-${item.instanceId}` : null);
                        if (isExpanded) setSelectedExecutable(item);
                      }}
                      disableGutters
                      elevation={0}
                      sx={{
                        border: 1,
                        borderColor: 'divider',
                        borderRadius: 1,
                        '&:before': { display: 'none' },
                      }}
                    >
                      <AccordionSummary
                        expandIcon={<ExpandMoreIcon sx={{ fontSize: 18 }} />}
                        sx={{
                          minHeight: 34,
                          px: 1,
                          py: 0,
                          '& .MuiAccordionSummary-content': {
                            my: 0.25,
                          },
                          '&.Mui-expanded': {
                            minHeight: 34,
                          },
                          '& .MuiAccordionSummary-content.Mui-expanded': {
                            my: 0.25,
                          },
                        }}
                      >
                        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%', gap: 1 }}>
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, minWidth: 0, flex: 1 }}>
                            <Chip
                              label={getExecutableBadge(item).label}
                              size="small"
                              color={getExecutableBadge(item).color}
                              sx={{ height: '16px', fontSize: '0.6rem', minWidth: '24px' }}
                            />
                            <Typography
                              variant="body2"
                              sx={{
                                fontWeight: 600,
                                fontSize: '0.82rem',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                              }}
                            >
                              {item.name}
                            </Typography>
                          </Box>
                          {item.is_virtual && (
                            <Box onClick={(event) => event.stopPropagation()} sx={{ flexShrink: 0 }}>
                              <CompactVersionSelector
                                valueKey={getItemEnvironment(item)}
                                disabled={getAvailableEnvironments(item).length <= 1}
                                options={getAvailableEnvironments(item).map((env) => ({
                                  key: env,
                                  label: ENVIRONMENT_LABELS[env],
                                  versionNumber: null,
                                }))}
                                onChange={(option) => setItemEnvironment((prev) => ({
                                  ...prev,
                                  [item.instanceId]: option.key as 'dev' | 'test' | 'prod',
                                }))}
                              />
                            </Box>
                          )}
                          <IconButton
                            size="small"
                            color="error"
                            sx={{ mr: 0.25 }}
                            onClick={(event) => { event.stopPropagation(); removeTestSelection(item.instanceId); }}
                          >
                            <DeleteOutlineIcon fontSize="small" />
                          </IconButton>
                        </Box>
                      </AccordionSummary>
                      <AccordionDetails sx={{ px: 1, pt: 0.5, pb: 0.5 }}>
                        {selectedTargetEntries.length === 0 && (
                          <Typography variant="caption" color="text.secondary" sx={{ py: 0.5, display: 'block' }}>
                            Select targets first to configure per-device parameters
                          </Typography>
                        )}
                        {/* Single shared horizontal scrollbar for all device rows */}
                        <Stack spacing={0.25} sx={{ overflowX: 'auto', pb: 0.5 }}>
                          {selectedTargetEntries.map(({ deviceKey, label }) => {
                            const itemAnalysis = item.type === 'script' ? getScriptAnalysisFor(item.id) : null;
                            const itemDisplayParameters = itemAnalysis?.parameters.filter((param) => !FRAMEWORK_PARAMS.includes(param.name)) || [];
                            const locked = isTargetLocked(deviceKey);
                            return (
                              <Box key={deviceKey} sx={{ display: 'flex', alignItems: 'center', gap: 0, minHeight: 36, width: 'max-content', minWidth: '100%' }}>
                                {/* Device label — sticky so it stays visible while the row scrolls */}
                                <Box sx={{ width: 140, flexShrink: 0, pr: 1, position: 'sticky', left: 0, zIndex: 1, bgcolor: 'background.paper' }}>
                                  <Chip
                                    size="small"
                                    label={label}
                                    icon={locked ? <LockIcon sx={{ fontSize: 14 }} /> : undefined}
                                    variant="filled"
                                    color={locked ? 'warning' : 'default'}
                                    sx={{ maxWidth: '100%', fontSize: '0.7rem' }}
                                  />
                                </Box>
                                {/* Copy-to-all: push this row's params (except UI/variant) to every other target */}
                                {selectedTargetEntries.length > 1 && itemDisplayParameters.length > 0 && (
                                  <Box sx={{ flexShrink: 0, pr: 0.5 }}>
                                    <Tooltip title="Copy these parameters to all targets (keeps each target's userinterface & variant)">
                                      <IconButton
                                        size="small"
                                        onClick={() => copyParamsToAllTargets(item.instanceId, deviceKey, itemDisplayParameters)}
                                        sx={{ p: 0.25 }}
                                      >
                                        <ContentCopyIcon sx={{ fontSize: 16 }} />
                                      </IconButton>
                                    </Tooltip>
                                  </Box>
                                )}
                                {/* Params — one line, no wrap; scrolls with the shared Stack scrollbar */}
                                {item.type === 'script' && !itemAnalysis ? (
                                  <Typography variant="caption" color="text.secondary">Loading parameters...</Typography>
                                ) : itemDisplayParameters.length > 0 ? (
                                  <Box sx={{ display: 'flex', gap: 0.75, alignItems: 'center', pt: 1, pb: 0.25 }}>
                                    {itemDisplayParameters.map((param) => renderParamControl(item.instanceId, deviceKey, param))}
                                  </Box>
                                ) : (
                                  <Typography variant="caption" color="text.secondary">No parameters</Typography>
                                )}
                              </Box>
                            );
                          })}
                        </Stack>
                      </AccordionDetails>
                    </Accordion>
                  ))}

                  {selectedCampaignExecutableItems.map((item) => (
                    <Accordion
                      key={`campaign-${item.id}`}
                      expanded={expandedItemId === `campaign-${item.id}`}
                      onChange={(_, isExpanded) => {
                        setExpandedItemId(isExpanded ? `campaign-${item.id}` : null);
                        if (isExpanded) handleSelectCampaignExecutable(item);
                      }}
                      disableGutters
                      elevation={0}
                      sx={{
                        border: 1,
                        borderColor: 'divider',
                        borderRadius: 1,
                        '&:before': { display: 'none' },
                        overflow: 'hidden',
                      }}
                    >
                      <AccordionSummary
                        expandIcon={<ExpandMoreIcon sx={{ fontSize: 18 }} />}
                        sx={{
                          minHeight: 34,
                          px: 1,
                          py: 0,
                          '& .MuiAccordionSummary-content': {
                            my: 0.25,
                          },
                          '&.Mui-expanded': {
                            minHeight: 34,
                          },
                          '& .MuiAccordionSummary-content.Mui-expanded': {
                            my: 0.25,
                          },
                        }}
                      >
                        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%', gap: 1 }}>
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, minWidth: 0, flex: 1 }}>
                            <Chip
                              label={getCampaignBadge(item.source).label}
                              size="small"
                              color={getCampaignBadge(item.source).color}
                              sx={{ height: '16px', fontSize: '0.6rem', minWidth: '24px' }}
                            />
                            <Typography
                              variant="body2"
                              sx={{
                                fontWeight: 600,
                                fontSize: '0.82rem',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                              }}
                            >
                              {item.name}
                            </Typography>
                          </Box>
                          <IconButton
                            size="small"
                            color="error"
                            sx={{ mr: 0.25 }}
                            onClick={(event) => { event.stopPropagation(); removeCampaignSelection(item.id); }}
                          >
                            <DeleteOutlineIcon fontSize="small" />
                          </IconButton>
                        </Box>
                      </AccordionSummary>
                      <AccordionDetails sx={{ px: 1, pt: 0.5, pb: 0.5 }}>
                        {selectedTargetEntries.length === 0 && (
                          <Typography variant="caption" color="text.secondary" sx={{ py: 0.5, display: 'block' }}>
                            Select targets first to configure per-device parameters
                          </Typography>
                        )}
                        <Stack spacing={0.75}>
                          {getContainedScriptsForCampaign(item).map((scriptConfig) => {
                            const campaignScriptKey = getCampaignScriptKey(getCampaignScopeId(item), scriptConfig.script_name);
                            const scriptAnalysis = getScriptAnalysisFor(campaignScriptKey);
                            const displayParams = scriptAnalysis?.parameters.filter((p) => !FRAMEWORK_PARAMS.includes(p.name)) || [];

                            return (
                              <Box key={scriptConfig.script_name}>
                                <Typography variant="caption" sx={{ fontWeight: 600, fontSize: '0.75rem', color: 'text.secondary', pl: 0.5, display: 'block', mb: 0.25 }}>
                                  {scriptConfig.script_name}
                                </Typography>
                                {/* Single shared horizontal scrollbar for all device rows */}
                                <Stack spacing={0.25} sx={{ overflowX: 'auto', pb: 0.5 }}>
                                  {selectedTargetEntries.map(({ deviceKey, label }) => {
                                    const locked = isTargetLocked(deviceKey);
                                    return (
                                      <Box key={deviceKey} sx={{ display: 'flex', alignItems: 'center', gap: 0, minHeight: 36, width: 'max-content', minWidth: '100%' }}>
                                        <Box sx={{ width: 140, flexShrink: 0, pr: 1, position: 'sticky', left: 0, zIndex: 1, bgcolor: 'background.paper' }}>
                                          <Chip
                                            size="small"
                                            label={label}
                                            icon={locked ? <LockIcon sx={{ fontSize: 14 }} /> : undefined}
                                            variant="filled"
                                            color={locked ? 'warning' : 'default'}
                                            sx={{ maxWidth: '100%', fontSize: '0.7rem' }}
                                          />
                                        </Box>
                                        {/* Copy-to-all: push this row's params (except UI/variant) to every other target */}
                                        {selectedTargetEntries.length > 1 && displayParams.length > 0 && (
                                          <Box sx={{ flexShrink: 0, pr: 0.5 }}>
                                            <Tooltip title="Copy these parameters to all targets (keeps each target's userinterface & variant)">
                                              <IconButton
                                                size="small"
                                                onClick={() => copyParamsToAllTargets(campaignScriptKey, deviceKey, displayParams)}
                                                sx={{ p: 0.25 }}
                                              >
                                                <ContentCopyIcon sx={{ fontSize: 16 }} />
                                              </IconButton>
                                            </Tooltip>
                                          </Box>
                                        )}
                                        {!scriptAnalysis ? (
                                          <Typography variant="caption" color="text.secondary">Loading parameters...</Typography>
                                        ) : displayParams.length > 0 ? (
                                          <Box sx={{ display: 'flex', gap: 0.75, alignItems: 'center', pt: 1, pb: 0.25 }}>
                                            {displayParams.map((param) => renderParamControl(campaignScriptKey, deviceKey, param))}
                                          </Box>
                                        ) : (
                                          <Typography variant="caption" color="text.secondary">No parameters</Typography>
                                        )}
                                      </Box>
                                    );
                                  })}
                                </Stack>
                              </Box>
                            );
                          })}
                        </Stack>
                      </AccordionDetails>
                    </Accordion>
                  ))}
                </Stack>
              </CardContent>
            </Card>
          </Grid>
        ) : null}



        {/* Device Stream Grid - Show when we have at least one device */}
        {visibleStreamTargets.length > 0 && !isMobile && (
          <Grid item xs={12}>
            <Card sx={{ '& .MuiCardContent-root': { p: 2, '&:last-child': { pb: 2 } } }}>
              <CardContent>
                <Stack
                  direction="row"
                  alignItems="center"
                  justifyContent="space-between"
                  sx={{ mb: streamsExpanded ? 2 : 0 }}
                >
                  <Typography variant="h6">
                    Device Streams ({visibleStreamTargets.length})
                  </Typography>
                  <Button
                    size="small"
                    variant="text"
                    onClick={() => setStreamsExpanded((prev) => !prev)}
                    startIcon={streamsExpanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                  >
                    {streamsExpanded ? 'Hide Streams' : 'Show Streams'}
                  </Button>
                </Stack>

                <Collapse in={streamsExpanded}>
                  <DeviceStreamGrid
                    devices={visibleStreamTargets}
                    allHosts={allHosts}
                    getDevicesFromHost={getDevicesFromHost}
                    isActive={streamsExpanded}
                  />
                </Collapse>
              </CardContent>
            </Card>
          </Grid>
        )}

        {/* Last Executions */}
        <Grid item xs={12}>
          <ExecutionHistorySection
            title="Last Executions"
            rows={executionHistoryRows}
            scriptColumnLabel={browserTab === 'campaigns' ? 'Campaign' : 'Test'}
            emptyMessage={browserTab === 'campaigns' ? 'No campaign executions yet' : 'No test executions yet'}
            onOpenUrl={handleOpenR2Url}
            onRerun={handleRerun}
            isCompact={isCompact}
            isTablet={isTablet}
            cardSx={{ '& .MuiCardContent-root': { p: 2, '&:last-child': { pb: 2 } } }}
            contentSx={{ p: 2, '&:last-child': { pb: 2 } }}
            headerCellSx={execColumns.headerCellSx}
            bodyCellSx={execColumns.bodyCellSx}
            renderHeaderExtra={(key) => (
              <Box component="span" onMouseDown={execColumns.onMouseDown(key)} sx={execColumns.resizeHandleSx} />
            )}
            tableSx={{ tableLayout: 'fixed', '& .MuiTableCell-root': { py: 0.5 } }}
          />
        </Grid>
      </Grid>

      <DeviceInfoModal
        open={deviceInfoModalOpen}
        onClose={() => setDeviceInfoModalOpen(false)}
        devices={selectedTargetEntries.map(({ deviceKey, label }) => ({ deviceKey, label }))}
        value={deviceInfoByDevice}
        onChange={setDeviceInfoByDevice}
      />

      {/* Run-with-inputs — collect values for a parameterized testcase's
          non-protected inputs, then relaunch with them. */}
      <RunWithInputsDialog
        open={!!testcaseRunPrompt}
        inputs={testcaseRunPrompt?.inputs || []}
        testcaseName={testcaseRunPrompt?.testcaseName}
        onRun={(values) => {
          const prompt = testcaseRunPrompt;
          setTestcaseRunPrompt(null);
          if (!prompt) return;
          void executeTestCaseOnDevices(
            prompt.pending.allDevices,
            prompt.pending.testcaseVersionNumber,
            prompt.pending.preloaded,
            values,
          );
        }}
        onCancel={() => setTestcaseRunPrompt(null)}
      />
    </Box>
  );
};

export default RunTests;
