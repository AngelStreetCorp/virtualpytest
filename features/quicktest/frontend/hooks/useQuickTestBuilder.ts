/**
 * useQuickTestBuilder
 *
 * Composition hook for the QuickTest (linear "shopping list") builder. It reuses
 * the SAME primitives as the visual TestCaseBuilder — device/host control,
 * navigation-tree loading, available actions/verifications, testcase execution,
 * and save/load — but drives a flat ordered step list instead of a ReactFlow
 * graph. The step list compiles to the standard testcase graph_json
 * (compileStepsToGraph) so execution + reporting are identical.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useDeviceData } from '../../../../frontend/src/contexts/device/DeviceDataContext';
import { useNavigationConfig } from '../../../../frontend/src/contexts/navigation/NavigationConfigContext';
import { useWorkspaceContext } from '../../../../frontend/src/contexts/workspace/WorkspaceContext';
import { api } from '../../../../frontend/src/utils/apiClient';
import { buildServerUrl, buildServerUrlWithParams } from '../../../../frontend/src/utils/buildUrlUtils';
import { filterCompatibleInterfaces } from '../../../../frontend/src/utils/userinterface/deviceCompatibilityUtils';
import {
  compileStepsToGraph,
  parseGraphToSteps,
} from '../utils/compileStepsToGraph';
import {
  LoopBreak,
  QuickStepType,
  QuickTestLoop,
  QuickTestStep,
  QuickTestUnit,
  createEmptyStep,
  createLoopUnit,
  isQuickLoop,
} from '../types/QuickTest_Types';
import { ScriptInput } from '../../../../frontend/src/types/testcase/TestCase_Types';
import {
  collectPlaceholders,
  placeholderName,
  stampInputValues,
} from '../../../../frontend/src/utils/testcase/scriptInputUtils';
import { useDeviceControlWithForceUnlock } from '../../../../frontend/src/hooks/useDeviceControlWithForceUnlock';
import { useHostControl, useHostData } from '../../../../frontend/src/hooks/useHostManager';
import { useExecutionState } from '../../../../frontend/src/hooks/testcase/useExecutionState';
import { useTestCaseSave } from '../../../../frontend/src/hooks/testcase/useTestCaseSave';
import { useUserInterface } from '../../../../frontend/src/hooks/pages/useUserInterface';

const POLL_INTERVAL_MS = 1000;
const MAX_POLLS = 600; // ~10 min safety ceiling

let idCounter = 0;
const newStepId = () => `s${Date.now().toString(36)}${(idCounter++).toString(36)}`;

/**
 * Marker stamped into testcase_definitions.created_by for QuickTest-authored
 * cases. It's how each builder filters its own list out of the shared table:
 * QuickTest shows only these; TestCaseBuilder excludes them.
 */
export const QUICKTEST_CREATED_BY = 'quicktest';

export interface QuickTestSnackbar {
  open: boolean;
  message: string;
  severity: 'success' | 'error' | 'info';
}

export const useQuickTestBuilder = () => {
  // ==================== HOST & DEVICE ====================
  // Workspace scope: hide devices the active workspace doesn't allow, the same
  // way RunTests' target picker does (useTargetSelection) — filter each host's
  // device list, then drop hosts left with none.
  const { availableHosts: rawAvailableHosts } = useHostData();
  const { isDeviceAllowed } = useWorkspaceContext();
  const availableHosts = useMemo(
    () =>
      rawAvailableHosts
        .map((h: any) => ({
          ...h,
          devices: (h.devices || []).filter((d: any) => isDeviceAllowed(h.host_name, d.device_id)),
        }))
        .filter((h: any) => (h.devices?.length ?? 0) > 0),
    [rawAvailableHosts, isDeviceAllowed],
  );
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

  const isDeviceLocked = useCallback(
    (deviceKey: string) => {
      const [hostName, deviceId] = deviceKey.includes(':')
        ? deviceKey.split(':')
        : [deviceKey, 'device1'];
      const host = rawAvailableHosts.find((h: any) => h.host_name === hostName);
      return hostManagerIsDeviceLocked(host || null, deviceId);
    },
    [rawAvailableHosts, hostManagerIsDeviceLocked],
  );

  // ==================== TREE / SNACKBAR (early, for device-control hook) ====================
  const [currentTreeId, setCurrentTreeId] = useState<string | null>(null);
  const [isLoadingTree, setIsLoadingTree] = useState(false);
  const [snackbar, setSnackbar] = useState<QuickTestSnackbar>({
    open: false,
    message: '',
    severity: 'info',
  });
  const showSnackbar = useCallback(
    (message: string, severity: QuickTestSnackbar['severity'] = 'info') =>
      setSnackbar({ open: true, message, severity }),
    [],
  );

  // Mirror the Navigation editor's device control: pass tree_id for cache
  // population WHEN available, but do NOT require it (requireTreeId defaults to
  // false). The tree loads in parallel; gating control on it caused the
  // post-refresh "tree_id is missing" race.
  const { isControlLoading, handleDeviceControl, controlError, clearError } =
    useDeviceControlWithForceUnlock({
      host: selectedHost,
      device_id: selectedDeviceId,
      sessionId: 'quicktest-builder-session',
      autoCleanup: true,
      tree_id: currentTreeId || undefined,
      onControlStateChange: handleControlStateChange,
    });

  useEffect(() => {
    if (controlError) {
      showSnackbar(controlError, 'error');
      clearError();
    }
  }, [controlError, clearError, showSnackbar]);

  // ==================== DEVICE DATA (actions / verifications) ====================
  const {
    setControlState,
    getAvailableActions,
    getAvailableVerificationTypes,
    availableActionsLoading,
    fetchAvailableActions,
    // Aliased to avoid colliding with this hook's local userinterfaceName state.
    setUserinterfaceName: setDeviceDataUserinterfaceName,
  } = useDeviceData();

  useEffect(() => {
    setControlState(selectedHost, selectedDeviceId, isControlActive);
  }, [selectedHost, selectedDeviceId, isControlActive, setControlState]);

  useEffect(() => {
    if (!isControlActive || !selectedHost || !selectedDeviceId) return;
    const timer = setTimeout(() => {
      fetchAvailableActions(true);
    }, 1000);
    return () => clearTimeout(timer);
  }, [isControlActive, selectedHost, selectedDeviceId, fetchAvailableActions]);

  const availableActions = getAvailableActions();
  const availableVerifications = getAvailableVerificationTypes();
  const areActionsLoaded =
    isControlActive &&
    !availableActionsLoading &&
    Object.values(availableActions || {}).flat().length > 0;

  // ==================== INTERFACE & NAVIGATION ====================
  const { loadTreeByUserInterface } = useNavigationConfig();
  const { getAllUserInterfaces, getUserInterfaceByName } = useUserInterface();

  const [userinterfaceName, setUserinterfaceName] = useState('');
  const [variant, setVariant] = useState(''); // '' = base
  const [compatibleInterfaceNames, setCompatibleInterfaceNames] = useState<string[]>([]);
  const [navNodes, setNavNodes] = useState<any[]>([]);

  // Reset the chosen variant whenever the user interface changes.
  useEffect(() => {
    setVariant('');
  }, [userinterfaceName]);

  // Mirror the selected UI into DeviceDataContext (same as NavigationEditor) so
  // getAllReferences fetches via the OPTIMAL userinterface_name path — the
  // server then applies shared-reference visibility and buckets refs under the
  // UI name, which is the key InlineVerificationConfig looks them up by.
  // Without this the fetch falls back to device_model and the verification
  // reference dropdown shows "No image references available".
  useEffect(() => {
    setDeviceDataUserinterfaceName(userinterfaceName || null);
  }, [userinterfaceName, setDeviceDataUserinterfaceName]);

  // ==================== AV / REMOTE PANEL STATE (mirrors TestCaseBuilder) ====================
  const [isAVPanelCollapsed, setIsAVPanelCollapsed] = useState(true);
  const [isAVPanelMinimized, setIsAVPanelMinimized] = useState(false);
  const [captureMode, setCaptureMode] = useState<'stream' | 'screenshot' | 'video'>('stream');
  const [isMobileOrientationLandscape, setIsMobileOrientationLandscape] = useState(false);
  const isVerificationVisible = captureMode === 'screenshot' || captureMode === 'video';

  const handleAVPanelCollapsedChange = useCallback(
    (collapsed: boolean) => setIsAVPanelCollapsed(collapsed),
    [],
  );
  const handleAVPanelMinimizedChange = useCallback(
    (minimized: boolean) => setIsAVPanelMinimized(minimized),
    [],
  );
  const handleCaptureModeChange = useCallback(
    (mode: 'stream' | 'screenshot' | 'video') => setCaptureMode(mode),
    [],
  );
  const handleMobileOrientationChange = useCallback(
    (landscape: boolean) => setIsMobileOrientationLandscape(landscape),
    [],
  );

  // Compatible interfaces for the selected device.
  useEffect(() => {
    const run = async () => {
      if (!selectedDeviceId || !selectedHost) {
        setCompatibleInterfaceNames([]);
        setUserinterfaceName('');
        return;
      }
      const selectedDevice = selectedHost.devices?.find(
        (d: any) => d.device_id === selectedDeviceId,
      );
      if (!selectedDevice) return;
      try {
        const interfaces = await getAllUserInterfaces();
        const compatible = filterCompatibleInterfaces(interfaces, selectedDevice);
        setCompatibleInterfaceNames(compatible.map((ui: any) => ui.name));
      } catch (e) {
        console.warn('[useQuickTestBuilder] Failed to load interfaces:', e);
        setCompatibleInterfaceNames([]);
      }
    };
    run();
  }, [selectedDeviceId, selectedHost, getAllUserInterfaces]);

  // Navigation nodes for the "go to node" dropdown.
  useEffect(() => {
    const run = async () => {
      if (!userinterfaceName) {
        setNavNodes([]);
        setCurrentTreeId(null);
        return;
      }
      setIsLoadingTree(true);
      try {
        const ui = await getUserInterfaceByName(userinterfaceName);
        const result = await loadTreeByUserInterface(ui.id, { includeNested: true });
        setNavNodes(result?.tree?.metadata?.nodes || result?.nodes || []);
        setCurrentTreeId(result?.tree?.id || ui.root_tree || null);
      } catch (e) {
        console.warn('[useQuickTestBuilder] Failed to load tree:', e);
        setNavNodes([]);
        setCurrentTreeId(null);
      } finally {
        setIsLoadingTree(false);
      }
    };
    run();
  }, [userinterfaceName, getUserInterfaceByName, loadTreeByUserInterface]);

  // ==================== STEP LIST (units = steps + loops) ====================
  // A unit is a plain step or a LOOP holding a contiguous group of child steps.
  // The dropdown on a row writes `onFail` (top-level) or `loopBreak` (loop child)
  // via updateStep; the compiler turns the unit list into the standard graph.
  const [units, setUnits] = useState<QuickTestUnit[]>([]);

  // Flat list of every step (top-level + loop children) — for scans, isExecutable,
  // and the execution overlay (which keys block state by `node-${step.id}`).
  const allSteps = useMemo(
    () => units.flatMap((u) => (isQuickLoop(u) ? u.steps : [u])),
    [units],
  );

  const addStep = useCallback((type: QuickStepType) => {
    setUnits((prev) => [...prev, createEmptyStep(newStepId(), type)]);
  }, []);
  const addLoop = useCallback(() => {
    setUnits((prev) => [...prev, createLoopUnit(newStepId())]);
  }, []);
  const addStepInLoop = useCallback((loopId: string, type: QuickStepType) => {
    setUnits((prev) =>
      prev.map((u) =>
        isQuickLoop(u) && u.id === loopId
          ? { ...u, steps: [...u.steps, { ...createEmptyStep(newStepId(), type), loopBreak: 'onFailure' as LoopBreak }] }
          : u,
      ),
    );
  }, []);

  // Patch a step wherever it lives (top-level or inside a loop).
  const updateStep = useCallback((id: string, patch: Partial<QuickTestStep>) => {
    setUnits((prev) =>
      prev.map((u) => {
        if (isQuickLoop(u)) {
          return { ...u, steps: u.steps.map((s) => (s.id === id ? { ...s, ...patch } : s)) };
        }
        return u.id === id ? { ...u, ...patch } : u;
      }),
    );
  }, []);

  // Remove a step from the top level or from whichever loop holds it (an emptied
  // loop is kept — it just compiles to nothing until it has steps again).
  const removeStep = useCallback((id: string) => {
    setUnits((prev) =>
      prev
        .filter((u) => isQuickLoop(u) || u.id !== id)
        .map((u) => (isQuickLoop(u) ? { ...u, steps: u.steps.filter((s) => s.id !== id) } : u)),
    );
  }, []);

  const changeStepType = useCallback((id: string, type: QuickStepType) => {
    setUnits((prev) =>
      prev.map((u) => {
        if (isQuickLoop(u)) {
          return {
            ...u,
            steps: u.steps.map((s) =>
              s.id === id ? { ...createEmptyStep(s.id, type), loopBreak: s.loopBreak } : s,
            ),
          };
        }
        return u.id === id ? createEmptyStep(u.id, type) : u;
      }),
    );
  }, []);

  // Move a step by one position. A top-level step swaps with its neighbor, or
  // ENTERS an adjacent loop (down -> first child, up -> last child). A loop child
  // reorders within the loop, or EXITS to the top level at the loop's boundary.
  // Repeated presses therefore traverse a step right through a loop.
  const moveStep = useCallback((stepId: string, dir: -1 | 1) => {
    setUnits((prev) => {
      const topIndex = prev.findIndex((u) => !isQuickLoop(u) && u.id === stepId);
      if (topIndex >= 0) {
        const target = topIndex + dir;
        if (target < 0 || target >= prev.length) return prev;
        const neighbor = prev[target];
        const step = prev[topIndex] as QuickTestStep;
        if (isQuickLoop(neighbor)) {
          const entered: QuickTestStep = { ...step, loopBreak: step.loopBreak ?? 'onFailure' };
          const newLoop: QuickTestLoop =
            dir === 1
              ? { ...neighbor, steps: [entered, ...neighbor.steps] }
              : { ...neighbor, steps: [...neighbor.steps, entered] };
          const next = [...prev];
          next[target] = newLoop;
          next.splice(topIndex, 1);
          return next;
        }
        const next = [...prev];
        [next[topIndex], next[target]] = [next[target], next[topIndex]];
        return next;
      }

      const loopIndex = prev.findIndex(
        (u) => isQuickLoop(u) && u.steps.some((s) => s.id === stepId),
      );
      if (loopIndex < 0) return prev;
      const loop = prev[loopIndex] as QuickTestLoop;
      const childIndex = loop.steps.findIndex((s) => s.id === stepId);
      const targetChild = childIndex + dir;

      if (targetChild >= 0 && targetChild < loop.steps.length) {
        const steps = [...loop.steps];
        [steps[childIndex], steps[targetChild]] = [steps[targetChild], steps[childIndex]];
        const next = [...prev];
        next[loopIndex] = { ...loop, steps };
        return next;
      }

      // Crossing the loop boundary -> pop out to the top level (drop loopBreak).
      const child = loop.steps[childIndex];
      const newLoop: QuickTestLoop = {
        ...loop,
        steps: loop.steps.filter((s) => s.id !== stepId),
      };
      const outStep: QuickTestStep = { ...child, loopBreak: undefined };
      const next = [...prev];
      next[loopIndex] = newLoop;
      next.splice(dir === -1 ? loopIndex : loopIndex + 1, 0, outStep);
      return next;
    });
  }, []);

  // Move a whole loop among the top-level units.
  const moveLoop = useCallback((loopId: string, dir: -1 | 1) => {
    setUnits((prev) => {
      const index = prev.findIndex((u) => isQuickLoop(u) && u.id === loopId);
      if (index < 0) return prev;
      const target = index + dir;
      if (target < 0 || target >= prev.length) return prev;
      const next = [...prev];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }, []);

  const updateLoop = useCallback((loopId: string, patch: Partial<QuickTestLoop>) => {
    setUnits((prev) =>
      prev.map((u) => (isQuickLoop(u) && u.id === loopId ? { ...u, ...patch } : u)),
    );
  }, []);

  // Ungroup a loop: its child steps splice back into the top level in place.
  const removeLoop = useCallback((loopId: string) => {
    setUnits((prev) => {
      const index = prev.findIndex((u) => isQuickLoop(u) && u.id === loopId);
      if (index < 0) return prev;
      const loop = prev[index] as QuickTestLoop;
      return [...prev.slice(0, index), ...loop.steps, ...prev.slice(index + 1)];
    });
  }, []);

  // ==================== INPUT VARIABLES ====================
  // Typed variables ({name} placeholders) declared once with a default and used
  // in step fields (goto target / wait / action & verification params). Saved as
  // standard scriptConfig.inputs; values are picked at Run time (RunWithInputsDialog)
  // and resolved SERVER-SIDE by the TestCaseExecutor.
  const [inputs, setInputs] = useState<ScriptInput[]>([]);

  const addInput = useCallback((input: ScriptInput) => {
    setInputs((prev) =>
      prev.some((i) => i.name === input.name) ? prev : [...prev, input],
    );
  }, []);
  const updateInput = useCallback((name: string, patch: Partial<ScriptInput>) => {
    setInputs((prev) => prev.map((i) => (i.name === name ? { ...i, ...patch } : i)));
  }, []);
  const removeInput = useCallback((name: string) => {
    setInputs((prev) => prev.filter((i) => i.name !== name));
  }, []);

  // Every {name} the steps reference, with the type implied by WHERE it's used
  // (goto target → node, wait → number, params → string).
  const referencedInputs = useMemo(() => {
    const found = new Map<string, string>();
    const scanStep = (step: QuickTestStep) => {
      const gotoVar = placeholderName(step.targetNodeLabel);
      if (gotoVar && !found.has(gotoVar)) found.set(gotoVar, 'node');
      const waitVar = placeholderName(step.waitMs);
      if (waitVar && !found.has(waitVar)) found.set(waitVar, 'number');
      collectPlaceholders(step.data).forEach((name) => {
        if (!found.has(name)) found.set(name, 'string');
      });
    };
    units.forEach((u) => {
      if (isQuickLoop(u)) {
        const itVar = placeholderName(u.iterations);
        if (itVar && !found.has(itVar)) found.set(itVar, 'number');
        u.steps.forEach(scanStep);
      } else {
        scanStep(u);
      }
    });
    return found;
  }, [units]);
  const referencedNames = useMemo(() => new Set(referencedInputs.keys()), [referencedInputs]);

  // Variables are created BY USE: typing an unknown {name} anywhere auto-adds it
  // to the chip-bar (required, empty default — the Run dialog gates until filled).
  useEffect(() => {
    setInputs((prev) => {
      const known = new Set(prev.map((i) => i.name));
      const missing = [...referencedInputs].filter(([name]) => !known.has(name));
      if (!missing.length) return prev;
      return [
        ...prev,
        ...missing.map(([name, type]) => ({ name, type, required: true, default: '' })),
      ];
    });
  }, [referencedInputs]);

  const graph = useMemo(() => compileStepsToGraph(units, inputs), [units, inputs]);

  // ==================== SAVE / LOAD ====================
  const { saveTestCase, listTestCases, getTestCase, deleteTestCase } = useTestCaseSave();
  const [testcaseName, setTestcaseName] = useState('');
  const [currentTestcaseId, setCurrentTestcaseId] = useState<string | null>(null);
  const [testcaseList, setTestcaseList] = useState<any[]>([]);
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [isLoadingTestCases, setIsLoadingTestCases] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  // Saved quick tests are shown in an always-visible left rail (like Virtual
  // Scripts), not behind a Load dialog — so the list is fetched up front and
  // refreshed after every save/delete instead of on demand.
  const refreshTestcaseList = useCallback(async () => {
    setIsLoadingTestCases(true);
    try {
      const result = await listTestCases();
      // QuickTest only lists test cases it authored (created_by === 'quicktest').
      // Visual-builder / AI test cases stay in the TestCaseBuilder list.
      const quickTests = (result.testcases || []).filter(
        (tc: any) => tc.created_by === QUICKTEST_CREATED_BY,
      );
      setTestcaseList(quickTests);
    } finally {
      setIsLoadingTestCases(false);
    }
  }, [listTestCases]);

  useEffect(() => {
    refreshTestcaseList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSave = useCallback(async () => {
    if (!testcaseName.trim() || !userinterfaceName) return;
    setIsSaving(true);
    try {
      const result = await saveTestCase(
        testcaseName.trim(),
        graph,
        '',
        userinterfaceName,
        QUICKTEST_CREATED_BY,
        'dev',
        true, // overwrite by name
      );
      if (result.success) {
        setCurrentTestcaseId(result.testcase?.testcase_id || currentTestcaseId);
        setSaveDialogOpen(false);
        showSnackbar(`Saved "${testcaseName.trim()}"`, 'success');
        refreshTestcaseList();
      } else {
        showSnackbar(result.error || 'Save failed', 'error');
      }
    } finally {
      setIsSaving(false);
    }
  }, [testcaseName, userinterfaceName, graph, saveTestCase, currentTestcaseId, showSnackbar, refreshTestcaseList]);

  const handleLoad = useCallback(
    async (testcaseId: string) => {
      const result = await getTestCase(testcaseId);
      if (!result.success || !result.testcase) {
        showSnackbar(result.error || 'Failed to load test case', 'error');
        return;
      }
      const tc = result.testcase;
      const parsed = parseGraphToSteps(tc.graph_json);
      if (parsed === null) {
        showSnackbar(
          'This test case is not a simple linear list — open it in the full Test Builder.',
          'error',
        );
        return;
      }
      setUnits(parsed.units);
      setInputs(parsed.inputs);
      setTestcaseName(tc.testcase_name || '');
      setCurrentTestcaseId(tc.testcase_id);
      if (tc.userinterface_name) setUserinterfaceName(tc.userinterface_name);
      showSnackbar(`Loaded "${tc.testcase_name}"`, 'success');
    },
    [getTestCase, showSnackbar],
  );

  const handleDelete = useCallback(
    async (testcaseId: string) => {
      const result = await deleteTestCase(testcaseId);
      if (result.success) {
        setTestcaseList((prev) => prev.filter((t) => t.testcase_id !== testcaseId));
        if (testcaseId === currentTestcaseId) setCurrentTestcaseId(null);
      } else {
        showSnackbar(result.error || 'Delete failed', 'error');
      }
    },
    [deleteTestCase, currentTestcaseId, showSnackbar],
  );

  const handleNew = useCallback(() => {
    setUnits([]);
    setInputs([]);
    setTestcaseName('');
    setCurrentTestcaseId(null);
  }, []);

  // ==================== EXECUTION ====================
  const unifiedExecution = useExecutionState();
  const isExecutingRef = useRef(false);

  const isExecutable =
    isControlActive &&
    !!selectedHost &&
    !!selectedDeviceId &&
    !!userinterfaceName &&
    allSteps.length > 0;

  // Push a status snapshot from the host into the unified execution state so the
  // step rows + overlay reflect live per-step progress.
  const applyStatusSnapshot = useCallback(
    (status: any) => {
      if (status?.current_block_id) {
        unifiedExecution.startBlockExecution(status.current_block_id);
      }
      Object.entries(status?.block_states || {}).forEach(([blockId, bs]: [string, any]) => {
        unifiedExecution.updateBlockState(blockId, {
          status: bs.status,
          duration: bs.duration,
          error: bs.error,
          result: bs,
        });
      });
    },
    [unifiedExecution],
  );

  // Run an arbitrary compiled graph through the async execute + poll flow. Used
  // for both the whole test (handleExecute) and a single step (handleRunStep) —
  // a single step is just a 1-step graph.
  const runGraph = useCallback(
    async (g: any, opts?: { generateReport?: boolean }) => {
      if (isExecutingRef.current) return;
      if (!selectedHost || !selectedDeviceId || !userinterfaceName) return;
      isExecutingRef.current = true;

      const blockIds = g.nodes
        .filter((n: any) => !['start', 'success', 'failure'].includes(n.type as string))
        .map((n: any) => n.id);
      unifiedExecution.startExecution('test_case', blockIds);

      const fail = (error: string) =>
        unifiedExecution.completeExecution({
          success: false,
          result_type: 'error',
          execution_time_ms: 0,
          error,
        });

      try {
        const start = await api.post<any>(buildServerUrl('/server/testcase/execute'), {
          graph_json: g,
          device_id: selectedDeviceId,
          host_name: (selectedHost as any).host_name,
          userinterface_name: userinterfaceName,
          testcase_name: testcaseName.trim() || 'quicktest',
          execution_metadata: variant ? { variant } : {},
          async_execution: true,
          // Single-step runs skip the report tail (video/R2/HTML/DB) so they finish
          // fast and don't generate a report; the full "Run" keeps generate_report.
          generate_report: opts?.generateReport ?? true,
        });
        if (!start?.success || !start.execution_id) {
          fail(start?.error || 'Failed to start execution');
          return;
        }

        // Poll for live per-step progress + completion. The host updates
        // block_states/current_block_id during the run (the socket only emits at
        // start/finish), so polling is what makes the step rows light up live.
        // host_name is REQUIRED on the status GET — the server resolves the host
        // via get_host_from_request() from the query string (else 400).
        const statusUrl = buildServerUrlWithParams(
          `/server/testcase/execution/${start.execution_id}/status`,
          { host_name: (selectedHost as any).host_name },
        );
        for (let i = 0; i < MAX_POLLS; i++) {
          await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
          let payload: any;
          try {
            payload = await api.get<any>(statusUrl);
          } catch {
            continue; // transient — keep polling
          }
          const status = payload?.status;
          if (!status) continue;

          applyStatusSnapshot(status);

          if (status.status && status.status !== 'running') {
            const result = status.result || {};
            unifiedExecution.completeExecution({
              success: result.success ?? status.status === 'completed',
              result_type:
                result.result_type ||
                (status.status === 'completed'
                  ? 'success'
                  : status.status === 'failed'
                    ? 'failure'
                    : 'error'),
              execution_time_ms: result.execution_time_ms || status.elapsed_time_ms || 0,
              error: result.error || status.error,
              step_count: result.step_count,
              report_url: result.report_url,
              logs_url: result.logs_url,
            });
            return;
          }
        }
        fail('Execution timed out waiting for completion');
      } catch (e) {
        fail(e instanceof Error ? e.message : 'Execution error');
      } finally {
        isExecutingRef.current = false;
      }
    },
    [
      selectedHost,
      selectedDeviceId,
      userinterfaceName,
      variant,
      testcaseName,
      applyStatusSnapshot,
      unifiedExecution,
    ],
  );

  // Run-with-inputs: a test with variables prompts for values first (pre-filled
  // with defaults); the values are stamped as scriptConfig.inputs[].value onto a
  // COPY of the graph — never persisted — and resolved server-side.
  const [runInputsOpen, setRunInputsOpen] = useState(false);
  const runnableInputs = useMemo(() => inputs.filter((i) => !i.protected), [inputs]);
  const lastRunValuesRef = useRef<Record<string, any>>({});

  const handleExecute = useCallback(() => {
    if (!isExecutable) return;
    if (runnableInputs.length > 0) {
      setRunInputsOpen(true);
      return;
    }
    return runGraph(graph);
  }, [isExecutable, runGraph, graph, runnableInputs]);

  const handleRunWithInputs = useCallback(
    (values: Record<string, any>) => {
      setRunInputsOpen(false);
      lastRunValuesRef.current = values;
      return runGraph(stampInputValues(graph, values));
    },
    [runGraph, graph],
  );

  // Run a single step on the device (compiles a 1-step graph). Lets the user
  // try one row in isolation. Inputs ride along so a {variable} row resolves
  // (last-used run values, else defaults via the backend).
  const handleRunStep = useCallback(
    (step: QuickTestStep) => {
      if (!isControlActive || isExecutingRef.current) return;
      // Single step: execute only, no report (fast). The full "Run" generates one.
      return runGraph(stampInputValues(compileStepsToGraph([step], inputs), lastRunValuesRef.current), {
        generateReport: false,
      });
    },
    [runGraph, isControlActive, inputs],
  );

  return {
    // host / device
    availableHosts,
    selectedHost,
    selectedDeviceId,
    isControlActive,
    isControlLoading,
    isRemotePanelOpen,
    showRemotePanel,
    isDeviceLocked,
    handleDeviceSelect,
    handleDeviceControl,
    handleToggleRemotePanel,
    handleDisconnectComplete,

    // AV / remote panel state (reused from TestCaseBuilder)
    showAVPanel,
    isAVPanelCollapsed,
    isAVPanelMinimized,
    captureMode,
    isVerificationVisible,
    isMobileOrientationLandscape,
    handleAVPanelCollapsedChange,
    handleAVPanelMinimizedChange,
    handleCaptureModeChange,
    handleMobileOrientationChange,

    // interface / navigation
    userinterfaceName,
    setUserinterfaceName,
    variant,
    setVariant,
    compatibleInterfaceNames,
    navNodes,
    isLoadingTree,

    // actions / verifications metadata
    availableActions,
    availableVerifications,
    areActionsLoaded,

    // steps + loops (units)
    units,
    allSteps,
    addStep,
    addLoop,
    addStepInLoop,
    updateStep,
    removeStep,
    moveStep,
    moveLoop,
    updateLoop,
    removeLoop,
    changeStepType,

    // input variables
    inputs,
    addInput,
    updateInput,
    removeInput,
    referencedNames,
    runnableInputs,
    runInputsOpen,
    setRunInputsOpen,
    handleRunWithInputs,

    // save / load
    testcaseName,
    setTestcaseName,
    currentTestcaseId,
    testcaseList,
    isLoadingTestCases,
    isSaving,
    saveDialogOpen,
    setSaveDialogOpen,
    handleSave,
    handleLoad,
    handleDelete,
    handleNew,

    // execution
    isExecutable,
    handleExecute,
    handleRunStep,
    unifiedExecution,

    // misc
    snackbar,
    setSnackbar,
  };
};
