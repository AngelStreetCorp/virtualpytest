import { useState, useCallback, useEffect } from 'react';

import { useDeviceData } from '../../contexts/device/DeviceDataContext';
import { useToastContext } from '../../contexts/ToastContext';
import { Verification } from '../../types/verification/Verification_Types';

import { buildServerUrl } from '../../utils/buildUrlUtils';
import { api } from '../../utils/apiClient';
import { waitForExecutionSocketEvent } from '../../utils/executionSocketWait';
// Define interfaces for verification data structures
interface ImageComparisonDialogData {
  open: boolean;
  sourceUrl: string;
  referenceUrl: string;
  overlayUrl?: string;
  userThreshold?: number;
  matchingResult?: number;
  resultType?: 'PASS' | 'FAIL' | 'ERROR';
  imageFilter?: 'none' | 'greyscale' | 'binary';
}

/**
 * Why every verification batch must declare its intent up-front.
 *
 * `/server/verification/executeBatch` is shared by three call sites with three
 * different recording semantics. The host dispatcher decides what to do based
 * on the request body: if `tree_id` + `node_id` are both present it routes
 * through `NavigationExecutor.execute_single_node_verification` (writes a
 * node_metrics row); otherwise it runs the primitive only (no DB write).
 *
 * Carrying nullable `treeId` / `nodeId` props in the hook signature meant the
 * intent was implicit — and easy to break by passing `undefined` (which
 * `JSON.stringify` silently strips). The discriminated union below makes the
 * intent part of the type, so TypeScript catches "node-visit without IDs" at
 * compile time and the dispatcher gate fields are emitted from a single,
 * obvious place.
 *
 *   node-visit     → records a node_metrics row (Run on the node Edit dialog)
 *   reference-test → no record (in-stream reference-capture editor)
 *   kpi-test       → no record (edge KPI reference test)
 */
export type RecordAs =
  | { kind: 'node-visit'; treeId: string; nodeId: string }
  | { kind: 'reference-test' }
  | { kind: 'kpi-test' };

export const useVerification = ({
  captureSourcePath,
  recordAs,
  userinterfaceName,
  verificationPassCondition,
}: {
  captureSourcePath?: string;
  recordAs: RecordAs;
  userinterfaceName?: string;  // Optional but recommended for proper reference resolution
  verificationPassCondition?: string;  // 'all' or 'any' - determines pass logic
}) => {
  // Get verification data from centralized context
  const { getAvailableVerificationTypes, currentDeviceId, currentHost } = useDeviceData();
  const { showError } = useToastContext();

  // State for verification execution (not data fetching)
  const [verifications, setVerifications] = useState<Verification[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Verification[]>([]);
  // Localize cross-check returned by node verification (true/false/unknown that
  // the live screen is on this node). Null for edge/standalone runs.
  const [localizeCheck, setLocalizeCheck] = useState<any>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [runningVerificationIndex, setRunningVerificationIndex] = useState<number | null>(null);
  // Wall-clock duration of the most recent test run (cleared on next start).
  // Used by the dialog summary line to render "✅ Execution X/Y passed in Xm:YYs".
  const [lastTestDurationMs, setLastTestDurationMs] = useState<number | null>(null);

  // Image comparison modal state
  const [imageComparisonDialog, setImageComparisonDialog] = useState<ImageComparisonDialogData>({
    open: false,
    sourceUrl: '',
    referenceUrl: '',
    overlayUrl: '',
    userThreshold: undefined,
    matchingResult: undefined,
    resultType: undefined,
    imageFilter: 'none',
  });

  // URL processing utilities
  const processImageUrl = useCallback((url: string): string => {
    if (!url) return '';

    console.log(`[@hook:useVerification] Processing image URL: ${url}`);

    // Handle data URLs (base64) - return as is
    if (url.startsWith('data:')) {
      console.log('[@hook:useVerification] Using data URL');
      return url;
    }

    // Handle HTTP URLs - use proxy to convert to HTTPS
    if (url.startsWith('http:')) {
      console.log('[@hook:useVerification] HTTP URL detected, using proxy');
      // URL is already processed by backend
      const proxyUrl = url;
      console.log(`[@hook:useVerification] Generated proxy URL: ${proxyUrl}`);
      return proxyUrl;
    }

    // Handle HTTPS URLs - return as is (no proxy needed)
    if (url.startsWith('https:')) {
      console.log('[@hook:useVerification] Using HTTPS URL directly');
      return url;
    }

    // For relative paths or other formats, use directly
    console.log('[@hook:useVerification] Using URL directly');
    return url;
  }, []);

  const getCacheBustedUrl = useCallback((url: string) => {
    if (!url) return url;
    const timestamp = Date.now();
    const separator = url.includes('?') ? '&' : '?';
    return `${url}${separator}t=${timestamp}`;
  }, []);

  // Image comparison modal handlers
  const openImageComparisonModal = useCallback((data: Partial<ImageComparisonDialogData>) => {
    setImageComparisonDialog({
      open: true,
      sourceUrl: data.sourceUrl || '',
      referenceUrl: data.referenceUrl || '',
      overlayUrl: data.overlayUrl || '',
      userThreshold: data.userThreshold,
      matchingResult: data.matchingResult,
      resultType: data.resultType,
      imageFilter: data.imageFilter || 'none',
    });
  }, []);

  const closeImageComparisonModal = useCallback(() => {
    setImageComparisonDialog((prev) => ({
      ...prev,
      open: false,
    }));
  }, []);

  // Effect to clear success message after delay
  useEffect(() => {
    if (successMessage) {
      const timer = setTimeout(() => {
        setSuccessMessage(null);
      }, 3000);
      return () => clearTimeout(timer);
    }
  }, [successMessage]);

  // Handle verifications change
  const handleVerificationsChange = useCallback((newVerifications: Verification[]) => {
    setVerifications(prevVerifications => {
      // Clear test results when verifications change (any change, not just length)
      if (JSON.stringify(prevVerifications) !== JSON.stringify(newVerifications)) {
        setTestResults([]);
      }
      return newVerifications;
    });
  }, []);

  const isVerificationValid = useCallback((verification: Verification, index: number): boolean => {
    if (!verification.command || verification.command.trim() === '') {
      console.log(`[useVerification] Verification ${index}: No verification type selected`);
      return false;
    }

    if (verification.verification_type === 'image') {
      // Icon commands run on the image controller but use a built-in glyph
      // (params.icon) + an area instead of an R2 reference image.
      const isIconCmd =
        verification.command === 'waitForIconToAppear' ||
        verification.command === 'waitForIconToDisappear';
      if (isIconCmd) {
        if (!verification.params?.icon || !verification.params?.area) {
          console.log(`[useVerification] Verification ${index}: icon verification needs icon + area`);
          return false;
        }
      } else if (!verification.params?.image_path) {
        console.log(`[useVerification] Verification ${index}: No image reference specified`);
        return false;
      }
    } else if (verification.verification_type === 'text') {
      const hasText = verification.params?.text && verification.params.text.trim() !== '';
      if (!hasText) {
        console.log(`[useVerification] Verification ${index}: No text specified`);
        return false;
      }
    } else if (verification.verification_type === 'adb') {
      const hasSearchTerm =
        verification.params?.search_term && verification.params.search_term.trim() !== '';
      if (!hasSearchTerm) {
        console.log(`[useVerification] Verification ${index}: No search term specified`);
        return false;
      }
    }

    return true;
  }, []);

  const executeVerificationBatch = useCallback(
    async (
      verificationsToRun: Verification[],
      runningIndex: number | null = null,
      localizeOnly: boolean = false,
    ) => {
      const testStartTime = Date.now();
      try {
        setLoading(true);
        setError(null);
        setTestResults([]);
        setLocalizeCheck(null);
        setLastTestDurationMs(null);
        setRunningVerificationIndex(runningIndex);

        // Extract capture filename from captureSourcePath for specific capture selection
        let image_source_url = null;
        if (captureSourcePath) {
          image_source_url = captureSourcePath;
          console.log('[useVerification] Using specific capture source:', image_source_url);
        }

        console.log('[useVerification] Submitting batch verification request');
        console.log('[useVerification] Valid verifications count:', verificationsToRun.length);

        // Wait-for verifications poll the live stream over their configured
        // timeout. But a manual "Test" from the frontend always runs against the
        // frame that is already on screen — there is nothing to wait for. Force
        // timeout=0 for those commands so the test evaluates the current frame
        // once, regardless of the timeout stored on the reference/edit form.
        const WAIT_FOR_COMMANDS = new Set([
          'waitForImageToAppear',
          'waitForImageToDisappear',
          'waitForIconToAppear',
          'waitForIconToDisappear',
          'waitForTextToAppear',
          'waitForTextToDisappear',
        ]);

        // Add userinterface_name to each verification for proper reference resolution
        // Also embed verification_pass_condition in FIRST verification so backend can auto-detect
        const verificationsWithUserInterface = verificationsToRun.map((v, index) => ({
          ...v,
          userinterface_name: userinterfaceName,
          ...(WAIT_FOR_COMMANDS.has(v.command)
            ? { params: { ...(v.params as any), timeout: 0 } }
            : {}),
          ...(index === 0 && verificationPassCondition
            ? { verification_pass_condition: verificationPassCondition }
            : {}),
        }));

        // Gate fields are only emitted when the caller declared a
        // node-visit. The host dispatcher checks (tree_id && node_id) to
        // decide whether to record, so omission here keeps reference-test
        // and kpi-test on the no-record path even if those values were
        // somehow ambiently in scope.
        //
        // is_test=true is paired with node-visit because every node-visit
        // through this hook is an interactive Editor "Run" — it should land
        // in execution_results but stay out of node_metrics. CLI flows write
        // node rows from NavigationExecutor's per-step loop, where is_test
        // defaults to false unless --test is set.
        const batchPayload = {
          verifications: verificationsWithUserInterface,
          // Top-level userinterface_name lets a localize-only run (empty verifications)
          // still resolve the node — the backend can't read it from verifications[0].
          userinterface_name: userinterfaceName,
          ...(localizeOnly ? { localize_only: true } : {}),
          ...(recordAs.kind === 'node-visit'
            ? { tree_id: recordAs.treeId, node_id: recordAs.nodeId, is_test: true }
            : {}),
          image_source_url: image_source_url,
        };

        console.log('[useVerification] Batch payload:', batchPayload);
        console.log(
          '[useVerification] Verification areas with fuzzy coordinates:',
          verificationsWithUserInterface.map((v) => ({
            command: v.command,
            area: (v.params as any)?.area,
            hasFuzzy: !!(
              (v.params as any)?.area?.fx !== undefined || (v.params as any)?.area?.fy !== undefined
            ),
          })),
        );

        const result = await api.post(buildServerUrl('/server/verification/executeBatch'), {
          host_name: currentHost?.host_name,
          device_id: currentDeviceId,
          ...batchPayload,
        });

        console.log(
          `[useVerification] Fetching from: /server/verification/executeBatch with host: ${currentHost?.host_name} and device: ${currentDeviceId}`,
        );
        console.log('[useVerification] Batch test result:', result);

        // Check if response is async (execution_id present) or synchronous
        if (result.execution_id) {
          console.log('[useVerification] ✅ Async execution started:', result.execution_id);
          // Use verification-defined timeouts instead of a fixed 120s socket wait.
          // Batch verifications execute sequentially, so sum all configured timeouts.
          // NOTE: params.timeout is in MILLISECONDS everywhere (the dialog labels
          // it "Timeout (ms)"), so these values are already ms — do NOT multiply.
          const timeoutMsList = verificationsToRun
            .map((verification) => Number((verification.params as any)?.timeout))
            .filter((value) => Number.isFinite(value) && value > 0);
          const timeoutMsTotal = timeoutMsList.length > 0
            ? timeoutMsList.reduce((sum, value) => sum + value, 0)
            : Math.max(10000, verificationsToRun.length * 10000);
          // Add small overhead (15s) for setup/screenshot/log emission and clamp to sane bounds.
          const socketTimeoutMs = Math.min(
            Math.max(Math.ceil(timeoutMsTotal + 15000), 20000),
            300000,
          );
          console.log('[useVerification] Socket wait timeout(ms):', socketTimeoutMs);
          const socketEvent = await waitForExecutionSocketEvent(
            result.execution_id,
            ['verification'],
            socketTimeoutMs,
          );
          const finalResult = socketEvent.result;
          if (!finalResult) {
            throw new Error(socketEvent.error || 'Verification execution failed');
          }
          setTestResults(finalResult.results || []);
          setLocalizeCheck(finalResult.localize || null);
          const passedCount = finalResult.passed_count || 0;
          const totalCount = finalResult.total_count || 0;
          setLastTestDurationMs(Date.now() - testStartTime);
          setSuccessMessage(`Test completed: ${passedCount}/${totalCount} passed`);
          return;
        }

        // Synchronous response (backward compatibility)
        setTestResults(result.results || []);
        setLocalizeCheck(result.localize || null);
        console.log('[useVerification] Test results set:', result.results);

        const passedCount = result.passed_count || 0;
        const totalCount = result.total_count || 0;
        setLastTestDurationMs(Date.now() - testStartTime);

        if (result.success) {
          setSuccessMessage(`Verification completed: ${passedCount}/${totalCount} passed`);
        } else {
          setSuccessMessage(`Test completed: ${passedCount}/${totalCount} passed`);
        }
      } catch (error) {
        console.error('[useVerification] Error during verification test:', error);
        const message =
          error instanceof Error ? error.message : 'Unknown error during verification test';
        setError(message);
        // Surface socket-wait timeouts and other failures so they don't disappear
        // into the console — the user otherwise sees the spinner stop with no
        // explanation of why no test results appeared.
        const isTimeout = /Execution timeout/i.test(message);
        showError(
          isTimeout
            ? `Verification timed out — host did not respond in time`
            : `Verification failed: ${message}`,
        );
      } finally {
        setLoading(false);
        setRunningVerificationIndex(null);
      }
    },
    [
      captureSourcePath,
      currentDeviceId,
      currentHost,
      recordAs,
      userinterfaceName,
      verificationPassCondition,
      showError,
    ],
  );

  // Handle test execution
  const handleTest = useCallback(
    async (event?: React.MouseEvent) => {
      if (event) {
        event.preventDefault();
        event.stopPropagation();
      }

      if (verifications.length === 0) {
        console.log('[useVerification] No verifications to test');
        return;
      }

      console.log('[useVerification] === VERIFICATION TEST DEBUG ===');
      console.log(
        '[useVerification] Number of verifications before filtering:',
        verifications.length,
      );

      // Filter out empty/invalid verifications before testing
      const validVerifications = verifications.filter((verification, index) =>
        isVerificationValid(verification, index),
      );

      // Update verifications list if any were filtered out
      if (validVerifications.length !== verifications.length) {
        console.log(
          `[useVerification] Filtered out ${verifications.length - validVerifications.length} empty verifications`,
        );
        setVerifications(validVerifications);

        if (validVerifications.length === 0) {
          setError(
            'All verifications were empty and have been removed. Please add valid verifications.',
          );
          return;
        } else {
          setSuccessMessage(
            `Removed ${verifications.length - validVerifications.length} empty verification(s). Testing ${validVerifications.length} valid verification(s).`,
          );
        }
      }

      await executeVerificationBatch(validVerifications, null);
    },
    [executeVerificationBatch, isVerificationValid, verifications],
  );

  const handleTestSingle = useCallback(
    async (index: number, event?: React.MouseEvent) => {
      if (event) {
        event.preventDefault();
        event.stopPropagation();
      }

      const selectedVerification = verifications[index];
      if (!selectedVerification) {
        setError(`Verification ${index + 1} not found`);
        return;
      }

      if (!isVerificationValid(selectedVerification, index)) {
        setError(`Verification ${index + 1} is incomplete. Complete its required fields first.`);
        return;
      }

      await executeVerificationBatch([selectedVerification], index);
    },
    [executeVerificationBatch, isVerificationValid, verifications],
  );

  // Run ONLY the node localize-check — same path/plumbing as Run (host/device/node
  // from this hook), but with NO reference verifications. Populates localizeCheck.
  const handleLocalizeOnly = useCallback(
    async (event?: React.MouseEvent) => {
      if (event) {
        event.preventDefault();
        event.stopPropagation();
      }
      await executeVerificationBatch([], null, true);
    },
    [executeVerificationBatch],
  );

  // Verify THIS node by its stored fingerprint — runs a real (non-empty) match_fingerprint
  // verification against the live frame, so it no longer trips the backend's "verifications are
  // required" guard that the old empty localize-only run hit. Result shows in testResults (pass/fail).
  const handleFingerprintVerify = useCallback(
    async (fingerprint: any, nodeLabel?: string, event?: React.MouseEvent) => {
      if (event) {
        event.preventDefault();
        event.stopPropagation();
      }
      if (!fingerprint?.dhash) return;
      await executeVerificationBatch(
        [
          {
            verification_type: 'image',
            command: 'match_fingerprint',
            params: { fingerprint, threshold: 14, node_label: nodeLabel || '' },
          } as any,
        ],
        null,
        false,
      );
    },
    [executeVerificationBatch],
  );

  return {
    localizeCheck,
    availableVerificationTypes: getAvailableVerificationTypes(), // Get from context
    verifications,
    loading,
    error,
    testResults,
    successMessage,
    lastTestDurationMs,
    handleVerificationsChange,
    handleTest,
    handleTestSingle,
    handleLocalizeOnly,
    handleFingerprintVerify,
    runningVerificationIndex,
    currentHost,
    currentDeviceId,
    // Image comparison modal
    imageComparisonDialog,
    openImageComparisonModal,
    closeImageComparisonModal,
    // URL processing utilities
    processImageUrl,
    getCacheBustedUrl,
  };
};

export type UseVerificationType = ReturnType<typeof useVerification>;
