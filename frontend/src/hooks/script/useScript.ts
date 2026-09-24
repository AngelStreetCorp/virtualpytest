/**
 * Script Execution Hook
 *
 * This hook handles script execution operations with progress tracking and API calls.
 * Follows the same patterns as useValidation and other hooks.
 */

import { useState, useCallback } from 'react';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { apiClient } from '../../utils/apiClient';
import { waitForExecutionSocketEvent, ExecutionSocketEvent } from '../../utils/executionSocketWait';
import { getScriptIdentity } from '../../utils/executionUtils';
import { useUserSession } from '../useUserSession';
import { useAuthContext } from '../../contexts/auth';

interface ScriptExecutionResult {
  // Set when the server queued the run instead of starting it (device was locked)
  queued?: boolean;
  deployment_id?: string;
  success: boolean;
  stdout: string;
  stderr: string;
  exit_code: number;
  task_id?: string;
  host?: string;
  report_url?: string;
  logs_url?: string;
  script_success?: boolean; // Extracted from SCRIPT_SUCCESS marker
  errorType?: string;
  message?: string;
  owner_type?: string;
  can_wait?: boolean;
  lock_info?: any;
}

interface UseScriptReturn {
  executeScript: (
    scriptName: string,
    hostName: string,
    deviceId: string,
    parameters?: string,
    callbackUrl?: string,
    signal?: AbortSignal,
    onProgress?: (event: ExecutionSocketEvent) => void,
    onTaskStarted?: (taskId: string) => void,
    virtualScriptId?: string,
  ) => Promise<ScriptExecutionResult>;
  waitForTask: (
    taskId: string,
    hostName: string,
    signal?: AbortSignal,
    onProgress?: (event: ExecutionSocketEvent) => void,
  ) => Promise<ScriptExecutionResult>;
  executeMultipleScripts: (
    executions: Array<{
      id: string;
      scriptName: string;
      hostName: string;
      deviceId: string;
      parameters?: string;
      callbackUrl?: string;
      forceUnlock?: boolean;
      // false = fail with 423 on a locked device instead of being queued server-side
      queueIfLocked?: boolean;
      environment?: 'dev' | 'test' | 'prod';
      virtualScriptId?: string;
    }>,
    onExecutionComplete?: (executionId: string, result: ScriptExecutionResult) => void,
    onTaskStarted?: (executionId: string, taskId: string) => void,
  ) => Promise<{ [executionId: string]: ScriptExecutionResult }>;
  isExecuting: boolean;
  executingIds: string[];
  lastResult: ScriptExecutionResult | null;
  error: string | null;
}

// Build script API URLs properly - don't append paths to URLs with query params

export const useScript = (): UseScriptReturn => {
  const { userId, sessionId } = useUserSession();
  // Display name forwarded with the run so viewers see WHO launched the script
  // next to the script name (server stores it on the device lock).
  const { profile } = useAuthContext();
  const userName = profile?.full_name || null;
  const [isExecuting, setIsExecuting] = useState(false);
  const [executingIds, setExecutingIds] = useState<string[]>([]);
  const [lastResult, setLastResult] = useState<ScriptExecutionResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const extractReportAndLogsUrls = useCallback((payload: any): { reportUrl?: string; logsUrl?: string } => {
    const candidates = [payload, payload?.result, payload?.data, payload?.result?.data];

    for (const candidate of candidates) {
      if (!candidate || typeof candidate !== 'object') continue;

      const reportUrl =
        candidate.report_url ||
        candidate.reportUrl ||
        candidate.html_report_r2_url ||
        candidate.htmlReportR2Url;
      const logsUrl =
        candidate.logs_url ||
        candidate.logsUrl ||
        candidate.logs_r2_url ||
        candidate.logsR2Url;

      if (reportUrl || logsUrl) {
        return { reportUrl, logsUrl };
      }
    }

    return {};
  }, []);

  // Task completion wait: socket push first, status polling as fallback.
  const waitForTaskCompletion = useCallback(async (
    taskId: string,
    hostName: string,
    onComplete: (result: ScriptExecutionResult) => void,
    signal?: AbortSignal,
    onProgress?: (event: ExecutionSocketEvent) => void,
  ): Promise<ScriptExecutionResult> => {
    let socketFallbackReason: string | null = null;

    const pollTaskStatus = async () => {
      const terminalStatuses = new Set(['completed', 'failed']);
      const POLL_INTERVAL_MS = 30_000;
      const POLL_TIMEOUT_MS = 7_200_000; // 2 hours — matches socket wait timeout
      const deadline = Date.now() + POLL_TIMEOUT_MS;

      while (Date.now() < deadline) {
        if (signal?.aborted) {
          return {
            type: 'execution_update',
            execution_type: 'script',
            execution_id: taskId,
            status: 'failed',
            result: {},
            error: 'Aborted',
            source: 'poll',
          };
        }

        try {
          const response = await apiClient(buildServerUrl(`/server/script/status/${taskId}`), {
            method: 'GET',
          });

          if (response.ok) {
            const statusPayload = await response.json();
            const task = statusPayload?.task;
            const status = String(task?.status || '').toLowerCase();
            if (terminalStatuses.has(status)) {
              return {
                type: 'execution_update',
                execution_type: 'script',
                execution_id: taskId,
                status,
                result: task?.result || {},
                error: task?.error || undefined,
                source: 'poll',
              };
            }
          }
        } catch {
          // Ignore transient status lookup errors and keep trying.
        }

        await new Promise<void>((resolve, reject) => {
          const tid = window.setTimeout(resolve, POLL_INTERVAL_MS);
          if (signal) {
            const onAbort = () => { clearTimeout(tid); reject(new DOMException('Aborted', 'AbortError')); };
            signal.addEventListener('abort', onAbort, { once: true });
          }
        }).catch(() => {/* aborted — loop condition will catch it */});
      }

      // Timed out — return a synthetic failed result so the UI unblocks.
      return {
        type: 'execution_update',
        execution_type: 'script',
        execution_id: taskId,
        status: 'failed',
        result: {},
        error: 'Polling timed out waiting for task completion',
        source: 'poll',
      };
    };

    const socketWaitPromise = waitForExecutionSocketEvent(taskId, ['script'], 7200000, signal, onProgress)
      .catch((err) => {
        socketFallbackReason = err instanceof Error ? err.message : 'socket wait failed';
        return null;
      });

    // Only fall back to polling if socket fails — do NOT race them simultaneously.
    const event = await socketWaitPromise ?? await pollTaskStatus();

    const resultPayload = event?.result || {};
    const { reportUrl, logsUrl } = extractReportAndLogsUrls(resultPayload);
    const result: ScriptExecutionResult = {
      success: resultPayload.success || event?.status === 'completed',
      stdout: resultPayload.stdout || '',
      stderr: resultPayload.stderr || event?.error || '',
      exit_code: typeof resultPayload.exit_code === 'number' ? resultPayload.exit_code : (resultPayload.success ? 0 : 1),
      host: hostName,
      report_url: reportUrl,
      logs_url: logsUrl,
      script_success: resultPayload.script_success,
    };

    const eventSource = (event as any)?.source === 'poll' ? 'poll' : 'socket';
    if (eventSource === 'poll') {
      console.warn(
        `[@hook:useScript:waitForTaskCompletion] Task ${taskId} completed via polling fallback` +
          (socketFallbackReason ? ` (socket issue: ${socketFallbackReason})` : '')
      );
    }

    onComplete(result);
    return result;
  }, [extractReportAndLogsUrls]);

  const executeScript = useCallback(
    async (
      scriptName: string,
      hostName: string,
      deviceId: string,
      parameters?: string,
      callbackUrl?: string,
      signal?: AbortSignal,
      onProgress?: (event: ExecutionSocketEvent) => void,
      onTaskStarted?: (taskId: string) => void,
      virtualScriptId?: string,
    ): Promise<ScriptExecutionResult> => {
      console.log(
        `[@hook:useScript:executeScript] Executing script: ${scriptName} on ${hostName}:${deviceId}${parameters ? ` with parameters: ${parameters}` : ''}`,
      );

      setIsExecuting(true);
      setError(null);

      try {
        const requestBody: any = {
          script_name: scriptName,
          host_name: hostName,
          device_id: deviceId,
          user_id: userId,
          session_id: sessionId,
          ...(userName ? { user_name: userName } : {}),
        };

        // Add parameters if provided
        if (parameters && parameters.trim()) {
          requestBody.parameters = parameters.trim();
        }
        if (callbackUrl && callbackUrl.trim()) {
          requestBody.callback_url = callbackUrl.trim();
        }
        // Virtual script: DB-stored source resolved + materialized on the host.
        if (virtualScriptId) {
          requestBody.virtual_script_id = virtualScriptId;
        }

        // Forward script identity (prefix / display_name) from the frontend's
        // bundled identity map so it lands in script_results.metadata without
        // requiring the JSON file on the host VM.
        const identity = getScriptIdentity(scriptName);
        if (identity?.prefix) requestBody.prefix = identity.prefix;
        if (identity?.display_name) requestBody.display_name = identity.display_name;

        // Forward the frontend's own build version. The server adds its version
        // and the host its own; all three land in script_results.metadata so a
        // run records exactly which frontend/server/host code produced it.
        const frontendVersion =
          typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : undefined;
        if (frontendVersion && frontendVersion !== 'unknown') {
          requestBody.versions = { frontend: frontendVersion };
        }

        // Start async script execution
        const response = await apiClient(buildServerUrl('/server/script/execute'), {
          method: 'POST',
          body: JSON.stringify(requestBody),
        });
        const initialResult = await response.json();

        // Device busy: the server queued the run as a one-shot deployment and will
        // complete task_id itself when it actually runs. Nothing to wait on here -
        // the queued row shows up through the deployment executions feed.
        if (initialResult.queued) {
          console.log(`[@hook:useScript:executeScript] Run queued server-side: ${initialResult.deployment_id}`);
          setLastResult(initialResult);
          return initialResult;
        }

        // Handle async task response (202 status code)
        if (response.status === 202 && initialResult.task_id) {
          console.log(
            `[@hook:useScript:executeScript] Script started async with task_id: ${initialResult.task_id}`,
          );

          // Wait for completion via socket push.
          const taskId = initialResult.task_id;
          onTaskStarted?.(taskId);
          const result = await waitForTaskCompletion(taskId, hostName, () => {}, signal, onProgress);
          if (!result.success) {
            throw new Error(result.stderr || 'Script execution failed');
          }
          console.log(`[@hook:useScript:executeScript] Script completed successfully`);
          setLastResult(result);
          return result;
        } else {
          // Handle synchronous response or error
          if (!response.ok) {
            throw new Error(
              initialResult.stderr || initialResult.error || 'Script execution failed',
            );
          }

          console.log(`[@hook:useScript:executeScript] Script completed:`, initialResult);
          setLastResult(initialResult);
          return initialResult;
        }
      } catch (error) {
        console.error(`[@hook:useScript:executeScript] Error executing script:`, error);
        const errorMessage = error instanceof Error ? error.message : 'Unknown error';
        setError(errorMessage);
        throw error;
      } finally {
        setIsExecuting(false);
      }
    },
    [waitForTaskCompletion],
  );

  const executeMultipleScripts = useCallback(async (
    executions: Array<{
      id: string;
      scriptName: string;
      hostName: string;
      deviceId: string;
      parameters?: string;
      callbackUrl?: string;
      forceUnlock?: boolean;
      // false = fail with 423 on a locked device instead of being queued server-side
      queueIfLocked?: boolean;
      environment?: 'dev' | 'test' | 'prod';
      virtualScriptId?: string;
    }>,
    onExecutionComplete?: (executionId: string, result: ScriptExecutionResult) => void,
    onTaskStarted?: (executionId: string, taskId: string) => void,
  ) => {
    console.log(`[@hook:useScript:executeMultipleScripts] Starting ${executions.length} concurrent executions`);
    
    setIsExecuting(true);
    setExecutingIds(executions.map(e => e.id));
    setError(null);

    const results: { [executionId: string]: ScriptExecutionResult } = {};

    // Start all executions in parallel with live callback
    const promises = executions.map(async (execution) => {
      try {
        console.log(`[@hook:useScript] Starting execution ${execution.id} on ${execution.hostName}:${execution.deviceId}`);
        
        const requestBody: any = {
          script_name: execution.scriptName,
          host_name: execution.hostName,
          device_id: execution.deviceId,
          user_id: userId,
          session_id: sessionId,
          ...(userName ? { user_name: userName } : {}),
        };

        if (execution.parameters && execution.parameters.trim()) {
          requestBody.parameters = execution.parameters.trim();
        }
        if (execution.virtualScriptId) {
          requestBody.virtual_script_id = execution.virtualScriptId;
        }
        if (execution.callbackUrl && execution.callbackUrl.trim()) {
          requestBody.callback_url = execution.callbackUrl.trim();
        }
        if (execution.forceUnlock) {
          requestBody.force_unlock = true;
        }
        if (execution.queueIfLocked === false) {
          requestBody.queue_if_locked = false;
        }
        if (execution.environment) {
          requestBody.environment = execution.environment;
        }

        const identity = getScriptIdentity(execution.scriptName);
        if (identity?.prefix) requestBody.prefix = identity.prefix;
        if (identity?.display_name) requestBody.display_name = identity.display_name;

        // Forward the frontend's own build version (server + host add theirs).
        const frontendVersion =
          typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : undefined;
        if (frontendVersion && frontendVersion !== 'unknown') {
          requestBody.versions = { frontend: frontendVersion };
        }

        const response = await apiClient(buildServerUrl('/server/script/execute'), {
          method: 'POST',
          body: JSON.stringify(requestBody),
        });
        const initialResult = await response.json();

        // Device busy: queued server-side (see executeScript above). Report it as
        // its own outcome so the page can drop the local row and refresh the feed.
        if (initialResult.queued) {
          const queuedResult = { ...initialResult, success: true, queued: true };
          results[execution.id] = queuedResult;
          onExecutionComplete?.(execution.id, queuedResult);
          return queuedResult;
        }

        if (response.status === 202 && initialResult.task_id) {
          console.log(`[@hook:useScript] Execution ${execution.id} started with task_id: ${initialResult.task_id}`);
          onTaskStarted?.(execution.id, initialResult.task_id);

          // Wait with live callback (socket push).
          const result = await waitForTaskCompletion(
            initialResult.task_id, 
            execution.hostName,
            (result) => {
              // LIVE UPDATE: Call callback immediately when this execution completes
              results[execution.id] = { ...result, task_id: initialResult.task_id };
              setExecutingIds(prev => prev.filter(id => id !== execution.id));
              onExecutionComplete?.(execution.id, { ...result, task_id: initialResult.task_id });
              console.log(`[@hook:useScript] Execution ${execution.id} completed with exit_code: ${result.exit_code}`);
            }
          );
          
          return { ...result, task_id: initialResult.task_id };
        } else {
          if (response.status === 423 && initialResult?.errorType === 'device_locked') {
            const lockedResult: ScriptExecutionResult = {
              success: false,
              stdout: '',
              stderr: initialResult.error || initialResult.message || 'Device is locked',
              exit_code: 1,
              host: execution.hostName,
              errorType: initialResult.errorType,
              message: initialResult.message,
              owner_type: initialResult.owner_type,
              can_wait: initialResult.can_wait,
              lock_info: initialResult.lock_info,
            };

            results[execution.id] = lockedResult;
            setExecutingIds(prev => prev.filter(id => id !== execution.id));
            onExecutionComplete?.(execution.id, lockedResult);

            return lockedResult;
          }

          if (!response.ok) {
            throw new Error(initialResult.stderr || initialResult.error || 'Script execution failed');
          }
          
          // Extract SCRIPT_SUCCESS marker for immediate completion
          if (initialResult.stdout && initialResult.stdout.includes('SCRIPT_SUCCESS:')) {
            const successMatch = initialResult.stdout.match(/SCRIPT_SUCCESS:(true|false)/);
            if (successMatch) {
              initialResult.script_success = successMatch[1] === 'true';
            }
          }
          
          // Immediate completion for synchronous response
          results[execution.id] = initialResult;
          setExecutingIds(prev => prev.filter(id => id !== execution.id));
          onExecutionComplete?.(execution.id, initialResult);
          
          return initialResult;
        }
      } catch (error) {
        console.error(`[@hook:useScript] Error in execution ${execution.id}:`, error);
        const errorResult: ScriptExecutionResult = {
          success: false,
          stdout: '',
          stderr: error instanceof Error ? error.message : 'Unknown error',
          exit_code: 1,
          host: execution.hostName,
        };
        
        results[execution.id] = errorResult;
        setExecutingIds(prev => prev.filter(id => id !== execution.id));
        onExecutionComplete?.(execution.id, errorResult);
        
        return errorResult;
      }
    });

    // Wait for ALL executions to complete before allowing new ones
    await Promise.allSettled(promises);
    
    setIsExecuting(false);
    setExecutingIds([]);
    
    console.log(`[@hook:useScript:executeMultipleScripts] All ${executions.length} executions completed`);
    return results;
  }, [waitForTaskCompletion]);

  const waitForTask = useCallback(
    async (
      taskId: string,
      hostName: string,
      signal?: AbortSignal,
      onProgress?: (event: ExecutionSocketEvent) => void,
    ): Promise<ScriptExecutionResult> => {
      return waitForTaskCompletion(taskId, hostName, () => {}, signal, onProgress);
    },
    [waitForTaskCompletion],
  );

  return {
    executeScript,
    executeMultipleScripts,
    waitForTask,
    isExecuting,
    executingIds,
    lastResult,
    error,
  };
};
