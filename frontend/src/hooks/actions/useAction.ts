import { useState, useCallback, useEffect } from 'react';

import { useDeviceData } from '../../contexts/device/DeviceDataContext';
import type { EdgeAction } from '../../types/controller/Action_Types';

import { buildServerUrl, buildServerUrlWithParams } from '../../utils/buildUrlUtils';
import { api } from '../../utils/apiClient';
import { waitForExecutionSocketEvent } from '../../utils/executionSocketWait';

const formatActionDuration = (ms: number): string => {
  const totalSeconds = Math.max(0, Math.round(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes === 0) return `${seconds}s`;
  return `${minutes}m:${String(seconds).padStart(2, '0')}s`;
};

// Define interfaces for action data structures
interface ActionExecutionResult {
  success: boolean;
  message: string;
  results?: any[];
  passed_count?: number;
  total_count?: number;
  error?: string;
  logs?: string;  // ✅ Add logs field
  output_data?: any;  // ✅ Add output_data field
  duration_ms?: number;  // wall-clock execution duration for summary display
  // HTML verification report for a repeat_until ("press until appears/disappears")
  // leg, so the Edge Run panel can link to the evidence that drove pass/fail.
  verification_report_url?: string | null;
}

export const useAction = () => {
  // Get actions from centralized context
  const { getAvailableActions, currentDeviceId, currentHost } = useDeviceData();

  // State for action execution (not data fetching)
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [executionResults, setExecutionResults] = useState<EdgeAction[]>([]);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [runningExecutionId, setRunningExecutionId] = useState<string | null>(null);
  
  // AbortController for cancelling ongoing polling requests
  const [abortController, setAbortController] = useState<AbortController | null>(null);

  // Effect to clear success message after delay
  useEffect(() => {
    if (successMessage) {
      const timer = setTimeout(() => {
        setSuccessMessage(null);
      }, 3000);
      return () => clearTimeout(timer);
    }
  }, [successMessage]);
  
  // Cleanup abort controller on unmount
  useEffect(() => {
    return () => {
      if (abortController) {
        console.log('[useAction] Unmounting - aborting any ongoing polling');
        abortController.abort();
      }
    };
  }, [abortController]);

  // Execute batch actions
  const executeActions = useCallback(
    async (
      actions: EdgeAction[],
      retryActions: EdgeAction[] = [],
      failureActions: EdgeAction[] = [],
      navigationContext?: {
        tree_id?: string;
        edge_id?: string;
        action_set_id?: string;
        // When all four edge fields are present, the host dispatches to
        // NavigationExecutor.execute_single_edge_step (records the row,
        // queues KPI, updates position). Without them the host runs the
        // actions ad-hoc with no DB write.
        target_node_id?: string;
        current_node_id?: string;
        userinterface_name?: string;
        final_wait_time?: number;
        variant?: string | null;
      }
    ): Promise<ActionExecutionResult> => {
      if (!currentHost) {
        const errorMsg = 'No host selected for action execution';
        setError(errorMsg);
        throw new Error(errorMsg);
      }

      if (actions.length === 0) {
        console.log('[useAction] No actions to execute');
        return { success: true, message: 'No actions to execute' };
      }

      console.log('[useAction] === ACTION EXECUTION DEBUG ===');
      console.log('[useAction] Number of actions:', actions.length);
      console.log('[useAction] Number of retry actions:', retryActions.length);
      console.log('[useAction] Number of failure actions:', failureActions.length);
      console.log('[useAction] Navigation Context:', navigationContext);

      // Filter out empty/invalid actions before execution
      const validActions = actions.filter((action, index) => {
        if (!action.command || action.command.trim() === '') {
          console.log(`[useAction] Removing action ${index}: No action type selected`);
          return false;
        }

        if (action.requiresInput) {
          const hasInputValue = action.inputValue && action.inputValue.trim() !== '';
          if (!hasInputValue) {
            console.log(`[useAction] Removing action ${index}: No input value specified`);
            return false;
          }
        }

        return true;
      });

      // Filter retry actions similarly
      const validRetryActions = retryActions.filter((action, index) => {
        if (!action.command || action.command.trim() === '') {
          console.log(`[useAction] Removing retry action ${index}: No action type selected`);
          return false;
        }

        if (action.requiresInput) {
          const hasInputValue = action.inputValue && action.inputValue.trim() !== '';
          if (!hasInputValue) {
            console.log(`[useAction] Removing retry action ${index}: No input value specified`);
            return false;
          }
        }

        return true;
      });

      // Filter failure actions similarly
      const validFailureActions = failureActions.filter((action, index) => {
        if (!action.command || action.command.trim() === '') {
          console.log(`[useAction] Removing failure action ${index}: No action type selected`);
          return false;
        }

        if (action.requiresInput) {
          const hasInputValue = action.inputValue && action.inputValue.trim() !== '';
          if (!hasInputValue) {
            console.log(`[useAction] Removing failure action ${index}: No input value specified`);
            return false;
          }
        }

        return true;
      });

      if (validActions.length === 0) {
        const errorMsg = 'All actions were empty and have been removed. Please add valid actions.';
        setError(errorMsg);
        return { success: false, message: errorMsg };
      }

      // Create new AbortController for this execution
      const controller = new AbortController();
      setAbortController(controller);
      setRunningExecutionId(null);

      const executionStartTime = Date.now();

      try {
        setLoading(true);
        setError(null);
        setExecutionResults([]);

        console.log('[useAction] Submitting batch action request');
        console.log('[useAction] Valid actions count:', validActions.length);
        console.log('[useAction] Valid retry actions count:', validRetryActions.length);
        console.log('[useAction] Valid failure actions count:', validFailureActions.length);

        const batchPayload = {
          actions: validActions,
          retry_actions: validRetryActions,
          failure_actions: validFailureActions,
        };

        console.log('[useAction] Batch payload:', batchPayload);

        console.log(
          `[useAction] Fetching from: /server/action/executeBatch with host: ${currentHost?.host_name} and device: ${currentDeviceId}`,
        );

        const responseData = await api.post(buildServerUrl('/server/action/executeBatch'), {
          host_name: currentHost.host_name,
          device_id: currentDeviceId,
          // Editor-driven Edge Run / action batch = interactive test. Marks
          // execution_results.is_test=true so edge_metrics aggregates skip it.
          // CLI invocations of equivalent endpoints (testcases, campaigns)
          // omit this and default to false on the host.
          is_test: true,
          ...batchPayload,
          ...(navigationContext || {}),
        }, { signal: controller.signal });
        console.log('[useAction] Batch execution response:', responseData);

        // ALL actions return execution_id and are completed via /system socket events
        if (!responseData.execution_id) {
          throw new Error('Server did not return execution_id');
        }
        
        console.log('[useAction] ✅ Async execution started:', responseData.execution_id);
        const executionId = responseData.execution_id;
        setRunningExecutionId(executionId);
        const pollExecutionStatus = async () => {
          const terminalStatuses = new Set(['completed', 'error', 'aborted']);

          while (true) {
            if (controller.signal.aborted) {
              throw new DOMException('Execution aborted', 'AbortError');
            }

            try {
              const statusResponse = await api.get<any>(
                buildServerUrlWithParams(`/server/action/execution/${executionId}/status`, {
                  host_name: currentHost.host_name,
                  device_id: currentDeviceId || undefined,
                }),
                { signal: controller.signal },
              );

              const status = String(statusResponse?.status || '').toLowerCase();
              if (terminalStatuses.has(status)) {
                return {
                  type: 'execution_update',
                  execution_type: 'action',
                  execution_id: executionId,
                  status,
                  result: statusResponse?.result,
                  error: statusResponse?.error,
                  message: statusResponse?.message,
                };
              }
            } catch (statusError: any) {
              // Ignore transient status lookup failures unless the request was aborted.
              if (statusError?.name === 'AbortError') {
                throw statusError;
              }
            }

            await new Promise<void>((resolve, reject) => {
              const abortHandler = () => {
                window.clearTimeout(timeoutId);
                reject(new DOMException('Execution aborted', 'AbortError'));
              };

              const timeoutId = window.setTimeout(() => {
                controller.signal.removeEventListener('abort', abortHandler);
                resolve();
              }, 1000);

              controller.signal.addEventListener('abort', abortHandler, { once: true });
            });
          }
        };

        // Socket is primary; status polling guarantees completion if socket event is missed.
        const socketEvent = await Promise.race([
          waitForExecutionSocketEvent(
            executionId,
            ['action'],
            180000,
            controller.signal,
          ),
          pollExecutionStatus(),
        ]);
        const result = socketEvent.result;

        if (!result) {
          throw new Error(socketEvent.error || 'Missing action execution result');
        }

        setExecutionResults(result.results || []);
        const passedCount = result.passed_count || 0;
        const totalCount = result.total_count || 0;
        const durationMs = Date.now() - executionStartTime;
        const summaryMessage = `Execution ${passedCount}/${totalCount} passed in ${formatActionDuration(durationMs)}`;
        setSuccessMessage(summaryMessage);

        return {
          success: result.success,
          message: summaryMessage,
          results: result.results,
          passed_count: passedCount,
          total_count: totalCount,
          logs: result.logs,
          output_data: result.output_data,
          duration_ms: durationMs,
          error: socketEvent.error,
          verification_report_url: result.verification_report_url ?? null,
        };
        
      } catch (error) {
        console.error('[useAction] Error during action execution:', error);

        if (error instanceof DOMException && error.name === 'AbortError') {
          return {
            success: false,
            message: '⏹️ Action execution aborted by user',
            error: 'Action execution aborted by user',
          };
        }
        
        // Abort any ongoing requests
        controller.abort();
        
        const errorMsg =
          error instanceof Error ? error.message : 'Unknown error during action execution';
        setError(errorMsg);
        return { success: false, message: errorMsg, error: errorMsg };
      } finally {
        setLoading(false);
        setRunningExecutionId(null);
        setAbortController(null);  // Clear abort controller after execution
      }
    },
    [currentHost, currentDeviceId],
  );

  const abortExecution = useCallback(async () => {
    if (!loading) {
      return { success: true, message: 'No action execution is running' };
    }

    if (runningExecutionId && currentHost && currentDeviceId) {
      try {
        await api.post(buildServerUrl('/server/action/abortExecution'), {
          host_name: currentHost.host_name,
          device_id: currentDeviceId,
          execution_id: runningExecutionId,
        });
      } catch (abortError: any) {
        const abortMessage = abortError?.message || '';
        if (abortMessage.includes('Execution already completed')) {
          return { success: true, message: 'Execution already completed' };
        }
        console.warn('[useAction] Failed to notify backend about abort:', abortError);
      }
    }

    if (abortController) {
      abortController.abort();
    }

    return { success: true, message: 'Abort requested' };
  }, [loading, runningExecutionId, currentHost, currentDeviceId, abortController]);

  // Format execution results for display
  const formatExecutionResults = useCallback((result: ActionExecutionResult): string => {
    if (!result.results || result.results.length === 0) {
      // No per-action breakdown available — surface the summary message
      // (already formatted as "Execution X/Y passed in Xm:YYs"), prefixed
      // with the success/failure marker so panel bgcolor matching works.
      const icon = result.success ? '✅' : '❌';
      return `${icon} ${result.message}`;
    }

    const lines: string[] = [];

    const formatActionLine = (actionResult: any): string => {
      // command/params can live at the top level OR nested in action_details
      // (the host's _execute_single_action returns them nested) — check both so
      // the line shows "press_key(RIGHT)" instead of a bare "action".
      const details = actionResult.action_details || {};
      const command = actionResult.command || details.command || actionResult.action_type || 'action';
      // Inline the first param value so HOME / OK / etc. are visible:
      // "press_key(HOME)". Falls back to bare command for paramless actions.
      const params = actionResult.params || details.params || {};
      // Surface the key explicitly when present; otherwise the first param value.
      const primaryValue = params.key ?? params[Object.keys(params)[0]];
      let label = command;
      if (primaryValue !== undefined) {
        const valueStr =
          typeof primaryValue === 'string' ? primaryValue : JSON.stringify(primaryValue);
        const truncated = valueStr.length > 50 ? `${valueStr.slice(0, 50)}...` : valueStr;
        label = `${command}(${truncated})`;
      }

      // Debug annotations: repeat-until config, count, and per-press wait —
      // so a "press until appears" leg is self-explanatory in the run box.
      const annotations: string[] = [];
      const repeat = actionResult.repeat_until || details.repeat_until;
      const iteratorCount = details.iterator_count ?? actionResult.iterator_count;
      if (repeat) {
        annotations.push(
          `until ${repeat.condition} (${repeat.match}), max ×${repeat.max_iterations ?? iteratorCount ?? '?'}`,
        );
      } else if (typeof iteratorCount === 'number' && iteratorCount > 1) {
        annotations.push(`×${iteratorCount}`);
      }
      const waitMs = params.wait_time ?? details.wait_time_ms;
      if (typeof waitMs === 'number' && waitMs > 0) {
        annotations.push(`wait:${waitMs}ms`);
      }
      const annotationStr = annotations.length ? ` [${annotations.join(', ')}]` : '';

      if (actionResult.success) {
        return `✅ ${label}${annotationStr}`;
      }
      const detail = actionResult.error || actionResult.message;
      return detail ? `❌ ${label}${annotationStr}: ${detail}` : `❌ ${label}${annotationStr}`;
    };

    result.results.forEach((actionResult: any) => {
      lines.push(formatActionLine(actionResult));

      // Show iteration details if available. For repeat-until legs this is the
      // press-by-press trace ("Iteration 6/7"), the key signal for debugging
      // how many presses it took to satisfy the stop condition.
      if (actionResult.iterations && actionResult.iterations.length > 0) {
        const max =
          (actionResult.action_details || {}).iterator_count ??
          actionResult.iterator_count ??
          actionResult.iterations.length;
        actionResult.iterations.forEach((iteration: any) => {
          const iterationIcon = iteration.success ? '✅' : '❌';
          lines.push(
            `   ${iterationIcon} Iteration ${iteration.iteration}/${max}: ${iteration.message} (${iteration.execution_time_ms}ms)`,
          );
        });
      }
    });

    const passed = result.passed_count ?? result.results.filter((r: any) => r.success).length;
    const total = result.total_count ?? result.results.length;
    const icon = result.success ? '✅' : '❌';
    const durationStr =
      typeof result.duration_ms === 'number' ? formatActionDuration(result.duration_ms) : null;
    lines.push(
      durationStr
        ? `${icon} Execution ${passed}/${total} passed in ${durationStr}`
        : `${icon} Execution ${passed}/${total} passed`,
    );

    return lines.join('\n');
  }, []);

  return {
    // Get actions from context
    availableActions: getAvailableActions(),
    loading,
    error,
    executionResults,
    successMessage,
    executeActions,
    abortExecution,
    formatExecutionResults,
    currentHost,
    currentDeviceId,
  };
};

export type UseActionType = ReturnType<typeof useAction>;
