import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useDeviceData } from '../../contexts/device/DeviceDataContext';
import { useNavigation } from '../../contexts/navigation/NavigationContext';
import { Host } from '../../types/common/Host_Types';
import { Action, ActionSet, EdgeForm, UINavigationEdge } from '../../types/pages/Navigation_Types';
import { useEdge } from './useEdge';
import { useVerification } from '../verification/useVerification';

const DIRECTION_FORWARD = 'forward';
const DIRECTION_INDEX_FORWARD = 0;
const DIRECTION_INDEX_REVERSE = 1;

export interface UseEdgeEditProps {
  isOpen: boolean;
  edgeForm: EdgeForm | null;
  setEdgeForm: (form: EdgeForm) => void;
  selectedEdge?: UINavigationEdge | null;
  selectedHost?: Host | null;
  isControlActive?: boolean;
}

export const useEdgeEdit = ({
  isOpen,
  edgeForm,
  setEdgeForm,
  selectedEdge,
  selectedHost,
  isControlActive = false,
}: UseEdgeEditProps) => {

  // Get navigation context for save. saveEdgeWithStateUpdate owns the
  // /cache/update-edge fan-out — do not call it from here too.
  const { saveEdgeWithStateUpdate, userInterface } = useNavigation();

  // Get device data context for model references
  const { getModelReferences, referencesLoading, references, refreshReferences } = useDeviceData();

  // Use userinterface name for reference lookup
  const referenceKey = userInterface?.name;

  // Get model references using the userinterface name
  const modelReferences = useMemo(() => {
    if (!referenceKey) return {};
    return getModelReferences(referenceKey);
  }, [getModelReferences, referenceKey, references]);

  // Re-fetch references every time the dialog opens so references created
  // elsewhere (e.g. captured in the stream panel's Verification Editor) while
  // this dialog was closed appear without a page refresh. Uses refreshReferences
  // (honours the server's 60s cache) NOT reloadReferences (busts it) — busting
  // on every open caused fresh DB queries and the multi-minute loading hang.
  // Mirrors useNodeEdit.
  useEffect(() => {
    if (isOpen) {
      void refreshReferences();
    }
  }, [isOpen, refreshReferences]);

  // Verification hook for managing KPI reference verifications. The Edge
  // edit dialog uses these to test whether the chosen images / texts
  // produce a measurable KPI signal — not to verify a node visit. The
  // dispatcher runs the primitive only (no DB write).
  const verification = useVerification({
    captureSourcePath: undefined,
    userinterfaceName: referenceKey,
    recordAs: { kind: 'kpi-test' },
  });

  // Edge hook for loading actions from IDs
  const edgeHook = useEdge({
    selectedHost,
    isControlActive,
  });

  // Local state for dialog-specific concerns
  const [localActions, setLocalActions] = useState<Action[]>([]);
  const [localRetryActions, setLocalRetryActions] = useState<Action[]>([]);
  const [localFailureActions, setLocalFailureActions] = useState<Action[]>([]);
  const [dependencyCheckResult, setDependencyCheckResult] = useState<any>(null);
  
  // Track if we're currently updating from user edits to prevent reload loop
  const isUserEditRef = useRef(false);
  
  // Track the edge ID to detect when we switch to a different edge
  const prevEdgeIdRef = useRef<string | null>(null);

  // Initialize actions when dialog opens - FIXED: Support both unidirectional (1 action set) and bidirectional (2 action sets)
  useEffect(() => {
    console.log('[@useEdgeEdit] useEffect triggered:', { 
      isOpen, 
      isUserEdit: isUserEditRef.current,
      edgeId: edgeForm?.edgeId,
      prevEdgeId: prevEdgeIdRef.current,
      direction: edgeForm?.direction,
      actionSetsLength: edgeForm?.action_sets?.length
    });
    
    // Skip reload if this is a user edit (not a new edge or direction change)
    if (isUserEditRef.current) {
      console.log('[@useEdgeEdit] Skipping reload - user edit in progress');
      isUserEditRef.current = false;
      return;
    }
    
    // Detect edge change
    const currentEdgeId = edgeForm?.edgeId;
    if (currentEdgeId && prevEdgeIdRef.current !== currentEdgeId) {
      console.log('[@useEdgeEdit] Edge changed:', { from: prevEdgeIdRef.current, to: currentEdgeId });
      prevEdgeIdRef.current = currentEdgeId;
      // Continue to load - new edge selected
    }
    if (isOpen && edgeForm?.action_sets && edgeForm.action_sets.length >= 1) {
      const direction = edgeForm.direction || DIRECTION_FORWARD;
      const actionSetIndex = edgeForm.action_sets.length === 1
        ? DIRECTION_INDEX_FORWARD
        : (direction === DIRECTION_FORWARD ? DIRECTION_INDEX_FORWARD : DIRECTION_INDEX_REVERSE);
      const actionSet = edgeForm.action_sets[actionSetIndex];
      
      console.log('[@useEdgeEdit] Loading action set for direction:', direction, actionSet.id, { 
        isUnidirectional: edgeForm.action_sets.length === 1,
        actionSetIndex,
        actions: actionSet.actions?.length || 0, 
        retry_actions: actionSet.retry_actions?.length || 0,
        failure_actions: actionSet.failure_actions?.length || 0
      });
      console.log('[@useEdgeEdit] Loaded actions detail from edgeForm:', JSON.stringify(actionSet.actions, null, 2));
      
      setLocalActions(actionSet.actions || []);
      setLocalRetryActions(actionSet.retry_actions || []);
      setLocalFailureActions(actionSet.failure_actions || []);
    } else if (isOpen && selectedEdge?.data?.action_sets?.[0]) {
      // Fallback: Load actions from selectedEdge if form doesn't have them
      const actionSet = selectedEdge.data.action_sets[0];
      console.log('[@useEdgeEdit] Loading from selectedEdge (fallback):', { 
        actions: actionSet.actions?.length || 0, 
        retry_actions: actionSet.retry_actions?.length || 0,
        failure_actions: actionSet.failure_actions?.length || 0
      });
      setLocalActions(actionSet.actions || []);
      setLocalRetryActions(actionSet.retry_actions || []);
      setLocalFailureActions(actionSet.failure_actions || []);

      // Update the form with the loaded actions
      if (edgeForm && edgeForm.action_sets) {
        const updatedActionSets = [...edgeForm.action_sets];
        if (updatedActionSets[0]) {
          updatedActionSets[0] = {
            ...updatedActionSets[0],
            actions: actionSet.actions || [],
            retry_actions: actionSet.retry_actions || [],
            failure_actions: actionSet.failure_actions || []
          };
        }
        // Remove setEdgeForm call to prevent infinite loop
        // The form will be updated when saving, not during initialization
      }
    }
  }, [isOpen, edgeForm?.direction, edgeForm?.action_sets, edgeForm?.edgeId]);

  // Reset state when dialog closes
  useEffect(() => {
    if (!isOpen) {
      setLocalActions([]);
      setLocalRetryActions([]);
      setDependencyCheckResult(null);
    }
  }, [isOpen]);

  // Check dependencies for actions - SIMPLIFIED: Legacy action_ids removed, actions are now embedded in action_sets
  const checkDependencies = useCallback(async (_actions: Action[]): Promise<any> => {
    // Since actions are now embedded within action_sets in each edge, there are no shared dependencies
    console.log('[@hook:useEdgeEdit] Dependency check skipped - actions are embedded in action_sets');
    return { success: true, has_shared_actions: false, edges: [], count: 0 };
  }, []);

  // Handle actions change - SIMPLIFIED DIRECTION-BASED
  const handleActionsChange = useCallback(
    (newActions: Action[]) => {
      console.log('[@useEdgeEdit:handleActionsChange] Called with actions:', newActions.length);
      console.log('[@useEdgeEdit:handleActionsChange] Actions detail:', JSON.stringify(newActions, null, 2));
      if (!edgeForm) return;

      setLocalActions(newActions);
      
      // Mark as user edit to prevent reload loop
      console.log('[@useEdgeEdit:handleActionsChange] Setting isUserEditRef = true');
      isUserEditRef.current = true;
      
      const direction = edgeForm.direction || DIRECTION_FORWARD;
      const targetIndex = direction === DIRECTION_FORWARD ? DIRECTION_INDEX_FORWARD : DIRECTION_INDEX_REVERSE;
      const updatedActionSets = [...(edgeForm.action_sets || [])];
      if (updatedActionSets[targetIndex]) {
        updatedActionSets[targetIndex] = { ...updatedActionSets[targetIndex], actions: newActions };
      }
      console.log('[@useEdgeEdit:handleActionsChange] Updated action_sets:', JSON.stringify(updatedActionSets, null, 2));
      console.log('[@useEdgeEdit:handleActionsChange] Updating edgeForm, isUserEditRef =', isUserEditRef.current);
      setEdgeForm({
        ...edgeForm,
        action_sets: updatedActionSets,
      });
    },
    [edgeForm, setEdgeForm],
  );

  // Handle retry actions change - SIMPLIFIED DIRECTION-BASED
  const handleRetryActionsChange = useCallback(
    (newRetryActions: Action[]) => {
      if (!edgeForm) return;

      setLocalRetryActions(newRetryActions);
      isUserEditRef.current = true;
      const direction = edgeForm.direction || DIRECTION_FORWARD;
      const targetIndex = direction === DIRECTION_FORWARD ? DIRECTION_INDEX_FORWARD : DIRECTION_INDEX_REVERSE;
      
      const updatedActionSets = [...(edgeForm.action_sets || [])];
      if (updatedActionSets[targetIndex]) {
        updatedActionSets[targetIndex] = { 
          ...updatedActionSets[targetIndex], 
          retry_actions: newRetryActions 
        };
      }
      
      setEdgeForm({
        ...edgeForm,
        action_sets: updatedActionSets,
      });
    },
    [edgeForm, setEdgeForm],
  );

  // Handle failure actions change - SIMPLIFIED DIRECTION-BASED
  const handleFailureActionsChange = useCallback(
    (newFailureActions: Action[]) => {
      if (!edgeForm) return;

      setLocalFailureActions(newFailureActions);
      isUserEditRef.current = true;
      const direction = edgeForm.direction || DIRECTION_FORWARD;
      const targetIndex = direction === DIRECTION_FORWARD ? DIRECTION_INDEX_FORWARD : DIRECTION_INDEX_REVERSE;
      
      const updatedActionSets = [...(edgeForm.action_sets || [])];
      if (updatedActionSets[targetIndex]) {
        updatedActionSets[targetIndex] = { 
          ...updatedActionSets[targetIndex], 
          failure_actions: newFailureActions 
        };
      }
      
      setEdgeForm({
        ...edgeForm,
        action_sets: updatedActionSets,
      });
    },
    [edgeForm, setEdgeForm],
  );

  // Handle KPI reference change for specific action set
  const handleKpiReferencesChange = useCallback(
    (actionSetIndex: number, newKpiReferences: any[]) => {
      if (!edgeForm) return;

      // Mark as user edit to prevent reload loop
      isUserEditRef.current = true;

      const updatedActionSets = [...(edgeForm.action_sets || [])];
      if (updatedActionSets[actionSetIndex]) {
        updatedActionSets[actionSetIndex] = {
          ...updatedActionSets[actionSetIndex],
          kpi_references: newKpiReferences
        };
      }

      setEdgeForm({
        ...edgeForm,
        action_sets: updatedActionSets,
      });
    },
    [edgeForm, setEdgeForm],
  );

  // Handle use_verifications_for_kpi flag change for specific action set
  const handleUseVerificationsForKpiChange = useCallback(
    (actionSetIndex: number, useVerifications: boolean) => {
      if (!edgeForm) return;

      // Mark as user edit to prevent reload loop
      isUserEditRef.current = true;

      const updatedActionSets = [...(edgeForm.action_sets || [])];
      if (updatedActionSets[actionSetIndex]) {
        updatedActionSets[actionSetIndex] = {
          ...updatedActionSets[actionSetIndex],
          use_verifications_for_kpi: useVerifications
        };
      }

      setEdgeForm({
        ...edgeForm,
        action_sets: updatedActionSets,
      });
    },
    [edgeForm, setEdgeForm],
  );

  // Execute local actions - simple wrapper around edge hook
  const executeLocalActions = useCallback(async () => {
    if (!selectedEdge) return;
    return await edgeHook.executeEdgeActions(selectedEdge, localActions, localRetryActions, localFailureActions);
  }, [edgeHook, selectedEdge, localActions, localRetryActions, localFailureActions]);

  // Validate form
  const isFormValid = useCallback((): boolean => {
    return localActions.every((action) => {
      if (!action.command || action.command.trim() === '') {
        return false;
      }

      // Check required parameters based on command using type assertion
      const params = action.params as any;

      if (action.command === 'input_text' && (!params?.text || params.text.trim() === '')) {
        return false;
      }
      if (
        action.command === 'click_element' &&
        (!params?.element_id || params.element_id.trim() === '')
      ) {
        return false;
      }
      if (
        (action.command === 'launch_app' || action.command === 'close_app') &&
        (!params?.package || params.package.trim() === '')
      ) {
        return false;
      }
      if (
        action.command === 'tap_coordinates' &&
        (params?.x === undefined || params?.y === undefined)
      ) {
        return false;
      }

      return true;
    });
  }, [localActions]);

  // Handle save operation - INCREMENTAL CACHE UPDATE (no rebuild)
  const handleSave = useCallback(async () => {
    if (!edgeForm) {
      console.error('[useEdgeEdit] Cannot save: edgeForm is null');
      return;
    }
    
    try {
      // Filter out empty actions from all action sets before saving
      const validatedActionSets = (edgeForm.action_sets || []).map((actionSet: ActionSet) => {
        return {
          ...actionSet,
          actions: (actionSet.actions || []).filter((action: Action) => {
            // Must have a command
            if (!action.command || action.command.trim() === '') {
              console.warn('[useEdgeEdit] Filtered out action with missing command:', action);
              return false;
            }
            return true;
          }),
          retry_actions: (actionSet.retry_actions || []).filter((action: Action) => {
            if (!action.command || action.command.trim() === '') {
              console.warn('[useEdgeEdit] 🛡️ Filtered out retry action with missing command:', action);
              return false;
            }
            return true;
          }),
          failure_actions: (actionSet.failure_actions || []).filter((action: Action) => {
            if (!action.command || action.command.trim() === '') {
              console.warn('[useEdgeEdit] 🛡️ Filtered out failure action with missing command:', action);
              return false;
            }
            return true;
          })
        };
      });
      
      // Update edgeForm with validated action sets
      const validatedEdgeForm = {
        ...edgeForm,
        action_sets: validatedActionSets
      };
      
      const totalBefore = (edgeForm.action_sets || []).reduce((sum, as) => 
        sum + (as.actions?.length || 0) + (as.retry_actions?.length || 0) + (as.failure_actions?.length || 0), 0);
      const totalAfter = validatedActionSets.reduce((sum, as) => 
        sum + (as.actions?.length || 0) + (as.retry_actions?.length || 0) + (as.failure_actions?.length || 0), 0);
      
      console.log(`[useEdgeEdit] Validation: ${totalBefore} → ${totalAfter} actions across all sets`);
      
      // Save to database via context. NavigationContext.saveEdgeWithStateUpdate
      // owns the host cache-update call (it passes skipCacheUpdate:true to the
      // inner POST and then fires /cache/update-edge itself), so we must NOT
      // fire it from here too — that produced the duplicate POST seen in logs.
      console.log('[useEdgeEdit] 💾 Saving edge to database:', validatedEdgeForm.edgeId);
      await saveEdgeWithStateUpdate(validatedEdgeForm);
      console.log('[useEdgeEdit] ✅ Edge saved to database');
    } catch (error) {
      console.error('[useEdgeEdit] ❌ Failed to save edge:', error);
      throw error;
    }
  }, [edgeForm, saveEdgeWithStateUpdate]);

  // Use edgeHook.canRunActions directly instead of duplicating logic

  return {
    // Action execution
    executeLocalActions,
    checkDependencies,

    // Local state
    localActions,
    localRetryActions,
    localFailureActions,
    dependencyCheckResult,

    // Handlers
    handleActionsChange,
    handleRetryActionsChange,
    handleFailureActionsChange,
    handleKpiReferencesChange,
    handleUseVerificationsForKpiChange,

    // Verification (for KPI references)
    verification,
    modelReferences,
    referencesLoading,

    // Validation & Save (aligned with useNodeEdit)
    isFormValid,
    handleSave,
  };
};
