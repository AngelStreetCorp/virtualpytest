import {
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  ClickAwayListener,
  Grid,
  Paper,
  Popper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
  InputAdornment,
  Collapse,
  IconButton,
  Tooltip,
  Select,
  MenuItem,
  Switch,
  FormControlLabel,
  FormControl,
  InputLabel,
  CircularProgress,
} from '@mui/material';
import { Search as SearchIcon, Link as LinkIcon, Check, Close, ExpandMore as ExpandMoreIcon, ExpandLess as ExpandLessIcon, Pause, PlayArrow, DeleteOutline, Visibility, VisibilityOff } from '@mui/icons-material';
import { useTheme } from '@mui/material/styles';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { isDeploymentsEnabled } from '../config/featureFlags';
import { useRunExecutions } from '../contexts/RunExecutionsContext';
import { useDeployment, Deployment, DeploymentExecution } from '../hooks/useDeployment';
import { useResizableColumns } from '../hooks/useResizableColumns';
import { useHostData } from '../hooks/useHostManager';
import { useResponsiveMode } from '../hooks/useResponsiveMode';
import { useToast } from '../hooks/useToast';
import { formatToLocalTime, getUserTimezone } from '../utils/dateUtils';
import { cronToHuman, validateCronExpression } from '../utils/cronUtils';
import { CronHelper } from '../components/common/CronHelper';
import { getLogsUrl, getStatusChip, getScriptDisplayName, ensureScriptIdentityMap } from '../utils/executionUtils';
import { openR2Url } from '../utils/infrastructure/cloudflareUtils';
import { buildServerUrl } from '../utils/buildUrlUtils';
import { api } from '../utils/apiClient';
import ExecutionHistorySection from '../components/common/ExecutionHistorySection';
import { ExecutionHistoryRow } from '../components/common/ExecutionHistoryTable';
import { getCampaignDisplayName, isCampaignDeployment, mapDeploymentExecutionToHistoryRow, stripTimestampSuffix } from '../utils/executionHistoryUtils';
const ONE_SHOT_QUEUE_CRON = '0 0 1 1 *';
const SCHEDULE_VISIBLE_STATUSES = new Set(['active', 'paused']);

const isQueueArtifactDeployment = (deployment: Deployment): boolean => (
  deployment.max_executions === 1 &&
  deployment.cron_expression === ONE_SHOT_QUEUE_CRON &&
  !deployment.start_date
);

const isVisibleScheduledDeployment = (deployment: Deployment): boolean => {
  if (!SCHEDULE_VISIBLE_STATUSES.has(deployment.status)) {
    return false;
  }

  if (deployment.max_executions === 1) {
    return false;
  }

  return !isQueueArtifactDeployment(deployment);
};

const getExecutionTimestamp = (execution: DeploymentExecution): string | undefined => (
  execution.started_at || execution.completed_at || execution.scheduled_at
);

const parseExecutionTimestamp = (value?: string | null): number => {
  if (!value) return 0;
  const parsed = new Date(value).getTime();
  return Number.isNaN(parsed) ? 0 : parsed;
};

const getExecutionStableSortTimestamp = (execution: DeploymentExecution): number => (
  parseExecutionTimestamp(execution.started_at) ||
  parseExecutionTimestamp(execution.completed_at) ||
  parseExecutionTimestamp(execution.scheduled_at)
);

const getExecutionStableTargetKey = (execution: DeploymentExecution): string => (
  `${execution.deployments?.host_name || ''}:${execution.deployments?.device_id || 'host'}`
);

const getExecutionStableScriptKey = (execution: DeploymentExecution): string => (
  execution.deployments?.script_name || execution.deployments?.name || ''
);

const sortExecutionsStable = (executions: DeploymentExecution[]): DeploymentExecution[] => (
  [...executions].sort((a, b) => {
    const timeDiff = getExecutionStableSortTimestamp(b) - getExecutionStableSortTimestamp(a);
    if (timeDiff !== 0) return timeDiff;

    const targetDiff = getExecutionStableTargetKey(a).localeCompare(getExecutionStableTargetKey(b));
    if (targetDiff !== 0) return targetDiff;

    const scriptDiff = getExecutionStableScriptKey(a).localeCompare(getExecutionStableScriptKey(b));
    if (scriptDiff !== 0) return scriptDiff;

    return a.id.localeCompare(b.id);
  })
);

const getScheduledNextRun = (deployment: Deployment): Date | null => {
  if (!deployment.next_run) {
    return null;
  }
  const nextRun = new Date(deployment.next_run);
  return Number.isNaN(nextRun.getTime()) ? null : nextRun;
};

const getRepeatLabel = (deployment: Deployment): string => {
  return deployment.cron_expression ? cronToHuman(deployment.cron_expression) : '-';
};


const toDatetimeLocal = (iso: string): string => {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

// --- Parameter parsing utilities ---
interface ParsedParam {
  name: string;
  value: string;
  isPositional: boolean;
  isPassword: boolean;
}

interface ScriptConfig {
  script_name: string;
  script_type?: string;
  testcase_id?: string;
  description?: string;
  parameters: Record<string, string>;
  order: number;
}

interface ScriptParameterDef {
  name: string;
  type: 'positional' | 'optional';
  required: boolean;
  help: string;
  default?: string;
  choices?: string[];
  dataType?: string;
}

const FRAMEWORK_PARAMS = new Set(['host', 'device']);
const PASSWORD_PATTERN = /password|secret|token|key/i;
const SENSITIVE_PATTERN = /password|secret|token|key|username|email|mailbox|address|server|domain|path|url/i;

function tokenizeParamString(paramStr: string): string[] {
  const tokens: string[] = [];
  let current = '';
  let inQuote: string | null = null;
  for (const ch of paramStr) {
    if (inQuote) {
      if (ch === inQuote) {
        inQuote = null;
      } else {
        current += ch;
      }
    } else if (ch === '"' || ch === "'") {
      inQuote = ch;
    } else if (ch === ' ' || ch === '\t') {
      if (current) {
        tokens.push(current);
        current = '';
      }
    } else {
      current += ch;
    }
  }
  if (current) tokens.push(current);
  return tokens;
}

function parseParameterString(paramStr: string): ParsedParam[] {
  const tokens = tokenizeParamString(paramStr.trim());
  const params: ParsedParam[] = [];
  let i = 0;
  let positionalIdx = 0;
  while (i < tokens.length) {
    if (tokens[i].startsWith('--')) {
      const name = tokens[i].slice(2);
      const value = i + 1 < tokens.length && !tokens[i + 1].startsWith('--') ? tokens[++i] : '';
      if (!FRAMEWORK_PARAMS.has(name)) {
        params.push({ name, value, isPositional: false, isPassword: PASSWORD_PATTERN.test(name) });
      }
    } else {
      params.push({ name: positionalIdx === 0 ? 'userinterface' : `arg${positionalIdx}`, value: tokens[i], isPositional: true, isPassword: false });
      positionalIdx++;
    }
    i++;
  }
  return params;
}

function buildParameterStringFromParsed(params: ParsedParam[]): string {
  const parts: string[] = [];
  // Positional args first
  for (const p of params) {
    if (p.isPositional) {
      parts.push(p.value.includes(' ') ? `"${p.value}"` : p.value);
    }
  }
  // Named args
  for (const p of params) {
    if (!p.isPositional) {
      const val = p.value.includes(' ') ? `"${p.value}"` : p.value;
      parts.push(`--${p.name} ${val}`);
    }
  }
  return parts.join(' ');
}

const MonitorTests: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const theme = useTheme();
  const { isMobile, isTablet } = useResponsiveMode();
  const isCompact = isMobile || isTablet;
  const isDarkMode = theme.palette.mode === 'dark';
  const userTimezone = getUserTimezone();
  const getRowHoverSx = () => ({
    backgroundColor: 'transparent',
    '& > .MuiTableCell-root': {
      backgroundColor: 'transparent !important',
    },
    '&:hover': {
      backgroundColor: 'transparent !important',
    },
    '&:hover > .MuiTableCell-root': {
      backgroundColor: 'transparent !important',
    },
  });
  const isFileCampaignDeployment = (deployment: Deployment) =>
    !deployment.campaign_id && (deployment.script_name || '').toLowerCase().includes('campaign');

  const hasEditableParams = (deployment: Deployment) => {
    if (deployment.campaign_id || isFileCampaignDeployment(deployment)) return true;
    return Boolean(deployment.parameters && deployment.parameters.trim());
  };
  const { showError, showSuccess } = useToast();
  const { getDevicesFromHost } = useHostData();
  const {
    listDeployments,
    updateDeployment,
    pauseDeployment,
    resumeDeployment,
    deleteDeployment,
  } = useDeployment();
  const {
    runningExecutions,
    queuedExecutions,
    completedExecutions,
    refresh: refreshExecutions,
  } = useRunExecutions();

  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const execColumns = useResizableColumns([
    { key: 'target', initialWidth: 160, minWidth: 80 },
    { key: 'script', initialWidth: 240, minWidth: 100 },
    { key: 'start', initialWidth: 120, minWidth: 70 },
    { key: 'end', initialWidth: 120, minWidth: 70 },
    { key: 'status', initialWidth: 120, minWidth: 80 },
    { key: 'report', initialWidth: 120, minWidth: 80 },
    { key: 'logs', initialWidth: 120, minWidth: 80 },
  ]);
  const [searchQuery, setSearchQuery] = useState('');
  const [browserTab, setBrowserTab] = useState<'tests' | 'campaigns'>(
    searchParams.get('tab') === 'campaigns' ? 'campaigns' : 'tests',
  );
  const [runningExpanded, setRunningExpanded] = useState(true);
  const [scheduledExpanded, setScheduledExpanded] = useState(true);
  const [queueExpanded, setQueueExpanded] = useState(true);
  const [historyExpanded, setHistoryExpanded] = useState(true);
  const [hasAutoCollapsed, setHasAutoCollapsed] = useState(false);

  // Edit popover state
  const [editAnchorEl, setEditAnchorEl] = useState<HTMLElement | null>(null);
  const [editingDeployment, setEditingDeployment] = useState<Deployment | null>(null);
  const [editCron, setEditCron] = useState('');
  const [editStartDate, setEditStartDate] = useState('');
  const [editEndDate, setEditEndDate] = useState('');
  const [editMaxExecutions, setEditMaxExecutions] = useState('');
  const editPopperOpen = Boolean(editAnchorEl);

  // Expandable parameters state (below table rows)
  const [expandedDeploymentId, setExpandedDeploymentId] = useState<string | null>(null);
  const [expandedParams, setExpandedParams] = useState<ParsedParam[]>([]);
  const [expandedScriptConfigs, setExpandedScriptConfigs] = useState<ScriptConfig[]>([]);
  const [expandedScriptAnalysis, setExpandedScriptAnalysis] = useState<Record<string, ScriptParameterDef[]>>({});
  const [visiblePasswords, setVisiblePasswords] = useState<Record<string, boolean>>({});
  const [paramsSaving, setParamsSaving] = useState(false);
  const [paramsLoading, setParamsLoading] = useState(false);
  const scriptAnalysisCacheRef = useRef<Record<string, ScriptParameterDef[]>>({});
  const popperRef = useRef<HTMLDivElement>(null);
  const loadingRef = useRef(false);

  // Deployments-only load — recent_executions data + socket-driven reloads
  // live in RunExecutionsContext (shared with RunTests), which already fetches
  // on mount and keeps itself fresh via socket + backstop. Calling
  // refreshExecutions() here too would double-hit /executions/recent on load.
  const loadData = useCallback(async () => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    try {
      const deploymentResult = await listDeployments();
      if (deploymentResult?.success) {
        setDeployments(deploymentResult.deployments || []);
      }
    } catch (error) {
      showError(error instanceof Error ? error.message : 'Failed to load monitor data');
    } finally {
      loadingRef.current = false;
    }
  }, [listDeployments, showError]);

  useEffect(() => {
    void loadData();
    void ensureScriptIdentityMap();
  }, [loadData]);

  useEffect(() => {
    setBrowserTab(searchParams.get('tab') === 'campaigns' ? 'campaigns' : 'tests');
    setHasAutoCollapsed(false);
  }, [searchParams]);

  const normalizedQuery = searchQuery.trim().toLowerCase();

  const scheduledDeployments = useMemo(() => {
    const rows = [...deployments]
      .filter(isVisibleScheduledDeployment)
      .filter((deployment) => (
        browserTab === 'campaigns'
          ? isCampaignDeployment(deployment.campaign_id, deployment.script_name)
          : !isCampaignDeployment(deployment.campaign_id, deployment.script_name)
      ))
      .sort((a, b) => {
        const aTime = new Date(a.start_date || a.created_at || 0).getTime();
        const bTime = new Date(b.start_date || b.created_at || 0).getTime();
        return aTime - bTime;
      });

    if (!normalizedQuery) {
      return rows;
    }

    return rows.filter((deployment) => (
      deployment.name?.toLowerCase().includes(normalizedQuery) ||
      deployment.script_name?.toLowerCase().includes(normalizedQuery) ||
      deployment.host_name?.toLowerCase().includes(normalizedQuery) ||
      deployment.device_id?.toLowerCase().includes(normalizedQuery)
    ));
  }, [browserTab, deployments, normalizedQuery]);

  const filteredRunningExecutions = useMemo(() => {
    return sortExecutionsStable(runningExecutions
      .filter((execution) => (
        browserTab === 'campaigns'
          ? isCampaignDeployment(execution.deployments?.campaign_id, execution.deployments?.script_name, execution.is_campaign)
          : !isCampaignDeployment(execution.deployments?.campaign_id, execution.deployments?.script_name, execution.is_campaign)
      ))
      .filter((execution) => {
        if (!normalizedQuery) {
          return true;
        }
        return (
          execution.deployments?.name?.toLowerCase().includes(normalizedQuery) ||
          execution.deployments?.script_name?.toLowerCase().includes(normalizedQuery) ||
          execution.deployments?.host_name?.toLowerCase().includes(normalizedQuery) ||
          execution.deployments?.device_id?.toLowerCase().includes(normalizedQuery)
        );
      }));
  }, [browserTab, normalizedQuery, runningExecutions]);

  const filteredQueuedExecutions = useMemo(() => {
    return sortExecutionsStable(queuedExecutions
      .filter((execution) => (
        browserTab === 'campaigns'
          ? isCampaignDeployment(execution.deployments?.campaign_id, execution.deployments?.script_name, execution.is_campaign)
          : !isCampaignDeployment(execution.deployments?.campaign_id, execution.deployments?.script_name, execution.is_campaign)
      ))
      // Exclude scheduled (CRON) deployments from queue — they belong in "Scheduled" section
      .filter((execution) => execution.deployments?.cron_expression === ONE_SHOT_QUEUE_CRON)
      .filter((execution) => {
        if (!normalizedQuery) return true;
        return (
          execution.deployments?.name?.toLowerCase().includes(normalizedQuery) ||
          execution.deployments?.script_name?.toLowerCase().includes(normalizedQuery) ||
          execution.deployments?.host_name?.toLowerCase().includes(normalizedQuery) ||
          execution.deployments?.device_id?.toLowerCase().includes(normalizedQuery)
        );
      }));
  }, [browserTab, normalizedQuery, queuedExecutions]);

  const filteredCompletedExecutions = useMemo(() => {
    return sortExecutionsStable(completedExecutions
      .filter((execution) => (
        browserTab === 'campaigns'
          ? isCampaignDeployment(execution.deployments?.campaign_id, execution.deployments?.script_name, execution.is_campaign)
          : !isCampaignDeployment(execution.deployments?.campaign_id, execution.deployments?.script_name, execution.is_campaign)
      ))
      .filter((execution) => {
        if (!normalizedQuery) {
          return true;
        }
        return (
          execution.deployments?.name?.toLowerCase().includes(normalizedQuery) ||
          execution.deployments?.script_name?.toLowerCase().includes(normalizedQuery) ||
          execution.deployments?.host_name?.toLowerCase().includes(normalizedQuery) ||
          execution.deployments?.device_id?.toLowerCase().includes(normalizedQuery)
        );
      }));
  }, [browserTab, completedExecutions, normalizedQuery]);

  // Last executions: running + completed only (queued items have their own Queue section)
  // Cross-list dedup: an execution can briefly appear in both running and completed
  // when its status changes between the server's separate DB queries.
  const allExecutions = useMemo(() => {
    const seen = new Set<string>();
    return sortExecutionsStable(
      [...filteredRunningExecutions, ...filteredCompletedExecutions]
        .filter((e) => e.status !== 'aborted' && e.status !== 'skipped')
        .filter((e) => {
          if (seen.has(e.id)) return false;
          seen.add(e.id);
          return true;
        }),
    );
  }, [filteredRunningExecutions, filteredCompletedExecutions]);

  // Auto-collapse sections with 0 items once data has loaded
  useEffect(() => {
    if (hasAutoCollapsed) return;
    const totalItems = filteredRunningExecutions.length + filteredQueuedExecutions.length
      + scheduledDeployments.length + allExecutions.length;
    if (totalItems === 0) return; // data hasn't loaded yet
    setHasAutoCollapsed(true);
    if (filteredRunningExecutions.length === 0) setRunningExpanded(false);
    if (filteredQueuedExecutions.length === 0) setQueueExpanded(false);
    if (scheduledDeployments.length === 0) setScheduledExpanded(false);
    if (allExecutions.length === 0) setHistoryExpanded(false);
  }, [hasAutoCollapsed, filteredRunningExecutions.length, filteredQueuedExecutions.length, scheduledDeployments.length, allExecutions.length]);

  const getTargetLabel = (hostName?: string, deviceId?: string) => {
    if (!hostName) {
      return '-';
    }
    if (!deviceId || deviceId === 'host') {
      return hostName;
    }
    const hostDevices = getDevicesFromHost(hostName);
    const device = hostDevices.find((entry) => entry.device_id === deviceId);
    return `${hostName}:${device?.device_name || deviceId}`;
  };

  const executionHistoryRows = useMemo<ExecutionHistoryRow[]>(
    () => allExecutions.map((execution) => mapDeploymentExecutionToHistoryRow(execution, getTargetLabel)),
    [allExecutions],
  );

  const handlePauseToggle = async (deployment: Deployment) => {
    try {
      if (deployment.status === 'paused') {
        await resumeDeployment(deployment.id);
        showSuccess(`Resumed ${deployment.name}`);
      } else {
        await pauseDeployment(deployment.id);
        showSuccess(`Paused ${deployment.name}`);
      }
      await loadData();
    } catch (error) {
      showError(error instanceof Error ? error.message : 'Failed to update plan');
    }
  };

  const handleDelete = async (deployment: Deployment) => {
    try {
      await deleteDeployment(deployment.id);
      showSuccess(`Deleted ${deployment.name}`);
      await loadData();
    } catch (error) {
      showError(error instanceof Error ? error.message : 'Failed to delete plan');
    }
  };

  const handleAbortQueued = async (executionId: string) => {
    try {
      await api.post(buildServerUrl(`/server/deployment/execution/${executionId}/abort`));
      await Promise.all([loadData(), refreshExecutions()]);
    } catch (error) {
      showError(error instanceof Error ? error.message : 'Failed to abort queued execution');
    }
  };

  const handleEditOpen = (event: React.MouseEvent<HTMLElement>, deployment: Deployment) => {
    event.stopPropagation();
    setEditingDeployment(deployment);
    setEditCron(deployment.cron_expression);
    setEditStartDate(deployment.start_date ? toDatetimeLocal(deployment.start_date) : '');
    setEditEndDate(deployment.end_date ? toDatetimeLocal(deployment.end_date) : '');
    setEditMaxExecutions(deployment.max_executions?.toString() || '');
    setEditAnchorEl(event.currentTarget);
  };

  const handleEditClose = () => {
    setEditAnchorEl(null);
    setEditingDeployment(null);
  };

  const handleEditClickAway = (event: MouseEvent | TouchEvent) => {
    const target = event.target as HTMLElement;
    // Don't close if clicking on the anchor (Edit button) that opened the popover
    if (editAnchorEl && (editAnchorEl === target || editAnchorEl.contains(target))) {
      return;
    }
    // Don't close if clicking on a MUI portal element (e.g., CronHelper Select dropdown)
    if (target.closest('.MuiPopover-root, .MuiMenu-root, .MuiModal-root')) {
      return;
    }
    // Don't close if the target was removed from the DOM (e.g., MUI Select menu item
    // gets unmounted when the menu closes before ClickAwayListener fires)
    if (!document.body.contains(target)) {
      return;
    }
    handleEditClose();
  };

  const handleEditSave = async () => {
    if (!editingDeployment) return;

    const { valid } = validateCronExpression(editCron);
    if (!valid) {
      showError('Invalid cron expression');
      return;
    }

    try {
      const updateData = {
        cron_expression: editCron,
        start_date: editStartDate ? new Date(editStartDate).toISOString() : null,
        end_date: editEndDate ? new Date(editEndDate).toISOString() : null,
        max_executions: editMaxExecutions ? parseInt(editMaxExecutions) : null,
      };

      const data = await updateDeployment(editingDeployment.id, updateData);
      if (data.success) {
        if (data.deployment) {
          setDeployments((current) => current.map((deployment) => (
            deployment.id === editingDeployment.id ? data.deployment : deployment
          )));
        }
        showSuccess('Deployment updated');
        handleEditClose();
        await loadData();
      } else {
        showError(data.error || 'Failed to update deployment');
      }
    } catch (error) {
      showError('Failed to update deployment');
      console.error('Error updating deployment:', error);
    }
  };

  const handleParamsExpand = async (deployment: Deployment) => {
    if (expandedDeploymentId === deployment.id) {
      setExpandedDeploymentId(null);
      return;
    }
    setExpandedDeploymentId(deployment.id);
    setVisiblePasswords({});
    setExpandedScriptAnalysis({});
    setExpandedScriptConfigs([]);
    setExpandedParams([]);

    const isFileCampaign = isFileCampaignDeployment(deployment);

    if (deployment.campaign_id || isFileCampaign) {
      setParamsLoading(true);
      try {
        let rawConfigs: ScriptConfig[] = [];

        // Per-deployment snapshot wins over the canonical campaign template.
        // For both DB and file campaigns we store the snapshot as JSON in
        // deployments.parameters (same column file-based scripts use for CLI
        // args — disambiguated by the JSON shape). When the deployment was
        // created from RunTests with overrides, or saved here previously,
        // those values live there and must be used as-is.
        let deploymentSnapshot: ScriptConfig[] | null = null;
        const rawParams = (deployment.parameters || '').trim();
        if (rawParams.startsWith('[')) {
          try {
            const parsed = JSON.parse(rawParams);
            if (Array.isArray(parsed) && parsed.length > 0) {
              deploymentSnapshot = parsed as ScriptConfig[];
            }
          } catch { /* not a JSON snapshot — fall through to template */ }
        }

        if (deploymentSnapshot) {
          rawConfigs = deploymentSnapshot.map((sc, i) => ({
            ...sc,
            parameters: sc.parameters || {},
            order: sc.order ?? i,
          }));
        } else if (isFileCampaign) {
          // File campaign with no snapshot yet: resolve contained scripts
          // from the file system to seed the editor.
          const contained = await api.post<any>(
            buildServerUrl('/server/campaigns/getContainedScripts'),
            { script_name: deployment.script_name },
          );
          if (contained?.success && Array.isArray(contained.contained_scripts)) {
            rawConfigs = contained.contained_scripts.map((sc: any, i: number) => ({
              script_name: sc.script_name,
              script_type: sc.script_type || 'script',
              parameters: {},
              order: i,
            }));
          }
        } else {
          // DB campaign legacy fallback: deployment has no snapshot yet, so
          // seed the editor from the canonical campaign template. The save
          // path will write the result back to the deployment row, not the
          // template.
          const response = await api.get<any>(buildServerUrl(`/server/campaigns/getCampaign/${deployment.campaign_id}`));
          if (response?.success && response?.campaign?.script_configurations) {
            rawConfigs = (response.campaign.script_configurations as ScriptConfig[]).map((sc, i) => ({
              ...sc,
              parameters: sc.parameters || {},
              order: sc.order ?? i,
            }));
          }
        }

        if (rawConfigs.length > 0) {
          // Fetch script analysis (with in-memory cache) for choices, types, defaults
          const analysisMap: Record<string, ScriptParameterDef[]> = {};
          const enriched = await Promise.all(
            rawConfigs.map(async (sc) => {
              try {
                // Use cached analysis if available
                let userParamDefs = scriptAnalysisCacheRef.current[sc.script_name];
                if (!userParamDefs) {
                  const analysis = await api.post<any>(
                    buildServerUrl('/server/script/analyze'),
                    { script_name: sc.script_name },
                  );
                  if (analysis?.success && Array.isArray(analysis.parameters)) {
                    userParamDefs = (analysis.parameters as ScriptParameterDef[]).filter(
                      (p) => !FRAMEWORK_PARAMS.has(p.name)
                    );
                    scriptAnalysisCacheRef.current[sc.script_name] = userParamDefs;
                  }
                }
                if (userParamDefs) {
                  analysisMap[sc.script_name] = userParamDefs;

                  // Merge: discovered defaults for params not already in the campaign config
                  const existingUserParams = Object.keys(sc.parameters).filter((k) => !FRAMEWORK_PARAMS.has(k));
                  if (existingUserParams.length === 0) {
                    const discovered: Record<string, string> = {};
                    for (const p of userParamDefs) {
                      discovered[p.name] = p.default ?? '';
                    }
                    return { ...sc, parameters: { ...discovered, ...sc.parameters } };
                  }
                }
              } catch {
                // Script analysis failed — keep existing params
              }
              return sc;
            }),
          );
          setExpandedScriptAnalysis(analysisMap);
          setExpandedScriptConfigs(enriched);
        } else {
          console.warn('[@MonitorTests] Campaign has no scripts:', deployment.campaign_id);
          setExpandedScriptConfigs([]);
        }
      } catch (error) {
        console.error('[@MonitorTests] Failed to load campaign parameters:', deployment.campaign_id, error);
        showError('Failed to load campaign parameters');
        setExpandedScriptConfigs([]);
      } finally {
        setParamsLoading(false);
      }
    } else {
      setExpandedParams(parseParameterString(deployment.parameters || ''));
      setExpandedScriptConfigs([]);
    }
  };

  const handleParamsSave = async () => {
    const deployment = deployments.find((d) => d.id === expandedDeploymentId);
    if (!deployment) return;
    setParamsSaving(true);
    try {
      if (expandedScriptConfigs.length > 0) {
        // Both DB and file campaigns: persist the script_configurations
        // snapshot on the deployment row itself as a JSON string in the
        // shared parameters column — never mutate the canonical campaign
        // template. This keeps overrides scoped to this deployment (and its
        // target host/device) instead of bleeding into every other deployment
        // that points at the same campaign_id.
        const snapshotJson = JSON.stringify(expandedScriptConfigs);
        const result = await api.put(
          buildServerUrl(`/server/deployment/update/${deployment.id}`),
          { parameters: snapshotJson },
        );
        if (!result?.success) {
          showError(result?.error || 'Failed to update parameters');
          return;
        }
        // Reflect the new snapshot locally so the next expand reads from it
        setDeployments((prev) => prev.map((dep) =>
          dep.id === deployment.id
            ? { ...dep, parameters: snapshotJson }
            : dep
        ));
      } else if (expandedParams.length > 0) {
        const result = await api.put(
          buildServerUrl(`/server/deployment/update/${deployment.id}`),
          { parameters: buildParameterStringFromParsed(expandedParams) },
        );
        if (!result?.success) {
          showError(result?.error || 'Failed to update parameters');
          return;
        }
      }
      showSuccess('Parameters updated');
    } catch {
      showError('Failed to update parameters');
    } finally {
      setParamsSaving(false);
    }
  };

  const handleOpenR2Url = async (url: string) => {
    try {
      await openR2Url(url);
    } catch (error) {
      console.error('[@MonitorTests] Failed to open R2 URL:', error);
    }
  };

  const emptySection = (message: string) => (
    <Box
      sx={{
        p: 2,
        textAlign: 'center',
        borderRadius: 1,
        backgroundColor: 'background.default',
      }}
    >
      <Typography variant="body2" color="text.secondary">
        {message}
      </Typography>
    </Box>
  );

  const renderParamControl = (
    paramName: string,
    paramValue: string,
    visKey: string,
    onChange: (val: string) => void,
    paramDef?: ScriptParameterDef,
  ) => {
    const hasChoices = paramDef?.choices && paramDef.choices.length > 0;
    const isBool = paramDef?.dataType === 'bool' || paramDef?.choices?.every((c) => c === 'true' || c === 'false');
    const isPassword = PASSWORD_PATTERN.test(paramName);
    const isSensitive = SENSITIVE_PATTERN.test(paramName);
    const isNumeric = /port|count|max|timeout|attempts|interval|delay/i.test(paramName);

    if (hasChoices && !isBool) {
      return (
        <FormControl key={visKey} size="small" sx={{ flex: '0 0 auto', minWidth: 120 }}>
          <InputLabel sx={{ fontSize: '0.75rem' }}>{paramName}</InputLabel>
          <Select
            value={paramValue || paramDef?.default || ''}
            label={paramName}
            onChange={(e) => onChange(e.target.value as string)}
            sx={{ fontSize: '0.75rem', height: 32 }}
          >
            {paramDef!.choices!.map((choice) => (
              <MenuItem key={choice} value={choice} sx={{ fontSize: '0.75rem' }}>
                {choice}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      );
    }

    if (isBool) {
      return (
        <FormControlLabel
          key={visKey}
          control={
            <Switch
              size="small"
              checked={(paramValue || paramDef?.default || 'false') === 'true'}
              onChange={(e) => onChange(e.target.checked ? 'true' : 'false')}
            />
          }
          label={<Typography variant="caption" sx={{ fontSize: '0.7rem' }}>{paramName}</Typography>}
          sx={{ ml: 0 }}
        />
      );
    }

    return (
      <TextField
        key={visKey}
        label={paramName}
        value={paramValue}
        onChange={(e) => onChange(e.target.value)}
        size="small"
        type={isPassword && !visiblePasswords[visKey] ? 'password' : isNumeric ? 'number' : 'text'}
        InputProps={(isPassword || isSensitive) ? {
          endAdornment: isPassword ? (
            <InputAdornment position="end">
              <IconButton
                size="small"
                onClick={() => setVisiblePasswords((prev) => ({ ...prev, [visKey]: !prev[visKey] }))}
                edge="end"
              >
                {visiblePasswords[visKey] ? <VisibilityOff sx={{ fontSize: 16 }} /> : <Visibility sx={{ fontSize: 16 }} />}
              </IconButton>
            </InputAdornment>
          ) : undefined,
        } : undefined}
        sx={{ flex: '0 0 auto', width: isNumeric ? 80 : 140, '& .MuiInputBase-input': { fontSize: '0.75rem' } }}
      />
    );
  };

  const renderExpandedParams = (deploymentId: string) => {
    if (expandedDeploymentId !== deploymentId) return null;

    if (paramsLoading) {
      return (
        <Box sx={{ py: 1, px: 1, display: 'flex', alignItems: 'center', gap: 1 }}>
          <CircularProgress size={16} />
          <Typography variant="caption" color="text.secondary">Loading parameters...</Typography>
        </Box>
      );
    }

    const isCampaign = expandedScriptConfigs.length > 0;
    const hasParams = isCampaign || expandedParams.length > 0;

    return (
      <Box sx={{ py: 1, px: 1 }}>
        {!hasParams ? (
          <Typography variant="caption" color="text.secondary">No parameters</Typography>
        ) : isCampaign ? (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
            {expandedScriptConfigs.map((sc, scIdx) => {
              const analysisDefs = expandedScriptAnalysis[sc.script_name] || [];
              // Use analysis definitions if available, otherwise fall back to stored params
              const paramEntries = analysisDefs.length > 0
                ? analysisDefs.map((def) => [def.name, sc.parameters[def.name] ?? def.default ?? ''] as [string, string])
                : Object.entries(sc.parameters).filter(([k]) => !FRAMEWORK_PARAMS.has(k));
              const analysisMap = Object.fromEntries(analysisDefs.map((d) => [d.name, d]));

              return (
                <Box key={`${sc.script_name}-${scIdx}`}>
                  <Typography variant="caption" sx={{ fontWeight: 600, color: 'primary.main', display: 'block', mb: 0.5 }}>
                    {sc.script_name}
                  </Typography>
                  {paramEntries.length > 0 ? (
                    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75, alignItems: 'center', overflowX: 'auto', pt: 0.5 }}>
                      {paramEntries.map(([paramName, paramValue]) =>
                        renderParamControl(
                          paramName,
                          String(paramValue ?? ''),
                          `${scIdx}-${paramName}`,
                          (val) => {
                            const updated = [...expandedScriptConfigs];
                            updated[scIdx] = { ...updated[scIdx], parameters: { ...updated[scIdx].parameters, [paramName]: val } };
                            setExpandedScriptConfigs(updated);
                          },
                          analysisMap[paramName],
                        )
                      )}
                    </Box>
                  ) : (
                    <Typography variant="caption" color="text.disabled">No parameters</Typography>
                  )}
                </Box>
              );
            })}
            <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
              <Button size="small" variant="contained" onClick={handleParamsSave} disabled={paramsSaving}>
                {paramsSaving ? 'Saving...' : 'Save'}
              </Button>
            </Box>
          </Box>
        ) : (
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75, alignItems: 'center' }}>
            {expandedParams.map((param, idx) =>
              renderParamControl(param.name, param.value, `${param.name}-${idx}`, (val) => {
                const updated = [...expandedParams];
                updated[idx] = { ...updated[idx], value: val };
                setExpandedParams(updated);
              })
            )}
            <Box sx={{ ml: 'auto' }}>
              <Button size="small" variant="contained" onClick={handleParamsSave} disabled={paramsSaving}>
                {paramsSaving ? 'Saving...' : 'Save'}
              </Button>
            </Box>
          </Box>
        )}
      </Box>
    );
  };

  return (
    <Box sx={{ px: isMobile ? 0.25 : isTablet ? 0.75 : 1, pt: isMobile ? 0.25 : 0.5, pb: isMobile ? 0.25 : isTablet ? 0.75 : 1 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: isCompact ? 'flex-start' : 'center', mb: 2, gap: 1, flexDirection: isCompact ? 'column' : 'row' }}>
        <Box sx={{ display: 'flex', alignItems: isCompact ? 'stretch' : 'center', gap: 1, flexDirection: isCompact ? 'column' : 'row', flex: 1, minWidth: 0 }}>
          <Typography variant="h4" sx={{ flexShrink: 0 }}>
            Monitor Tests
          </Typography>
          <TextField
            size="small"
            placeholder="Search..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon fontSize="small" />
                </InputAdornment>
              ),
            }}
            sx={{ minWidth: isCompact ? '100%' : 260, maxWidth: isCompact ? '100%' : 340 }}
          />
        </Box>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Chip
            label="Tests"
            clickable
            color={browserTab === 'tests' ? 'primary' : 'default'}
            variant={browserTab === 'tests' ? 'filled' : 'outlined'}
            onClick={() => {
              setBrowserTab('tests');
              setSearchParams((prev) => {
                const next = new URLSearchParams(prev);
                next.set('tab', 'tests');
                return next;
              });
            }}
          />
          <Chip
            label="Campaigns"
            clickable
            color={browserTab === 'campaigns' ? 'primary' : 'default'}
            variant={browserTab === 'campaigns' ? 'filled' : 'outlined'}
            onClick={() => {
              setBrowserTab('campaigns');
              setSearchParams((prev) => {
                const next = new URLSearchParams(prev);
                next.set('tab', 'campaigns');
                return next;
              });
            }}
          />
        </Box>
      </Box>

      <Grid container spacing={2}>
        {/* Tests Running */}
        <Grid item xs={12}>
          <Card sx={{ '& .MuiCardContent-root': { p: 2, '&:last-child': { pb: 2 } } }}>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', cursor: 'pointer', mb: runningExpanded ? 1 : 0 }} onClick={() => setRunningExpanded((v) => !v)}>
                <IconButton size="small" sx={{ mr: 0.5, p: 0.25 }}>
                  {runningExpanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                </IconButton>
                <Typography variant="h6">
                  {browserTab === 'campaigns' ? 'Campaigns Running' : 'Tests Running'} - {filteredRunningExecutions.length}
                </Typography>
              </Box>
              <Collapse in={runningExpanded}>
              {filteredRunningExecutions.length === 0 ? (
                emptySection('No running executions')
              ) : isCompact ? (
                <Box>
                  {filteredRunningExecutions.map((execution, idx) => (
                    <Box
                      key={execution.id}
                      sx={{
                        py: 0.75,
                        borderBottom: idx < filteredRunningExecutions.length - 1 ? '1px solid' : 'none',
                        borderColor: 'divider',
                      }}
                    >
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <Typography variant="body2" sx={{ fontWeight: 600 }}>
                          {getTargetLabel(execution.deployments?.host_name, execution.deployments?.device_id)}
                        </Typography>
                        <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
                          {getStatusChip('running')}
                          {execution.report_url ? (
                            <Chip label="R" clickable onClick={() => handleOpenR2Url(execution.report_url!)} size="small" color="primary" variant="outlined" sx={{ minWidth: 0 }} />
                          ) : null}
                        </Box>
                      </Box>
                      <Typography variant="caption" color="text.secondary" sx={{ overflowWrap: 'anywhere' }}>
                        {isCampaignDeployment(execution.deployments?.campaign_id, execution.deployments?.script_name, execution.is_campaign)
                              ? getCampaignDisplayName(execution.deployments?.script_name, execution.deployments?.name)
                              : getScriptDisplayName(execution.deployments?.script_name || execution.deployments?.name || '-')} · {formatToLocalTime(getExecutionTimestamp(execution) || '')}
                      </Typography>
                    </Box>
                  ))}
                </Box>
              ) : (
                <TableContainer component={Paper} variant="outlined">
                  <Table size="small" sx={{ '& .MuiTableCell-root': { py: 0.5 } }}>
                    <TableHead>
                      <TableRow>
                        <TableCell>Target</TableCell>
                        <TableCell>{browserTab === 'campaigns' ? 'Campaign' : 'Test'}</TableCell>
                        <TableCell>Start</TableCell>
                        <TableCell>Status</TableCell>
                        <TableCell>Report</TableCell>
                        <TableCell>Logs</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {filteredRunningExecutions.map((execution) => (
                        <TableRow key={execution.id} sx={{ ...getRowHoverSx() }}>
                          <TableCell>
                            <Typography variant="body2">
                              {getTargetLabel(execution.deployments?.host_name, execution.deployments?.device_id)}
                            </Typography>
                          </TableCell>
                          <TableCell>
                            <Typography variant="body2">
                              {isCampaignDeployment(execution.deployments?.campaign_id, execution.deployments?.script_name, execution.is_campaign)
                              ? getCampaignDisplayName(execution.deployments?.script_name, execution.deployments?.name)
                              : getScriptDisplayName(execution.deployments?.script_name || execution.deployments?.name || '-')}
                            </Typography>
                          </TableCell>
                          <TableCell>
                            {formatToLocalTime(getExecutionTimestamp(execution) || '')}
                            <Typography variant="caption" display="block" color="text.secondary">{userTimezone}</Typography>
                          </TableCell>
                          <TableCell>{getStatusChip('running')}</TableCell>
                          <TableCell>
                            {execution.report_url ? (
                              <Chip label="View Report" clickable onClick={() => handleOpenR2Url(execution.report_url!)} size="small" sx={{ cursor: 'pointer' }} icon={<LinkIcon />} color="primary" variant="outlined" />
                            ) : (
                              <Chip label="No Report" size="small" variant="outlined" disabled />
                            )}
                          </TableCell>
                          <TableCell>
                            {execution.report_url ? (
                              <Chip icon={<LinkIcon />} label="Logs" size="small" clickable onClick={() => handleOpenR2Url(getLogsUrl(execution.report_url!))} color="secondary" variant="outlined" />
                            ) : (
                              <Chip label="No Logs" size="small" variant="outlined" disabled />
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              )}
              </Collapse>
            </CardContent>
          </Card>
        </Grid>

        {/* Queued Executions */}
        <Grid item xs={12}>
          <Card sx={{ '& .MuiCardContent-root': { p: 2, '&:last-child': { pb: 2 } } }}>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', cursor: 'pointer', mb: queueExpanded ? 1 : 0 }} onClick={() => setQueueExpanded((v) => !v)}>
                <IconButton size="small" sx={{ mr: 0.5, p: 0.25 }}>
                  {queueExpanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                </IconButton>
                <Typography variant="h6">
                  {browserTab === 'campaigns' ? 'Campaign Queue' : 'Test Queue'} - {filteredQueuedExecutions.length}
                </Typography>
              </Box>
              <Collapse in={queueExpanded}>
                {filteredQueuedExecutions.length === 0 ? (
                  emptySection('No queued executions')
                ) : isCompact ? (
                  <Box>
                    {filteredQueuedExecutions.map((execution, idx) => (
                      <Box
                        key={execution.id}
                        sx={{
                          py: 0.75,
                          borderBottom: idx < filteredQueuedExecutions.length - 1 ? '1px solid' : 'none',
                          borderColor: 'divider',
                        }}
                      >
                        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <Typography variant="body2" sx={{ fontWeight: 600 }}>
                            {getTargetLabel(execution.deployments?.host_name, execution.deployments?.device_id)}
                          </Typography>
                          <Chip label="Queued" size="small" color="info" variant="outlined" />
                        </Box>
                        <Typography variant="caption" color="text.secondary" display="block" sx={{ overflowWrap: 'anywhere' }}>
                          {isCampaignDeployment(execution.deployments?.campaign_id, execution.deployments?.script_name, execution.is_campaign)
                              ? getCampaignDisplayName(execution.deployments?.script_name, execution.deployments?.name)
                              : getScriptDisplayName(execution.deployments?.script_name || execution.deployments?.name || '-')}
                        </Typography>
                        <Typography variant="caption" color="text.secondary" display="block">
                          Queued: {formatToLocalTime(execution.scheduled_at || execution.started_at || execution.completed_at || '')}
                        </Typography>
                      </Box>
                    ))}
                  </Box>
                ) : (
                  <TableContainer component={Paper} variant="outlined">
                    <Table size="small" sx={{ '& .MuiTableCell-root': { py: 0.5 } }}>
                      <TableHead>
                        <TableRow>
                          <TableCell>Target</TableCell>
                          <TableCell>{browserTab === 'campaigns' ? 'Campaign' : 'Test'}</TableCell>
                          <TableCell>Status</TableCell>
                          <TableCell>Queued At</TableCell>
                          <TableCell sx={{ width: 40 }} />
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {filteredQueuedExecutions.map((execution) => (
                          <TableRow key={execution.id} sx={{ ...getRowHoverSx() }}>
                            <TableCell>
                              <Typography variant="body2">
                                {getTargetLabel(execution.deployments?.host_name, execution.deployments?.device_id)}
                              </Typography>
                            </TableCell>
                            <TableCell>
                              <Typography variant="body2">
                                {isCampaignDeployment(execution.deployments?.campaign_id, execution.deployments?.script_name, execution.is_campaign)
                              ? getCampaignDisplayName(execution.deployments?.script_name, execution.deployments?.name)
                              : getScriptDisplayName(execution.deployments?.script_name || execution.deployments?.name || '-')}
                              </Typography>
                            </TableCell>
                            <TableCell>
                              <Chip label="Queued" size="small" color="info" variant="outlined" />
                            </TableCell>
                            <TableCell>
                              {formatToLocalTime(execution.scheduled_at || execution.started_at || execution.completed_at || '')}
                            </TableCell>
                            <TableCell>
                              <IconButton size="small" color="error" onClick={() => handleAbortQueued(execution.id)} title="Cancel queued execution">
                                <DeleteOutline fontSize="small" />
                              </IconButton>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                )}
              </Collapse>
            </CardContent>
          </Card>
        </Grid>

        {/* Tests Scheduled */}
        {isDeploymentsEnabled() && (
        <Grid item xs={12}>
          <Card sx={{ '& .MuiCardContent-root': { p: 2, '&:last-child': { pb: 2 } } }}>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', cursor: 'pointer', mb: scheduledExpanded ? 1 : 0 }} onClick={() => setScheduledExpanded((v) => !v)}>
                <IconButton size="small" sx={{ mr: 0.5, p: 0.25 }}>
                  {scheduledExpanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                </IconButton>
                <Typography variant="h6">
                  {browserTab === 'campaigns' ? 'Campaigns Scheduled' : 'Tests Scheduled'} - {scheduledDeployments.length}
                </Typography>
              </Box>
              <Collapse in={scheduledExpanded}>
              {scheduledDeployments.length === 0 ? (
                emptySection('No scheduled executions')
              ) : isCompact ? (
                <Box>
                  {scheduledDeployments.map((deployment, idx) => {
                    const nextRun = getScheduledNextRun(deployment);
                    return (
                    <Box
                      key={deployment.id}
                      sx={{
                        py: 0.75,
                        borderBottom: idx < scheduledDeployments.length - 1 ? '1px solid' : 'none',
                        borderColor: 'divider',
                      }}
                    >
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <Typography variant="body2" sx={{ fontWeight: 600 }}>
                          {getTargetLabel(deployment.host_name, deployment.device_id)}
                        </Typography>
                        <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
                          <Chip label={deployment.status} color={deployment.status === 'active' ? 'success' : deployment.status === 'paused' ? 'warning' : 'default'} size="small" variant="outlined" />
                          {hasEditableParams(deployment) && (
                          <IconButton size="small" onClick={() => handleParamsExpand(deployment)}>
                            {expandedDeploymentId === deployment.id ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
                          </IconButton>
                          )}
                          <Button size="small" variant="text" sx={{ minWidth: 0, px: 0.5 }} onClick={(e) => handleEditOpen(e, deployment)}>Edit</Button>
                          <Button size="small" variant="text" sx={{ minWidth: 0, px: 0.5 }} onClick={() => handlePauseToggle(deployment)}>{deployment.status === 'paused' ? '>' : '||'}</Button>
                          <Button size="small" variant="text" color="error" sx={{ minWidth: 0, px: 0.5 }} onClick={() => handleDelete(deployment)}>X</Button>
                        </Box>
                      </Box>
                      <Typography variant="caption" color="text.secondary" display="block" sx={{ overflowWrap: 'anywhere' }}>
                        {browserTab === 'campaigns' ? getCampaignDisplayName(deployment.script_name, deployment.name) : stripTimestampSuffix(getScriptDisplayName(deployment.script_name || deployment.name))} · {getRepeatLabel(deployment)}
                      </Typography>
                      <Typography variant="caption" color="text.secondary" display="block">
                        Start: {deployment.start_date ? formatToLocalTime(deployment.start_date) : 'Now'} · Next: {nextRun ? formatToLocalTime(nextRun.toISOString()) : '-'}
                      </Typography>
                      {hasEditableParams(deployment) && (
                      <Collapse in={expandedDeploymentId === deployment.id}>
                        {renderExpandedParams(deployment.id)}
                      </Collapse>
                      )}
                    </Box>
                    );
                  })}
                </Box>
              ) : (
                <TableContainer component={Paper} variant="outlined">
                  <Table size="small" sx={{ '& .MuiTableCell-root': { py: 0.25, whiteSpace: 'nowrap' } }}>
                    <TableHead>
                        <TableRow>
                          <TableCell>Target</TableCell>
                          <TableCell>{browserTab === 'campaigns' ? 'Campaign' : 'Test'}</TableCell>
                          <TableCell>Repeat</TableCell>
                        <TableCell>End</TableCell>
                        <TableCell>Next Run</TableCell>
                        <TableCell>Runs</TableCell>
                        <TableCell>Status</TableCell>
                        <TableCell>Actions</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {scheduledDeployments.map((deployment) => {
                        const nextRun = getScheduledNextRun(deployment);
                        const isExpanded = expandedDeploymentId === deployment.id;
                        return (
                        <React.Fragment key={deployment.id}>
                        <TableRow sx={{ ...getRowHoverSx(), ...(isExpanded ? { '& > .MuiTableCell-root': { borderBottom: 'none' } } : {}) }}>
                          <TableCell>
                            <Typography variant="body2">
                              {getTargetLabel(deployment.host_name, deployment.device_id)}
                            </Typography>
                          </TableCell>
                          <TableCell>
                            <Typography variant="body2">
                              {browserTab === 'campaigns' ? getCampaignDisplayName(deployment.script_name, deployment.name) : stripTimestampSuffix(getScriptDisplayName(deployment.script_name || deployment.name))}
                            </Typography>
                          </TableCell>
                          <TableCell>{getRepeatLabel(deployment)}</TableCell>
                          <TableCell>{deployment.end_date ? formatToLocalTime(deployment.end_date) : '-'}</TableCell>
                          <TableCell>
                            <Typography variant="body2" color={nextRun ? 'text.primary' : 'text.disabled'}>
                              {nextRun ? formatToLocalTime(nextRun.toISOString()) : '-'}
                            </Typography>
                          </TableCell>
                          <TableCell>{deployment.execution_count}</TableCell>
                          <TableCell>
                            <Chip label={deployment.status} color={deployment.status === 'active' ? 'success' : deployment.status === 'paused' ? 'warning' : 'default'} size="small" variant="outlined" />
                          </TableCell>
                          <TableCell>
                            <Box sx={{ display: 'flex', gap: 0.25, alignItems: 'center' }}>
                              {hasEditableParams(deployment) && (
                              <Tooltip title="Parameters">
                                <IconButton size="small" onClick={() => handleParamsExpand(deployment)}>
                                  {isExpanded ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
                                </IconButton>
                              </Tooltip>
                              )}
                              <Button size="small" variant="text" onClick={(e) => handleEditOpen(e, deployment)}>Edit</Button>
                              <Tooltip title={deployment.status === 'paused' ? 'Resume' : 'Pause'}>
                                <IconButton size="small" onClick={() => handlePauseToggle(deployment)}>
                                  {deployment.status === 'paused' ? <PlayArrow fontSize="small" /> : <Pause fontSize="small" />}
                                </IconButton>
                              </Tooltip>
                              <Tooltip title="Delete">
                                <IconButton size="small" color="error" onClick={() => handleDelete(deployment)}>
                                  <DeleteOutline fontSize="small" />
                                </IconButton>
                              </Tooltip>
                            </Box>
                          </TableCell>
                        </TableRow>
                        {hasEditableParams(deployment) && (
                        <TableRow sx={getRowHoverSx()}>
                          <TableCell colSpan={8} sx={{ py: 0, ...(isExpanded ? {} : { borderBottom: 'none' }) }}>
                            <Collapse in={isExpanded}>
                              {renderExpandedParams(deployment.id)}
                            </Collapse>
                          </TableCell>
                        </TableRow>
                        )}
                        </React.Fragment>
                        );
                      })}
                    </TableBody>
                  </Table>
                </TableContainer>
              )}
              </Collapse>
            </CardContent>
          </Card>
        </Grid>
        )}

        {/* Last Executions */}
        <Grid item xs={12}>
          <ExecutionHistorySection
            title={`${browserTab === 'campaigns' ? 'Last Campaign Executions' : 'Last Executions'} - ${allExecutions.length}`}
            rows={executionHistoryRows}
            scriptColumnLabel={browserTab === 'campaigns' ? 'Campaign' : 'Test'}
            emptyMessage="No execution history"
            onOpenUrl={handleOpenR2Url}
            isCompact={isCompact}
            isTablet={isTablet}
            collapsible
            expanded={historyExpanded}
            onToggleExpanded={() => setHistoryExpanded((v) => !v)}
            cardSx={{ '& .MuiCardContent-root': { p: 2, '&:last-child': { pb: 2 } } }}
            contentSx={{ p: 2, '&:last-child': { pb: 2 } }}
            headerCellSx={execColumns.headerCellSx}
            bodyCellSx={execColumns.bodyCellSx}
            renderHeaderExtra={(key) => (
              <Box component="span" onMouseDown={execColumns.onMouseDown(key)} sx={execColumns.resizeHandleSx} />
            )}
            tableSx={{ tableLayout: 'fixed', '& .MuiTableCell-root': { py: 0.25, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' } }}
          />
        </Grid>
      </Grid>

      {/* Edit Popover */}
      <Popper
        open={editPopperOpen}
        anchorEl={editAnchorEl}
        placement="bottom-start"
        style={{ zIndex: 1300 }}
        modifiers={[
          { name: 'offset', options: { offset: [0, 4] } },
          { name: 'preventOverflow', options: { boundary: 'viewport', padding: 8 } },
        ]}
      >
        <ClickAwayListener onClickAway={handleEditClickAway}>
          <Paper
            ref={popperRef}
            elevation={8}
            sx={{
              width: isCompact ? 'calc(100vw - 32px)' : 420,
              maxWidth: '100vw',
              border: '1px solid',
              borderColor: isDarkMode ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.12)',
              borderRadius: 2,
            }}
          >
            {/* Header */}
            <Box sx={{
              px: 2, py: 1.25,
              borderBottom: '1px solid',
              borderColor: isDarkMode ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)',
            }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                {getCampaignDisplayName(editingDeployment?.script_name, editingDeployment?.name)}
              </Typography>
            </Box>

            {/* Fields */}
            <Box sx={{ px: 2, py: 1.5, display: 'flex', flexDirection: 'column', gap: 1.5 }}>
              {/* Cron with presets */}
              <CronHelper
                value={editCron}
                onChange={setEditCron}
              />

              {/* Start / End / Max on one row */}
              <Box sx={{ display: 'flex', gap: 1 }}>
                <TextField
                  label="Start"
                  type="datetime-local"
                  value={editStartDate}
                  onChange={(e) => setEditStartDate(e.target.value)}
                  size="small"
                  InputLabelProps={{ shrink: true }}
                  sx={{ flex: 1, '& .MuiInputBase-input': { fontSize: '0.75rem' } }}
                />
                <TextField
                  label="End"
                  type="datetime-local"
                  value={editEndDate}
                  onChange={(e) => setEditEndDate(e.target.value)}
                  size="small"
                  InputLabelProps={{ shrink: true }}
                  sx={{ flex: 1, '& .MuiInputBase-input': { fontSize: '0.75rem' } }}
                />
                <TextField
                  label="Max runs"
                  type="number"
                  value={editMaxExecutions}
                  onChange={(e) => setEditMaxExecutions(e.target.value)}
                  size="small"
                  placeholder="-"
                  inputProps={{ min: 1 }}
                  sx={{ width: 90, '& .MuiInputBase-input': { fontSize: '0.75rem' } }}
                />
              </Box>
            </Box>

            {/* Actions */}
            <Box sx={{
              px: 2, py: 1,
              borderTop: '1px solid',
              borderColor: isDarkMode ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)',
              display: 'flex', justifyContent: 'flex-end', gap: 0.5,
            }}>
              <Button size="small" onClick={handleEditClose} startIcon={<Close sx={{ fontSize: 16 }} />}>
                Cancel
              </Button>
              <Button size="small" variant="contained" onClick={handleEditSave} startIcon={<Check sx={{ fontSize: 16 }} />}>
                Save
              </Button>
            </Box>
          </Paper>
        </ClickAwayListener>
      </Popper>
    </Box>
  );
};

export default MonitorTests;
