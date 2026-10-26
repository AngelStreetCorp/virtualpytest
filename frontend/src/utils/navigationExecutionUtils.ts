import { buildHostServerUrl } from './buildUrlUtils';
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

// Terminal statuses the host reports for a navigation (host_navigation_routes.py and
// TERMINAL_STATUSES in execution_event_utils.py). Anything else is progress.
const TERMINAL_NAVIGATION_STATUSES = new Set(['completed', 'error', 'failed', 'aborted']);
const STATUS_POLL_INTERVAL_MS = 2_000;
const NAVIGATION_TIMEOUT_MS = 600_000;
// How many consecutive "execution not found" answers end the wait: the host forgot the
// run (restart) and it will never report an outcome.
const MAX_NOT_FOUND_POLLS = 3;

/**
 * Wait for an async navigation to finish (BUG-0395).
 *
 * The socket event and the status endpoint are raced from the start. Before, the
 * status endpoint was only read after the socket wait gave up — 120 s later — so any
 * missed `execution_update` (socket refused or still connecting when the event fired,
 * a fast navigation finishing before the socket joined) left the Go To panel on
 * "Executing…" for two minutes after the device had arrived. Whichever source sees a
 * terminal status first wins; the other is stopped. Rejects on timeout, so the caller
 * always leaves its executing state.
 */
export async function waitForNavigationOutcome(
  executionId: string,
  hostName: string,
  deviceId: string,
  options: { pollIntervalMs?: number; timeoutMs?: number; host?: { server_url?: string } | null } = {},
): Promise<ExecutionSocketEvent> {
  const pollIntervalMs = options.pollIntervalMs ?? STATUS_POLL_INTERVAL_MS;
  const timeoutMs = options.timeoutMs ?? NAVIGATION_TIMEOUT_MS;
  const stop = new AbortController();

  const statusUrl = buildHostServerUrl(
    options.host,
    `/server/navigation/execution/${executionId}/status?host_name=${encodeURIComponent(hostName)}&device_id=${encodeURIComponent(deviceId)}`,
  );

  const sleep = (ms: number) =>
    new Promise<void>((resolve) => {
      const id = setTimeout(resolve, ms);
      stop.signal.addEventListener('abort', () => { clearTimeout(id); resolve(); }, { once: true });
    });

  const poll = async (): Promise<ExecutionSocketEvent> => {
    const deadline = Date.now() + timeoutMs;
    let notFound = 0;
    while (!stop.signal.aborted && Date.now() < deadline) {
      try {
        const resp = await fetch(statusUrl, { method: 'GET', signal: stop.signal });
        const status = await resp.json().catch(() => null);
        const s = String(status?.status || '').toLowerCase();
        if (TERMINAL_NAVIGATION_STATUSES.has(s)) {
          return {
            type: 'execution_update',
            execution_type: 'navigation',
            execution_id: executionId,
            status: s,
            result: status?.result,
            error: status?.error,
            message: status?.message,
          };
        }
        const missing = status?.success === false && /not found/i.test(String(status?.error || ''));
        notFound = missing ? notFound + 1 : 0;
        if (notFound >= MAX_NOT_FOUND_POLLS) {
          throw new Error(`Navigation ${executionId} is no longer known to the host`);
        }
      } catch (err) {
        if (stop.signal.aborted) break;
        if (err instanceof Error && err.message.includes('no longer known')) throw err;
        // transient network error — keep polling
      }
      await sleep(pollIntervalMs);
    }
    if (stop.signal.aborted) return new Promise<ExecutionSocketEvent>(() => {});
    throw new Error(`Timed out waiting for navigation ${executionId}`);
  };

  // A socket failure is not an outcome: the poll keeps going, so never let it win the race.
  const socket = waitForExecutionSocketEvent(executionId, ['navigation'], timeoutMs, stop.signal).catch(
    (err) => {
      if (!stop.signal.aborted) {
        console.warn(
          `[@navigationExecutionUtils] Socket wait for ${executionId} ended (${err instanceof Error ? err.message : err}); relying on status polling`,
        );
      }
      return new Promise<ExecutionSocketEvent>(() => {});
    },
  );

  try {
    return await Promise.race([socket, poll()]);
  } finally {
    stop.abort();
  }
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
  /** The host object: the run goes to the server that owns it (several servers / "All servers"). */
  host?: { server_url?: string } | null;
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
    host,
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

  const executionUrl = buildHostServerUrl(host, `/server/navigation/execute/${treeId}`);

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

    const socketEvent = await waitForNavigationOutcome(executionId, hostName, deviceId, { host });
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
