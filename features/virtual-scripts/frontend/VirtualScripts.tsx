import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import FiberManualRecordIcon from '@mui/icons-material/FiberManualRecord';
import HistoryIcon from '@mui/icons-material/History';
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
  List,
  ListItemButton,
  ListItemText,
  ListSubheader,
  Menu,
  MenuItem,
  Paper,
  Select,
  Stack,
  Tab,
  Tabs,
  TextField,
  Tooltip,
  Typography,
  useTheme,
} from '@mui/material';
import { python } from '@codemirror/lang-python';
import CodeMirror from '@uiw/react-codemirror';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

// Core component: features import core by relative path (docs/technical/FEATURES.md).
import { LifecycleChips } from '../../../frontend/src/components/common/LifecycleChips';

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
  const actualMode = theme.palette.mode;
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
  const [folderFilter, setFolderFilter] = useState('All');
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
  const folderFilterOptions = useMemo(() => allGroupedScripts.map(([name]) => name), [allGroupedScripts]);
  const groupedScripts = useMemo(
    () => (folderFilter === 'All' ? allGroupedScripts : allGroupedScripts.filter(([name]) => name === folderFilter)),
    [allGroupedScripts, folderFilter],
  );

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
  }, []);

  const handleSelect = useCallback(
    async (id: string) => {
      try {
        const res = await getScript(id);
        if (!res?.script) return;
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
    [getScript, seedParamDefaults, showError, scripts],
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
      if (result?.report_url) {
        showSuccess(`"${name}" finished — report ready`);
        window.open(result.report_url, '_blank');
      } else if ((result as any)?.exit_code === 0 || (result as any)?.script_success) {
        showSuccess(`"${name}" finished`);
      } else {
        showError(`"${name}" failed — check logs`);
      }
    } catch (err) {
      showError(`Run failed: ${err instanceof Error ? err.message : 'unknown error'}`);
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
    const color = !validation ? 'text.disabled' : validation.valid ? 'success.main' : 'error.main';
    const title = !validation
      ? 'Checking…'
      : validation.valid
        ? validation.warnings?.length
          ? validation.warnings.join('  •  ')
          : 'Syntax OK'
        : `Line ${validation.error?.line}: ${validation.error?.msg}`;
    return (
      <Tooltip title={title}>
        <FiberManualRecordIcon sx={{ color, fontSize: 16 }} />
      </Tooltip>
    );
  }, [source, validation]);

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
          background: actualMode === 'dark' ? '#111827' : '#ffffff',
          height: 46,
          flexShrink: 0,
        }}
      >
        {/* Title + name */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flex: '0 0 auto', minWidth: 0 }}>
          <Typography variant="h6" fontWeight="bold" sx={{ whiteSpace: 'nowrap' }}>
            Virtual Script
          </Typography>
          {name && (
            <>
              <Typography variant="h6" sx={{ color: 'text.disabled' }}>•</Typography>
              {dirty && <Typography variant="h6" sx={{ color: '#f97316', fontWeight: 700 }}>*</Typography>}
              <Typography
                variant="h6"
                sx={{
                  fontWeight: dirty ? 700 : 600,
                  color: dirty ? '#f97316' : 'primary.main',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  maxWidth: 180,
                }}
              >
                {name}
              </Typography>
            </>
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

        {/* Actions */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, flex: '0 0 auto', ml: 2 }}>
          {/* Lifecycle: which env rows exist + current prod version. Editing always
              writes dev; Promote copies dev->test then test->prod. */}
          {selectedId && (
            <>
              {/* Same renderer the Test Cases list uses (core component) — two copies of
                  these chips would drift. The prod chip stays a rollback affordance here. */}
              <Box sx={{ mr: 0.5 }}>
                <LifecycleChips
                  environments={{
                    dev: envExists('dev'),
                    test: envExists('test'),
                    prod: envExists('prod'),
                  }}
                  prodVersion={selectedMeta?.prod_version}
                  onProdClick={
                    selectedMeta?.environments?.prod
                      ? (e) => openHistory(e as any, selectedMeta.environments!.prod as string)
                      : undefined
                  }
                />
              </Box>
              <Tooltip title={dirty ? 'Save before promoting' : 'Promote dev → test → prod'}>
                <span>
                  <Button
                    size="small"
                    variant="outlined"
                    startIcon={<PublishIcon />}
                    onClick={(e) => setPromoteAnchor(e.currentTarget)}
                    disabled={dirty || promoting}
                  >
                    Promote
                  </Button>
                </span>
              </Tooltip>
            </>
          )}
          <Tooltip title="Version history">
            <span>
              <IconButton size="small" onClick={openHistory} disabled={!selectedId}>
                <HistoryIcon fontSize="small" />
              </IconButton>
            </span>
          </Tooltip>
          <Tooltip title="Delete">
            <span>
              <IconButton size="small" onClick={() => setDeleteOpen(true)} disabled={!selectedId}>
                <DeleteIcon fontSize="small" />
              </IconButton>
            </span>
          </Tooltip>
          <Button size="small" variant="outlined" startIcon={<AddIcon />} onClick={handleNew}>
            New
          </Button>
          <Button
            size="small"
            variant="outlined"
            startIcon={saving ? <CircularProgress size={14} /> : <SaveIcon />}
            onClick={handleSave}
            disabled={saving || !dirty}
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
          />
        </Box>
      </Box>

      {/* Content: scripts rail + editor (internal scroll, no page scroll) */}
      <Box sx={{ flex: 1, minHeight: 0, display: 'flex', gap: 1, p: 1 }}>
        <Paper sx={{ width: 230, display: 'flex', flexDirection: 'column' }}>
          <Box sx={{ p: 1, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1 }}>
            <Typography variant="subtitle2">Scripts</Typography>
            <Select
              size="small"
              variant="standard"
              value={folderFilter}
              onChange={(e) => setFolderFilter(e.target.value)}
              disableUnderline
              sx={{ fontSize: 12 }}
            >
              <MenuItem value="All">All folders</MenuItem>
              {folderFilterOptions.map((f) => (
                <MenuItem key={f} value={f}>{f}</MenuItem>
              ))}
            </Select>
          </Box>
          <Divider />
          <List dense sx={{ overflow: 'auto', flex: 1 }} subheader={<li />}>
            {groupedScripts.map(([folderName, items]) => {
              const collapsed = collapsedFolders.has(folderName);
              return (
                <li key={folderName}>
                  <ul style={{ padding: 0 }}>
                    <ListSubheader
                      disableSticky
                      onClick={() => toggleFolder(folderName)}
                      sx={{
                        lineHeight: '28px',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 0.5,
                        userSelect: 'none',
                        color: 'primary.main',
                        fontWeight: 700,
                      }}
                    >
                      <ExpandMoreIcon
                        fontSize="small"
                        sx={{
                          transition: 'transform 0.15s',
                          transform: collapsed ? 'rotate(-90deg)' : 'rotate(0deg)',
                          color: 'primary.main',
                        }}
                      />
                      {folderName}
                    </ListSubheader>
                    <Collapse in={!collapsed} timeout="auto" unmountOnExit>
                      {items.map((s) => (
                        <Tooltip key={s.id} title={s.name} placement="right" enterDelay={400}>
                          <ListItemButton
                            selected={s.id === selectedId}
                            onClick={() => handleSelect(s.id)}
                            sx={{ '&:hover': { backgroundColor: 'transparent' } }}
                          >
                            <ListItemText primary={s.name} primaryTypographyProps={{ noWrap: true }} />
                          </ListItemButton>
                        </Tooltip>
                      ))}
                    </Collapse>
                  </ul>
                </li>
              );
            })}
            {scripts.length === 0 && (
              <Typography variant="caption" sx={{ p: 2, display: 'block', color: 'text.secondary' }}>
                No virtual scripts yet. Click New to create one.
              </Typography>
            )}
          </List>
        </Paper>

        <Paper sx={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {/* Name + description + script-specific params (node, verify, …) */}
          <Box sx={{ p: 1, display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
            <TextField
              size="small"
              label="Name"
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setDirty(true);
              }}
              sx={{ width: 180 }}
            />
            <TextField
              size="small"
              label="Description"
              value={description}
              onChange={(e) => {
                setDescription(e.target.value);
                setDirty(true);
              }}
              sx={{ minWidth: 200, flex: 1 }}
            />
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
                sx={{ width: 160 }}
                renderInput={(params) => <TextField {...params} label="Folder" />}
              />
            </Tooltip>
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
            {syntaxDot}
          </Box>
          <Divider />

          <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ minHeight: 36 }}>
            <Tab label="Script" sx={{ minHeight: 36, py: 0 }} />
            <Tab label="Doc" sx={{ minHeight: 36, py: 0 }} />
          </Tabs>
          <Divider />

          <Box sx={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
            {tab === 0 ? (
              <Box sx={{ height: '100%', overflow: 'auto' }}>
                <CodeMirror
                  value={source}
                  height="100%"
                  theme={theme.palette.mode === 'dark' ? 'dark' : 'light'}
                  extensions={[python()]}
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
