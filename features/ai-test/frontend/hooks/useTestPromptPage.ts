/**
 * TestPrompt Page Hook
 *
 * Manages device control, interface/navigation loading, form state,
 * save/load, execution, and feedback loop.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { useHostData, useHostControl } from '../../../../frontend/src/contexts/index';
import { useDeviceControlWithForceUnlock } from '../../../../frontend/src/../../frontend/src/hooks/useDeviceControlWithForceUnlock';
import { useNavigationConfig } from '../../../../frontend/src/contexts/navigation/NavigationConfigContext';
import { useSocket } from '../../../../frontend/src/contexts/SocketContext';
import { useUserInterface } from '../../../../frontend/src/../../frontend/src/hooks/pages/useUserInterface';
import { filterCompatibleInterfaces, isDeviceCompatibleWithInterface } from '../../../../frontend/src/utils/userinterface/deviceCompatibilityUtils';
import { api } from '../../../../frontend/src/utils/apiClient';
import { buildRunningLogUrl, buildServerUrl } from '../../../../frontend/src/utils/buildUrlUtils';
import { useUserSession } from '../../../../frontend/src/hooks/useUserSession';
import { useRunningLog, type RunningLogData } from '../../../../frontend/src/hooks/rec/useRunningLog';
import type { AIGraphEditProposal } from '../../../../frontend/src/hooks/testcase/useAIGraphEdit';
import type { Host } from '../../../../frontend/src/types/common/Host_Types';
import {
  TestPromptFormState,
  TestPromptExecution,
  TestPromptStep,
  TestPrompt,
  TestPromptLiveEvent,
  TestPromptRunMode,
  LinkedTestcase,
  DEFAULT_TEST_PROMPT_FORM,
} from '../types/TestPrompt_Types';

export interface UseTestPromptPageReturn {
  // Device & Host
  selectedHost: any;
  selectedDeviceId: string | null;
  isControlActive: boolean;
  isControlLoading: boolean;
  isRemotePanelOpen: boolean;
  availableHosts: any[];
  handleDeviceSelect: (host: any | null, deviceId: string | null) => void;
  handleDeviceControl: () => Promise<void>;
  handleToggleRemotePanel: () => void;
  isDeviceLocked: (deviceKey: string) => boolean;

  // Interface & Navigation
  compatibleInterfaceNames: string[];
  userinterfaceName: string;
  setUserinterfaceName: (name: string) => void;
  navNodes: any[];
  isLoadingTree: boolean;
  currentTreeId: string | null;

  // Form
  formState: TestPromptFormState;
  updateFormField: <K extends keyof TestPromptFormState>(field: K, value: TestPromptFormState[K]) => void;
  resetForm: () => void;
  isFormValid: boolean;
  isDirty: boolean;

  // Save/Load
  savedPrompts: TestPrompt[];
  currentPromptId: string | null;
  currentVersion: number;
  currentMode: 'dev' | 'prod';
  isSaving: boolean;
  isLoadingPrompts: boolean;
  handleSave: () => Promise<void>;
  handleLoad: (promptId: string) => Promise<void>;
  handleDelete: (promptId: string) => Promise<void>;
  refreshPromptList: () => Promise<void>;

  // Execution
  executions: TestPromptExecution[];
  isExecuting: boolean;
  runMode: TestPromptRunMode;
  setRunMode: (mode: TestPromptRunMode) => void;
  handleRunTestPrompt: (options?: { regenerate?: boolean }) => void;
  liveEventsByExecutionId: Record<string, TestPromptLiveEvent[]>;
  /** running.log of the current run (both modes write it), for the step overlay. */
  runningLogData: RunningLogData | null;

  // Linked testcase (graph mode)
  linkedTestcase: LinkedTestcase | null;
  handleSaveAsTestcase: (executionId: string) => Promise<void>;
  /** Passing exploration -> proposed testcase graph (its steps + checks for the criteria). */
  explorePreview: { executionId: string; proposal: AIGraphEditProposal } | null;
  buildingFromExploreId: string | null;
  handleProposeFromExplore: (executionId: string) => Promise<void>;
  handleApplyExplorePreview: () => Promise<void>;
  handleCancelExplorePreview: () => void;
  handleUnlinkTestcase: () => Promise<void>;

  // Feedback & Versioning
  handleSubmitFeedback: (executionId: string, feedback: string) => Promise<void>;
  handlePromote: () => Promise<void>;

  // Snackbar
  snackbar: { open: boolean; message: string; severity: 'success' | 'error' | 'info' };
  showSnackbar: (message: string, severity?: 'success' | 'error' | 'info') => void;
  closeSnackbar: () => void;
}

// Session the page takes control with; a run sends it so the server sees the caller's control.
const TEST_PROMPT_SESSION_ID = 'test-prompt-session';

/** A test_prompt_executions row's stored details (run_details, host/device) as card fields. */
const runDetailsFields = (e: any): Partial<TestPromptExecution> => {
  const d = e?.run_details || {};
  return {
    version: d.version,
    edited: d.edited,
    ranPrompt: d.prompt,
    ranCriteria: d.acceptance_criteria,
    ranTarget: d.target_screen_label || undefined,
    ranUserinterface: d.userinterface_name || undefined,
    replayedTestcase: d.testcase_id ? { id: d.testcase_id, name: d.testcase_name } : undefined,
    generated: d.generated,
    verdict: d.verdict,
    error: d.error,
    savedTestcaseId: d.saved_testcase_id,
    hostName: e?.host_name,
    deviceId: e?.device_id,
    hasTrace: Array.isArray(e?.tool_trace) && e.tool_trace.length > 0,
    auto: d.auto || undefined,
    autoFrom: d.auto_from,
    retryOf: d.retry_of,
    decision: d.decision,
    outcome: d.outcome,
  };
};

/** One execution row, read again once it finishes (verdict, error and graph are written at the end). */
const fetchExecutionRow = async (promptId: string, executionId: string): Promise<any | null> => {
  try {
    const res = await api.get<any>(buildServerUrl(`/server/testprompt/${promptId}/executions`));
    return (res?.executions || []).find((e: any) => e.id === executionId) || null;
  } catch {
    return null;
  }
};

export function useTestPromptPage(): UseTestPromptPageReturn {
  // ==================== HOST & DEVICE ====================
  const { availableHosts } = useHostData();
  const {
    selectedHost,
    selectedDeviceId,
    isControlActive,
    isRemotePanelOpen,
    handleDeviceSelect: hostManagerDeviceSelect,
    handleControlStateChange,
    handleToggleRemotePanel,
    isDeviceLocked: hostManagerIsDeviceLocked,
  } = useHostControl();

  const handleDeviceSelect = hostManagerDeviceSelect;

  const isDeviceLocked = useCallback((deviceKey: string) => {
    const [hostName, deviceId] = deviceKey.includes(':')
      ? deviceKey.split(':')
      : [deviceKey, 'device1'];
    const host = availableHosts.find((h: any) => h.host_name === hostName);
    return hostManagerIsDeviceLocked(host || null, deviceId);
  }, [availableHosts, hostManagerIsDeviceLocked]);

  // ==================== INTERFACE & NAVIGATION ====================
  const [currentTreeId, setCurrentTreeId] = useState<string | null>(null);
  const [isLoadingTree, setIsLoadingTree] = useState(false);

  // ==================== SNACKBAR ====================
  const [snackbar, setSnackbar] = useState<{
    open: boolean;
    message: string;
    severity: 'success' | 'error' | 'info';
  }>({ open: false, message: '', severity: 'info' });

  const showSnackbar = useCallback(
    (message: string, severity: 'success' | 'error' | 'info' = 'info') => {
      setSnackbar({ open: true, message, severity });
    },
    []
  );

  const closeSnackbar = useCallback(() => {
    setSnackbar(prev => ({ ...prev, open: false }));
  }, []);

  // ==================== DEVICE CONTROL ====================
  const {
    isControlLoading,
    handleDeviceControl,
    controlError,
    clearError,
  } = useDeviceControlWithForceUnlock({
    host: selectedHost,
    device_id: selectedDeviceId,
    sessionId: TEST_PROMPT_SESSION_ID,
    autoCleanup: true,
    tree_id: currentTreeId || undefined,
    requireTreeId: true,
    onControlStateChange: handleControlStateChange,
  });

  useEffect(() => {
    if (controlError) {
      showSnackbar(controlError, 'error');
      clearError();
    }
  }, [controlError, clearError, showSnackbar]);

  // ==================== PENDING DEVICE SELECTION STATE ====================
  const [pendingUIName, setPendingUIName] = useState<string | null>(null);

  // ==================== INTERFACE LOADING ====================
  const { loadTreeByUserInterface } = useNavigationConfig();
  const { getAllUserInterfaces, getUserInterfaceByName } = useUserInterface();

  const [compatibleInterfaceNames, setCompatibleInterfaceNames] = useState<string[]>([]);
  const [userinterfaceName, setUserinterfaceName] = useState<string>('');
  const [formState, setFormState] = useState<TestPromptFormState>(DEFAULT_TEST_PROMPT_FORM);
  // A target screen belongs to one interface: drop it when the interface really changes
  // (a manual pick, or a device that cannot use it), not when a loaded prompt sets its own.
  const clearTargetScreen = useCallback(() => {
    setFormState(prev => ({ ...prev, targetScreenNodeId: '', targetScreenLabel: '' }));
  }, []);
  const [navNodes, setNavNodes] = useState<any[]>([]);

  const loadTreeForInterface = useCallback(async (interfaceName: string) => {
    if (!interfaceName) {
      setNavNodes([]);
      setCurrentTreeId(null);
      return;
    }

    setIsLoadingTree(true);
    try {
      const userInterface = await getUserInterfaceByName(interfaceName);
      if (userInterface) {
        const result = await loadTreeByUserInterface(userInterface.id, { includeNested: true });
        if (result) {
          const nodes = result?.tree?.metadata?.nodes || result?.nodes || [];
          const treeId = result?.tree?.id || userInterface.root_tree;
          setNavNodes(nodes);
          setCurrentTreeId(treeId);
          return;
        }
      }
      setNavNodes([]);
      setCurrentTreeId(null);
    } catch (error) {
      console.warn('[@useTestPromptPage] Failed to load navigation tree:', error);
      setNavNodes([]);
      setCurrentTreeId(null);
    } finally {
      setIsLoadingTree(false);
    }
  }, [getUserInterfaceByName, loadTreeByUserInterface]);

  useEffect(() => {
    // A newer run (device or interface changed meanwhile) supersedes this one.
    let cancelled = false;
    const loadCompatibleInterfaces = async () => {
      if (!selectedDeviceId || !selectedHost) {
        // Keep userinterfaceName: a loaded prompt sets it before its device is
        // picked, and clearing it here made the device's first interface win.
        setCompatibleInterfaceNames([]);
        return;
      }

      try {
        const selectedDevice = selectedHost.devices?.find((d: any) => d.device_id === selectedDeviceId);
        if (!selectedDevice) return;

        const interfaces = await getAllUserInterfaces();
        if (cancelled) return;
        const compatibleInterfaces = filterCompatibleInterfaces(interfaces, selectedDevice);
        const names = compatibleInterfaces.map((ui: any) => ui.name);

        setCompatibleInterfaceNames(names);

        const activeName = names.includes(userinterfaceName) ? userinterfaceName : names[0] || '';
        if (activeName !== userinterfaceName) {
          setUserinterfaceName(activeName);
          clearTargetScreen();
        }
        if (activeName) {
          await loadTreeForInterface(activeName);
        }
      } catch (error) {
        console.error('[@useTestPromptPage] Failed to load compatible interfaces:', error);
      }
    };

    loadCompatibleInterfaces();
    return () => {
      cancelled = true;
    };
  }, [selectedDeviceId, selectedHost, getAllUserInterfaces, userinterfaceName, loadTreeForInterface, clearTargetScreen]);

  const handleSetUserinterfaceName = useCallback((name: string) => {
    setUserinterfaceName(name);
    clearTargetScreen();
    loadTreeForInterface(name);
  }, [loadTreeForInterface, clearTargetScreen]);

  // ==================== PENDING DEVICE SELECTION EFFECT ====================
  // When hosts become available and we have a pending UI to auto-select a device for
  useEffect(() => {
    if (!pendingUIName || availableHosts.length === 0) return;

    const autoSelect = async () => {
      try {
        const allInterfaces = await getAllUserInterfaces();
        const targetUI = allInterfaces.find((ui: any) => ui.name === pendingUIName);
        if (targetUI) {
          for (const host of availableHosts) {
            const devices = host.devices || [];
            const compatDevice = devices.find((d: any) => isDeviceCompatibleWithInterface(d, targetUI));
            if (compatDevice) {
              handleDeviceSelect(host, compatDevice.device_id);
              setPendingUIName(null);
              return;
            }
          }
        }
      } catch (e) {
        console.warn('[@useTestPromptPage] Pending device auto-select failed:', e);
      }
    };

    autoSelect();
  }, [pendingUIName, availableHosts, getAllUserInterfaces, handleDeviceSelect]);

  // ==================== FORM STATE ====================
  // Snapshot of form values at last save/load — used to detect unsaved edits.
  const [savedSnapshot, setSavedSnapshot] = useState<TestPromptFormState>(DEFAULT_TEST_PROMPT_FORM);

  const updateFormField = useCallback(<K extends keyof TestPromptFormState>(
    field: K,
    value: TestPromptFormState[K]
  ) => {
    setFormState(prev => ({ ...prev, [field]: value }));
  }, []);

  const resetForm = useCallback(() => {
    setFormState(DEFAULT_TEST_PROMPT_FORM);
    setSavedSnapshot(DEFAULT_TEST_PROMPT_FORM);
    setCurrentPromptId(null);
    setCurrentVersion(1);
    setCurrentMode('dev');
    setLinkedTestcase(null);
  }, []);

  const isDirty = (
    formState.name !== savedSnapshot.name ||
    formState.prompt !== savedSnapshot.prompt ||
    formState.acceptanceCriteria !== savedSnapshot.acceptanceCriteria ||
    formState.targetScreenNodeId !== savedSnapshot.targetScreenNodeId ||
    formState.targetScreenLabel !== savedSnapshot.targetScreenLabel
  );

  const isFormValid = Boolean(
    formState.prompt.trim() &&
    formState.acceptanceCriteria.trim() &&
    isControlActive &&
    userinterfaceName
  );

  // ==================== SAVE / LOAD ====================
  const [savedPrompts, setSavedPrompts] = useState<TestPrompt[]>([]);
  const [currentPromptId, setCurrentPromptId] = useState<string | null>(null);
  const [currentVersion, setCurrentVersion] = useState<number>(1);
  const [currentMode, setCurrentMode] = useState<'dev' | 'prod'>('dev');
  const [linkedTestcase, setLinkedTestcase] = useState<LinkedTestcase | null>(null);

  // The prompt's linked testcase, shown by name; a graph run replays it.
  const loadLinkedTestcase = useCallback(async (testcaseId: string | null | undefined) => {
    if (!testcaseId) {
      setLinkedTestcase(null);
      return;
    }
    setLinkedTestcase({ id: testcaseId, name: '' });
    try {
      const result = await api.get<any>(buildServerUrl(`/server/testcase/${testcaseId}`));
      if (result.success && result.testcase) {
        setLinkedTestcase({ id: testcaseId, name: result.testcase.testcase_name });
      }
    } catch {
      // Keep the id; the chip falls back to it.
    }
  }, []);
  const [isSaving, setIsSaving] = useState(false);
  const [isLoadingPrompts, setIsLoadingPrompts] = useState(false);

  const refreshPromptList = useCallback(async () => {
    setIsLoadingPrompts(true);
    try {
      const result = await api.get<any>(buildServerUrl('/server/testprompt/list'));
      if (result.success) {
        setSavedPrompts(result.test_prompts || []);
      }
    } catch (error) {
      console.error('[@useTestPromptPage] Failed to load prompts:', error);
    } finally {
      setIsLoadingPrompts(false);
    }
  }, []);

  // Load prompt list on mount
  useEffect(() => {
    refreshPromptList();
  }, [refreshPromptList]);

  const handleSave = useCallback(async () => {
    if (!formState.name.trim()) {
      showSnackbar('Please enter a name', 'error');
      return;
    }

    setIsSaving(true);
    try {
      const payload: any = {
        name: formState.name,
        prompt: formState.prompt,
        acceptance_criteria: formState.acceptanceCriteria,
        userinterface_name: userinterfaceName,
        target_screen_node_id: formState.targetScreenNodeId || '',
        target_screen_label: formState.targetScreenLabel || '',
      };

      if (currentPromptId) {
        payload.id = currentPromptId;
      }

      const result = await api.post<any>(buildServerUrl('/server/testprompt/save'), payload);
      if (result.success) {
        const saved = result.test_prompt;
        setCurrentPromptId(saved.id);
        setCurrentVersion(saved.version);
        setCurrentMode(saved.mode);
        // Capture current form values as the new clean baseline.
        setSavedSnapshot({
          name: formState.name,
          targetScreenNodeId: formState.targetScreenNodeId,
          targetScreenLabel: formState.targetScreenLabel,
          prompt: formState.prompt,
          acceptanceCriteria: formState.acceptanceCriteria,
        });
        showSnackbar('Saved', 'success');
        await refreshPromptList();
      } else {
        showSnackbar(result.message || 'Save failed', 'error');
      }
    } catch (error) {
      showSnackbar('Save failed', 'error');
    } finally {
      setIsSaving(false);
    }
  }, [formState, userinterfaceName, currentPromptId, showSnackbar, refreshPromptList]);

  const handleLoad = useCallback(async (promptId: string) => {
    try {
      const result = await api.get<any>(buildServerUrl(`/server/testprompt/${promptId}`));
      if (result.success && result.test_prompt) {
        const p = result.test_prompt;
        const loaded: TestPromptFormState = {
          name: p.name,
          targetScreenNodeId: p.target_screen_node_id || '',
          targetScreenLabel: p.target_screen_label || '',
          prompt: p.prompt,
          acceptanceCriteria: p.acceptance_criteria,
        };
        setFormState(loaded);
        setSavedSnapshot(loaded);
        setCurrentPromptId(p.id);
        setCurrentVersion(p.version);
        setCurrentMode(p.mode);
        loadLinkedTestcase(p.testcase_id);

        // Auto-select device + interface for this prompt
        if (p.userinterface_name) {
          setUserinterfaceName(p.userinterface_name);
          loadTreeForInterface(p.userinterface_name);
          // Queue device selection — effect will pick up when hosts are available
          setPendingUIName(p.userinterface_name);
        }

        // Load executions for this prompt
        const execResult = await api.get<any>(buildServerUrl(`/server/testprompt/${promptId}/executions`));
        if (execResult.success) {
          setExecutions((execResult.executions || []).map((e: any) => ({
            id: e.id,
            executionId: e.id,
            testPromptId: e.test_prompt_id,
            mode: e.run_mode,
            status: e.status,
            steps: [],
            reportUrl: e.report_url,
            logsUrl: e.logs_url,
            humanFeedback: e.human_feedback,
            scriptResultId: e.script_result_id,
            executionTimeMs: e.execution_time_ms,
            startedAt: e.created_at ? new Date(e.created_at).getTime() : undefined,
            completedAt: e.execution_time_ms ? (new Date(e.created_at).getTime() + e.execution_time_ms) : undefined,
            // Version, inputs, verdict… as recorded for the run (none for runs before 20261001i).
            ...runDetailsFields(e),
          } as any)));
        }

        showSnackbar(`Loaded "${p.name}" v${p.version}`, 'info');
      }
    } catch (error) {
      showSnackbar('Failed to load prompt', 'error');
    }
  }, [showSnackbar, loadTreeForInterface, loadLinkedTestcase]);

  const handleDelete = useCallback(async (promptId: string) => {
    try {
      const result = await api.delete<any>(buildServerUrl(`/server/testprompt/${promptId}`));
      if (result.success) {
        if (currentPromptId === promptId) {
          resetForm();
        }
        showSnackbar('Deleted', 'success');
        await refreshPromptList();
      }
    } catch (error) {
      showSnackbar('Delete failed', 'error');
    }
  }, [currentPromptId, resetForm, showSnackbar, refreshPromptList]);

  // ==================== EXECUTION ====================
  const [executions, setExecutions] = useState<TestPromptExecution[]>([]);
  // Read by the socket handler, which is registered once.
  const executionsRef = useRef<TestPromptExecution[]>([]);
  executionsRef.current = executions;
  const [isExecuting, setIsExecuting] = useState(false);
  const [runMode, setRunMode] = useState<TestPromptRunMode>('explore');
  const { userId } = useUserSession();
  // start_time of the running.log already on the device when Run was clicked (null: none).
  // A log with any other start_time is this run's. Both values come from the host, so a
  // browser clock that is off cannot hide the overlay.
  const previousRunLogStartRef = useRef<string | null>(null);
  // Only polled while a run is in flight and a host is selected, so the cast never reaches a request.
  const { logData: polledRunningLog } = useRunningLog(
    selectedHost as Host,
    selectedDeviceId || undefined,
    isExecuting && Boolean(selectedHost),
  );
  const runningLogData =
    polledRunningLog && polledRunningLog.start_time !== previousRunLogStartRef.current
      ? polledRunningLog
      : null;
  // Ref to the fallback poll timer so the socket handler can cancel it
  // when testprompt_completed arrives (no need to keep polling).
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [liveEventsByExecutionId, setLiveEventsByExecutionId] = useState<
    Record<string, TestPromptLiveEvent[]>
  >({});

  // ==================== LIVE AGENT EVENTS ====================
  // Subscribe to the /agent socket namespace once and append every testprompt
  // event to the matching execution. Before this, the UI only saw the final
  // row from the polling endpoint — tool calls and errors were invisible.
  const socketCtx = useSocket();
  const { socket, connect, isConnected, registerEventHandler, unregisterEventHandler } = socketCtx;
  const joinedRoomsRef = useRef<Set<string>>(new Set());

  // Re-join testprompt rooms on socket reconnect (browser throttles
  // WebSockets in background tabs, causing disconnects after ~5min).
  useEffect(() => {
    if (!isConnected || !socket || joinedRoomsRef.current.size === 0) return;
    for (const room of joinedRoomsRef.current) {
      socket.emit('join_session', { session_id: room });
    }
  }, [isConnected, socket]);

  // Buffer incoming live events in a ref and flush to React state on a 200ms
  // debounce. Prior version called setState on every socket event, forcing a
  // page-wide re-render per event — fine at 5 events/sec but janky if we ever
  // stream finer-grained events (per token, per screenshot). Buffering caps
  // render rate at ~5/sec regardless of event volume while keeping terminal
  // events (testprompt_completed) immediate so the UI updates without lag.
  const pendingEventsRef = useRef<Record<string, TestPromptLiveEvent[]>>({});
  const flushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Monotonic counter for assigning stable React keys to live events so the
  // log list doesn't re-mount every row on each append.
  const eventIdCounterRef = useRef(0);

  const flushPendingEvents = useCallback(() => {
    const pending = pendingEventsRef.current;
    pendingEventsRef.current = {};
    if (flushTimerRef.current) {
      clearTimeout(flushTimerRef.current);
      flushTimerRef.current = null;
    }
    const execIds = Object.keys(pending);
    if (execIds.length === 0) return;
    setLiveEventsByExecutionId(prev => {
      const next = { ...prev };
      for (const execId of execIds) {
        const existing = next[execId] || [];
        next[execId] = [...existing, ...pending[execId]].slice(-200);
      }
      return next;
    });
  }, []);

  useEffect(() => {
    connect();
  }, [connect]);

  useEffect(() => {
    const handlerId = 'testprompt-live';
    registerEventHandler(handlerId, (event: any) => {
      const execId = event?.execution_id;
      if (!execId) return;
      if (event.agent !== 'TestPrompt') return;
      eventIdCounterRef.current += 1;
      const live: TestPromptLiveEvent = {
        id: `${execId}-${eventIdCounterRef.current}`,
        type: event.type,
        content: String(event.content ?? ''),
        toolName: event.tool_name,
        toolParams: event.tool_params,
        stepNumber: event.step_number,
        timestamp: event.timestamp || new Date().toISOString(),
      };
      const bucket = pendingEventsRef.current[execId] || [];
      bucket.push(live);
      pendingEventsRef.current[execId] = bucket;

      if (event.type === 'testprompt_completed') {
        // Terminal event: flush buffered events AND patch the execution row
        // immediately. Cancel the fallback poll — socket delivered first.
        flushPendingEvents();
        if (pollTimerRef.current) {
          clearInterval(pollTimerRef.current);
          pollTimerRef.current = null;
        }
        const passed = event.status === 'passed';
        setExecutions(prev => prev.map(e =>
          e.executionId === execId
            ? {
                ...e,
                status: (event.status as TestPromptExecution['status']) || e.status,
                reportUrl: event.report_url ?? e.reportUrl,
                logsUrl: event.logs_url ?? e.logsUrl,
                executionTimeMs: event.execution_time_ms ?? e.executionTimeMs,
                completedAt: Date.now(),
              }
            : e
        ));
        const finished = executionsRef.current.find(e => e.executionId === execId);
        if (finished?.testPromptId) {
          // This run, and for an Auto follow-up the failed run it follows (its outcome is now set).
          for (const id of [execId, finished.autoFrom, finished.retryOf]) {
            if (!id) continue;
            fetchExecutionRow(finished.testPromptId, id).then(row => {
              if (row) setExecutions(prev => prev.map(e => e.executionId === id ? { ...e, ...runDetailsFields(row) } : e));
            });
          }
        }
        // Auto mode: the failed run started a follow-up (exploration or one retry) — keep going.
        if (event.follow_up_execution_id && finished) {
          followUpRef.current(finished, event.follow_up_execution_id, event.follow_up_mode);
          return;
        }
        setIsExecuting(false);
        showSnackbar(passed ? 'Test prompt passed' : 'Test prompt failed', passed ? 'success' : 'error');
        return;
      }

      if (!flushTimerRef.current) {
        flushTimerRef.current = setTimeout(flushPendingEvents, 200);
      }
    });
    return () => {
      unregisterEventHandler(handlerId);
      if (flushTimerRef.current) {
        clearTimeout(flushTimerRef.current);
        flushTimerRef.current = null;
      }
    };
  }, [registerEventHandler, unregisterEventHandler, flushPendingEvents]);

  const joinExecutionRoom = useCallback((executionId: string) => {
    if (!socket || !executionId) return;
    const room = `testprompt:${executionId}`;
    if (joinedRoomsRef.current.has(room)) return;
    socket.emit('join_session', { session_id: room });
    joinedRoomsRef.current.add(room);
  }, [socket]);

  // Auto mode follow-up: add its card, join its room, and poll it slowly in case the socket
  // misses its end (the socket handler is registered once, so it calls this through a ref).
  const followUpRef = useRef<(parent: TestPromptExecution, followUpId: string, mode?: string) => void>(() => {});
  followUpRef.current = (parent, followUpId, mode) => {
    const followUpMode: TestPromptRunMode = mode === 'graph' ? 'graph' : 'explore';
    setExecutions(prev => [{
      id: followUpId,
      executionId: followUpId,
      testPromptId: parent.testPromptId,
      mode: followUpMode,
      status: 'running',
      steps: [],
      auto: true,
      autoFrom: followUpMode === 'explore' ? parent.executionId : undefined,
      retryOf: followUpMode === 'graph' ? parent.executionId : undefined,
      version: parent.version,
      edited: parent.edited,
      ranPrompt: parent.ranPrompt,
      ranCriteria: parent.ranCriteria,
      ranTarget: parent.ranTarget,
      hostName: parent.hostName,
      deviceId: parent.deviceId,
      startedAt: Date.now(),
    }, ...prev]);
    joinExecutionRoom(followUpId);
    showSnackbar(`Auto: the saved test failed — ${followUpMode === 'explore' ? 'exploring' : 'retrying once'}`, 'info');
    let polls = 0;
    const timer = setInterval(async () => {
      polls++;
      const row = await fetchExecutionRow(parent.testPromptId, followUpId);
      const current = executionsRef.current.find(e => e.executionId === followUpId);
      if ((row && row.status !== 'running') || polls >= 180) {
        clearInterval(timer);
        if (row && current?.status === 'running') {
          setExecutions(prev => prev.map(e => e.executionId === followUpId
            ? { ...e, status: row.status, reportUrl: row.report_url, logsUrl: row.logs_url,
                executionTimeMs: row.execution_time_ms, completedAt: Date.now(), ...runDetailsFields(row) }
            : e));
          setIsExecuting(false);
        }
      }
    }, 10000);
  };

  const handleRunTestPrompt = useCallback(async (options?: { regenerate?: boolean }) => {
    if (!isFormValid || !selectedHost || !selectedDeviceId) return;
    const regenerate = Boolean(options?.regenerate);

    // Need a prompt row to attach the execution to. If none exists yet,
    // auto-create one so the execution has a parent — but only the first time.
    // On subsequent runs we never auto-save: dirty edits are sent as overrides
    // so the user can iterate without bumping the saved version.
    let promptIdToExecute = currentPromptId;
    if (!promptIdToExecute) {
      const promptName = formState.name.trim() || `Prompt ${new Date().toLocaleTimeString()}`;
      const snapshotForCreate: TestPromptFormState = {
        name: promptName,
        targetScreenNodeId: formState.targetScreenNodeId || '',
        targetScreenLabel: formState.targetScreenLabel || '',
        prompt: formState.prompt,
        acceptanceCriteria: formState.acceptanceCriteria,
      };
      if (!formState.name.trim()) {
        updateFormField('name', promptName);
      }
      const payload = {
        name: promptName,
        prompt: formState.prompt,
        acceptance_criteria: formState.acceptanceCriteria,
        userinterface_name: userinterfaceName,
        target_screen_node_id: formState.targetScreenNodeId || '',
        target_screen_label: formState.targetScreenLabel || '',
      };

      try {
        const saveResult = await api.post<any>(buildServerUrl('/server/testprompt/save'), payload);
        if (saveResult.success) {
          promptIdToExecute = saveResult.test_prompt.id;
          setCurrentPromptId(promptIdToExecute);
          setCurrentVersion(saveResult.test_prompt.version);
          setSavedSnapshot(snapshotForCreate);
          await refreshPromptList();
        } else {
          showSnackbar(saveResult.message || 'Failed to save before execution', 'error');
          return;
        }
      } catch (error) {
        showSnackbar(error instanceof Error ? error.message : 'Failed to save before execution', 'error');
        return;
      }
    }

    previousRunLogStartRef.current = null;
    if (selectedHost && selectedDeviceId) {
      try {
        const res = await fetch(`${buildRunningLogUrl(selectedHost, selectedDeviceId)}?t=${Date.now()}`);
        if (res.ok) previousRunLogStartRef.current = (await res.json())?.start_time ?? null;
      } catch {
        // No log yet (404) or unreadable: every log seen during the run is this run's.
      }
    }
    setIsExecuting(true);

    const effectiveMode = runMode === 'auto' ? (linkedTestcase ? 'graph' : 'explore') : runMode;
    const replaysLinked = effectiveMode === 'graph' && Boolean(linkedTestcase) && !regenerate;
    const steps: TestPromptStep[] = [];
    if (effectiveMode === 'graph') {
      steps.push({
        phase: 'graph',
        label: replaysLinked ? `Run testcase ${linkedTestcase?.name || ''}`.trim() : 'Generate the graph and run it',
        status: 'pending',
      });
    } else {
      steps.push({ phase: 'go_home', label: 'Go to Home', status: 'pending' });
      if (formState.targetScreenLabel) {
        steps.push({ phase: 'navigate', label: `Navigate to ${formState.targetScreenLabel}`, status: 'pending' });
      }
      steps.push({ phase: 'action', label: 'Execute prompt actions', status: 'pending' });
      steps.push({ phase: 'criteria_check', label: 'Evaluate acceptance criteria', status: 'pending' });
    }

    const execution: TestPromptExecution = {
      id: `tp_${Date.now()}`,
      executionId: `tp_${Date.now()}`,
      testPromptId: promptIdToExecute || '',
      // Auto replays the linked testcase (a graph run), or explores when none is linked.
      mode: effectiveMode,
      auto: runMode === 'auto' || undefined,
      status: 'queued',
      steps,
      version: currentVersion ?? undefined,
      edited: isDirty,
      ranPrompt: formState.prompt,
      ranCriteria: formState.acceptanceCriteria,
      ranTarget: formState.targetScreenLabel || undefined,
      ranUserinterface: userinterfaceName || undefined,
      hostName: selectedHost?.host_name,
      deviceId: selectedDeviceId || undefined,
      startedAt: Date.now(),
    };

    setExecutions(prev => [execution, ...prev]);

    // Call backend execute endpoint
    try {
      // Always send the in-memory form values as overrides so unsaved edits
      // execute as-typed rather than the last persisted version.
      const result = await api.post<any>(buildServerUrl('/server/testprompt/execute'), {
        test_prompt_id: promptIdToExecute,
        host_name: selectedHost.host_name,
        device_id: selectedDeviceId,
        prompt: formState.prompt,
        acceptance_criteria: formState.acceptanceCriteria,
        target_screen_node_id: formState.targetScreenNodeId || '',
        target_screen_label: formState.targetScreenLabel || '',
        mode: runMode,
        regenerate,
        // The run goes under this page's Take Control: same user, same session.
        user_id: userId,
        session_id: TEST_PROMPT_SESSION_ID,
      });

      if (result.success) {
        const backendExecId = result.execution_id;
        const promptId = promptIdToExecute;

        // Update execution with backend ID (and, for a graph run, the graph it generated)
        setExecutions(prev => prev.map(e =>
          e.executionId === execution.executionId
            ? {
                ...e,
                id: backendExecId,
                executionId: backendExecId,
                status: 'running' as const,
                generatedGraph: result.generated_graph || undefined,
                analysis: result.analysis || undefined,
                steps: e.steps.map((s, i) => i === 0 ? { ...s, status: 'running' as const } : s),
              }
            : e
        ));

        // Join the live-event room so socket messages for this run reach us.
        joinExecutionRoom(backendExecId);

        // Fallback poll — socket should deliver testprompt_completed first,
        // but if the socket disconnects mid-run this catches the result from DB.
        // Reduced frequency (10s) since socket is the primary path.
        // Poll until the run row has a final status: the server decides when a run ends (an
        // exploration is bounded by its skill's time limit, a graph run by the executor). The page
        // used to stop at 180 s and show "Execution timed out" while the run went on and passed.
        const pollInterval = 10000;
        const maxPolls = 720; // 2 h: then only stop polling, never mark the run as failed
        let polls = 0;
        if (pollTimerRef.current) clearInterval(pollTimerRef.current);
        const pollTimer = setInterval(async () => {
          polls++;
          try {
            const execResult = await api.get<any>(buildServerUrl(`/server/testprompt/${promptId}/executions`));
            const exec = (execResult.executions || []).find((e: any) => e.id === backendExecId);
            if (exec && exec.status !== 'running') {
              clearInterval(pollTimer);
              pollTimerRef.current = null;
              const passed = exec.status === 'passed';
              setExecutions(prev => prev.map(e =>
                e.executionId === backendExecId
                  ? {
                      ...e,
                      status: exec.status as TestPromptExecution['status'],
                      completedAt: Date.now(),
                      reportUrl: exec.report_url,
                      logsUrl: exec.logs_url,
                      scriptResultId: exec.script_result_id,
                      executionTimeMs: exec.execution_time_ms,
                      steps: e.steps.map(s => ({ ...s, status: passed ? 'passed' as const : 'failed' as const, duration: Math.floor((exec.execution_time_ms || 3000) / e.steps.length) })),
                      ...runDetailsFields(exec),
                    }
                  : e
              ));
              setIsExecuting(false);
              showSnackbar(passed ? 'Test prompt passed' : 'Test prompt failed', passed ? 'success' : 'error');
            }
          } catch {
            // Ignore poll errors
          }
          if (polls >= maxPolls) {
            clearInterval(pollTimer);
            pollTimerRef.current = null;
          }
        }, pollInterval);
        pollTimerRef.current = pollTimer;
      } else {
        setExecutions(prev => prev.map(e =>
          e.executionId === execution.executionId
            ? { ...e, id: result.execution_id || e.id, status: 'error' as const, error: result.message }
            : e
        ));
        setIsExecuting(false);
        showSnackbar(result.message || 'Execution failed', 'error');
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to start execution';
      setExecutions(prev => prev.map(e =>
        e.executionId === execution.executionId
          ? { ...e, status: 'error' as const, error: message }
          : e
      ));
      setIsExecuting(false);
      showSnackbar(message, 'error');
    }
  }, [isFormValid, selectedHost, selectedDeviceId, currentPromptId, formState, userinterfaceName, updateFormField, showSnackbar, refreshPromptList, runMode, linkedTestcase, userId, isDirty, currentVersion]);

  // ==================== LINKED TESTCASE ====================
  // Save a graph as a testcase linked to the prompt (a graph run's generated graph, or an
  // exploration's proposal), then mark the execution card as saved.
  const saveGraphAsTestcase = useCallback(async (executionId: string, graph: any, analysis?: string): Promise<boolean> => {
    if (!currentPromptId) return false;
    try {
      const result = await api.post<any>(buildServerUrl(`/server/testprompt/${currentPromptId}/save-testcase`), {
        graph,
        analysis,
        execution_id: executionId,
        testcase_name: formState.name.trim() ? `prompt_${formState.name.trim().replace(/[\s/]+/g, '_')}` : undefined,
        created_by: userId,
      });
      if (!result.success) {
        showSnackbar(result.message || 'Save as testcase failed', 'error');
        return false;
      }
      setExecutions(prev => prev.map(e => e.executionId === executionId ? { ...e, savedTestcaseId: result.testcase_id } : e));
      await loadLinkedTestcase(result.testcase_id);
      showSnackbar('Saved as testcase — Run graph now replays it', 'success');
      return true;
    } catch (error) {
      showSnackbar(error instanceof Error ? error.message : 'Save as testcase failed', 'error');
      return false;
    }
  }, [currentPromptId, formState.name, userId, loadLinkedTestcase, showSnackbar]);

  const handleSaveAsTestcase = useCallback(async (executionId: string) => {
    const exec = executions.find(e => e.executionId === executionId);
    if (!exec?.generatedGraph) return;
    await saveGraphAsTestcase(executionId, exec.generatedGraph, exec.analysis);
  }, [executions, saveGraphAsTestcase]);

  // ==================== EXPLORE → TESTCASE (TASK-36 §3) ====================
  const [explorePreview, setExplorePreview] = useState<{ executionId: string; proposal: AIGraphEditProposal } | null>(null);
  const [buildingFromExploreId, setBuildingFromExploreId] = useState<string | null>(null);

  const handleProposeFromExplore = useCallback(async (executionId: string) => {
    setBuildingFromExploreId(executionId);
    setExplorePreview(null);
    try {
      const result = await api.post<any>(buildServerUrl(`/server/testprompt/execution/${executionId}/to-graph`), {});
      if (result?.success && result.graph) {
        setExplorePreview({
          executionId,
          proposal: {
            graph: result.graph,
            analysis: result.analysis || '',
            stepsBefore: result.steps_before || [],
            stepsAfter: result.steps_after || [],
          },
        });
      } else {
        showSnackbar(result?.message || result?.error || 'Could not build a testcase from this run', 'error');
      }
    } catch (error) {
      showSnackbar(error instanceof Error ? error.message : 'Could not build a testcase from this run', 'error');
    } finally {
      setBuildingFromExploreId(null);
    }
  }, [showSnackbar]);

  const handleApplyExplorePreview = useCallback(async () => {
    if (!explorePreview) return;
    const saved = await saveGraphAsTestcase(explorePreview.executionId, explorePreview.proposal.graph, explorePreview.proposal.analysis);
    if (saved) setExplorePreview(null);
  }, [explorePreview, saveGraphAsTestcase]);

  const handleCancelExplorePreview = useCallback(() => setExplorePreview(null), []);

  const handleUnlinkTestcase = useCallback(async () => {
    if (!currentPromptId) return;
    try {
      const result = await api.post<any>(buildServerUrl(`/server/testprompt/${currentPromptId}/unlink-testcase`), {});
      if (result.success) {
        setLinkedTestcase(null);
        showSnackbar('Testcase unlinked — the next graph run generates a new graph', 'info');
      } else {
        showSnackbar(result.message || 'Unlink failed', 'error');
      }
    } catch (error) {
      showSnackbar(error instanceof Error ? error.message : 'Unlink failed', 'error');
    }
  }, [currentPromptId, showSnackbar]);

  // ==================== FEEDBACK & VERSIONING ====================
  const handleSubmitFeedback = useCallback(async (executionId: string, feedback: string) => {
    try {
      const result = await api.post<any>(
        buildServerUrl(`/server/testprompt/execution/${executionId}/feedback`),
        { feedback }
      );
      if (result.success) {
        setExecutions(prev => prev.map(e =>
          e.executionId === executionId || e.id === executionId
            ? { ...e, humanFeedback: feedback }
            : e
        ));
        showSnackbar('Feedback saved', 'success');
      }
    } catch (error) {
      showSnackbar('Failed to save feedback', 'error');
    }
  }, [showSnackbar]);

  const handlePromote = useCallback(async () => {
    if (!currentPromptId) return;
    try {
      const result = await api.post<any>(buildServerUrl(`/server/testprompt/${currentPromptId}/promote`), {});
      if (result.success) {
        setCurrentMode('prod');
        showSnackbar('Promoted to production', 'success');
        await refreshPromptList();
      }
    } catch (error) {
      showSnackbar('Failed to promote', 'error');
    }
  }, [currentPromptId, showSnackbar, refreshPromptList]);

  return {
    selectedHost,
    selectedDeviceId,
    isControlActive,
    isControlLoading,
    isRemotePanelOpen,
    availableHosts,
    handleDeviceSelect,
    handleDeviceControl,
    handleToggleRemotePanel,
    isDeviceLocked,
    compatibleInterfaceNames,
    userinterfaceName,
    setUserinterfaceName: handleSetUserinterfaceName,
    navNodes,
    isLoadingTree,
    currentTreeId,
    formState,
    updateFormField,
    resetForm,
    isFormValid,
    isDirty,
    savedPrompts,
    currentPromptId,
    currentVersion,
    currentMode,
    isSaving,
    isLoadingPrompts,
    handleSave,
    handleLoad,
    handleDelete,
    refreshPromptList,
    executions,
    isExecuting,
    runMode,
    setRunMode,
    handleRunTestPrompt,
    liveEventsByExecutionId,
    runningLogData,
    linkedTestcase,
    handleSaveAsTestcase,
    explorePreview,
    buildingFromExploreId,
    handleProposeFromExplore,
    handleApplyExplorePreview,
    handleCancelExplorePreview,
    handleUnlinkTestcase,
    handleSubmitFeedback,
    handlePromote,
    snackbar,
    showSnackbar,
    closeSnackbar,
  };
}
