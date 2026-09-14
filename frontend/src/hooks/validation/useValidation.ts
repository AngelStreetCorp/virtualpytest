/**
 * Validation Hook - Using useScript
 *
 * This hook provides state management for validation operations using the existing useScript infrastructure.
 */

import { useState, useCallback, useEffect } from 'react';

import { ValidationPreviewData } from '../../types/features/Validation_Types';
import { useHostControl } from '../useHostManager';
import { useScript } from '../script/useScript';
import { useNavigation } from '../../contexts/navigation/NavigationContext';
import { buildServerUrlWithParams } from '../../utils/buildUrlUtils';
import { api } from '../../utils/apiClient';
import { extractR2Path, getR2Url, isCloudflareR2Url } from '../../utils/infrastructure/cloudflareUtils';

export interface ValidationStepEvent {
  from_node: string;
  to_node: string;
  success: boolean;
  error?: string | null;
}

// Simplified shared state store for validation - only track report URLs
const validationStore: Record<
  string,
  {
    isValidating: boolean;
    lastReportUrl: string | null; // Store last report URL for "View Last Results"
    preview: ValidationPreviewData | null;
    isLoadingPreview: boolean;
    validationError: string | null;
    validationResult: { success: boolean; duration: number; reportUrl?: string } | null;
    startTime: number | null;
    progress: number | null;
    currentMessage: string | null;
    currentStep: number | null;
    totalSteps: number | null;
    recentSteps: ValidationStepEvent[];
    isRecovering: boolean;
    listeners: Set<() => void>;
  }
> = {};

// Load persisted report URL from localStorage
const loadPersistedReportUrl = (treeId: string): string | null => {
  try {
    const key = `validation_report_url_${treeId}`;
    return localStorage.getItem(key);
  } catch (error) {
    console.warn('Failed to load persisted report URL:', error);
    return null;
  }
};

// Save report URL to localStorage for "View Last Results" functionality
const saveReportUrl = (treeId: string, reportUrl: string) => {
  try {
    const key = `validation_report_url_${treeId}`;
    localStorage.setItem(key, reportUrl);
  } catch (error) {
    console.warn('Failed to save report URL:', error);
  }
};

// Pending-task persistence: lets the UI recover the last validation result
// when the tab was backgrounded (and missed the socket completion event) or
// after a full page refresh while a run is still in flight.
interface PendingTask {
  task_id: string;
  host_name: string;
  device_id: string;
  started_at: number;
}

const savePendingTask = (treeId: string, info: PendingTask) => {
  try {
    localStorage.setItem(`validation_pending_task_${treeId}`, JSON.stringify(info));
  } catch (error) {
    console.warn('Failed to save pending task:', error);
  }
};

const loadPendingTask = (treeId: string): PendingTask | null => {
  try {
    const raw = localStorage.getItem(`validation_pending_task_${treeId}`);
    return raw ? (JSON.parse(raw) as PendingTask) : null;
  } catch {
    return null;
  }
};

const clearPendingTask = (treeId: string) => {
  try {
    localStorage.removeItem(`validation_pending_task_${treeId}`);
  } catch {
    // best-effort
  }
};

const getValidationState = (treeId: string) => {
  if (!validationStore[treeId]) {
    const persistedReportUrl = loadPersistedReportUrl(treeId);
    validationStore[treeId] = {
      isValidating: false,
      lastReportUrl: persistedReportUrl,
      preview: null,
      isLoadingPreview: false,
      validationError: null,
      validationResult: null,
      startTime: null,
      progress: null,
      currentMessage: null,
      currentStep: null,
      totalSteps: null,
      recentSteps: [],
      isRecovering: false,
      listeners: new Set(),
    };
  }
  return validationStore[treeId];
};

const updateValidationState = (
  treeId: string,
  updates: Partial<(typeof validationStore)[string]>,
) => {
  const state = getValidationState(treeId);
  Object.assign(state, updates);
  // Notify all listeners
  state.listeners.forEach((listener) => listener());
};

export const useValidation = (treeId: string, providedHost?: any, providedDeviceId?: string | null) => {
  const { selectedHost: contextHost, selectedDeviceId: contextDeviceId } = useHostControl();
  const { executeScript, waitForTask } = useScript();
  const { treeName, currentTreeName } = useNavigation();
  
  // Use provided values if available, otherwise fall back to context
  const selectedHost = providedHost || contextHost;
  const selectedDeviceId = providedDeviceId || contextDeviceId;
  const [, forceUpdate] = useState({});

  // Force re-render when state changes
  const rerender = useCallback(() => {
    forceUpdate({});
  }, []);

  // Subscribe to state changes
  useEffect(() => {
    const state = getValidationState(treeId);
    state.listeners.add(rerender);

    return () => {
      state.listeners.delete(rerender);
    };
  }, [treeId, rerender]);

  const state = getValidationState(treeId);

  /**
   * Recover a previously-started validation whose terminal event was missed
   * — e.g. tab was backgrounded and the socket was throttled, or the page
   * was refreshed while a run is still in flight. Reads the pending task_id
   * from localStorage and either polls the status endpoint (terminal cases)
   * or re-attaches via waitForTask (still running). Idempotent — guarded by
   * isRecovering so concurrent mounts don't fan out duplicate watchers.
   */
  const recoverPendingTask = useCallback(async () => {
    const current = getValidationState(treeId);
    if (current.isRecovering || current.isValidating) return;

    const pending = loadPendingTask(treeId);
    if (!pending?.task_id) return;

    updateValidationState(treeId, { isRecovering: true });

    try {
      const statusResponse = await api.get(buildServerUrlWithParams(`/server/script/status/${pending.task_id}`, {}));
      const task = (statusResponse as any)?.task;
      const status = String(task?.status || '').toLowerCase();

      const finalize = (result: { report_url?: string; success?: boolean }) => {
        const success = !!result?.success;
        const reportUrl = result?.report_url || null;
        if (reportUrl) {
          saveReportUrl(treeId, reportUrl);
        }
        updateValidationState(treeId, {
          isValidating: false,
          isRecovering: false,
          startTime: null,
          progress: null,
          currentMessage: null,
          currentStep: null,
          totalSteps: null,
          recentSteps: [],
          lastReportUrl: reportUrl,
          validationResult: {
            success,
            duration: pending.started_at ? (Date.now() - pending.started_at) / 1000 : 0,
            reportUrl: reportUrl || undefined,
          },
        });
        clearPendingTask(treeId);
      };

      if (status === 'completed' || status === 'failed') {
        finalize(task?.result || {});
        return;
      }

      // Still running on the server — show the running dialog and re-attach
      // to socket+poll so the next terminal event is captured.
      updateValidationState(treeId, {
        isValidating: true,
        startTime: pending.started_at,
      });

      const result = await waitForTask(pending.task_id, pending.host_name);
      finalize({ report_url: result.report_url, success: result.script_success ?? result.success });
    } catch (error) {
      console.warn('[@hook:useValidation] recoverPendingTask failed:', error);
      updateValidationState(treeId, { isRecovering: false });
    }
  }, [treeId, waitForTask]);

  // Run recovery on mount and whenever the tab returns to visibility.
  useEffect(() => {
    recoverPendingTask();
    const onVisible = () => {
      if (document.visibilityState === 'visible') {
        recoverPendingTask();
      }
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [recoverPendingTask]);

  /**
   * Resolve a validation report URL to a signed URL when needed (private R2 buckets)
   */
  const resolveReportUrl = useCallback(async (reportUrl: string): Promise<string> => {
    const isHttpUrl = /^https?:\/\//i.test(reportUrl);

    // Non-R2 HTTP links can be used as-is
    if (isHttpUrl && !isCloudflareR2Url(reportUrl)) {
      return reportUrl;
    }

    // Normalize to R2 path for signing
    let path = reportUrl;
    if (isCloudflareR2Url(reportUrl)) {
      const extracted = extractR2Path(reportUrl);
      if (extracted) {
        path = extracted;
      }
    }

    return getR2Url(path);
  }, []);

  /**
   * Open validation report in new tab
   */
  const openValidationReport = useCallback(async (reportUrl: string) => {
    try {
      const resolvedUrl = await resolveReportUrl(reportUrl);
      console.log(`[@hook:useValidation] Opening validation report: ${resolvedUrl}`);
      window.open(resolvedUrl, '_blank');
    } catch (error) {
      console.error('[@hook:useValidation] Failed to open validation report:', error);
      updateValidationState(treeId, { validationError: 'Failed to open validation report' });
    }
  }, [resolveReportUrl, treeId]);

  /**
   * Load validation preview
   */
  const loadPreview = useCallback(async () => {
    if (!treeId || !selectedHost) return;

    updateValidationState(treeId, { isLoadingPreview: true });

    try {
      // Use centralized URL builder with params
      const url = buildServerUrlWithParams(
        `/server/validation/preview/${treeId}`,
        { host_name: selectedHost.host_name }
      );
      
      const result = await api.get(url);

      if (result.success) {
        updateValidationState(treeId, { preview: result });
      } else {
        updateValidationState(treeId, { validationError: result.error || 'Failed to load preview' });
      }
    } catch (error) {
      updateValidationState(treeId, {
        validationError: error instanceof Error ? error.message : 'Failed to load preview',
      });
    } finally {
      updateValidationState(treeId, { isLoadingPreview: false });
    }
  }, [treeId]);

  /**
   * Run validation using the existing useScript infrastructure
   */
  const runValidation = useCallback(
    async (selectedEdgeIds?: string[], subtreeRootNodeId?: string) => {
      // Preview is required only for whole-tree / edge-selection runs.
      // "Run Validation from here" bypasses the preview dialog.
      const previewRequired = !subtreeRootNodeId;
      if (
        !treeId ||
        !selectedHost ||
        !selectedDeviceId ||
        (previewRequired && !state.preview)
      ) {
        updateValidationState(treeId, {
          validationError: 'Tree ID, host, device, and preview data are required',
        });
        return;
      }

      updateValidationState(treeId, {
        isValidating: true,
        validationError: null,
        validationResult: null,
        startTime: Date.now(),
        progress: null,
        currentMessage: null,
        currentStep: null,
        totalSteps: null,
        recentSteps: [],
      });

      try {
        console.log(`[@hook:useValidation] Starting validation script for tree ${treeId}`);

        // Use the validation script with the existing useScript infrastructure
        const userinterface_name = treeName || currentTreeName || treeId;
        let parameters = `--userinterface ${userinterface_name} --host ${selectedHost.host_name} --device ${selectedDeviceId}`;

        // Add selected step numbers if provided (format: "1,2,3,...").
        // Only send --edges parameter when a selection was made; otherwise the
        // script validates the full sequence.
        if (selectedEdgeIds && selectedEdgeIds.length > 0) {
          const edgesParam = selectedEdgeIds.join(',');
          parameters += ` --edges "${edgesParam}"`;
          console.log(`[@hook:useValidation] Running validation with ${selectedEdgeIds.length} selected step(s)`);
        } else {
          console.log(`[@hook:useValidation] Running validation with ALL transitions (no selection)`);
        }

        // Subtree mode: validate only the linked child tree of the given entry node.
        if (subtreeRootNodeId) {
          parameters += ` --subtree-root ${subtreeRootNodeId}`;
          console.log(`[@hook:useValidation] Subtree mode — validating subtree of node ${subtreeRootNodeId}`);
        }

        const onProgress = (event: { progress?: number; message?: string; result?: any }) => {
          const stepInfo = event?.result?.step as ValidationStepEvent | undefined;
          const currentState = getValidationState(treeId);
          const nextRecent = stepInfo
            ? [...currentState.recentSteps, stepInfo].slice(-5)
            : currentState.recentSteps;

          updateValidationState(treeId, {
            progress: typeof event?.progress === 'number' ? event.progress : currentState.progress,
            currentMessage: event?.message ?? currentState.currentMessage,
            currentStep:
              typeof event?.result?.step_number === 'number'
                ? event.result.step_number
                : currentState.currentStep,
            totalSteps:
              typeof event?.result?.total_steps === 'number'
                ? event.result.total_steps
                : currentState.totalSteps,
            recentSteps: nextRecent,
          });
        };

        const onTaskStarted = (taskId: string) => {
          savePendingTask(treeId, {
            task_id: taskId,
            host_name: selectedHost.host_name,
            device_id: selectedDeviceId,
            started_at: Date.now(),
          });
        };

        const scriptResult = await executeScript(
          'validation',
          selectedHost.host_name,
          selectedDeviceId,
          parameters,
          undefined,
          undefined,
          onProgress,
          onTaskStarted,
        );

        console.log(`[@hook:useValidation] Validation script completed:`, scriptResult);

        // Calculate duration
        const duration = state.startTime ? (Date.now() - state.startTime) / 1000 : 0;
        
        // CRITICAL: Only use script_success (from SCRIPT_SUCCESS marker in stdout)
        // DO NOT fall back to overall success, as it includes non-validation failures like video capture
        const success = scriptResult.script_success ?? false;
        
        console.log(`[@hook:useValidation] Final success value (script_success only): ${success}`);

        // Save report URL for "View Last Results" functionality
        if (scriptResult.report_url) {
          saveReportUrl(treeId, scriptResult.report_url);
        }

        // Store validation result to show in dialog
        updateValidationState(treeId, {
          lastReportUrl: scriptResult.report_url || null,
          validationResult: {
            success,
            duration,
            reportUrl: scriptResult.report_url,
          },
        });

      } catch (error) {
        console.error('[@hook:useValidation] Validation error:', error);
        updateValidationState(treeId, {
          validationError: error instanceof Error ? error.message : 'Unknown validation error',
        });
      } finally {
        clearPendingTask(treeId);
        updateValidationState(treeId, {
          isValidating: false,
          startTime: null,
          progress: null,
          currentMessage: null,
          currentStep: null,
          totalSteps: null,
          recentSteps: [],
        });
      }
    },
    [treeId, selectedHost, selectedDeviceId, state.preview, executeScript],
  );

  /**
   * View last validation results by opening the saved report URL
   */
  const viewLastValidationResults = useCallback(() => {
    const state = getValidationState(treeId);
    if (state.lastReportUrl) {
      console.log(`[@hook:useValidation] Opening last validation report for tree ${treeId}: ${state.lastReportUrl}`);
      openValidationReport(state.lastReportUrl);
      return true;
    }
    console.log(`[@hook:useValidation] No last validation report available for tree ${treeId}`);
    return false;
  }, [treeId, openValidationReport]);

  /**
   * Clear validation result (close the results dialog)
   */
  const clearValidationResult = useCallback(() => {
    updateValidationState(treeId, { validationResult: null });
  }, [treeId]);

  return {
    // State
    isValidating: state.isValidating,
    preview: state.preview,
    isLoadingPreview: state.isLoadingPreview,
    validationError: state.validationError,
    validationResult: state.validationResult,
    progress: state.progress,
    currentMessage: state.currentMessage,
    currentStep: state.currentStep,
    totalSteps: state.totalSteps,
    recentSteps: state.recentSteps,

    // Computed properties for button logic
    canRunValidation: !state.isValidating, // Always enabled when not validating
    hasLastResults: !!state.lastReportUrl, // Check if we have a saved report URL

    // Actions
    loadPreview,
    runValidation,
    viewLastValidationResults,
    clearValidationResult,
  };
};