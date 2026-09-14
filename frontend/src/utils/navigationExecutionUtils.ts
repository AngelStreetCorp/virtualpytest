import { buildServerUrl } from './buildUrlUtils';
import { waitForExecutionSocketEvent, ExecutionSocketEvent } from './executionSocketWait';

/**
 * Navigation execution result
 */
export interface NavigationExecuteResponse {
  success: boolean;
  error?: string;
  error_details?: {
    debug_report_url?: string;
    debug_report_path?: string;
    // Every failure report for the failed step: the expected target branch
    // plus any conditional siblings that were checked and also failed.
    verification_reports?: Array<{
      label?: string;
      kind?: 'target' | 'sibling';
      debug_report_url?: string;
      error?: string;
    }>;
    [key: string]: any;
  };
  final_position_node_id?: string;
  verification_results?: Array<{ success: boolean }>;
  transitions?: any[];
  /**
   * The path the executor ACTUALLY ran, including any conditional-edge
   * recovery splices. Replaces the pre-execution preview in the goto panel.
   * Steps inserted by recovery carry `is_recovery: true` and
   * `recovered_from_node_label`. Returned on both success and failure.
   */
  navigation_path?: any[];
  /**
   * Set when a final-hop conditional edge legitimately resolved to one of its
   * sibling outcomes instead of the exact requested target. Navigation still
   * succeeded, but the device is on the sibling — surfaced as a distinct
   * "arrived on sibling" banner in the goto panel.
   */
  arrived_on_sibling?: {
    node_id: string;
    node_label: string;
    requested_node_id: string;
    requested_node_label: string;
  } | null;
  logs?: string; // ✅ Navigation execution logs
  message?: string; // ✅ Result message
}

/**
 * Execute navigation with async socket completion - reusable utility
 * 
 * @param params Navigation execution parameters
 * @returns Navigation execution result
 */
export type VerificationMode = 'end' | 'each' | 'auto';

export async function executeNavigationAsync(params: {
  treeId: string;
  targetNodeId?: string;  // UUID parameter
  targetNodeLabel?: string;  // Label parameter
  hostName: string;
  deviceId: string;
  userinterfaceName: string;
  currentNodeId?: string;
  variant?: string | null;  // Active canvas viewing scope; null = base
  /**
   * Verification mode for the navigation:
   *   'end'  → only the last step's destination is verified (default)
   *   'each' → every step's destination is verified
   *   'auto' → last step always; intermediate steps verify only when both
   *            edge confidence and destination node confidence are below
   *            0.7 (or no metrics yet)
   */
  verificationMode?: VerificationMode;
  onProgress?: (message: string) => void;
}): Promise<NavigationExecuteResponse> {
  const {
    treeId,
    targetNodeId,
    targetNodeLabel,
    hostName,
    deviceId,
    userinterfaceName,
    currentNodeId,
    variant,
    verificationMode,
    onProgress,
  } = params;

  // Validate: must provide either targetNodeId OR targetNodeLabel
  if (!targetNodeId && !targetNodeLabel) {
    throw new Error('Either targetNodeId or targetNodeLabel must be provided');
  }

  const executionUrl = buildServerUrl(`/server/navigation/execute/${treeId}`);

  // Lowercase the variant before sending; the DB CHECK constraint enforces
  // lowercase. Empty string / whitespace coerces to null (= base run).
  const normalizedVariant =
    typeof variant === 'string' && variant.trim() ? variant.trim().toLowerCase() : null;

  const normalizedMode: VerificationMode =
    verificationMode === 'each' || verificationMode === 'auto' ? verificationMode : 'end';

  // The backend rejects requests that carry both target_node_id and
  // target_node_label. Callers may pass the label purely for the progress
  // message (see onProgress below); when an id is also present, prefer the
  // id and drop the label from the wire payload.
  const startResult = await fetch(executionUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      ...(targetNodeId
        ? { target_node_id: targetNodeId }
        : { target_node_label: targetNodeLabel }),
      host_name: hostName,
      device_id: deviceId,
      current_node_id: currentNodeId,
      userinterface_name: userinterfaceName,
      variant: normalizedVariant,
      verification_mode: normalizedMode,
      // Editor-driven Goto = interactive test run. Marks the row so the
      // metrics trigger excludes it from edge_metrics / node_metrics
      // aggregates. CLI / pipeline goto.py defaults to false.
      is_test: true,
    }),
  });

  const startResponse = await startResult.json();

  if (!startResponse.success) {
    throw new Error(startResponse.error || 'Failed to start navigation');
  }

  // Check if response is synchronous (web devices) or async (other devices)
  if (startResponse.execution_id) {
    // ASYNC RESPONSE: Non-web devices (ADB, remote, etc.) - wait for completion event
    const executionId = startResponse.execution_id;
    console.log('[@navigationExecutionUtils] ✅ Async execution started:', executionId);
    
    if (onProgress) {
      onProgress(`Navigating to ${targetNodeLabel || targetNodeId}...`);
    }

    let socketFallbackReason: string | null = null;

    const pollExecutionStatus = async (): Promise<ExecutionSocketEvent> => {
      const POLL_INTERVAL_MS = 2_000;
      const POLL_TIMEOUT_MS = 600_000;
      const deadline = Date.now() + POLL_TIMEOUT_MS;
      const statusUrl = buildServerUrl(
        `/server/navigation/execution/${executionId}/status?host_name=${encodeURIComponent(hostName)}&device_id=${encodeURIComponent(deviceId)}`,
      );

      while (Date.now() < deadline) {
        try {
          const resp = await fetch(statusUrl, { method: 'GET' });
          if (resp.ok) {
            const status = await resp.json();
            const s = String(status?.status || '').toLowerCase();
            if (s === 'completed' || s === 'error' || s === 'failed') {
              return {
                type: 'execution_update',
                execution_type: 'navigation',
                execution_id: executionId,
                status: s,
                result: status?.result,
                error: status?.error,
              };
            }
          }
        } catch {
          // transient — keep polling
        }
        await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
      }
      throw new Error(`Polling timed out waiting for navigation ${executionId}`);
    };

    const socketWaitPromise = waitForExecutionSocketEvent(
      executionId,
      ['navigation'],
      120000,
    ).catch((err) => {
      socketFallbackReason = err instanceof Error ? err.message : 'socket wait failed';
      return null;
    });

    const socketEvent = (await socketWaitPromise) ?? (await pollExecutionStatus());
    if (socketFallbackReason) {
      console.warn(
        `[@navigationExecutionUtils] Navigation ${executionId} completed via polling fallback (socket issue: ${socketFallbackReason})`,
      );
    }
    const finalResult = socketEvent.result;
    if (!finalResult) {
      throw new Error(socketEvent.error || 'Navigation execution failed');
    }
    const response: NavigationExecuteResponse = {
      ...finalResult,
      logs: finalResult?.logs || '',
      message: finalResult?.message || socketEvent.message,
    };
    if (!response.success) {
      const error: any = new Error(response.error || 'Navigation execution failed');
      error.debugReportUrl = response.error_details?.debug_report_url;
      error.errorDetails = response.error_details;
      // Forward the actually-executed path so the catcher can replace the
      // preview with the spliced version (sibling recovery, etc.). Without
      // this the goto panel keeps showing the pre-execution preview.
      error.navigationPath = response.navigation_path;
      error.logs = response.logs;
      throw error;
    }
    if (onProgress) {
      onProgress(`Navigation to ${targetNodeLabel || targetNodeId} completed successfully`);
    }
    return response;

  } else {
    // SYNC RESPONSE: Web devices (Playwright) - result returned immediately
    console.log('[@navigationExecutionUtils] ✅ Synchronous execution completed (web device)');
    
    const response: NavigationExecuteResponse = {
      ...startResponse,
      logs: startResponse.logs || '',
      message: startResponse.message || 'Navigation completed',
    };

    if (!response.success) {
      const error: any = new Error(response.error || 'Navigation execution failed');
      error.debugReportUrl = response.error_details?.debug_report_url;
      error.errorDetails = response.error_details;
      // See async branch above — forward the spliced path so the goto panel
      // re-renders steps with the recovery tail instead of the stale preview.
      error.navigationPath = response.navigation_path;
      error.logs = response.logs;
      throw error;
    }

    if (onProgress) {
      onProgress(`Navigation to ${targetNodeLabel || targetNodeId} completed successfully`);
    }

    console.log('[@navigationExecutionUtils] ✅ Sync navigation completed with logs:', {
      hasLogs: Boolean(response.logs),
      logsLength: response.logs?.length || 0
    });

    return response;
  }
}
