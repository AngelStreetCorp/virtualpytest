import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import FiberManualRecordIcon from '@mui/icons-material/FiberManualRecord';
import HistoryIcon from '@mui/icons-material/History';
import MoreHorizIcon from '@mui/icons-material/MoreHoriz';
import SearchIcon from '@mui/icons-material/Search';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import HighlightOffIcon from '@mui/icons-material/HighlightOff';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import DescriptionOutlinedIcon from '@mui/icons-material/DescriptionOutlined';
import TerminalIcon from '@mui/icons-material/Terminal';
import ChevronRightIcon from '@mui/icons-material/ChevronRight';
import PublishIcon from '@mui/icons-material/Publish';
import SaveIcon from '@mui/icons-material/Save';
import {
  Autocomplete,
  Box,
  Button,
  CircularProgress,
  Collapse,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Divider,
  IconButton,
  InputBase,
  Menu,
  MenuItem,
  Paper,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
  useTheme,
} from '@mui/material';
import { python } from '@codemirror/lang-python';
import CodeMirror, { EditorView, Prec } from '@uiw/react-codemirror';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { useAgentChatPalette } from '../../../frontend/src/constants/agentChatTheme';

import { BuilderPageLayout } from '../../../frontend/src/components/common/builder';
import { DeviceControlPanels } from '../../../frontend/src/components/common/DeviceControlPanels';
import { ScriptParameterRow } from '../../../frontend/src/components/common/ParameterInput/ScriptParameterRow';
import { UserinterfaceSelector } from '../../../frontend/src/components/common/UserinterfaceSelector';
import { VariantSelector } from '../../../frontend/src/components/common/VariantSelector';
import { NavigationEditorDeviceControls } from '../../../frontend/src/components/navigation/Navigation_NavigationEditor_DeviceControls';
import { StyledDialog } from '../../../frontend/src/components/common/StyledDialog';
import { RunButton } from '../../../frontend/src/components/testcase/builder/RunButton';
import {
  isDeviceCompatibleWithRules,
  isHostCompatibleWithRules,
  TargetRules,
} from '../../../frontend/src/utils/targetCompatibility';
import {
  useVirtualScripts,
  VirtualScriptParam,
  VirtualScriptValidation,
  VirtualScriptVersion,
} from './hooks/useVirtualScripts';
import { useDeviceControlWithForceUnlock } from '../../../frontend/src/hooks/useDeviceControlWithForceUnlock';
import { useHostControl, useHostData } from '../../../frontend/src/hooks/useHostManager';
import { useScript } from '../../../frontend/src/hooks/script/useScript';
import { useToast } from '../../../frontend/src/hooks/useToast';

// userinterface + variant are surfaced by the shared header selectors (same as
// QuickTestBuilder); every other _script_args param goes in the params strip.
const HEADER_PARAMS = new Set(['userinterface', 'variant']);

type Palette = ReturnType<typeof useAgentChatPalette>;

/** Outcome of the last Run on this page (session only — runs are not listed per virtual script). */
interface LastRun {
  status: 'passed' | 'failed' | 'error';
  host: string;
  deviceId: string;
  startedAt: number;
  durationMs: number;
  reportUrl?: string;
  logsUrl?: string;
  error?: string;
}

/** dev › test › prod — a stage is filled when its row exists; prod opens its rollback history. */
const LifecyclePipeline: React.FC<{
  environments: { dev: boolean; test: boolean; prod: boolean };
  prodVersion?: number | null;
  onProdClick?: (e: React.MouseEvent<HTMLElement>) => void;
}> = ({ environments, prodVersion, onProdClick }) => {
  const P = useAgentChatPalette();
  const stages: Array<{ key: 'dev' | 'test' | 'prod'; label: string }> = [
    { key: 'dev', label: 'dev' },
    { key: 'test', label: 'test' },
    { key: 'prod', label: prodVersion ? `prod v${prodVersion}` : 'prod' },
  ];
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', bgcolor: P.hoverBg, borderRadius: 2, p: 0.375 }}>
      {stages.map((st, i) => {
        const on = environments[st.key];
        const isProd = st.key === 'prod';
        const clickable = isProd && on && !!onProdClick;
        const chip = (
          <Box
            onClick={clickable ? onProdClick : undefined}
            sx={{
              px: 1, height: 22, display: 'inline-flex', alignItems: 'center', borderRadius: 1.5,
              fontSize: '0.7rem', fontWeight: 600, whiteSpace: 'nowrap',
              cursor: clickable ? 'pointer' : 'default',
              color: !on ? P.textMuted : isProd ? P.gold : P.textPrimary,
              bgcolor: on ? (isProd ? `${P.gold}1f` : P.surface) : 'transparent',
              border: `1px solid ${on ? (isProd ? `${P.gold}66` : P.borderColor) : 'transparent'}`,
              textDecoration: on ? 'none' : 'line-through',
            }}
          >
            {st.label}
          </Box>
        );
        return (
          <React.Fragment key={st.key}>
            {i > 0 && <ChevronRightIcon sx={{ fontSize: 14, color: P.textMuted }} />}
            {clickable ? <Tooltip title="Prod history — roll back">{chip}</Tooltip> : <Tooltip title={on ? `In ${st.key}` : `Not in ${st.key} yet`}>{chip}</Tooltip>}
          </React.Fragment>
        );
      })}
    </Box>
  );
};

/** One line under the editor: how the last Run ended, where, how long, and its report/logs. */
const LastRunBar: React.FC<{ run: LastRun; P: Palette }> = ({ run, P }) => {
  const color = run.status === 'passed' ? P.success : run.status === 'failed' ? P.error : P.warning;
  const Icon = run.status === 'passed' ? CheckCircleOutlineIcon : run.status === 'failed' ? HighlightOffIcon : WarningAmberIcon;
  const linkSx = { p: 0.5, color: P.textSecondary, '&:hover': { color: P.accentText, bgcolor: P.hoverBg } };
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.25, px: 2, py: 0.75, borderTop: `1px solid ${P.borderColor}`, fontSize: '0.78rem', bgcolor: `${color}0f` }}>
      <Typography sx={{ fontSize: '0.72rem', color: P.textMuted }}>Last run</Typography>
      <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5, color, fontWeight: 600 }}>
        <Icon sx={{ fontSize: 16 }} />
        {run.status.charAt(0).toUpperCase() + run.status.slice(1)}
      </Box>
      <Typography noWrap sx={{ fontSize: '0.75rem', color: P.textSecondary, minWidth: 0 }} title={run.error}>
        {run.host} · {run.deviceId} · {(run.durationMs / 1000).toFixed(1)}s · {new Date(run.startedAt).toLocaleTimeString([], { hour12: false })}
        {run.error ? ` · ${run.error}` : ''}
      </Typography>
      <Box sx={{ flex: 1 }} />
      {run.reportUrl && (
        <Tooltip title="Report">
          <IconButton size="small" component="a" href={run.reportUrl} target="_blank" rel="noopener noreferrer" aria-label="Report" sx={linkSx}>
            <DescriptionOutlinedIcon sx={{ fontSize: 17 }} />
          </IconButton>
        </Tooltip>
      )}
      {run.logsUrl && (
        <Tooltip title="Logs">
          <IconButton size="small" component="a" href={run.logsUrl} target="_blank" rel="noopener noreferrer" aria-label="Logs" sx={linkSx}>
            <TerminalIcon sx={{ fontSize: 17 }} />
          </IconButton>
        </Tooltip>
      )}
    </Box>
  );
};

const STARTER_TEMPLATE = `#!/usr/bin/env python3
"""
My Virtual Script for VirtualPyTest

Edited in the browser, stored in the database, and run on a host with no
rsync deploy. Keep the @script decorator and _script_args below.
"""

import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_context, get_args, get_device


@script("my_script", "Describe what this script does", default_device="device1")
def main():
    args = get_args()
    context = get_context()
    device = get_device()

    print(f"Running on device: {device.device_name} ({device.device_model})")
    print(f"Param node = {args.node}")

    context.overall_success = True
    return True


main._script_args = [
    '--userinterface:str:stb_tv',
    '--variant:str:',
    '--node:str:home',
]
main._script_description = "Describe what this script does"
main._arg_descriptions = {
    'userinterface': 'UI interface name',
    'variant': 'Optional variant',
    'node': 'Target node',
}
main._target_rules = {
    "target_type": "device",
    "host_os": "all",
    "device_model": "all",
}

if __name__ == "__main__":
    main()
`;

const DOC_TEMPLATE = (name: string) =>
  `# ${name || 'My Script'}\n\nDescribe what this script does, its parameters, and expected results.\n`;

const VirtualScripts: React.FC = () => {
  const theme = useTheme();
  const P = useAgentChatPalette();
  // Editor chrome on the palette (the built-in light/dark themes paint grey gutters / a blue-grey page);
  // syntax colours still come from the built-in theme.
  const editorChrome = useMemo(
    () =>
      Prec.highest(
        EditorView.theme(
          {
            '&': { backgroundColor: P.surface, color: P.textPrimary },
            '.cm-gutters': { backgroundColor: P.surface, color: P.textMuted, borderRight: `1px solid ${P.borderColor}` },
            '.cm-activeLine': { backgroundColor: `${P.accent}14` },
            '.cm-activeLineGutter': { backgroundColor: `${P.accent}26` },
            '&.cm-focused .cm-selectionBackground, .cm-selectionBackground': { backgroundColor: `${P.accent}40` },
            '.cm-cursor': { borderLeftColor: P.accentText },
          },
          { dark: theme.palette.mode === 'dark' },
        ),
      ),
    [P, theme.palette.mode],
  );
  const { showInfo, showError, showSuccess } = useToast();
  const {
    scripts,
    folders,
    listScripts,
    getScript,
    validateSource,
    analyzeSource,
    saveScript,
    deleteScript,
    getVersions,
    restoreVersion,
    promoteScript,
  } = useVirtualScripts();
  const { executeScript } = useScript();

  // Device selection + control + stream — same stack as QuickTestBuilder.
  const { availableHosts } = useHostData();
  const {
    selectedHost,
    selectedDeviceId,
    isControlActive,
    isRemotePanelOpen,
    showRemotePanel,
    showAVPanel,
    handleDeviceSelect,
    handleControlStateChange,
    handleToggleRemotePanel,
    handleDisconnectComplete,
    isDeviceLocked: hostManagerIsDeviceLocked,
  } = useHostControl();

  // The loaded script's _target_rules (target_type/host_os/device_model) — null
  // (fully permissive) for a brand-new, unsaved script. Same rules RunTests uses
  // to filter the target picker (frontend/src/utils/targetCompatibility.ts), so a
  // mobile-only virtual script only offers mobile devices here too.
  const [targetRules, setTargetRules] = useState<TargetRules | null>(null);
  const targetFilteredHosts = useMemo(() => {
    if (!targetRules) return availableHosts;
    return availableHosts
      .map((host: any) => {
        if (!isHostCompatibleWithRules(host, targetRules)) return null;
        if (targetRules.target_type === 'host') {
          const hostDevices = (host.devices || []).filter(
            (d: any) => d.device_id === 'host' || (d.device_model || '').trim().toLowerCase() === 'host_vnc',
          );
          return hostDevices.length ? { ...host, devices: hostDevices } : null;
        }
        const devices = (host.devices || []).filter((d: any) => isDeviceCompatibleWithRules(host, d, targetRules));
        return devices.length ? { ...host, devices } : null;
      })
      .filter((h: any): h is NonNullable<typeof h> => h !== null);
  }, [availableHosts, targetRules]);

  // A script switch can leave a previously-picked device incompatible with the
  // new script's rules (it's no longer even listed) — clear it rather than run
  // against a target the picker itself would never have offered.
  useEffect(() => {
    if (!selectedHost || !selectedDeviceId) return;
    const stillOffered = targetFilteredHosts.some(
      (h: any) => h.host_name === selectedHost.host_name && (h.devices || []).some((d: any) => d.device_id === selectedDeviceId),
    );
    if (!stillOffered) handleDeviceSelect(null, null);
    // Only re-check when the rules (i.e. the loaded script) change, not on every
    // host/device poll — re-running per targetFilteredHosts tick would fight a
    // user who is actively selecting a target on an unrelated host refresh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetRules]);
  const isDeviceLocked = useCallback(
    (deviceKey: string) => {
      const [hostName, deviceId] = deviceKey.includes(':') ? deviceKey.split(':') : [deviceKey, 'device1'];
      const host = availableHosts.find((h: any) => h.host_name === hostName);
      return hostManagerIsDeviceLocked(host || null, deviceId);
    },
    [availableHosts, hostManagerIsDeviceLocked],
  );
  const { isControlLoading, handleDeviceControl } = useDeviceControlWithForceUnlock({
    host: selectedHost,
    device_id: selectedDeviceId,
    sessionId: 'virtual-scripts-session',
    autoCleanup: true,
    onControlStateChange: handleControlStateChange,
  });

  // Editor state
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [folder, setFolder] = useState('');
  const [search, setSearch] = useState('');
  // Folders start expanded; clicking a folder header collapses/expands it.
  const [collapsedFolders, setCollapsedFolders] = useState<Set<string>>(new Set());
  const toggleFolder = useCallback((folderName: string) => {
    setCollapsedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(folderName)) next.delete(folderName);
      else next.add(folderName);
      return next;
    });
  }, []);
  const [doc, setDoc] = useState('');
  const [source, setSource] = useState('');
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  // Result of the last Run in this session, shown under the editor (cleared on script switch).
  const [lastRun, setLastRun] = useState<LastRun | null>(null);
  const [moreAnchor, setMoreAnchor] = useState<null | HTMLElement>(null);
  const [tab, setTab] = useState(0);
  const [validation, setValidation] = useState<VirtualScriptValidation | null>(null);
  const [params, setParams] = useState<VirtualScriptParam[]>([]);
  const [paramValues, setParamValues] = useState<Record<string, string>>({});

  // Interface + variant (header selectors, mapped to --userinterface/--variant)
  const [userinterfaceName, setUserinterfaceName] = useState('');
  const [variant, setVariant] = useState('');

  // Dialogs / menus
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [historyAnchor, setHistoryAnchor] = useState<null | HTMLElement>(null);
  const [versions, setVersions] = useState<VirtualScriptVersion[]>([]);
  const [promoteAnchor, setPromoteAnchor] = useState<null | HTMLElement>(null);
  const [promoteConfirm, setPromoteConfirm] = useState<null | 'test' | 'prod'>(null);
  const [promoting, setPromoting] = useState(false);
  // Which row the History menu is showing versions for: the dev row (edit history,
  // via the History icon) or the prod row (rollback chain, via the prod chip).
  const [historyTargetId, setHistoryTargetId] = useState<string | null>(null);

  // Lifecycle metadata for the selected script (from the grouped list): which env
  // rows exist and the current prod version. Keyed by the dev row id === selectedId.
  const selectedMeta = useMemo(
    () => scripts.find((s) => s.id === selectedId) || null,
    [scripts, selectedId],
  );
  const envExists = useCallback(
    (env: 'dev' | 'test' | 'prod') => !!selectedMeta?.environments?.[env],
    [selectedMeta],
  );

  // Group the "Scripts" rail by folder — same shared folder taxonomy testcases
  // and disk scripts already use. '(Root)' (unassigned) always sorts first.
  const allGroupedScripts = useMemo(() => {
    const groups = new Map<string, typeof scripts>();
    scripts.forEach((s) => {
      const key = s.folder || '(Root)';
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(s);
    });
    return Array.from(groups.entries()).sort(([a], [b]) => {
      if (a === '(Root)') return -1;
      if (b === '(Root)') return 1;
      return a.localeCompare(b);
    });
  }, [scripts]);

  // Folder filter for the rail — "All" shows every group; a specific folder
  // shows only that one. Options are folders that actually contain a script.
  const groupedScripts = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return allGroupedScripts;
    return allGroupedScripts
      .map(([folderName, items]) => [
        folderName,
        folderName.toLowerCase().includes(q) ? items : items.filter((s) => s.name.toLowerCase().includes(q)),
      ] as [string, typeof items])
      .filter(([, items]) => items.length > 0);
  }, [allGroupedScripts, search]);

  const validateTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const autoSelectedRef = useRef(false);

  useEffect(() => {
    listScripts();
  }, [listScripts]);

  const selectedDeviceModel = useMemo(
    () => selectedHost?.devices?.find((d: any) => d.device_id === selectedDeviceId)?.device_model,
    [selectedHost, selectedDeviceId],
  );
  const hasParam = useCallback((n: string) => params.some((p) => p.name === n), [params]);
  const stripParams = useMemo(() => params.filter((p) => !HEADER_PARAMS.has(p.name)), [params]);

  const seedParamDefaults = useCallback((nextParams: VirtualScriptParam[]) => {
    setParamValues((prev) => {
      const next: Record<string, string> = {};
      nextParams.forEach((p) => {
        next[p.name] = prev[p.name] ?? (p.default ?? '');
      });
      return next;
    });
    // Seed interface/variant from the script's declared defaults.
    const ui = nextParams.find((p) => p.name === 'userinterface');
    if (ui) setUserinterfaceName((prev) => prev || ui.default || '');
    const v = nextParams.find((p) => p.name === 'variant');
    if (v) setVariant((prev) => prev || v.default || '');
  }, []);

  const runValidationAndAnalysis = useCallback(
    async (src: string, scriptName: string) => {
      try {
        const [vr, p] = await Promise.all([validateSource(src), analyzeSource(src, scriptName)]);
        setValidation(vr || null);
        setParams(p);
        seedParamDefaults(p);
      } catch (err) {
        console.error('[VirtualScripts] validate/analyze failed', err);
      }
    },
    [validateSource, analyzeSource, seedParamDefaults],
  );

  useEffect(() => {
    if (!source) {
      setValidation(null);
      setParams([]);
      return;
    }
    if (validateTimer.current) clearTimeout(validateTimer.current);
    validateTimer.current = setTimeout(() => {
      runValidationAndAnalysis(source, name || 'virtual_script');
    }, 500);
    return () => {
      if (validateTimer.current) clearTimeout(validateTimer.current);
    };
  }, [source, name, runValidationAndAnalysis]);

  const handleNew = useCallback(() => {
    // A new script must not inherit anything from the previously loaded one —
    // that includes the header selectors, which seedParamDefaults only fills in
    // when they are empty (so a stale interface/variant would stick forever).
    autoSelectedRef.current = true; // don't let the auto-select effect overwrite New
    setSelectedId(null);
    setName('');
    setDescription('');
    setFolder('(Root)');
    setTargetRules(null);
    setDoc(DOC_TEMPLATE(''));
    setSource(STARTER_TEMPLATE);
    setDirty(true);
    setValidation(null);
    setParams([]);
    setParamValues({});
    setUserinterfaceName('');
    setVariant('');
    setVersions([]);
    setTab(0);
    setLastRun(null);
  }, []);

  const handleSelect = useCallback(
    async (id: string) => {
      try {
        const res = await getScript(id);
        if (!res?.script) return;
        if (id !== selectedId) setLastRun(null);
        setSelectedId(id);
        setName(res.script.name);
        setDescription(res.script.description || '');
        setFolder(scripts.find((s) => s.id === id)?.folder || '(Root)');
        setTargetRules(res.script.target_rules || null);
        setDoc(res.script.doc || '');
        setSource(res.script.source || '');
        setParams(res.parameters || []);
        // Reset header selectors then seed from the loaded script's defaults.
        setUserinterfaceName('');
        setVariant('');
        seedParamDefaults(res.parameters || []);
        setDirty(false);
        setValidation({ valid: true });
      } catch {
        showError('Failed to load script');
      }
    },
    [getScript, seedParamDefaults, showError, scripts, selectedId],
  );

  // Open the first script once the list arrives, so the page never starts on an
  // empty editor. Ref-guarded: runs only on the initial load, so New / Delete
  // are not undone by a later listScripts() refresh.
  useEffect(() => {
    if (autoSelectedRef.current || scripts.length === 0) return;
    autoSelectedRef.current = true;

    // Deep link: /builder/virtual-scripts?script=<id> selects that script instead of the
    // first one. Used by the VS rows in the Test Cases list, which open this page in a new
    // tab — without this the tab would open on an unrelated script, which is worse than
    // not linking at all. An unknown or stale id falls back to the default.
    const requested = new URLSearchParams(window.location.search).get('script');
    const target = requested && scripts.some((s) => s.id === requested) ? requested : scripts[0].id;
    handleSelect(target);
  }, [scripts, handleSelect]);

  const handleSave = useCallback(async () => {
    if (!name.trim()) {
      showError('Give the script a name first');
      return;
    }
    setSaving(true);
    try {
      const res = await saveScript({
        id: selectedId || undefined,
        name: name.trim(),
        source,
        description: description || undefined,
        doc,
        folder,
      });
      if (!res?.success) {
        if (res?.validation?.error) {
          setValidation(res.validation);
          showError(`Syntax error on line ${res.validation.error.line}: ${res.validation.error.msg}`);
        } else {
          showError(res?.error || 'Save failed');
        }
        return;
      }
      setSelectedId(res.id || selectedId);
      setDirty(false);
      // The source may have changed the script's target_type/device_model —
      // extract_virtual_script_metadata re-derives target_rules on every save.
      setTargetRules(res.script?.target_rules || null);
      if (res.parameters) {
        setParams(res.parameters);
        seedParamDefaults(res.parameters);
      }
      showSuccess(`Saved "${name.trim()}"`);
      listScripts();
    } catch (err) {
      // Network / auth failure: say so instead of leaving a silent "Unsaved" (BUG-0392).
      showError(`Save failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSaving(false);
    }
  }, [name, source, description, folder, doc, selectedId, saveScript, seedParamDefaults, showError, showSuccess, listScripts]);

  const confirmDelete = useCallback(async () => {
    if (!selectedId) return;
    const res = await deleteScript(selectedId);
    setDeleteOpen(false);
    if (res?.success) {
      showInfo(`Deleted "${name}"`);
      setSelectedId(null);
      setName('');
      setDescription('');
      setFolder('(Root)');
      setDoc('');
      setSource('');
      setParams([]);
      setParamValues({});
      setUserinterfaceName('');
      setVariant('');
      listScripts();
    } else {
      showError('Delete failed');
    }
  }, [selectedId, name, deleteScript, showInfo, showError, listScripts]);

  const buildParameterString = useCallback(() => {
    const parts: string[] = [];
    if (hasParam('userinterface') && userinterfaceName) parts.push(`--userinterface ${userinterfaceName}`);
    if (hasParam('variant') && variant) parts.push(`--variant ${variant}`);
    stripParams.forEach((p) => {
      if (p.name === 'host' || p.name === 'device') return; // framework params, added below
      const val = paramValues[p.name];
      if (val !== undefined && val !== '') parts.push(`--${p.name} ${val}`);
    });
    // Always append --host/--device at the end (same as RunTests/MCP). Without
    // --device the script falls back to the decorator's default_device and runs
    // host-only on hosts that lack that device (e.g. goto's default device1 on
    // vpt-pi3) -> 'NoneType' has no attribute device_name.
    if (selectedHost?.host_name) parts.push(`--host ${selectedHost.host_name}`);
    if (selectedDeviceId) parts.push(`--device ${selectedDeviceId}`);
    return parts.join(' ');
  }, [hasParam, userinterfaceName, variant, stripParams, paramValues, selectedHost, selectedDeviceId]);

  const handleRun = useCallback(async () => {
    if (!selectedId || dirty) {
      showError('Save the script before running');
      return;
    }
    if (!selectedHost || !selectedDeviceId) {
      showError('Select a host and device first');
      return;
    }
    // A device-targeted script (goto et al.) on a host-only target (device_id
    // 'host' / host_vnc) sets up host-only context and crashes with no device.
    // Block it with a clear message instead of letting it run and fail.
    if (selectedDeviceId === 'host' || selectedDeviceModel === 'host_vnc') {
      showError('This script needs a real device — pick an STB/mobile target, not the host.');
      return;
    }
    if (validation && !validation.valid) {
      showError('Fix syntax errors before running');
      return;
    }
    setRunning(true);
    showInfo(`Running "${name}" on ${selectedHost.host_name}:${selectedDeviceId}…`);
    const startedAt = Date.now();
    const record = (status: LastRun['status'], result?: any, error?: string) =>
      setLastRun({
        status,
        host: selectedHost.host_name,
        deviceId: selectedDeviceId,
        startedAt,
        durationMs: Date.now() - startedAt,
        reportUrl: result?.report_url,
        logsUrl: result?.logs_url,
        error,
      });
    try {
      const result = await executeScript(
        name,
        selectedHost.host_name,
        selectedDeviceId,
        buildParameterString(),
        undefined,
        undefined,
        undefined,
        undefined,
        selectedId, // virtualScriptId
      );
      const r = result as any;
      const ok = r?.exit_code === 0 || r?.script_success;
      if (result?.report_url) {
        // A report means the script ran to the end; it still failed if it said so.
        record(r?.script_success === false || (r?.exit_code != null && r.exit_code !== 0) ? 'failed' : 'passed', result);
        showSuccess(`"${name}" finished — report ready`);
        window.open(result.report_url, '_blank');
      } else if (ok) {
        record('passed', result);
        showSuccess(`"${name}" finished`);
      } else {
        record('failed', result);
        showError(`"${name}" failed — check logs`);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'unknown error';
      record('error', undefined, msg);
      showError(`Run failed: ${msg}`);
    } finally {
      setRunning(false);
    }
  }, [selectedId, dirty, selectedHost, selectedDeviceId, validation, name, executeScript, buildParameterString, showInfo, showSuccess, showError]);

  const openHistory = useCallback(
    async (e: React.MouseEvent<HTMLElement>, targetId?: string) => {
      const id = targetId || selectedId;
      if (!id) return;
      setHistoryTargetId(id);
      setHistoryAnchor(e.currentTarget);
      setVersions(await getVersions(id));
    },
    [selectedId, getVersions],
  );

  const handleRestore = useCallback(
    async (versionNumber: number | null) => {
      const id = historyTargetId || selectedId;
      if (!id || versionNumber == null) return;
      const res = await restoreVersion(id, versionNumber);
      if (res?.success && res.script) {
        // Only reflect into the editor when we restored the row being edited (dev).
        // A prod rollback must not overwrite the dev source in the editor.
        if (id === selectedId) {
          setSource(res.script.source);
          setDescription(res.script.description || '');
          setDoc(res.script.doc || '');
          setDirty(false);
        }
        showSuccess(
          id === selectedId
            ? `Restored version ${versionNumber}`
            : `Rolled back prod to version ${versionNumber}`,
        );
        listScripts();
      }
      setHistoryAnchor(null);
    },
    [selectedId, historyTargetId, restoreVersion, showSuccess, listScripts],
  );

  const handlePromote = useCallback(async () => {
    if (!selectedId || !promoteConfirm) return;
    const targetEnv = promoteConfirm;
    setPromoting(true);
    try {
      const res = await promoteScript(selectedId, targetEnv);
      if (res?.success) {
        const suffix = targetEnv === 'prod' && res.prod_version ? ` (v${res.prod_version})` : '';
        showSuccess(`Promoted to ${targetEnv}${suffix}`);
        listScripts(); // refresh env chips + prod_version
      } else {
        showError(res?.error || 'Promote failed');
      }
    } finally {
      setPromoting(false);
      setPromoteConfirm(null);
    }
  }, [selectedId, promoteConfirm, promoteScript, showSuccess, showError, listScripts]);

  const syntaxDot = useMemo(() => {
    if (!source) return null;
    const title = !validation
      ? 'Checking…'
      : validation.valid
        ? validation.warnings?.length
          ? validation.warnings.join('  •  ')
          : 'Syntax OK'
        : `Line ${validation.error?.line}: ${validation.error?.msg}`;
    const label = !validation ? 'Checking…' : validation.valid ? (validation.warnings?.length ? 'Warnings' : 'Syntax OK') : `Error line ${validation.error?.line}`;
    const tone = !validation ? P.textMuted : !validation.valid ? P.error : validation.warnings?.length ? P.warning : P.success;
    return (
      <Tooltip title={title}>
        <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5, px: 1, height: 22, borderRadius: 11, fontSize: '0.7rem', fontWeight: 600, whiteSpace: 'nowrap', color: tone, border: `1px solid ${tone}55`, bgcolor: `${tone}14` }}>
          <FiberManualRecordIcon sx={{ fontSize: 8 }} />
          {label}
        </Box>
      </Tooltip>
    );
  }, [source, validation, P]);

  const interfaceDropdownStyles = {
    select: { height: 32, fontSize: '0.75rem', '& .MuiSelect-select': { display: 'flex', alignItems: 'center' } },
  };

  return (
    <BuilderPageLayout>
      {/* Shared header bar — same controls as QuickTestBuilder (device control +
          Take Control + Interface + Variant + RunButton). */}
      <Box
        sx={{
          px: 2,
          py: 0,
          borderBottom: 1,
          borderColor: 'divider',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: P.surface,
          height: 46,
          flexShrink: 0,
        }}
      >
        {/* Title + unsaved marker (the name itself is edited in the editor panel) */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flex: '0 0 auto', minWidth: 0 }}>
          <Typography variant="subtitle1" fontWeight={600} sx={{ whiteSpace: 'nowrap' }}>
            Virtual Scripts
          </Typography>
          {dirty && (
            <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5, fontSize: '0.7rem', fontWeight: 600, color: P.accentText }}>
              <FiberManualRecordIcon sx={{ fontSize: 8 }} /> Unsaved
            </Box>
          )}
        </Box>

        {/* Device control + Interface + Variant */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flex: '0 0 auto', ml: 2, borderLeft: 1, borderColor: 'divider', pl: 2 }}>
          <NavigationEditorDeviceControls
            selectedHost={selectedHost}
            selectedDeviceId={selectedDeviceId}
            isControlActive={isControlActive}
            isControlLoading={isControlLoading}
            isRemotePanelOpen={isRemotePanelOpen}
            availableHosts={targetFilteredHosts}
            isDeviceLocked={isDeviceLocked}
            onDeviceSelect={handleDeviceSelect as any}
            onTakeControl={handleDeviceControl as any}
            onToggleRemotePanel={handleToggleRemotePanel}
            disableTakeControl={hasParam('userinterface') && !userinterfaceName}
            middleContent={
              <>
                <UserinterfaceSelector
                  deviceModel={selectedDeviceModel}
                  value={userinterfaceName}
                  // Interface/variant are runtime run-args, NOT stored script
                  // content — changing them must not mark the script dirty (which
                  // would block Run). Only source/name/description/doc edits do.
                  onChange={setUserinterfaceName}
                  label="Interface"
                  size="small"
                  fullWidth={false}
                  sx={{ minWidth: 180 }}
                  dropdownStyles={interfaceDropdownStyles}
                  disabled={!selectedDeviceId}
                  disableAutoSelect
                />
                {userinterfaceName && hasParam('variant') && (
                  <VariantSelector
                    userinterfaceName={userinterfaceName}
                    value={variant}
                    onChange={setVariant}
                    size="small"
                    fullWidth={false}
                  />
                )}
              </>
            }
          />
        </Box>

        {/* Actions: lifecycle pipeline + Promote, then history / more / Save / Run */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, flex: '0 0 auto', ml: 2 }}>
          {selectedId && (
            <>
              <LifecyclePipeline
                environments={{ dev: envExists('dev'), test: envExists('test'), prod: envExists('prod') }}
                prodVersion={selectedMeta?.prod_version}
                onProdClick={
                  selectedMeta?.environments?.prod
                    ? (e) => openHistory(e as any, selectedMeta.environments!.prod as string)
                    : undefined
                }
              />
              <Tooltip title={dirty ? 'Save before promoting' : 'Promote dev → test → prod'}>
                <span>
                  <Button
                    size="small"
                    variant="outlined"
                    startIcon={<PublishIcon />}
                    endIcon={<ExpandMoreIcon />}
                    onClick={(e) => setPromoteAnchor(e.currentTarget)}
                    disabled={dirty || promoting}
                    sx={{ textTransform: 'none', borderColor: P.accent, color: P.accentText, '&:hover': { borderColor: P.accent, bgcolor: `${P.accent}1a` } }}
                  >
                    Promote
                  </Button>
                </span>
              </Tooltip>
              <Divider orientation="vertical" flexItem sx={{ mx: 0.5, my: 1 }} />
            </>
          )}
          <Tooltip title="Version history">
            <span>
              <IconButton size="small" onClick={openHistory} disabled={!selectedId}>
                <HistoryIcon fontSize="small" />
              </IconButton>
            </span>
          </Tooltip>
          <Tooltip title="More">
            <span>
              <IconButton size="small" onClick={(e) => setMoreAnchor(e.currentTarget)} disabled={!selectedId}>
                <MoreHorizIcon fontSize="small" />
              </IconButton>
            </span>
          </Tooltip>
          <Button
            size="small"
            variant="outlined"
            startIcon={saving ? <CircularProgress size={14} /> : <SaveIcon />}
            onClick={handleSave}
            disabled={saving || !dirty}
            sx={{ textTransform: 'none', ...(dirty && { borderColor: P.accent, color: P.accentText, bgcolor: `${P.accent}14`, '&:hover': { borderColor: P.accent, bgcolor: `${P.accent}22` } }) }}
          >
            Save
          </Button>
          <RunButton
            onExecute={handleRun}
            isExecuting={running}
            isExecutable={!!selectedId && !dirty}
            selectedDeviceId={selectedDeviceId}
            isControlActive={isControlActive}
            userinterfaceName={userinterfaceName}
            sx={{
              px: 2, fontWeight: 600, textTransform: 'none', boxShadow: 'none',
              backgroundColor: P.accent, color: '#1a1a1a',
              '&:hover': { backgroundColor: P.accentHover, boxShadow: 'none' },
              '&:disabled': { backgroundColor: P.hoverBg, color: P.textMuted },
            }}
          />
        </Box>
      </Box>

      {/* Content: scripts rail + editor (internal scroll, no page scroll) */}
      <Box sx={{ flex: 1, minHeight: 0, display: 'flex', gap: 1, p: 1 }}>
        <Paper variant="outlined" sx={{ width: 230, display: 'flex', flexDirection: 'column', borderRadius: 2, borderColor: P.borderColor, bgcolor: P.sidebarBg }}>
          <Box sx={{ px: 1.5, pt: 1.25, pb: 1, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <Typography variant="subtitle2" fontWeight={600}>Scripts</Typography>
            <Tooltip title="New script">
              <IconButton size="small" onClick={handleNew} sx={{ color: P.accentText, border: `1px solid ${P.borderColor}`, borderRadius: 1.5, p: 0.5 }}>
                <AddIcon sx={{ fontSize: 18 }} />
              </IconButton>
            </Tooltip>
          </Box>
          <Box sx={{ px: 1.5, pb: 1 }}>
            <InputBase
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search scripts or folders"
              startAdornment={<SearchIcon sx={{ fontSize: 16, color: P.textMuted, mr: 0.75 }} />}
              sx={{
                width: '100%', height: 30, px: 1, fontSize: '0.8rem',
                bgcolor: P.inputBg, border: `1px solid ${P.borderColor}`, borderRadius: 1.5,
                '&.Mui-focused': { borderColor: P.accent },
              }}
            />
          </Box>
          <Box sx={{ overflow: 'auto', flex: 1, px: 1, pb: 1 }}>
            {groupedScripts.map(([folderName, items]) => {
              const collapsed = collapsedFolders.has(folderName) && !search.trim();
              return (
                <Box key={folderName}>
                  <Box
                    onClick={() => toggleFolder(folderName)}
                    sx={{ display: 'flex', alignItems: 'center', gap: 0.25, px: 0.5, pt: 1, pb: 0.5, cursor: 'pointer', userSelect: 'none', color: P.textMuted, '&:hover': { color: P.textSecondary } }}
                  >
                    <ExpandMoreIcon sx={{ fontSize: 16, transition: 'transform 0.15s', transform: collapsed ? 'rotate(-90deg)' : 'none' }} />
                    <Typography noWrap sx={{ fontSize: '0.7rem', fontWeight: 600 }}>{folderName} · {items.length}</Typography>
                  </Box>
                  <Collapse in={!collapsed} timeout="auto" unmountOnExit>
                    {items.map((s) => {
                      const selected = s.id === selectedId;
                      const inProd = !!s.environments?.prod;
                      return (
                        <Box
                          key={s.id}
                          title={s.name}
                          onClick={() => handleSelect(s.id)}
                          sx={{
                            display: 'flex', alignItems: 'center', gap: 1, px: 1, py: 0.6, mb: 0.25, borderRadius: 1.5, cursor: 'pointer',
                            bgcolor: selected ? `${P.accent}26` : 'transparent',
                            '&:hover': { bgcolor: selected ? `${P.accent}26` : P.hoverBg },
                          }}
                        >
                          <Typography noWrap sx={{ flex: 1, minWidth: 0, fontSize: '0.8rem', fontWeight: selected ? 600 : 400, color: selected ? P.accentText : P.textPrimary }}>
                            {s.name}
                          </Typography>
                          <Tooltip title={inProd ? `In prod${s.prod_version ? ` (v${s.prod_version})` : ''}` : s.environments?.test ? 'In test' : 'Dev only'}>
                            <Box sx={{ width: 6, height: 6, borderRadius: '50%', flexShrink: 0, bgcolor: inProd ? P.accent : s.environments?.test ? P.textSecondary : P.borderColor }} />
                          </Tooltip>
                        </Box>
                      );
                    })}
                  </Collapse>
                </Box>
              );
            })}
            {scripts.length === 0 && (
              <Typography variant="caption" sx={{ p: 2, display: 'block', color: 'text.secondary' }}>
                No virtual scripts yet. Click + to create one.
              </Typography>
            )}
            {scripts.length > 0 && groupedScripts.length === 0 && (
              <Typography variant="caption" sx={{ p: 2, display: 'block', color: 'text.secondary' }}>
                No script matches.
              </Typography>
            )}
          </Box>
          <Box sx={{ display: 'flex', gap: 1.5, px: 1.5, py: 0.75, borderTop: `1px solid ${P.borderColor}`, fontSize: '0.68rem', color: P.textMuted }}>
            {([['prod', P.accent], ['test', P.textSecondary], ['dev', P.borderColor]] as const).map(([label, c]) => (
              <Box key={label} sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}>
                <Box sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: c }} />{label}
              </Box>
            ))}
          </Box>
        </Paper>

        <Paper variant="outlined" sx={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden', borderRadius: 2, borderColor: P.borderColor }}>
          {/* Name (title) + folder + syntax status, description, script-specific params */}
          <Box sx={{ px: 2, pt: 1.5, pb: 1.25, display: 'flex', flexDirection: 'column', gap: 0.75 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Tooltip title="Select an existing folder or type a new name to create one — Save to apply.">
                <Autocomplete
                  freeSolo
                  size="small"
                  value={folder}
                  onChange={(_, newValue) => {
                    setFolder(newValue || '(Root)');
                    setDirty(true);
                  }}
                  options={folders.map((f) => f.name)}
                  disableClearable
                  sx={{ width: `${Math.min(200, Math.max(36, (folder || 'Folder').length * 8.5 + 12))}px`, flexShrink: 0 }}
                  renderInput={(params) => (
                    <TextField
                      {...params}
                      variant="standard"
                      placeholder="Folder"
                      InputProps={{ ...params.InputProps, disableUnderline: true, sx: { fontSize: '0.85rem', color: P.textSecondary } }}
                    />
                  )}
                />
              </Tooltip>
              <Typography sx={{ color: P.textMuted }}>/</Typography>
              <InputBase
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                  setDirty(true);
                }}
                placeholder="script_name"
                inputProps={{ 'aria-label': 'Name' }}
                sx={{
                  flex: 1, minWidth: 0, fontSize: '1.15rem', fontWeight: 600, fontFamily: 'monospace',
                  borderRadius: 1, px: 0.5, '&:hover, &.Mui-focused': { bgcolor: P.hoverBg },
                }}
              />
              {syntaxDot}
            </Box>
            <InputBase
              value={description}
              onChange={(e) => {
                setDescription(e.target.value);
                setDirty(true);
              }}
              placeholder="Add a description"
              inputProps={{ 'aria-label': 'Description' }}
              fullWidth
              sx={{ fontSize: '0.82rem', color: P.textSecondary, borderRadius: 1, px: 0.5, mx: -0.5, '&:hover, &.Mui-focused': { bgcolor: P.hoverBg } }}
            />
            {stripParams.length > 0 && (
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', pt: 0.5 }}>
                <Typography sx={{ fontSize: '0.7rem', fontWeight: 600, color: P.textMuted }}>Parameters</Typography>
                <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', alignItems: 'center' }}>
                  {stripParams.map((p) => (
                    <ScriptParameterRow
                      key={p.name}
                      param={p}
                      value={paramValues[p.name] ?? ''}
                      onChange={(val) => setParamValues((prev) => ({ ...prev, [p.name]: val }))}
                      allValues={paramValues}
                      scriptName={name || 'virtual_script'}
                      deviceModel={selectedDeviceModel}
                    />
                  ))}
                </Stack>
              </Box>
            )}
          </Box>

          {/* Script / Doc */}
          <Box sx={{ px: 2, py: 0.75, borderTop: `1px solid ${P.borderColor}`, borderBottom: `1px solid ${P.borderColor}` }}>
            <ToggleButtonGroup
              size="small"
              exclusive
              value={tab}
              onChange={(_, v) => v !== null && setTab(v)}
              sx={{
                bgcolor: P.sidebarBg, p: 0.375, borderRadius: 2, gap: 0.375,
                '& .MuiToggleButton-root': {
                  border: '1px solid transparent !important', borderRadius: '6px !important',
                  textTransform: 'none', fontSize: 12, fontWeight: 500, color: P.textSecondary, py: 0.25, px: 1.5,
                  '&:hover': { bgcolor: P.hoverBg },
                },
                '& .MuiToggleButton-root.Mui-selected': {
                  bgcolor: P.surface, color: P.accentText, fontWeight: 600,
                  borderColor: `${P.borderColor} !important`, '&:hover': { bgcolor: P.surface },
                },
              }}
            >
              <ToggleButton value={0}>Script</ToggleButton>
              <ToggleButton value={1}>Doc</ToggleButton>
            </ToggleButtonGroup>
          </Box>

          <Box sx={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
            {tab === 0 ? (
              <Box sx={{ height: '100%', overflow: 'auto' }}>
                <CodeMirror
                  value={source}
                  height="100%"
                  theme={theme.palette.mode === 'dark' ? 'dark' : 'light'}
                  extensions={[python(), editorChrome]}
                  onChange={(val) => {
                    setSource(val);
                    setDirty(true);
                  }}
                />
              </Box>
            ) : (
              <Box sx={{ height: '100%', display: 'flex', gap: 1, p: 1, overflow: 'hidden' }}>
                <TextField
                  multiline
                  fullWidth
                  placeholder="# Markdown documentation for this script"
                  value={doc}
                  onChange={(e) => {
                    setDoc(e.target.value);
                    setDirty(true);
                  }}
                  sx={{
                    flex: 1,
                    '& .MuiInputBase-root': { height: '100%', alignItems: 'flex-start', fontFamily: 'monospace', fontSize: 13 },
                    '& textarea': { height: '100% !important', overflow: 'auto !important' },
                  }}
                />
                <Box sx={{ flex: 1, overflow: 'auto', p: 1, border: 1, borderColor: 'divider', borderRadius: 1 }}>
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{doc || '_No documentation yet._'}</ReactMarkdown>
                </Box>
              </Box>
            )}
          </Box>

          {lastRun && <LastRunBar run={lastRun} P={P} />}
        </Paper>
      </Box>

      {/* Floating live stream / remote — pinned bottom-left, same as QuickTest. */}
      <DeviceControlPanels
        showRemotePanel={showRemotePanel}
        showAVPanel={showAVPanel}
        selectedHost={selectedHost}
        selectedDeviceId={selectedDeviceId}
        isControlActive={isControlActive}
        userinterfaceName={userinterfaceName}
        isSidebarOpen={false}
        footerHeight={0}
        handleDisconnectComplete={handleDisconnectComplete}
      />

      {/* Delete confirmation (centered) */}
      <StyledDialog open={deleteOpen} onClose={() => setDeleteOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Delete virtual script</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Delete <strong>{name}</strong>? This cannot be undone.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteOpen(false)}>Cancel</Button>
          <Button color="error" variant="contained" onClick={confirmDelete}>
            Delete
          </Button>
        </DialogActions>
      </StyledDialog>

      {/* More: delete */}
      <Menu anchorEl={moreAnchor} open={Boolean(moreAnchor)} onClose={() => setMoreAnchor(null)}>
        <MenuItem
          onClick={() => {
            setMoreAnchor(null);
            setDeleteOpen(true);
          }}
          sx={{ color: P.error, gap: 1 }}
        >
          <DeleteIcon fontSize="small" /> Delete script
        </MenuItem>
      </Menu>

      {/* Version history */}
      <Menu anchorEl={historyAnchor} open={Boolean(historyAnchor)} onClose={() => setHistoryAnchor(null)}>
        {versions.map((v, i) => (
          <MenuItem key={i} disabled={v.is_current} onClick={() => handleRestore(v.version_number)}>
            {v.is_current
              ? `Current — ${v.name}`
              : `v${v.version_number} — ${v.change_description || ''} (${v.snapshot_timestamp?.slice(0, 19).replace('T', ' ')})`}
          </MenuItem>
        ))}
        {versions.length === 0 && <MenuItem disabled>No history</MenuItem>}
      </Menu>

      {/* Promote menu: dev -> test, test -> prod */}
      <Menu anchorEl={promoteAnchor} open={Boolean(promoteAnchor)} onClose={() => setPromoteAnchor(null)}>
        <MenuItem
          disabled={!envExists('dev')}
          onClick={() => {
            setPromoteAnchor(null);
            setPromoteConfirm('test');
          }}
        >
          Promote to test{envExists('test') ? ' (overwrite)' : ''}
        </MenuItem>
        <MenuItem
          disabled={!envExists('test')}
          onClick={() => {
            setPromoteAnchor(null);
            setPromoteConfirm('prod');
          }}
        >
          Promote to prod{envExists('prod') ? ' (new version)' : ''}
        </MenuItem>
      </Menu>

      {/* Promote confirmation */}
      <StyledDialog open={Boolean(promoteConfirm)} onClose={() => setPromoteConfirm(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Promote to {promoteConfirm}</DialogTitle>
        <DialogContent>
          <DialogContentText component="div">
            {promoteConfirm === 'test' ? (
              <>
                Copy the <strong>dev</strong> source of <strong>{name}</strong> into its{' '}
                <strong>test</strong> version.
                {envExists('test') && ' This overwrites the current test version.'}
              </>
            ) : (
              <>
                Copy the <strong>test</strong> source of <strong>{name}</strong> into{' '}
                <strong>prod</strong>.
                {envExists('prod') && selectedMeta?.prod_version
                  ? ` The current prod v${selectedMeta.prod_version} is kept in history for one-click rollback (History ▸ Restore).`
                  : ' This publishes prod v1.'}
              </>
            )}
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPromoteConfirm(null)} disabled={promoting}>
            Cancel
          </Button>
          <Button
            variant="contained"
            color={promoteConfirm === 'prod' ? 'success' : 'warning'}
            onClick={handlePromote}
            disabled={promoting}
            startIcon={promoting ? <CircularProgress size={14} /> : <PublishIcon />}
          >
            Promote
          </Button>
        </DialogActions>
      </StyledDialog>
    </BuilderPageLayout>
  );
};

export default VirtualScripts;
