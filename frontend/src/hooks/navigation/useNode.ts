import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useDeviceData } from '../../contexts/device/DeviceDataContext';
import { useNavigation } from '../../contexts/navigation/NavigationContext';
import { useNavigationConfig } from '../../contexts/navigation/NavigationConfigContext';
import { Host } from '../../types/common/Host_Types';
import {
  NodeForm,
  NavigationPreviewResponse,
  NavigationStep,
  UINavigationEdge,
  UINavigationNode,
} from '../../types/pages/Navigation_Types';
import { api } from '../../utils/apiClient';
import { buildServerUrl, buildServerUrlWithParams } from '../../utils/buildUrlUtils';
import { invalidateSignedUrl } from '../../utils/infrastructure/cloudflareUtils';
import { executeNavigationAsync } from '../../utils/navigationExecutionUtils';
import { useValidationColors } from '../validation/useValidationColors';
import { useEdge } from './useEdge';

const formatGotoDuration = (ms: number): string => {
  const totalSeconds = Math.max(0, Math.round(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes === 0) return `${seconds}s`;
  return `${minutes}m:${String(seconds).padStart(2, '0')}s`;
};
export interface UseNodeProps {
  selectedHost?: Host;
  selectedDeviceId?: string;
  isControlActive?: boolean;
  treeId?: string;
  currentNodeId?: string;
  /**
   * Active canvas viewing scope. null = base run; non-null = lowercase
   * variant name. Forwarded onto every navigation execute call so
   * execution_results.variant gets stamped and metrics aggregate per scope.
   */
  variant?: string | null;
  /**
   * Verification mode for the goto run:
   *   'end'  → only the destination is verified (default)
   *   'each' → every intermediate step is verified
   *   'auto' → intermediate steps verify only when confidence < 0.7;
   *            destination is always verified
   * KPI queueing is independent of this — every successful step queues KPI.
   */
  verificationMode?: 'end' | 'each' | 'auto';
  /**
   * Called after a successful goto with the actually-executed path and the
   * node the device landed on. NavigationEditor uses this to follow the result
   * into a subtree (switch canvas + breadcrumb) when the landing node isn't in
   * the currently-displayed tree. Optional — callers without a canvas omit it.
   */
  onGotoArrived?: (navigationPath: any[] | undefined, finalNodeId: string) => void;
}

export const useNode = (props?: UseNodeProps) => {
  const { getModelReferences, referencesLoading, currentDeviceId } = useDeviceData();
  const { currentNodeId, updateCurrentPosition, updateNodesWithMinimapIndicators, nodes, edges, parentChain, userInterface } =
    useNavigation();
  const {
    setNavigationEdgesSuccess,
    setNavigationEdgesFailure,
    resetNavigationEdgeColors,
    setNodeVerificationSuccess,
    setNodeVerificationFailure,
    resetNodeVerificationColors,
  } = useValidationColors();
  const navigationConfig = useNavigationConfig();

  // Edge hook for executing action node edges
  const { executeEdgeActions } = useEdge({
    selectedHost: props?.selectedHost,
    selectedDeviceId: props?.selectedDeviceId,
    isControlActive: props?.isControlActive,
    treeId: props?.treeId,
  });

  // Create a ref for the navigation callback to avoid circular dependency
  const navigationCallbackRef = useRef<((nodeId: string) => void) | undefined>();

  // Timer actions should only be used during actual action execution, not general navigation
  // This will be moved to action execution contexts where it's actually needed

  // Get the selected device from the host's devices array
  const selectedDevice = useMemo(() => {
    return props?.selectedHost?.devices?.find(
      (device) => device.device_id === props?.selectedDeviceId,
    );
  }, [props?.selectedHost, props?.selectedDeviceId]);

  // Get the device model from the selected device
  const deviceModel = selectedDevice?.device_model;

  // Get model references using the device model
  const modelReferences = useMemo(() => {
    if (!deviceModel) {
      return {};
    }
    return getModelReferences(deviceModel);
  }, [getModelReferences, deviceModel]);

  // State for screenshot operations
  const [screenshotSaveStatus, setScreenshotSaveStatus] = useState<'idle' | 'success' | 'error'>(
    'idle',
  );

  // Navigation state for NodeGotoPanel
  const [navigationTransitions, setNavigationTransitions] = useState<NavigationStep[]>([]);
  const [isLoadingPreview, setIsLoadingPreview] = useState<boolean>(false);
  const [isExecuting, setIsExecuting] = useState<boolean>(false);
  const [navigationError, setNavigationError] = useState<string | null>(null);
  const [debugReportUrl, setDebugReportUrl] = useState<string | null>(null);
  // All failure reports for the failed step (target + conditional siblings).
  const [verificationReports, setVerificationReports] = useState<
    Array<{ label?: string; kind?: 'target' | 'sibling'; debug_report_url?: string; error?: string }>
  >([]);
  const [executionMessage, setExecutionMessage] = useState<string | null>(null);
  // Set when a final-hop conditional edge resolved to a sibling instead of the
  // exact requested target. Navigation still SUCCEEDED, but the device is on the
  // sibling — the panel shows a distinct "arrived on sibling" banner.
  const [arrivedOnSibling, setArrivedOnSibling] = useState<{
    node_label: string;
    requested_node_label: string;
  } | null>(null);

  /**
   * Get node form data with verifications (already resolved by NavigationConfigContext)
   */
  const getNodeFormWithVerifications = useCallback((node: UINavigationNode): NodeForm => {
    return {
      // Carries the node_id through to useNodeEdit → useVerification's
      // recordAs={kind:'node-visit'} so the host dispatcher routes the Run
      // button through NavigationExecutor.execute_single_node_verification
      // (writes node_metrics). Without this id, recordAs would silently fall
      // back to 'reference-test' and the Run records nothing.
      id: node.id,
      label: node.data.label,
      type: node.type as 'screen' | 'menu' | 'action' | 'entry',
      description: node.data.description || '',
      // Carry the existing friendly name through to the Edit dialog. Without
      // this the Display name field opens blank, and saving the node writes
      // display_name:'' back (NavigationContext.saveNodeWithStateUpdate),
      // silently wiping a value the node picker still reads from the DB.
      display_name: node.data.display_name || '',
      screenshot: node.data.screenshot,
      fingerprint: (node.data as any).fingerprint,   // Localize region fingerprint
      dom: (node.data as any).dom,                   // DOM representation JSON (sibling of _dom.jpg in R2)
      depth: node.data.depth || 0,
      parent: node.data.parent || [],
      menu_type: node.data.menu_type,
      priority: node.data.priority || 'p3', // Default to p3 if not set
      verifications: node.data.verifications || [], // Embedded verifications - no ID resolution needed
      verification_pass_condition: node.data.verification_pass_condition || 'all', // Default to 'all' if not set
      use_fingerprint_for_verification: (node.data as any).use_fingerprint_for_verification === true, // Fingerprint-verify toggle
      // Per-variant model: surface hidden_in_base so the Edit dialog can tell a
      // variant-only (owned) row from a shared base row. Without this the
      // selection-panel Edit path opens the dialog with hidden_in_base
      // undefined → a node created on a variant is mis-treated as a shared base
      // row (topology locked, "Reset variant" shown) and can't be edited.
      // Mirrors NavigationContext.openNodeDialog.
      hidden_in_base: node.data.hidden_in_base === true,
    };
  }, []);

  /**
   * Take and save screenshot for a node
   */
  const takeAndSaveScreenshot = useCallback(
    async (
      label: string,
      nodeId: string,
      onUpdateNode?: (nodeId: string, updatedData: any) => void,
    ) => {
      if (!props?.selectedHost || !props?.selectedDeviceId) {
        console.warn('[useNode:takeAndSaveScreenshot] Cannot take screenshot - missing host or deviceId:', {
          hasHost: !!props?.selectedHost,
          selectedDeviceId: props?.selectedDeviceId,
        });
        return { success: false, message: 'Host or device not available' };
      }

      // Get userinterface name from navigation context
      const userinterfaceName = userInterface?.name;

      if (!userinterfaceName) {
        console.warn('[useNode:takeAndSaveScreenshot] Cannot take screenshot - userInterface not loaded:', { userInterface });
        return { success: false, message: 'User interface not available - cannot determine screenshot path' };
      }

      try {
        // Sanitize filename by removing spaces and special characters
        const baseName = label.replace(/\s+/g, '_').replace(/[^a-zA-Z0-9_-]/g, '');
        // A capture taken while viewing a variant lands on a SEPARATE R2 object
        // (<label>__<variant>.jpg) so it never overwrites base or another variant.
        const variantSlug = props?.variant
          ? props.variant.replace(/\s+/g, '_').replace(/[^a-zA-Z0-9_-]/g, '')
          : '';
        const sanitizedFilename = variantSlug ? `${baseName}__${variantSlug}` : baseName;

        const result = await api.post<{ success?: boolean; screenshot_url?: string; message?: string; fingerprint?: any; dom?: any }>(
          buildServerUrl('/server/av/saveScreenshot'),
          {
            host_name: props.selectedHost.host_name,
            device_id: props.selectedDeviceId,
            filename: sanitizedFilename,
            userinterface_name: userinterfaceName,
          }
        );

        if (result.success) {
          const timestamp = Date.now();
          // The signed-URL cache (memory + sessionStorage) would otherwise hand
          // back the previous URL for ~55 minutes; drop the entry so the next
          // batch call re-signs the overwritten object.
          invalidateSignedUrl(result.screenshot_url);
          if (onUpdateNode) {
            // A screenshot capture rebuilds BOTH the fingerprint and the DOM (the
            // Reset button does fingerprint only). These ride the same persistence
            // path as the screenshot — handleUpdateNode routes a patch carrying
            // `screenshot` to the active variant's override (else base). dom is
            // included only when the backend returns it, so it never clears an
            // existing dom while the backend generation is being wired up.
            const patch: any = {
              screenshot: result.screenshot_url,
              screenshot_timestamp: timestamp,
              fingerprint: result.fingerprint,
            };
            if (result.dom !== undefined) patch.dom = result.dom;
            onUpdateNode(nodeId, patch);
          }
          window.dispatchEvent(
            new CustomEvent('nodeScreenshotUpdated', {
              detail: { nodeId, cacheBuster: timestamp },
            }),
          );
          // DOM generation (GPT-5.5) takes ~45-60s — run it in the BACKGROUND so the
          // screenshot save stays instant. When it resolves, patch node.data.dom; the
          // <stem>_dom.jpg overlay is uploaded host-side, so the Edit-node DOM tab
          // resolves it from the screenshot key. Fire-and-forget; failures are non-fatal.
          if (onUpdateNode && result.screenshot_url) {
            api.post<{ success?: boolean; dom?: any }>(
              buildServerUrl('/server/av/generateDom'),
              {
                host_name: props.selectedHost.host_name,
                device_id: props.selectedDeviceId,
                screenshot_url: result.screenshot_url,
              },
            )
              .then((domRes) => {
                if (domRes.success && domRes.dom !== undefined) {
                  onUpdateNode(nodeId, { dom: domRes.dom });
                }
              })
              .catch((err) =>
                console.warn('[useNode:takeAndSaveScreenshot] background DOM generation failed:', err),
              );
          }
          return { success: true, screenshot_url: result.screenshot_url, fingerprint: result.fingerprint };
        } else {
          return { success: false, message: result.message };
        }
      } catch (error) {
        return {
          success: false,
          message: error instanceof Error ? error.message : 'Unknown error',
        };
      }
    },
    [props?.selectedHost, props?.selectedDeviceId, userInterface],
  );

  /**
   * Handle screenshot confirmation and execution
   */
  const handleScreenshotConfirm = useCallback(
    async (
      selectedNode: UINavigationNode,
      onUpdateNode?: (nodeId: string, updatedData: any) => void,
    ) => {
      if (!props?.isControlActive || !props?.selectedHost || !props?.selectedDeviceId) {
        console.warn('[useNode:handleScreenshotConfirm] Cannot take screenshot - control not active or missing host/device:', {
          isControlActive: props?.isControlActive,
          hasHost: !!props?.selectedHost,
          selectedDeviceId: props?.selectedDeviceId,
        });
        return;
      }

      const result = await takeAndSaveScreenshot(
        selectedNode.data.label,
        selectedNode.id,
        onUpdateNode,
      );

      if (result.success) {
        setScreenshotSaveStatus('success');
        setTimeout(() => setScreenshotSaveStatus('idle'), 3000);
      } else {
        setScreenshotSaveStatus('error');
        setTimeout(() => setScreenshotSaveStatus('idle'), 3000);
      }
    },
    [props?.isControlActive, props?.selectedHost, props?.selectedDeviceId, takeAndSaveScreenshot],
  );

  // --- Fingerprint variance samples (Localize) -------------------------------
  // Up to 3 samples per node; volatile pixels (dynamic background) are masked
  // out at match time so dHash ignores carousel/clock/video. Each sample is its
  // own R2 object (label_s0/1/2) so it can be recaptured/deleted independently.
  const MAX_FP_SAMPLES = 3;

  const captureSampleImage = useCallback(
    async (label: string, index: number) => {
      const userinterfaceName = userInterface?.name;
      if (!props?.selectedHost || !props?.selectedDeviceId || !userinterfaceName) {
        return { success: false } as const;
      }
      const base = label.replace(/\s+/g, '_').replace(/[^a-zA-Z0-9_-]/g, '');
      const result = await api.post<{ success?: boolean; screenshot_url?: string; fingerprint?: any }>(
        buildServerUrl('/server/av/saveScreenshot'),
        {
          host_name: props.selectedHost.host_name,
          device_id: props.selectedDeviceId,
          filename: `${base}_s${index}`,
          userinterface_name: userinterfaceName,
        },
      );
      if (!result.success || !result.fingerprint) return { success: false } as const;
      invalidateSignedUrl(result.screenshot_url);
      return {
        success: true,
        url: result.screenshot_url,
        dhash: result.fingerprint.dhash,
        focus: result.fingerprint.focus,
      } as const;
    },
    [props?.selectedHost, props?.selectedDeviceId, userInterface],
  );

  // Rebuild data.fingerprint from the sample list (sample 0 drives the display
  // dhash/focus; `samples` drives the variance mask at match time).
  const writeSamples = (
    selectedNode: UINavigationNode,
    onUpdateNode: ((nodeId: string, updatedData: any) => void) | undefined,
    samples: { url?: string; dhash?: string; focus?: any }[],
  ) => {
    const fingerprint =
      samples.length > 0
        ? {
            v: 1,
            dhash: samples[0].dhash,
            focus: samples[0].focus,
            samples: samples.map((s) => ({ url: s.url, dhash: s.dhash })),
          }
        : null;
    onUpdateNode?.(selectedNode.id, { fingerprint });
  };

  const captureFingerprintSample = useCallback(
    async (
      selectedNode: UINavigationNode,
      onUpdateNode?: (nodeId: string, updatedData: any) => void,
      replaceIndex: number | null = null,
    ) => {
      const existing = ((selectedNode.data as any)?.fingerprint?.samples || []) as any[];
      const index = replaceIndex != null ? replaceIndex : existing.length;
      if (index >= MAX_FP_SAMPLES) return;
      const cap = await captureSampleImage(selectedNode.data.label, index);
      if (!cap.success) {
        setScreenshotSaveStatus('error');
        setTimeout(() => setScreenshotSaveStatus('idle'), 3000);
        return;
      }
      const next = [...existing];
      next[index] = { url: cap.url, dhash: cap.dhash, focus: cap.focus };
      writeSamples(selectedNode, onUpdateNode, next);
      setScreenshotSaveStatus('success');
      setTimeout(() => setScreenshotSaveStatus('idle'), 3000);
    },
    [captureSampleImage],
  );

  const deleteFingerprintSample = useCallback(
    (
      selectedNode: UINavigationNode,
      onUpdateNode: ((nodeId: string, updatedData: any) => void) | undefined,
      index: number,
    ) => {
      const existing = ((selectedNode.data as any)?.fingerprint?.samples || []) as any[];
      writeSamples(selectedNode, onUpdateNode, existing.filter((_, i) => i !== index));
    },
    [],
  );

  /**
   * Resolve a list of parent IDs to a "home > home_apps" string.
   *
   * Looks up first in the current view's `nodes`, then walks `parentChain`
   * (the ancestor trees stacked in the breadcrumb) so a node viewed inside a
   * subtree still gets human labels for parents that live in the root tree.
   * Falls through to the raw ID if nothing matches.
   */
  const getParentNames = useCallback((parentIds: string[], nodes: UINavigationNode[]): string => {
    if (!parentIds || parentIds.length === 0) return 'None';

    const labelOf = (id: string): string => {
      if (Array.isArray(nodes)) {
        const local = nodes.find((n) => n.id === id);
        if (local) return local.data.label;
      }
      for (const ancestor of parentChain ?? []) {
        const hit = ancestor.nodes?.find((n) => n.id === id);
        if (hit) return hit.data.label;
      }
      return id;
    };

    return parentIds.map(labelOf).join(' > ');
  }, [parentChain]);

  /**
   * Get full path for navigation (NodeGotoPanel)
   * Shows the actual navigation path from current position, not hierarchical structure
   */
  const getFullPath = useCallback(
    (selectedNode: UINavigationNode, nodes: UINavigationNode[]): string => {
      // If we have navigation transitions, use them to show the actual path
      if (navigationTransitions && navigationTransitions.length > 0) {
        const pathSegments: string[] = [];

        // Add the starting position from the first transition
        const firstTransition = navigationTransitions[0] as any;
        if (firstTransition?.from_node_label) {
          pathSegments.push(firstTransition.from_node_label);
        }

        // Add each transition target
        navigationTransitions.forEach((transition: any) => {
          if (transition?.to_node_label) {
            pathSegments.push(transition.to_node_label);
          }
        });

        return pathSegments.join(' → ');
      }

      // If we have a current position, show current → target
      if (currentNodeId) {
        const currentNode = nodes.find((node) => node.id === currentNodeId);
        const currentLabel = currentNode?.data.label || 'Current';

        // If already at target, just show the target
        if (currentNodeId === selectedNode.id) {
          return selectedNode.data.label;
        }

        return `${currentLabel} → ${selectedNode.data.label}`;
      }

      // Fallback to hierarchical structure if no current position
      const parentNames = getParentNames(selectedNode.data.parent || [], nodes);
      if (parentNames === 'None') {
        return selectedNode.data.label;
      }
      return `${parentNames} → ${selectedNode.data.label}`;
    },
    [getParentNames, navigationTransitions, currentNodeId],
  );

  /**
   * Load navigation preview for NodeGotoPanel - ALWAYS fetch fresh data
   */
  const loadNavigationPreview = useCallback(
    async (
      selectedNode: UINavigationNode,
      _allNodes?: UINavigationNode[],
      shouldUpdateMinimap: boolean = false,
    ): Promise<NavigationStep[]> => {
      if (!props?.treeId) return [];


      // Use only context currentNodeId - no fallbacks
      const startingNodeId = currentNodeId;

      const pathfindingTreeId = parentChain[0]?.treeId || props.treeId;

      setIsLoadingPreview(true);
      setNavigationError(null);

      try {
        // Use centralized URL builder with params
        const url = buildServerUrlWithParams(
          `/server/navigation/preview/${pathfindingTreeId}/${selectedNode.id}`,
          {
            host_name: props.selectedHost?.host_name ?? undefined,
            device_id: currentDeviceId ?? undefined,
            current_node_id: startingNodeId ?? undefined,
            // Forward the canvas-selected variant so pathfinding picks the
            // variant-scoped unified graph. Without this the preview reads
            // device.navigation_context — which lags / is base by default —
            // and shows a path through hidden_in_base nodes that the user's
            // variant doesn't include.
            variant: props.variant ?? undefined,
          }
        );

        const result: NavigationPreviewResponse = await api.get(url);

        if (result.success) {
          // Use the correct property name from server response
          const transitions = result.transitions || [];
          setNavigationTransitions(transitions);

          // Only update minimap indicators if explicitly requested (during execution)
          if (shouldUpdateMinimap) {
            updateNodesWithMinimapIndicators(transitions);
          }

          return transitions;
        } else {
          setNavigationError(result.error || 'Failed to load navigation preview');
          return [];
        }
      } catch (err) {
        setNavigationError(
          `Failed to load navigation preview: ${err instanceof Error ? err.message : 'Unknown error'}`,
        );
        return [];
      } finally {
        setIsLoadingPreview(false);
      }
    },
    [props?.treeId, props?.selectedHost, props?.variant, currentNodeId, updateNodesWithMinimapIndicators, parentChain],
  );

  /**
   * Execute navigation using centralized NavigationContext method
   */
  const executeNavigation = useCallback(
    async (selectedNode: UINavigationNode) => {
      if (!props?.treeId) return;

      // Guard: prevent execution if already executing
      if (isExecuting) {
        console.log('[@useNode:executeNavigation] Ignoring click - navigation already in progress');
        return;
      }


      setIsExecuting(true);
      setNavigationError(null);
      setArrivedOnSibling(null);

      // Reset edge colors to grey before starting new navigation
      resetNavigationEdgeColors();

      // Reset node verification colors before starting new navigation
      if (currentNodeId) {
        resetNodeVerificationColors(currentNodeId);
      }

      try {
        const executionTreeId = parentChain[0]?.treeId || navigationConfig.actualTreeId;
        
        if (!executionTreeId) {
          throw new Error('No tree ID available for navigation execution');
        }
        
        console.log('[@useNode:executeNavigation] 🎯 NAVIGATION EXECUTION REQUEST:');
        console.log('[@useNode:executeNavigation]   → Target Node ID:', selectedNode.id);
        console.log('[@useNode:executeNavigation]   → Target Node Label:', selectedNode.data.label);
        console.log('[@useNode:executeNavigation]   → Target Node Type:', selectedNode.type);
        console.log('[@useNode:executeNavigation]   → Execution Tree ID:', executionTreeId);
        console.log('[@useNode:executeNavigation]   → Current Node ID:', currentNodeId || 'None');
        console.log('[@useNode:executeNavigation]   → UserInterface Name:', userInterface?.name);
        console.log('[@useNode:executeNavigation]   → Host:', props.selectedHost?.host_name);
        console.log('[@useNode:executeNavigation]   → Device:', currentDeviceId);
        
        if (!props.selectedHost?.host_name) {
          throw new Error('Host name is required for navigation execution');
        }

        const isActionNode = selectedNode.type === 'action';

        if (isActionNode) {
          // ACTION NODE: Navigate to parent first (if not already there), then execute edge
          // Find the edge from parent to action node to get the parent ID
          const actionEdge = edges.find((e: UINavigationEdge) => e.target === selectedNode.id);
          if (!actionEdge) {
            throw new Error(`No edge found leading to action node '${selectedNode.data.label}'`);
          }

          const parentNodeId = actionEdge.source;
          const parentNode = nodes.find(n => n.id === parentNodeId);

          // Check if already at parent node - if so, skip navigation
          const alreadyAtParent = currentNodeId === parentNodeId;

          const actionStartTime = Date.now();

          if (alreadyAtParent) {
            console.log(`[@useNode:executeNavigation] Already at parent '${parentNode?.data.label}' - executing action directly`);
          } else {
            console.log(`[@useNode:executeNavigation] Action node detected - navigating to parent '${parentNode?.data.label || parentNodeId}' first`);

            // Step 1: Navigate to parent node
            const response = await executeNavigationAsync({
              treeId: executionTreeId,
              targetNodeId: parentNodeId,
              targetNodeLabel: parentNode?.data.label,
              hostName: props.selectedHost.host_name,
              deviceId: props.selectedDeviceId || currentDeviceId || 'device1',
              userinterfaceName: userInterface?.name || '',
              currentNodeId: currentNodeId || undefined,
              variant: props.variant ?? null,
              verificationMode: props.verificationMode ?? 'end',
              onProgress: (message) => {
                setExecutionMessage(message);
              }
            });

            // Update position to parent node
            const finalPositionNodeId = response.final_position_node_id || parentNodeId;
            updateCurrentPosition(finalPositionNodeId, parentNode?.data.label || 'Parent');
          }

          // Step 2: Execute edge from parent to action node
          setExecutionMessage(`Executing ${selectedNode.data.label} actions...`);
          console.log(`[@useNode:executeNavigation] Executing edge from parent to action node`);

          await executeEdgeActions(actionEdge);

          setExecutionMessage(
            `Action ${selectedNode.data.label} succeeded in ${formatGotoDuration(Date.now() - actionStartTime)}`,
          );
        } else {
          // REGULAR NODE: Check if already at target
          const alreadyAtTarget = currentNodeId === selectedNode.id;

          if (alreadyAtTarget) {
            console.log(`[@useNode:executeNavigation] Already at target '${selectedNode.data.label}' - no navigation needed`);
            setExecutionMessage(`Already at ${selectedNode.data.label}`);
          } else {
            const navStartTime = Date.now();

            // Normal navigation
            const response = await executeNavigationAsync({
              treeId: executionTreeId,
              targetNodeId: selectedNode.id,
              targetNodeLabel: selectedNode.data.label,
              hostName: props.selectedHost.host_name,
              deviceId: props.selectedDeviceId || currentDeviceId || 'device1',
              userinterfaceName: userInterface?.name || '',
              currentNodeId: currentNodeId || undefined,
              variant: props.variant ?? null,
              verificationMode: props.verificationMode ?? 'end',
              onProgress: (message) => {
                setExecutionMessage(message);
              }
            });

            // If the executor performed a conditional-edge recovery, the
            // returned `navigation_path` differs from our pre-execution
            // preview (steps inserted from a sibling node). Replace the
            // displayed transitions with what actually ran so the goto panel
            // accurately reflects the route taken instead of the planned one.
            if (Array.isArray(response.navigation_path) && response.navigation_path.length > 0) {
              setNavigationTransitions(response.navigation_path as any);
            }

            // A final-hop conditional edge may have legitimately resolved to a
            // sibling instead of the exact requested target — still a success,
            // but the device is on the sibling. Surface it distinctly.
            const arrived = response.arrived_on_sibling || null;
            setArrivedOnSibling(arrived);
            if (arrived) {
              setExecutionMessage(
                `Passed — arrived on sibling '${arrived.node_label}', not the requested ` +
                  `'${arrived.requested_node_label}' (${formatGotoDuration(Date.now() - navStartTime)})`,
              );
            } else {
              setExecutionMessage(
                `Navigation succeeded in ${formatGotoDuration(Date.now() - navStartTime)}`,
              );
            }

            // Update current position to final position (the sibling when we
            // arrived on one, otherwise the requested target).
            const finalPositionNodeId =
              (arrived && arrived.node_id) || response.final_position_node_id || selectedNode.id;
            updateCurrentPosition(
              finalPositionNodeId,
              arrived ? arrived.node_label : selectedNode.data.label,
            );

            // Follow the result into a subtree when the landing node isn't in
            // the currently-displayed tree (e.g. apps_netflix under `apps`).
            // The executed path carries the per-step to_tree_id chain; the
            // canvas owner (NavigationEditor) uses it to switch trees + center.
            props?.onGotoArrived?.(
              response.navigation_path || navigationTransitions,
              finalPositionNodeId,
            );
          }
        }

        setIsExecuting(false);

        // Set edges to green for successful navigation
        if (navigationTransitions && navigationTransitions.length > 0) {
          setNavigationEdgesSuccess(navigationTransitions);
        }
      } catch (error: any) {
        console.error(`[@hook:useNode:executeNavigation] Navigation failed:`, error);
        const errorMessage = error.message || 'Navigation failed';
        setExecutionMessage(`Navigation failed: ${errorMessage}`);
        setNavigationError(errorMessage);

        // Extract debug report URL if available
        if (error.debugReportUrl) {
          console.log(`[@hook:useNode:executeNavigation] Debug report URL:`, error.debugReportUrl);
          setDebugReportUrl(error.debugReportUrl);
        } else {
          setDebugReportUrl(null);
        }

        // Replace the displayed transitions with the actually-executed path even
        // on failure, so when conditional recovery splices in a sibling tail and
        // THAT then fails, the panel shows which (recovered) step actually broke
        // — not the original pre-execution preview.
        if (Array.isArray(error.navigationPath) && error.navigationPath.length > 0) {
          setNavigationTransitions(error.navigationPath as any);
        }

        // Extract the full list of failure reports (target + conditional siblings).
        const reports = error.errorDetails?.verification_reports;
        setVerificationReports(Array.isArray(reports) ? reports : []);

        // Goto failed mid-path → we no longer know where the device is.
        // Clear the tracked position so the next goto starts from entry
        // instead of trusting a stale "current node". The React Flow
        // selection (purple focus) is separate state and stays put.
        updateCurrentPosition(null, null);

        setIsExecuting(false);

        // Set edges to red on failed navigation
        if (navigationTransitions && navigationTransitions.length > 0) {
          setNavigationEdgesFailure(navigationTransitions);
        }
      }
    },
    [
      props?.treeId,
      props?.selectedHost,
      props?.selectedDeviceId,
      props?.onGotoArrived,
      currentNodeId,
      updateCurrentPosition,
      navigationTransitions,
      resetNavigationEdgeColors,
      setNavigationEdgesSuccess,
      setNavigationEdgesFailure,
      resetNodeVerificationColors,
      setNodeVerificationSuccess,
      setNodeVerificationFailure,
      navigationConfig.actualTreeId,
      isExecuting,
      userInterface,
      currentDeviceId,
      parentChain,
      nodes,
      edges,
      executeEdgeActions,
    ],
  );

  // Set up the navigation callback ref
  useEffect(() => {
    navigationCallbackRef.current = (nodeId: string) => {
      const targetNode = nodes.find((n: UINavigationNode) => n.id === nodeId);
      if (targetNode) {
        executeNavigation(targetNode);
      }
    };
  }, [nodes, executeNavigation]);

  /**
   * Clear navigation state when node changes
   */
  const clearNavigationState = useCallback(() => {
    setNavigationError(null);
    setDebugReportUrl(null);
    setVerificationReports([]);
    setExecutionMessage(null);
    setArrivedOnSibling(null);
    // Clear navigation route indicators
    updateNodesWithMinimapIndicators([]);
  }, [updateNodesWithMinimapIndicators]);

  /**
   * Clear only navigation messages without affecting minimap indicators
   * Used when opening goto panel to clear previous messages but keep minimap unchanged
   */
  const clearNavigationMessages = useCallback(() => {
    setNavigationError(null);
    setExecutionMessage(null);
    // ❌ DON'T update minimap indicators when just clearing messages for preview
  }, []);

  /**
   * Check if node is an entry node
   */
  const isEntryNode = useCallback((node: UINavigationNode): boolean => {
    return node.type === 'entry';
  }, []);

  /**
   * Check if node is protected from deletion
   */
  const isProtectedNode = useCallback((node: UINavigationNode): boolean => {
    return (
      node.data.is_root ||
      node.type === 'entry' ||
      node.id === 'entry-node' ||
      node.data.label?.toLowerCase() === 'home' ||
      node.id?.toLowerCase().includes('entry') ||
      node.id?.toLowerCase().includes('home')
    );
  }, []);

  /**
   * Check button visibility states
   */
  const buttonVisibility = useMemo(() => {
    return {
      showSaveScreenshotButton: props?.isControlActive && props?.selectedHost,
      showGoToButton: props?.isControlActive && props?.selectedHost && props?.treeId,
      canRunGoto: props?.isControlActive && props?.selectedHost,
    };
  }, [props?.isControlActive, props?.selectedHost, props?.treeId]);

  /**
   * Get button visibility for a specific node
   */
  const getNodeButtonVisibility = useCallback((_node: UINavigationNode) => {
    return {
      showSaveScreenshotButton: buttonVisibility.showSaveScreenshotButton, // Allow screenshot for action nodes
      showGoToButton: buttonVisibility.showGoToButton, // Allow GoTo for action nodes
      canRunGoto: buttonVisibility.canRunGoto, // Allow execution for action nodes
    };
  }, [buttonVisibility]);

  const getButtonVisibility = useCallback(() => buttonVisibility, [buttonVisibility]);

  // Auto-clear screenshot status when node selection might change
  useEffect(() => {
    setScreenshotSaveStatus('idle');
  }, [props?.selectedHost, props?.selectedDeviceId]);

  return {
    // Core node operations
    getNodeFormWithVerifications,
    getParentNames,
    isProtectedNode,
    getButtonVisibility,
    getNodeButtonVisibility,

    // Screenshot operations
    takeAndSaveScreenshot,
    handleScreenshotConfirm,
    captureFingerprintSample,
    deleteFingerprintSample,
    MAX_FP_SAMPLES,
    screenshotSaveStatus,

    // Model references
    modelReferences,
    referencesLoading,
    deviceModel,

    // NodeGotoPanel operations
    navigationTransitions,
    isLoadingPreview,
    isExecuting,
    navigationError,
    debugReportUrl,
    verificationReports,
    executionMessage,
    arrivedOnSibling,
    loadNavigationPreview,
    executeNavigation,
    clearNavigationState,
    getFullPath,

    // Current position information
    currentNodeId,
    updateCurrentPosition,
    updateNodesWithMinimapIndicators,

    // Additional helper functions
    isEntryNode,

    // New functions
    clearNavigationMessages,
  };
};
