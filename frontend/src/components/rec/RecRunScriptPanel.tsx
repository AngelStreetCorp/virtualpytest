import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import RadioButtonUncheckedIcon from '@mui/icons-material/RadioButtonUnchecked';
import StopIcon from '@mui/icons-material/Stop';
import {
  Box,
  Button,
  CircularProgress,
  LinearProgress,
  Link,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useWorkspaceContext } from '../../contexts/workspace/WorkspaceContext';
import { useRunningLog } from '../../hooks/rec/useRunningLog';
import { useRun } from '../../hooks/useRun';
import { useMaintenanceGuard } from '../../hooks/platformUpdate/useMaintenanceGuard';
import { useScript } from '../../hooks/script/useScript';
import { useTestCaseExecution } from '../../hooks/testcase/useTestCaseExecution';
import { useTestCaseSave } from '../../hooks/testcase/useTestCaseSave';
import { useI18n } from '../../i18n/useI18n';
import { Device, Host } from '../../types/common/Host_Types';
import { api } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { getLogsUrl } from '../../utils/executionUtils';
import { getCachedExecutableList } from '../../utils/executionListCache';
import { openR2Url } from '../../utils/infrastructure/cloudflareUtils';
import { buildScriptArgs } from '../../utils/scriptArgsUtils';
import { isDeviceCompatibleWithRules } from '../../utils/targetCompatibility';
import { stampInputValues } from '../../utils/testcase/scriptInputUtils';
import { ExecutableItem } from '../common/UnifiedExecutableSelector';
import { ScriptParameterRow, ScriptParameterRowParam } from '../common/ParameterInput/ScriptParameterRow';
import { dangerButtonSx, primaryButtonSx, segmentedSx } from '../common/PageChrome';
import { RecOverlayPanel } from './RecOverlayPanel';
import { TYPOGRAPHY } from '../../constants/typography';

interface RecRunScriptPanelProps {
  host: Host;
  device: Device;
  isControlActive: boolean;
  onClose: () => void;
}

type Kind = 'script' | 'testcase' | 'virtual';
type Env = 'dev' | 'test' | 'prod';
type Outcome = 'passed' | 'failed' | 'aborted';

interface RunResult {
  outcome: Outcome;
  durationMs: number;
  reportUrl?: string;
  logsUrl?: string;
  message?: string;
}

interface PanelParam extends ScriptParameterRowParam {
  name: string;
}

// Framework args come from the target device, never from the form (same as RunTests).
const FRAMEWORK_PARAMS = ['host', 'device'];
const UI_PARAMS = ['userinterface', 'userinterface_name'];
const MAX_VISIBLE_STEPS = 4;

const storageKey = (host: Host, device: Device) =>
  `virtualpytest:runScriptPanel:${host.host_name}:${device.device_id || 'host'}`;

interface Remembered {
  itemId: string;
  kind: Kind;
  values: Record<string, string>;
  uiMode?: 'dev' | 'prod';
}

const readRemembered = (key: string): Remembered | null => {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as Remembered) : null;
  } catch {
    return null;
  }
};

const writeRemembered = (key: string, value: Remembered) => {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable: remembering is a convenience only */
  }
};

const kindOf = (item: ExecutableItem): Kind =>
  item.type === 'testcase' ? 'testcase' : item.is_virtual ? 'virtual' : 'script';

// A virtual script has up to 3 rows (dev/test/prod); RunTests prefers prod, else whichever exists.
const pickEnvironment = (item: ExecutableItem): Env => {
  if (!item.is_virtual) return 'prod';
  const ids = item.virtual_script_env_ids;
  const available = (['dev', 'test', 'prod'] as const).filter((env) => Boolean(ids?.[env]));
  if (available.length === 0) return 'dev';
  return available.includes('prod') ? 'prod' : available[0];
};

const resolveVirtualScriptId = (item: ExecutableItem, env: Env): string | undefined => {
  if (!item.is_virtual) return undefined;
  return item.virtual_script_env_ids?.[env] || item.virtual_script_id;
};

const formatDuration = (ms: number): string => {
  const s = Math.max(0, Math.round(ms / 1000));
  const m = Math.floor(s / 60);
  return m > 0 ? `${m}m ${String(s % 60).padStart(2, '0')}s` : `${s}s`;
};

const Content: React.FC<RecRunScriptPanelProps> = ({ host, device, onClose }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { isScriptAllowed } = useWorkspaceContext();
  const { executeMultipleScripts } = useScript();
  const { executeTestCase } = useTestCaseExecution();
  const { getTestCase } = useTestCaseSave();
  const { guardAny, guardDialog } = useMaintenanceGuard();

  const deviceId = device.device_id || 'host';
  const memoKey = storageKey(host, device);

  // ---- list (state 1) -------------------------------------------------------------------
  const [items, setItems] = useState<ExecutableItem[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [kind, setKind] = useState<Kind>('script');
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<ExecutableItem | null>(null);
  const restoredRef = useRef(false);
  const pendingValuesRef = useRef<Record<string, string> | null>(null);

  useEffect(() => {
    let cancelled = false;
    getCachedExecutableList(buildServerUrl('/server/executable/list'))
      .then((data: any) => {
        if (cancelled) return;
        if (!data?.success) throw new Error(data?.error || 'Failed to load executables');
        const flat: ExecutableItem[] = [];
        (data.folders || []).forEach((folder: any) =>
          (folder.items || []).forEach((item: any) => flat.push({ ...item, folder: folder.name })),
        );
        setItems(flat);
      })
      .catch((e) => {
        if (!cancelled) setListError(String(e?.message || e));
      })
      .finally(() => {
        if (!cancelled) setListLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const compatible = useCallback(
    (item: ExecutableItem): boolean => {
      if (item.folder === 'test_campaign') return false;
      if (item.type === 'script' && !isScriptAllowed(item.id)) return false;
      // No declared rules = runnable everywhere (same as RunTests), otherwise the device must match.
      if (!item.target_rules) return true;
      return isDeviceCompatibleWithRules(host, device, item.target_rules);
    },
    [host, device, isScriptAllowed],
  );

  const visibleItems = useMemo(() => {
    const q = search.trim().toLowerCase();
    return items
      .filter((item) => kindOf(item) === kind)
      .filter(compatible)
      .filter(
        (item) => !q || item.name.toLowerCase().includes(q),
      )
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [items, kind, search, compatible]);

  // ---- configure (state 2) --------------------------------------------------------------
  const env = selected ? pickEnvironment(selected) : 'prod';
  const selectedKind = selected ? kindOf(selected) : null;
  const virtualScriptId = selected ? resolveVirtualScriptId(selected, env) : undefined;

  // Script analysis + default values: the same hook RunTests uses. Testcases skip it ('' = idle).
  const {
    scriptAnalysis,
    parameterValues,
    analyzingScript,
    handleParameterChange,
  } = useRun({
    selectedScript: selected && selected.type === 'script' ? selected.id : '',
    selectedDevice: deviceId,
    selectedHost: host.host_name,
    showWizard: true,
    virtualScriptId,
  });

  // Testcases: parameters are the non-protected scriptConfig inputs of the graph.
  const [tcGraph, setTcGraph] = useState<any | null>(null);
  const [tcLoading, setTcLoading] = useState(false);
  const [tcError, setTcError] = useState<string | null>(null);
  const [tcValues, setTcValues] = useState<Record<string, string>>({});
  const [uiMode, setUiMode] = useState<'dev' | 'prod'>('dev');

  useEffect(() => {
    setTcGraph(null);
    setTcError(null);
    setTcValues({});
    if (!selected || selected.type !== 'testcase') return;
    let cancelled = false;
    setTcLoading(true);
    getTestCase(selected.id)
      .then((res) => {
        if (cancelled) return;
        if (!res.success || !res.testcase) throw new Error(res.error || 'Failed to load test case');
        const graph = res.testcase.graph_json;
        setTcGraph(graph);
        const inputs = (graph?.scriptConfig?.inputs || []).filter((i: any) => i && !i.protected);
        const defaults: Record<string, string> = {};
        inputs.forEach((i: any) => {
          defaults[i.name] = i.default != null ? String(i.default) : '';
        });
        setTcValues({ ...defaults, ...(pendingValuesRef.current || {}) });
        pendingValuesRef.current = null;
      })
      .catch((e) => {
        if (!cancelled) setTcError(String(e?.message || e));
      })
      .finally(() => {
        if (!cancelled) setTcLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selected?.id, selected?.type]);

  // After a script analysis lands: device preferred UI/variant first, then remembered values on top.
  useEffect(() => {
    if (!scriptAnalysis) return;
    const names = scriptAnalysis.parameters.map((p) => p.name);
    if (device.preferred_userinterface) {
      names.filter((n) => UI_PARAMS.includes(n)).forEach((n) => handleParameterChange(n, device.preferred_userinterface!));
      if (names.includes('variant')) handleParameterChange('variant', device.preferred_variant || '');
    }
    const saved = pendingValuesRef.current;
    if (saved) {
      Object.entries(saved).forEach(([name, value]) => {
        if (names.includes(name)) handleParameterChange(name, value);
      });
      pendingValuesRef.current = null;
    }
  }, [scriptAnalysis]);

  const params: PanelParam[] = useMemo(() => {
    if (selectedKind === 'testcase') {
      return (tcGraph?.scriptConfig?.inputs || [])
        .filter((i: any) => i && !i.protected)
        .map((i: any) => ({
          name: i.name,
          required: Boolean(i.required),
          default: i.default != null ? String(i.default) : undefined,
          dataType: i.type === 'number' ? 'float' : i.type === 'boolean' ? 'bool' : 'str',
        }));
    }
    return (scriptAnalysis?.parameters || [])
      .filter((p) => !FRAMEWORK_PARAMS.includes(p.name))
      .map((p) => ({
        name: p.name,
        required: p.required,
        default: p.default,
        choices: p.choices,
        dataType: p.dataType,
      }));
  }, [selectedKind, tcGraph, scriptAnalysis]);

  const values = selectedKind === 'testcase' ? tcValues : parameterValues;
  const setValue = useCallback(
    (name: string, value: string) => {
      if (selectedKind === 'testcase') setTcValues((prev) => ({ ...prev, [name]: value }));
      else handleParameterChange(name, value);
    },
    [selectedKind, handleParameterChange],
  );

  const uiParam = params.find((p) => UI_PARAMS.includes(p.name));
  const variantParam = params.find((p) => p.name === 'variant');
  const otherParams = params.filter((p) => !UI_PARAMS.includes(p.name) && p.name !== 'variant');
  const requiredParams = otherParams.filter((p) => p.required);
  const optionalParams = otherParams.filter((p) => !p.required);
  const [showOptional, setShowOptional] = useState(false);

  const missingRequired = params.some((p) => p.required && !(values[p.name] ?? '').trim());
  const configLoading = selectedKind === 'testcase' ? tcLoading : analyzingScript;
  const configReady =
    !!selected && !configLoading && (selectedKind === 'testcase' ? !!tcGraph && !tcError : !!scriptAnalysis);

  const allValues = {
    userinterface: values['userinterface'] || '',
    userinterface_name: values['userinterface_name'] || '',
    variant: values['variant'] || '',
  };

  const renderParam = (p: PanelParam) => (
    <ScriptParameterRow
      key={p.name}
      param={p}
      value={values[p.name] ?? ''}
      onChange={(v) => {
        setValue(p.name, v);
        // The variant belongs to the userinterface: a different UI starts from base again.
        if (UI_PARAMS.includes(p.name) && variantParam) setValue('variant', '');
      }}
      allValues={allValues}
      scriptName={(selected?.id || '').replace(/\.py$/, '')}
      deviceModel={device.device_model}
      uiMode={uiMode}
      onUiModeChange={UI_PARAMS.includes(p.name) ? setUiMode : undefined}
    />
  );

  const selectItem = (item: ExecutableItem, savedValues?: Record<string, string>) => {
    pendingValuesRef.current = savedValues || null;
    setShowOptional(false);
    setResult(null);
    setSelected(item);
  };

  // Last-used item for this device: reopen it with its values (Change goes back to the list).
  useEffect(() => {
    if (restoredRef.current || listLoading || items.length === 0) return;
    restoredRef.current = true;
    const saved = readRemembered(memoKey);
    if (!saved) return;
    const item = items.find((i) => i.id === saved.itemId && kindOf(i) === saved.kind);
    if (!item || !compatible(item)) return;
    setKind(saved.kind);
    if (saved.uiMode) setUiMode(saved.uiMode);
    selectItem(item, saved.values);
  }, [listLoading, items]);

  // ---- running (state 3) ----------------------------------------------------------------
  const [running, setRunning] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [result, setResult] = useState<RunResult | null>(null);
  const [startedAt, setStartedAt] = useState(0);
  const [now, setNow] = useState(0);
  const abortedRef = useRef(false);
  const launchingRef = useRef(false);

  const { logData } = useRunningLog(host, deviceId, running);

  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [running]);

  const finish = (res: Omit<RunResult, 'outcome'> & { passed: boolean | undefined }) => {
    const outcome: Outcome = abortedRef.current ? 'aborted' : res.passed === false ? 'failed' : 'passed';
    setResult({ outcome, durationMs: res.durationMs, reportUrl: res.reportUrl, logsUrl: res.logsUrl, message: res.message });
    setRunning(false);
    setStopping(false);
  };

  const launch = async () => {
    if (!selected || launchingRef.current) return;
    launchingRef.current = true;
    abortedRef.current = false;
    setResult(null);
    setRunning(true);
    const t0 = Date.now();
    setStartedAt(t0);
    setNow(t0);
    writeRemembered(memoKey, { itemId: selected.id, kind: selectedKind || 'script', values, uiMode });
    try {
      if (selectedKind === 'testcase') {
        const inputValues: Record<string, any> = { ...values };
        const uiName = selected.userinterface || device.preferred_userinterface || '';
        const runValues: Record<string, any> = {
          ...inputValues,
          device_model_name: device.device_model || 'unknown',
          host_name: host.host_name,
          device_name: deviceId,
          userinterface_name: uiName,
        };
        const stamped = stampInputValues(tcGraph, runValues);
        const res = await executeTestCase(stamped, deviceId, host.host_name, uiName, selected.name, {
          testcase_id: selected.id,
          testcase_inputs: inputValues,
        });
        const passed = res.success ? res.result_type !== 'failure' : false;
        finish({
          passed,
          durationMs: res.execution_time_ms ?? Date.now() - t0,
          reportUrl: res.report_url,
          logsUrl: res.logs_url || (res.report_url ? getLogsUrl(res.report_url) : undefined),
          message: res.success ? undefined : res.error,
        });
      } else {
        const parameters = buildScriptArgs(scriptAnalysis?.parameters, (name) => values[name] ?? '', {
          hostName: host.host_name,
          deviceId,
          uiMode,
        });
        const execId = `exec_${t0}_${host.host_name}_${deviceId}`;
        const results = await executeMultipleScripts([
          {
            id: execId,
            scriptName: selected.id,
            hostName: host.host_name,
            deviceId,
            parameters,
            // Locked device: fail with 423 instead of a hidden one-shot queue (this panel shows one live run).
            queueIfLocked: false,
            environment: env,
            virtualScriptId,
          },
        ]);
        const res: any = results[execId];
        if (res?.errorType === 'device_locked') {
          finish({ passed: false, durationMs: Date.now() - t0, message: res.message || t('Device is busy') });
        } else {
          const passed =
            res?.script_success !== undefined && res?.script_success !== null
              ? Boolean(res.script_success)
              : res?.exit_code !== undefined && res.exit_code !== 0
                ? false
                : undefined;
          finish({
            passed,
            durationMs: Date.now() - t0,
            reportUrl: res?.report_url,
            logsUrl: res?.logs_url || (res?.report_url ? getLogsUrl(res.report_url) : undefined),
            message: passed === false && !res?.report_url ? res?.stderr || undefined : undefined,
          });
        }
      }
    } catch (e) {
      finish({ passed: false, durationMs: Date.now() - t0, message: e instanceof Error ? e.message : String(e) });
    } finally {
      launchingRef.current = false;
    }
  };

  const run = () => {
    guardAny([{ hostName: host.host_name, deviceId }], () => void launch());
  };

  const stop = async () => {
    if (!running || stopping) return;
    setStopping(true);
    abortedRef.current = true;
    try {
      await api.post(
        buildServerUrl(selectedKind === 'testcase' ? '/server/testcase/abortRunning' : '/server/script/abortRunning'),
        { host_name: host.host_name, device_id: deviceId },
      );
    } catch {
      // The run may already be over; the pending execution settles the state either way.
    }
  };

  const openUrl = (url?: string) => {
    if (url) void openR2Url(url).catch(() => undefined);
  };

  // ---- render ---------------------------------------------------------------------------
  const muted = { color: P.textMuted, fontSize: TYPOGRAPHY.caption.size };

  const stepList = useMemo(() => {
    if (!logData) return [];
    const steps: Array<{ key: string; label: string; state: 'done' | 'current' | 'next' }> = [];
    const done = logData.completed_steps?.length
      ? logData.completed_steps
      : logData.previous_step
        ? [logData.previous_step]
        : [];
    done.forEach((s) => steps.push({ key: `d${s.step_number}`, label: s.description || s.command, state: 'done' }));
    if (logData.current_step) {
      const s = logData.current_step;
      steps.push({ key: `c${s.step_number}`, label: s.description || s.command, state: 'current' });
    }
    if (logData.next_step) {
      const s = logData.next_step;
      steps.push({ key: `n${s.step_number}`, label: s.description || s.command, state: 'next' });
    }
    const currentIdx = steps.findIndex((s) => s.state === 'current');
    const from = Math.max(0, (currentIdx < 0 ? steps.length : currentIdx) - 2);
    return steps.slice(from, from + MAX_VISIBLE_STEPS);
  }, [logData]);

  const pickList = (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <ToggleButtonGroup
        exclusive
        size="small"
        value={kind}
        onChange={(_, v) => v && setKind(v)}
        sx={segmentedSx(P, 'sm')}
      >
        <ToggleButton value="script">{t('Scripts')}</ToggleButton>
        <ToggleButton value="testcase">{t('Testcases')}</ToggleButton>
        <ToggleButton value="virtual">{t('Virtual')}</ToggleButton>
      </ToggleButtonGroup>
      <TextField
        size="small"
        placeholder={t('Search')}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        sx={{ '& .MuiInputBase-root': { fontSize: TYPOGRAPHY.caption.size } }}
      />
      <Box
        sx={{
          maxHeight: 300,
          overflowY: 'auto',
          border: `1px solid ${P.borderColor}`,
          borderRadius: 1.5,
        }}
      >
        {listLoading && (
          <Box sx={{ p: 2, display: 'flex', justifyContent: 'center' }}>
            <CircularProgress size={18} sx={{ color: P.accent }} />
          </Box>
        )}
        {listError && (
          <Typography variant="caption" sx={{ color: P.error, p: 1.5, display: 'block' }}>
            {listError}
          </Typography>
        )}
        {!listLoading && !listError && visibleItems.length === 0 && (
          <Typography sx={{ ...muted, p: 1.5 }}>{t('Nothing to run for this device')}</Typography>
        )}
        {visibleItems.map((item) => (
          <Box
            key={`${item.type}:${item.id}`}
            role="button"
            tabIndex={0}
            onClick={() => selectItem(item)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') selectItem(item);
            }}
            sx={{
              px: 1.25,
              py: 0.75,
              cursor: 'pointer',
              borderBottom: `1px solid ${P.borderColor}`,
              '&:last-of-type': { borderBottom: 'none' },
              '&:hover': { bgcolor: 'transparent', outline: `1px solid ${P.accent}`, outlineOffset: -1 },
            }}
          >
            <Typography sx={{ fontSize: TYPOGRAPHY.body.size, fontWeight: 500, color: P.textPrimary }} noWrap>
              {item.name}
            </Typography>
          </Box>
        ))}
      </Box>
    </Box>
  );

  const locked = running || !!result;

  const configure = selected && (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.25 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1 }}>
        <Typography sx={{ fontSize: TYPOGRAPHY.body.size, fontWeight: 600, color: P.textPrimary }} noWrap>
          {selected.name}
        </Typography>
        {!running && (
          <Link
            component="button"
            underline="hover"
            onClick={() => {
              setSelected(null);
              setResult(null);
            }}
            sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.accent, flexShrink: 0 }}
          >
            {t('Change')}
          </Link>
        )}
      </Box>

      {configLoading && <CircularProgress size={18} sx={{ alignSelf: 'center', color: P.accent }} />}
      {tcError && (
        <Typography variant="caption" sx={{ color: P.error }}>
          {tcError}
        </Typography>
      )}

      {configReady && (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.25, opacity: running ? 0.6 : 1 }}>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.25, pointerEvents: running ? 'none' : 'auto' }}>
            {(uiParam || variantParam) && (
              <Box sx={{ display: 'flex', gap: 1, '& > *': { flex: 1, minWidth: 0, width: 'auto !important' } }}>
                {uiParam && renderParam(uiParam)}
                {variantParam && renderParam(variantParam)}
              </Box>
            )}
            {requiredParams.length > 0 && (
              <Box
                sx={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
                  gap: 1,
                  '& > *': { width: '100% !important', minWidth: '0 !important' },
                }}
              >
                {requiredParams.map(renderParam)}
              </Box>
            )}
            {optionalParams.length > 0 && (
              <>
                <Link
                  component="button"
                  underline="hover"
                  onClick={() => setShowOptional((v) => !v)}
                  sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, alignSelf: 'flex-start' }}
                >
                  {showOptional ? t('Show fewer') : t('Show {n} more parameters', { n: optionalParams.length })}
                </Link>
                {showOptional && (
                  <Box
                    sx={{
                      display: 'grid',
                      gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
                      gap: 1,
                      '& > *': { width: '100% !important', minWidth: '0 !important' },
                    }}
                  >
                    {optionalParams.map(renderParam)}
                  </Box>
                )}
              </>
            )}
            {params.length === 0 && <Typography sx={muted}>{t('No parameters')}</Typography>}
          </Box>
        </Box>
      )}

      {!locked && (
        <Button
          variant="contained"
          size="small"
          startIcon={<PlayArrowIcon />}
          disabled={!configReady || missingRequired}
          onClick={run}
          sx={{ ...(primaryButtonSx(P) as object), alignSelf: 'flex-start', fontSize: TYPOGRAPHY.caption.size }}
        >
          {t('Run')}
        </Button>
      )}

      {running && (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.75 }}>
          <LinearProgress
            variant={logData && logData.total_steps > 0 ? 'determinate' : 'indeterminate'}
            value={
              logData && logData.total_steps > 0
                ? Math.min(100, (Math.max(0, logData.current_step_number - 1) / logData.total_steps) * 100)
                : undefined
            }
            sx={{ height: 4, borderRadius: 2, bgcolor: P.hoverBg, '& .MuiLinearProgress-bar': { bgcolor: P.accent } }}
          />
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Typography sx={muted}>
              {logData && logData.total_steps > 0
                ? t('Step {n}/{total}', { n: logData.current_step_number, total: logData.total_steps })
                : t('Starting')}
              {' · '}
              {formatDuration(now - startedAt)}
            </Typography>
            <Button
              size="small"
              variant="outlined"
              startIcon={<StopIcon />}
              disabled={stopping}
              onClick={stop}
              sx={{ ...(dangerButtonSx(P) as object), fontSize: TYPOGRAPHY.caption.size, textTransform: 'none' }}
            >
              {t('Stop')}
            </Button>
          </Box>
          {stepList.map((s) => (
            <Box key={s.key} sx={{ display: 'flex', alignItems: 'center', gap: 0.75, minWidth: 0 }}>
              {s.state === 'done' ? (
                <CheckCircleOutlineIcon sx={{ fontSize: TYPOGRAPHY.body.size, color: P.success }} />
              ) : s.state === 'current' ? (
                <CircularProgress size={12} sx={{ color: P.accent }} />
              ) : (
                <RadioButtonUncheckedIcon sx={{ fontSize: TYPOGRAPHY.body.size, color: P.textMuted }} />
              )}
              <Typography
                noWrap
                sx={{
                  fontSize: TYPOGRAPHY.caption.size,
                  color: s.state === 'next' ? P.textMuted : P.textPrimary,
                  fontWeight: s.state === 'current' ? 600 : 400,
                }}
              >
                {s.label}
              </Typography>
            </Box>
          ))}
        </Box>
      )}

      {result && (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
            {result.outcome === 'passed' ? (
              <CheckCircleOutlineIcon sx={{ fontSize: TYPOGRAPHY.cardTitle.size, color: P.success }} />
            ) : (
              <ErrorOutlineIcon sx={{ fontSize: TYPOGRAPHY.cardTitle.size, color: result.outcome === 'aborted' ? P.textMuted : P.error }} />
            )}
            <Typography sx={{ fontSize: TYPOGRAPHY.body.size, fontWeight: 600, color: P.textPrimary }}>
              {result.outcome === 'passed' ? t('Passed') : result.outcome === 'aborted' ? t('Aborted') : t('Failed')}
            </Typography>
            <Typography sx={muted}>{formatDuration(result.durationMs)}</Typography>
          </Box>
          {result.message && (
            <Typography sx={{ ...muted, color: P.error, wordBreak: 'break-word' }}>{result.message}</Typography>
          )}
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            {result.reportUrl && (
              <Link component="button" underline="hover" onClick={() => openUrl(result.reportUrl)} sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.accent }}>
                {t('Report')}
              </Link>
            )}
            {result.logsUrl && (
              <Link component="button" underline="hover" onClick={() => openUrl(result.logsUrl)} sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.accent }}>
                {t('Logs')}
              </Link>
            )}
            <Link
              component="button"
              underline="hover"
              onClick={run}
              sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.accent, ml: 'auto' }}
            >
              {t('Run again')}
            </Link>
          </Box>
        </Box>
      )}
    </Box>
  );

  return (
    <RecOverlayPanel title={t('Run script')} onClose={onClose}>
      {selected ? configure : pickList}
      {guardDialog}
    </RecOverlayPanel>
  );
};

export const RecRunScriptPanel: React.FC<RecRunScriptPanelProps> = (props) => <Content {...props} />;

export default RecRunScriptPanel;
