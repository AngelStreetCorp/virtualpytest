import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useDeviceData } from '../../contexts/device/DeviceDataContext';
import { useToastContext } from '../../contexts/ToastContext';
import { useNavigationConfig } from '../../contexts/navigation/NavigationConfigContext';
import { useNavigation } from '../../contexts/navigation/NavigationContext';
import { useNavigationPreviewCache } from '../../contexts/navigation/NavigationPreviewCacheContext';
import { Host } from '../../types/common/Host_Types';
import { NodeForm, UINavigationNode } from '../../types/pages/Navigation_Types';
import { Verification } from '../../types/verification/Verification_Types';
import { api } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { RecordAs, useVerification } from '../verification/useVerification';

export interface UseNodeEditProps {
  isOpen: boolean;
  nodeForm: NodeForm | null;
  setNodeForm: (form: NodeForm) => void;
  selectedHost?: Host;
  isControlActive?: boolean;
  onUpdateNode?: (nodeId: string, updatedData: any) => void;
}

export const useNodeEdit = ({
  isOpen,
  nodeForm,
  setNodeForm,
  selectedHost,
  isControlActive = false,
  onUpdateNode,
}: UseNodeEditProps) => {
  // Get device data context for model references
  const { getModelReferences, referencesLoading, references, reloadReferences, refreshReferences, addReferenceToCache } =
    useDeviceData();
  const { showError } = useToastContext();
  
  // Get navigation context for save and treeId
  const { userInterface, saveNodeWithStateUpdate, parentChain } = useNavigation();
  // The editor route is /navigation-editor/<interfaceId>; useParams' treeId
  // is undefined here. The actual canonical tree UUID is owned by
  // NavigationConfigContext as actualTreeId — that's what flows into all
  // recording paths.
  const { actualTreeId } = useNavigationConfig();
  const treeId = actualTreeId ?? undefined;

  // Get preview cache context for invalidation
  const { invalidateTree } = useNavigationPreviewCache();

  // Use userinterface name for reference lookup
  const referenceKey = userInterface?.name;

  // Get model references using the userinterface name
  // IMPORTANT: Must depend on references state to re-render when references are added
  const modelReferences = useMemo(() => {
    if (!referenceKey) return {};
    return getModelReferences(referenceKey);
  }, [getModelReferences, referenceKey, references]);

  // Re-fetch references every time the dialog opens. References can be created
  // elsewhere (e.g. captured in the stream panel's Verification Editor) while
  // this dialog is closed; the context cache may not have propagated them.
  // Reloading on open mirrors a page refresh so newly-created references appear
  // in the dropdown without one. Use refreshReferences (honours the server's
  // 60s cache), NOT reloadReferences (busts it) — busting the cache on every
  // open turned each node open into a fresh DB query and caused the
  // multi-minute "Loading…" hang during DB stalls. The loading gate
  // (`hasLoadedInitialData`) suppresses the body spinner for this reload.
  useEffect(() => {
    if (isOpen) {
      void refreshReferences();
    }
  }, [isOpen, refreshReferences]);

  // Run button on the Node Edit dialog = verifying a node visit. We emit
  // the node-visit intent only when both IDs are actually populated; before
  // the dialog has a node and the editor has a canonical tree UUID, fall
  // back to reference-test (no record). With both, the host dispatcher
  // routes through NavigationExecutor.execute_single_node_verification and
  // writes a node_metrics row.
  const recordAs: RecordAs = (treeId && nodeForm?.id)
    ? { kind: 'node-visit', treeId, nodeId: nodeForm.id }
    : { kind: 'reference-test' };
  const verification = useVerification({
    captureSourcePath: undefined,
    userinterfaceName: referenceKey,
    verificationPassCondition: nodeForm?.verification_pass_condition || 'all',
    recordAs,
  });

  // Local state for dialog-specific concerns
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Fix loop: Use a ref to track if we've already initialized, preventing re-calls during the same open session.
  // Also, use shallow equality for verifications dep to avoid triggering on new array references.
  const initializedRef = useRef(false);

  useEffect(() => {
    if (isOpen && nodeForm?.verifications && nodeForm.verifications.length > 0) {
      // Only initialize if we haven't already initialized with these exact verifications
      const currentVerifications = verification.verifications || [];
      const nodeFormVerifications = nodeForm.verifications || [];

      if (!initializedRef.current ||
          JSON.stringify(currentVerifications) !== JSON.stringify(nodeFormVerifications)) {
        console.log('[useNodeEdit] Initializing/updating verifications from nodeForm:', nodeForm.verifications);
        verification.handleVerificationsChange(nodeForm.verifications);
        initializedRef.current = true;
      }
    } else if (isOpen) {
      console.log('[useNodeEdit] Dialog opened but no verifications in nodeForm:', nodeForm);
    }

    // Reset ref when dialog closes
    return () => {
      if (!isOpen) {
        initializedRef.current = false;
      }
    };
  }, [isOpen, nodeForm, verification]); // Removed modelReferences dependency

  // Reset state when dialog closes
  useEffect(() => {
    if (!isOpen) {
      setSaveSuccess(false);
      // Don't clear verification state immediately to preserve test results
      // Let the user see results before dialog closes
      setTimeout(() => {
        verification.handleVerificationsChange([]);
      }, 100);
    }
  }, [isOpen, verification]);

  // Handle verification changes
  // In handleVerificationsChange, reuse the existing verifications array if unchanged to avoid new references.
  // This prevents unnecessary effect triggers.
  const handleVerificationsChange = useCallback(
    (newVerifications: Verification[]) => {
      if (!nodeForm) return;

      console.log('[useNodeEdit] Verification changes:', newVerifications);

      // Check if verifications actually changed (shallow compare)
      const isSame = JSON.stringify(nodeForm.verifications) === JSON.stringify(newVerifications);
      if (isSame) return; // Skip update to break potential loops

      setNodeForm({
        ...nodeForm,
        verifications: newVerifications, // Assume caller provides stable reference; don't create new array here
      });
      verification.handleVerificationsChange(newVerifications);
    },
    [nodeForm, setNodeForm, verification],
  );

  // Handle save operation - INCREMENTAL CACHE UPDATE (no rebuild)
  const handleSave = useCallback(async () => {
    if (!nodeForm) {
      console.error('[useNodeEdit] Cannot save: nodeForm is null');
      return;
    }
    
    try {
      // 0. Keep each TEXT verification's reference row in lockstep with the
      //    node's inline snapshot (params.text/area, what actually executes) —
      //    the same unconditional write the VerificationEditor's Save does.
      //
      //    We DON'T gate on the transient text_modified/area_modified UI flags:
      //    those only get set if the user types in the field this session and
      //    can be dropped across re-renders / reopen, so "save the node" would
      //    silently fail to sync (the exact bug we hit). Instead we diff the
      //    inline value against the current reference (from modelReferences,
      //    the same source the editor reads) and push only when they differ —
      //    idempotent, and self-healing for already-diverged rows.
      //
      //    Only TEXT references are handled (they're just text+area, no stored
      //    crop). Image references keep their crop and use the Recapture flow.
      //
      //    saveText proxies to a host (host_name is required by the server-side
      //    proxy). If a divergent text ref needs syncing but no host is
      //    selected we surface it rather than letting the row drift.
      const normCoord = (v: any) => (typeof v === 'number' ? Math.round(v) : (v ?? null));
      const AREA_KEYS = ['x', 'y', 'width', 'height', 'fx', 'fy', 'fwidth', 'fheight'];
      let propagatedReference = false;
      let blockedByNoHost = false;
      if (referenceKey && verification.verifications.length > 0) {
        for (const verif of verification.verifications) {
          if (verif.verification_type !== 'text') continue;

          const params: any = verif.params || {};
          // reference_name in params is the UI internalKey (e.g. "foo_text").
          // It always comes from modelReferences, so the lookup resolves the
          // un-suffixed DB name + the current `shared` flag — both required to
          // update the correct row (and avoid forking a divergent local copy).
          const reference = params.reference_name ? modelReferences[params.reference_name] : undefined;
          // Need a resolved DB name to target the row + key the cache patch.
          if (!reference?.name) continue;
          const refName = reference.name;

          const inlineArea: any = params.area || {};
          const refArea: any = reference.area || {};
          const textDiffers = (params.text || '') !== (reference.text || '');
          const areaDiffers = AREA_KEYS.some(
            (k) => normCoord(inlineArea[k]) !== normCoord(refArea[k]),
          );
          if (!textDiffers && !areaDiffers) continue; // already in sync — no-op

          if (!selectedHost?.host_name) {
            blockedByNoHost = true;
            console.error(
              '[useNodeEdit] ⚠️ Text reference differs from node but no host is selected — ' +
                'cannot propagate to verifications_references.',
            );
            continue;
          }

          console.log('[useNodeEdit] 📝 Syncing text reference:', refName, {
            textDiffers,
            areaDiffers,
            shared: Boolean(reference.shared),
          });

          try {
            await api.post(buildServerUrl('/server/verification/text/saveText'), {
              host_name: selectedHost.host_name,
              reference_name: refName, // un-suffixed DB name
              userinterface_name: referenceKey,
              area: inlineArea,
              text: params.text || '',
              shared: Boolean(reference.shared),
            });
            propagatedReference = true;
            console.log('[useNodeEdit] ✅ Text reference updated:', refName);

            // Patch the in-memory references cache immediately. References are
            // loaded once on Take Control; without this, other surfaces (the
            // in-stream Verification Editor, the node dropdowns) keep showing
            // the pre-edit value until the user releases + re-takes control.
            // addReferenceToCache rewrites state.references[referenceKey][name_text],
            // which flips getModelReferences' identity and re-renders every
            // consumer with the new text/area — no re-take needed.
            addReferenceToCache(referenceKey, {
              name: refName,
              type: 'text',
              url: '', // text references carry no R2 asset
              area: inlineArea,
              text: params.text || '',
              shared: Boolean(reference.shared),
            });
          } catch (err) {
            console.error('[useNodeEdit] Failed to propagate text reference edit:', err);
          }
        }
      }
      if (blockedByNoHost) {
        showError(
          'A text reference differs from this node but no host is selected — the reference ' +
            'was NOT updated. Take control of a host and re-save to keep them in sync.',
        );
      }

      // Filter out invalid/empty verifications before saving
      const validVerifications = (nodeForm.verifications || []).filter((v: any) => {
        // Must have a command (or method)
        const hasCommand = v.command || v.method;
        if (!hasCommand || hasCommand.trim() === '') {
          console.warn('[useNodeEdit] Filtered out verification with missing command:', v);
          return false;
        }
        
        // Type-specific validation
        if (v.verification_type === 'text' && (!v.params?.text || v.params.text.trim() === '')) {
          console.warn('[useNodeEdit] Filtered out text verification with missing text:', v);
          return false;
        }
        
        if (v.verification_type === 'image' && !v.params?.image_path) {
          console.warn('[useNodeEdit] Filtered out image verification with missing image_path:', v);
          return false;
        }
        
        return true;
      });
      
      // Update nodeForm with validated verifications
      const validatedNodeForm = {
        ...nodeForm,
        verifications: validVerifications
      };
      
      console.log(`[useNodeEdit] Validation: ${nodeForm.verifications?.length || 0} → ${validVerifications.length} verifications`);
      
      // 1. Save to database via context
      await saveNodeWithStateUpdate(validatedNodeForm);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 2000);
      
      // 2. Update cache incrementally on all hosts (no rebuild)
      if (treeId) {
        console.log('[useNodeEdit] Updating node in cache for tree:', treeId);
        // Call server to update node in cache on all hosts (buildServerUrl adds team_id automatically)
        try {
          const result = await api.post(buildServerUrl(`/server/navigation/cache/update-node`), {
            node: validatedNodeForm,  // Use validated form
            tree_id: treeId
          });
          console.log('[useNodeEdit] ✅ Node updated in cache (incremental):', result);
        } catch {
          console.error('[useNodeEdit] Failed to update node in cache');
        }
        
        // 3. Invalidate preview cache since node data changed
        invalidateTree(treeId);
        console.log('[useNodeEdit] Preview cache invalidated for tree:', treeId);
      }

      // 4. If we rewrote a reference, refresh the references cache so the
      //    dropdown / VerificationsList auto-resolve see the new text+area and
      //    don't pull the pre-edit value back over the node on the next render.
      if (propagatedReference) {
        try {
          await reloadReferences();
          console.log('[useNodeEdit] ✅ References reloaded after propagation');
        } catch (reloadErr) {
          console.warn('[useNodeEdit] Failed to reload references after propagation:', reloadErr);
        }
      }
    } catch (error) {
      console.error('[useNodeEdit] Failed to save node or update cache:', error);
      throw error;
    }
  }, [nodeForm, saveNodeWithStateUpdate, treeId, invalidateTree, referenceKey, verification.verifications, modelReferences, selectedHost, reloadReferences, addReferenceToCache, showError]);

  // Validate form
  const isFormValid = useCallback(
    (form: NodeForm | null) => {
      if (!form?.label?.trim()) return false;

      return verification.verifications.every((verificationItem) => {
        if (!verificationItem.command) return true;

        if (verificationItem.verification_type === 'image') {
          return Boolean(verificationItem.params?.image_path);
        } else if (verificationItem.verification_type === 'text') {
          return Boolean(verificationItem.params?.text);
        }

        return true;
      });
    },
    [verification.verifications],
  );


  // Get parent names from parent IDs. Falls back to parentChain (ancestor
  // trees) so a subtree node still resolves "home > home_apps" instead of
  // showing raw UUIDs for parents that live in the root tree.
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

  // Check button visibility
  const getButtonVisibility = useCallback(() => {
    return {
      canRunGoto: isControlActive && Boolean(selectedHost),
      canTest: isControlActive && Boolean(selectedHost) && verification.verifications.length > 0,
    };
  }, [isControlActive, selectedHost, verification.verifications.length]);

  // Handle screenshot deletion from R2
  const handleDeleteScreenshot = useCallback(async () => {
    if (!nodeForm?.screenshot) {
      console.log('[useNodeEdit] No screenshot to delete');
      return;
    }

    try {
      console.log('[useNodeEdit] Deleting screenshot:', nodeForm.screenshot);
      
      // Call delete endpoint
      const result = await api.post(buildServerUrl('/server/navigation/screenshot/delete'), {
        screenshot_url: nodeForm.screenshot
      });
      console.log('[useNodeEdit] ✅ Screenshot deleted:', result);
      
      // Clear screenshot field in form
      setNodeForm({
        ...nodeForm,
        screenshot: ''
      });
      
      // Update visual node immediately
      if (onUpdateNode && nodeForm.id) {
        onUpdateNode(nodeForm.id, { screenshot: '' });
      }
      
      // Auto-save the node with empty screenshot
      await saveNodeWithStateUpdate({
        ...nodeForm,
        screenshot: ''
      });
      
      console.log('[useNodeEdit] ✅ Node updated with empty screenshot');
      
    } catch (error) {
      console.error('[useNodeEdit] Error deleting screenshot:', error);
      throw error;
    }
  }, [nodeForm, setNodeForm, saveNodeWithStateUpdate]);

  return {
    // Verification
    verification,
    handleVerificationsChange,

    // Model references for verification dropdown
    modelReferences,
    referencesLoading,

    // Form validation and actions
    handleSave,
    isFormValid,
    saveSuccess,
    
    // Screenshot management
    handleDeleteScreenshot,

    // Utilities
    getParentNames,
    getButtonVisibility,
  };
};
