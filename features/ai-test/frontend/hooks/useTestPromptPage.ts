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
import { buildServerUrl } from '../../../../frontend/src/utils/buildUrlUtils';
import {
  TestPromptFormState,
  TestPromptExecution,
  TestPromptStep,
  TestPrompt,
  TestPromptLiveEvent,
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
  handleRunTestPrompt: () => void;
  liveEventsByExecutionId: Record<string, TestPromptLiveEvent[]>;

  // Feedback & Versioning
  handleSubmitFeedback: (executionId: string, feedback: string) => Promise<void>;
  handlePromote: () => Promise<void>;

  // Snackbar
  snackbar: { open: boolean; message: string; severity: 'success' | 'error' | 'info' };
  showSnackbar: (message: string, severity?: 'success' | 'error' | 'info') => void;
  closeSnackbar: () => void;
}

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
    sessionId: 'test-prompt-session',
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
    const loadCompatibleInterfaces = async () => {
      if (!selectedDeviceId || !selectedHost) {
        setCompatibleInterfaceNames([]);
        setUserinterfaceName('');
        setNavNodes([]);
        setCurrentTreeId(null);
        return;
      }

      try {
        const selectedDevice = selectedHost.devices?.find((d: any) => d.device_id === selectedDeviceId);
        if (!selectedDevice) return;

        const interfaces = await getAllUserInterfaces();
        const compatibleInterfaces = filterCompatibleInterfaces(interfaces, selectedDevice);
        const names = compatibleInterfaces.map((ui: any) => ui.name);

        setCompatibleInterfaceNames(names);

        const activeName = names.includes(userinterfaceName) ? userinterfaceName : names[0] || '';
        if (activeName !== userinterfaceName) {
          setUserinterfaceName(activeName);
        }
        if (activeName) {
          await loadTreeForInterface(activeName);
        }
      } catch (error) {
        console.error('[@useTestPromptPage] Failed to load compatible interfaces:', error);
      }
    };

    loadCompatibleInterfaces();
  }, [selectedDeviceId, selectedHost, getAllUserInterfaces, userinterfaceName, loadTreeForInterface]);

  const handleSetUserinterfaceName = useCallback((name: string) => {
    setUserinterfaceName(name);
    loadTreeForInterface(name);
  }, [loadTreeForInterface]);

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
  const [formState, setFormState] = useState<TestPromptFormState>(DEFAULT_TEST_PROMPT_FORM);
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
  }, []);

  const isDirty = (
    formState.name !== savedSnapshot.name ||
    formState.prompt !== savedSnapshot.prompt ||
    formState.acceptanceCriteria !== savedSnapshot.acceptanceCriteria ||
    formState.targetScreenNodeId !== savedSnapshot.targetScreenNodeId ||
    formState.targetScreenLabel !== savedSnapshot.targetScreenLabel
  );

  useEffect(() => {
    updateFormField('targetScreenNodeId', '');
    updateFormField('targetScreenLabel', '');
  }, [userinterfaceName, updateFormField]);

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
            status: e.status,
            steps: [],
            reportUrl: e.report_url,
            logsUrl: e.logs_url,
            humanFeedback: e.human_feedback,
            scriptResultId: e.script_result_id,
            executionTimeMs: e.execution_time_ms,
            startedAt: e.created_at ? new Date(e.created_at).getTime() : undefined,
            completedAt: e.execution_time_ms ? (new Date(e.created_at).getTime() + e.execution_time_ms) : undefined,
            version: p.version,
          } as any)));
        }

        showSnackbar(`Loaded "${p.name}" v${p.version}`, 'info');
      }
    } catch (error) {
      showSnackbar('Failed to load prompt', 'error');
    }
  }, [showSnackbar, loadTreeForInterface]);

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
  const [isExecuting, setIsExecuting] = useState(false);
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

  const handleRunTestPrompt = useCallback(async () => {
    if (!isFormValid || !selectedHost || !selectedDeviceId) return;

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
          showSnackbar('Failed to save before execution', 'error');
          return;
        }
      } catch {
        showSnackbar('Failed to save before execution', 'error');
        return;
      }
    }

    setIsExecuting(true);

    const steps: TestPromptStep[] = [
      { phase: 'go_home', label: 'Go to Home', status: 'pending' },
    ];
    if (formState.targetScreenLabel) {
      steps.push({ phase: 'navigate', label: `Navigate to ${formState.targetScreenLabel}`, status: 'pending' });
    }
    steps.push({ phase: 'action', label: 'Execute prompt actions', status: 'pending' });
    steps.push({ phase: 'criteria_check', label: 'Evaluate acceptance criteria', status: 'pending' });

    const execution: TestPromptExecution = {
      id: `tp_${Date.now()}`,
      executionId: `tp_${Date.now()}`,
      testPromptId: promptIdToExecute || '',
      status: 'queued',
      steps,
      version: currentVersion,
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
      });

      if (result.success) {
        const backendExecId = result.execution_id;
        const promptId = promptIdToExecute;

        // Update execution with backend ID
        setExecutions(prev => prev.map(e =>
          e.executionId === execution.executionId
            ? { ...e, id: backendExecId, executionId: backendExecId, status: 'running' as const, steps: e.steps.map((s, i) => i === 0 ? { ...s, status: 'running' as const } : s) }
            : e
        ));

        // Join the live-event room so socket messages for this run reach us.
        joinExecutionRoom(backendExecId);

        // Fallback poll — socket should deliver testprompt_completed first,
        // but if the socket disconnects mid-run this catches the result from DB.
        // Reduced frequency (10s) since socket is the primary path.
        const pollInterval = 10000;
        const maxPolls = 18; // 3 min max
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
                      error: exec.error_msg,
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
            setExecutions(prev => prev.map(e =>
              e.executionId === backendExecId
                ? { ...e, status: 'error' as const, error: 'Execution timed out' }
                : e
            ));
            setIsExecuting(false);
            showSnackbar('Execution timed out', 'error');
          }
        }, pollInterval);
        pollTimerRef.current = pollTimer;
      } else {
        setExecutions(prev => prev.map(e =>
          e.executionId === execution.executionId
            ? { ...e, status: 'error' as const, error: result.message }
            : e
        ));
        setIsExecuting(false);
        showSnackbar(result.message || 'Execution failed', 'error');
      }
    } catch (error) {
      setExecutions(prev => prev.map(e =>
        e.executionId === execution.executionId
          ? { ...e, status: 'error' as const, error: 'Failed to start execution' }
          : e
      ));
      setIsExecuting(false);
      showSnackbar('Execution failed', 'error');
    }
  }, [isFormValid, selectedHost, selectedDeviceId, currentPromptId, formState, userinterfaceName, updateFormField, showSnackbar, refreshPromptList]);

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
    handleRunTestPrompt,
    liveEventsByExecutionId,
    handleSubmitFeedback,
    handlePromote,
    snackbar,
    showSnackbar,
    closeSnackbar,
  };
}
