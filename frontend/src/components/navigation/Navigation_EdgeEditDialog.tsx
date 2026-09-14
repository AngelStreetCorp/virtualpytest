import CloseIcon from '@mui/icons-material/Close';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import ContentPasteIcon from '@mui/icons-material/ContentPaste';
import {
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Button,
  Box,
  Typography,
  IconButton,
  CircularProgress,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  LinearProgress,
  Checkbox,
  FormControlLabel,
  Menu,
  Tooltip,
} from '@mui/material';
import React, { useState, useMemo, useRef, useEffect } from 'react';

import { useEdgeEdit } from '../../hooks/navigation/useEdgeEdit';
import { useEdge } from '../../hooks/navigation/useEdge';
import { useNavigation } from '../../contexts/navigation/NavigationContext';
import { useDeviceData } from '../../contexts/device/DeviceDataContext';
import { useUserInterfaceVariants } from '../../hooks/userinterface/useUserInterfaceVariants';
import { useToast } from '../../hooks/useToast';
import { useConfirmDialog } from '../../hooks/useConfirmDialog';
import { ConfirmDialog } from '../common/ConfirmDialog';
import { Host } from '../../types/common/Host_Types';
import {
  EdgeForm,
  EdgeVariantOverride,
  UINavigationEdge,
} from '../../types/pages/Navigation_Types';
import {
  computeConditionalEdgeIds,
  getConditionalRole,
  forwardActionListsEqual,
  findConditionalOwnerForward,
} from '../../utils/conditionalEdgeUtils';
import { getZIndex } from '../../utils/zIndexUtils';
import { ActionsList } from '../actions';
import { ActionDependencyDialog } from '../actions/ActionDependencyDialog';
import { VerificationsList } from '../verification/VerificationsList';
import { StyledDialog } from '../common/StyledDialog';
import {
  Navigation_VariantToggle,
  type VariantScope,
} from './Navigation_VariantToggle';

type ActionRunSection = 'all' | 'main' | 'retry' | 'failure';

/** Deep clone via JSON — variant data is plain JSONB so this is safe. */
const deepClone = <T,>(value: T): T =>
  value === undefined || value === null ? value : (JSON.parse(JSON.stringify(value)) as T);

// Cross-edge action clipboard. Lives in sessionStorage so it survives closing
// one edge dialog and opening another (and dialog remounts), but clears when
// the tab closes. Copy stores the CURRENT direction's actions; Paste applies
// them to the open edge's current direction.
const EDGE_ACTION_CLIPBOARD_KEY = 'edge_action_clipboard_v1';

interface EdgeActionClipboard {
  actions: any[];
  retry_actions: any[];
  failure_actions: any[];
  final_wait_time?: number;
  sourceLabel?: string;
  // Identify the exact action set the copy came from so Paste can be disabled
  // on that same edge+direction (pasting onto the source is a no-op).
  sourceEdgeId?: string;
  sourceActionSetIndex?: number;
}

interface EdgeEditDialogProps {
  isOpen: boolean;
  edgeForm: EdgeForm | null;
  setEdgeForm: React.Dispatch<React.SetStateAction<EdgeForm | null>>;
  onSubmit: (formData: any) => void;
  onClose: () => void;
  selectedEdge?: UINavigationEdge | null;
  isControlActive?: boolean;
  selectedHost?: Host | null;
  selectedDeviceId?: string | null;
  fromLabel?: string;
  toLabel?: string;
  model?: string; // Device model for verifications
  /**
   * Canvas viewer scope at the moment the dialog opened. The dialog seeds
   * its local variantScope from this so "Edit while viewing variant X"
   * defaults to editing that variant.
   * (See docs/agent/ENHANCE_VARIANT.md §3.2.)
   */
  initialVariantScope?: string | null;
  /**
   * Effective (persisted + canvas-STAGED) per-variant override entry for THIS
   * edge, keyed by variant name. The canvas stages override edits until Save
   * (NavigationEditor.stagedOverrideEdits); registeredVariants only carries
   * the persisted maps, so without this the dialog seeds a variant scope from
   * STALE persisted content (e.g. old actions after a staged redraw-over-
   * deleted edge, while the canvas panel already shows the staged empties).
   */
  effectiveEdgeOverrides?: Record<string, EdgeVariantOverride>;
  /**
   * Called after this dialog PERSISTS (or deletes) a variant's override for
   * this edge, so the canvas can drop its STAGED copy of that entry —
   * otherwise the next canvas Save re-merges the stale staged entry over
   * what the dialog just saved.
   */
  onVariantOverrideCommitted?: (variantName: string, edgeId: string) => void;
  sx?: any; // Additional styles for the dialog
}

export const EdgeEditDialog: React.FC<EdgeEditDialogProps> = ({
  isOpen,
  edgeForm,
  setEdgeForm,
  onSubmit: _onSubmit,
  onClose,
  selectedEdge: _selectedEdge,
  isControlActive = false,
  selectedHost,
  selectedDeviceId,
  fromLabel = '',
  toLabel = '',
  model = 'android_mobile',
  initialVariantScope = null,
  effectiveEdgeOverrides,
  onVariantOverrideCommitted,
  sx,
}) => {
  // State for dependency dialog
  const [dependencyDialogOpen, setDependencyDialogOpen] = useState(false);
  const [dependencyEdges, setDependencyEdges] = useState<any[]>([]);
  const [pendingSubmit, setPendingSubmit] = useState<any>(null);
  const [isCheckingDependencies, setIsCheckingDependencies] = useState(false);
  const [runningAction, setRunningAction] = useState<{ section: ActionRunSection; index: number | null } | null>(null);
  const [runStatusBySection, setRunStatusBySection] = useState<{
    main: Record<number, 'success' | 'failure'>;
    retry: Record<number, 'success' | 'failure'>;
    failure: Record<number, 'success' | 'failure'>;
  }>({
    main: {},
    retry: {},
    failure: {},
  });
  const runStatusTimeoutsRef = useRef<number[]>([]);

  const edgeEdit = useEdgeEdit({
    isOpen,
    edgeForm,
    setEdgeForm,
    selectedEdge: _selectedEdge,
    selectedHost,
    isControlActive,
  });

  // Add the same edge hook used by the Edge Selection Panel
  const edgeHook = useEdge({
    selectedHost: selectedHost || null,
    selectedDeviceId: selectedDeviceId || null,
    isControlActive,
  });

  // ─── Variant scope plumbing (per-variant overrides model) ─────────────
  const {
    userInterface,
    edges: rawEdges,
    setSelectedEdge: setSelectedEdgeInContext,
  } = useNavigation();
  const userinterfaceId = userInterface?.id || null;
  const { variants: registeredVariants, updateVariantOverrides, refresh: refreshVariants } =
    useUserInterfaceVariants(userinterfaceId);

  // Action dropdowns and reference selects bind to DeviceDataContext. When
  // the dialog opens before the first fetch lands, saved commands appear
  // "unmatched" (warning triangle) and reference selects are empty until
  // the data arrives a moment later. Gate the form on those loading flags
  // so we show a spinner instead of a half-populated form.
  //
  // We INTENTIONALLY only gate on the explicit `*Loading` booleans — do NOT
  // also gate on `Object.keys(availableActions).length === 0`. The host can
  // legitimately return without device schemas (e.g. the schemas-on-2nd-push
  // pattern documented in DeviceDataContext) and end up at
  // `availableActionsLoading: false, availableActions: {}` indefinitely; any
  // emptiness-based gate then spins forever (seen after variant override
  // PUTs invalidated host caches, 2026-05-20).
  const {
    availableActionsLoading,
    referencesLoading,
    availableVerificationTypesLoading,
  } = useDeviceData();
  const isInitialDataLoading =
    availableActionsLoading ||
    referencesLoading ||
    availableVerificationTypesLoading;
  const { showSuccess: showToastSuccess, showError: showToastError } = useToast();
  const { dialogState, confirm, handleConfirm, handleCancel } = useConfirmDialog();

  const [variantScope, setVariantScope] = useState<VariantScope>('base');
  const [localOverrides, setLocalOverrides] = useState<Record<string, EdgeVariantOverride>>({});
  const dirtyVariantsRef = useRef<Set<string>>(new Set());

  // A variant-only edge (`hidden_in_base`) is OWNED by its variant scope — there
  // is no base version to protect, so it must be fully editable and its edits
  // write to the edge's OWN columns, never a variant override (the owning
  // variant falls through to base data — see VARIANT.md §5). Mirrors the node
  // dialog + useResolvedTree's isOwnedByCurrentScope.
  const edgeHiddenInBase = (edgeForm as any)?.hidden_in_base === true;
  const isVariantOnlyOwned =
    variantScope !== 'base' &&
    edgeHiddenInBase &&
    localOverrides[variantScope]?.disabled !== true;
  // Owned variant-only edges are edited like base: write base columns, no override.
  const editsBaseColumns = variantScope === 'base' || isVariantOnlyOwned;

  // Stable snapshot of the base action_sets at dialog open. Used as the
  // canonical "base" value when the user toggles scopes or commits a variant
  // override; never written into a variant entry directly.
  const baseActionSetsRef = useRef<any[]>([]);

  // Initialise local override map + scope when dialog opens / target edge changes.
  useEffect(() => {
    if (!isOpen || !edgeForm?.edgeId) return;
    // TRUE base comes from the raw edges store. `_selectedEdge` is the
    // canvas-RESOLVED edge — when the canvas is on a variant with a content
    // override, its action_sets are the variant-patched view; snapshotting
    // that as "base" made the Base scope show VARIANT content (and the
    // variant scope, seeded from the stale persisted entry, show base's —
    // the inverted dialog). Same rule as handleResetVariant /
    // refreshSelectedEdgeForCanvasScope below.
    const rawEdgeAtOpen = rawEdges.find((e) => e.id === edgeForm.edgeId);
    const originalBase =
      ((rawEdgeAtOpen?.data as any)?.action_sets as any[]) ||
      (_selectedEdge?.data?.action_sets as any[]) ||
      [];
    baseActionSetsRef.current = deepClone(originalBase);

    const map: Record<string, EdgeVariantOverride> = {};
    for (const v of registeredVariants) {
      // Prefer the effective entry (persisted + canvas-staged) when the
      // canvas provides it — the persisted map alone can be stale.
      const entry = effectiveEdgeOverrides
        ? effectiveEdgeOverrides[v.name]
        : (v.edge_overrides as any)?.[edgeForm.edgeId];
      if (entry) map[v.name] = deepClone(entry);
    }
    setLocalOverrides(map);
    dirtyVariantsRef.current = new Set();

    const desiredScope: VariantScope =
      initialVariantScope &&
      initialVariantScope !== 'base' &&
      registeredVariants.some((v) => v.name === initialVariantScope)
        ? initialVariantScope
        : 'base';
    setVariantScope(desiredScope);

    if (desiredScope !== 'base') {
      const entry = map[desiredScope];
      const entryActionSets = entry?.action_sets;
      // Only treat the variant's action_sets as a real override when it's a
      // NON-EMPTY array. An empty array means "no real override" — fall
      // through to base. (Treating empty as override leads to self-
      // perpetuating empties: dialog loads [], save writes [], next open
      // shows []. See the 2026-05-12 variant-test1 incident.)
      const initial =
        Array.isArray(entryActionSets) && entryActionSets.length > 0
          ? deepClone(entryActionSets as any[])
          : deepClone(originalBase);
      setEdgeForm({ ...edgeForm, action_sets: initial });
    }
  }, [isOpen, edgeForm?.edgeId]);

  const handleVariantScopeChange = (next: VariantScope) => {
    if (next === variantScope) return;
    if (!edgeForm) {
      setVariantScope(next);
      return;
    }
    const base = baseActionSetsRef.current;
    const formActionSets = (edgeForm.action_sets as any[]) || [];

    // Stash the form's current contents as the leaving scope's override —
    // same write rules as routeFormForVariantScope (no empty arrays, no
    // entry when form deep-equals base).
    let nextLocal = localOverrides;
    if (variantScope !== 'base') {
      const existing = localOverrides[variantScope];
      if (existing?.disabled !== true) {
        let leavingEntry: EdgeVariantOverride | undefined;
        if (formActionSets.length === 0) {
          leavingEntry = undefined;
        } else if (JSON.stringify(formActionSets) === JSON.stringify(base)) {
          leavingEntry = undefined;
        } else {
          // Spread the existing entry so non-content flags (drawn_reversed)
          // survive a rewrite of the action_sets.
          leavingEntry = { ...(existing || {}), action_sets: deepClone(formActionSets) };
        }
        if (leavingEntry === undefined) {
          const { [variantScope]: _removed, ...rest } = localOverrides;
          void _removed;
          nextLocal = rest;
        } else {
          nextLocal = { ...localOverrides, [variantScope]: leavingEntry };
        }
        dirtyVariantsRef.current.add(variantScope);
      }
    }

    // Load the entering scope's content: base if scope==='base', else the
    // variant's full action_sets if it has one (non-empty), else fall through
    // to base.
    let nextActionSets: any[];
    if (next === 'base') {
      nextActionSets = deepClone(base);
    } else {
      const entry = nextLocal[next];
      const entryActionSets = entry?.action_sets;
      nextActionSets =
        Array.isArray(entryActionSets) && entryActionSets.length > 0
          ? deepClone(entryActionSets as any[])
          : deepClone(base);
    }
    setLocalOverrides(nextLocal);
    setEdgeForm({ ...edgeForm, action_sets: nextActionSets });
    setVariantScope(next);
  };

  // ─── Replicate ▾ menu (per-row) ───────────────────────────────────────
  const [replicateAnchor, setReplicateAnchor] = useState<HTMLElement | null>(null);
  const replicateMenuOpen = Boolean(replicateAnchor);

  const replicateTargets = useMemo(() => {
    return registeredVariants
      .map((v) => v.name)
      .filter((name) => name !== variantScope);
  }, [registeredVariants, variantScope]);

  const openReplicateMenu = (e: React.MouseEvent<HTMLElement>) => {
    setReplicateAnchor(e.currentTarget);
  };
  const closeReplicateMenu = () => setReplicateAnchor(null);

  const performReplicate = (target: string) => {
    const source: VariantScope = variantScope;
    const base = baseActionSetsRef.current;
    const formActionSets = (edgeForm?.action_sets as any[]) || [];

    let newEntry: EdgeVariantOverride;
    if (source === 'base') {
      // Copy base's full action_sets onto the target variant.
      newEntry = { action_sets: deepClone(base) };
    } else {
      const sourceEntry = localOverrides[source];
      if (!sourceEntry) return;
      if (sourceEntry.disabled === true) {
        newEntry = { disabled: true };
      } else {
        // Take the form's live content (it's the source variant's view).
        newEntry = { action_sets: deepClone(formActionSets) };
      }
    }

    setLocalOverrides((m) => ({ ...m, [target]: newEntry }));
    dirtyVariantsRef.current.add(target);
    showToastSuccess(`Replicated to '${target}' on this edge.`);
  };

  const handlePickReplicate = (target: string) => {
    closeReplicateMenu();
    const exists = Boolean(localOverrides[target]);
    const sourceLabel = variantScope === 'base' ? 'Base' : variantScope;

    const doConfirm = () => {
      confirm({
        title: 'Replicate variant',
        message: `Replicate this edge's '${sourceLabel}' overrides to variant '${target}'?`,
        confirmText: 'Replicate',
        cancelText: 'Cancel',
        confirmColor: 'primary',
        onConfirm: () => performReplicate(target),
      });
    };

    if (exists) {
      confirm({
        title: 'Variant entry already exists',
        message: `Variant '${target}' already has overrides on this edge. Replace?`,
        confirmText: 'Replace',
        cancelText: 'Cancel',
        confirmColor: 'warning',
        onConfirm: doConfirm,
      });
    } else {
      doConfirm();
    }
  };

  // ─── Reset variant override (this edge only) ──────────────────────────
  // Clear THIS edge's entry from the active variant's `edge_overrides` map
  // so the edge falls through to Base for that variant. Other edges on the
  // same variant are untouched. Only shown when scope !== 'base'.
  //
  // Executes immediately on click — the toast is the user-visible feedback.
  // No confirm modal: layering a modal on top of an already-modal dialog
  // both flashes weirdly and is overkill for a reversible action (the user
  // can just re-edit the variant to recreate the override).
  const handleResetVariant = async () => {
    if (variantScope === 'base' || !edgeForm?.edgeId) return;
    const edgeId = edgeForm.edgeId;
    const variant = registeredVariants.find((v) => v.name === variantScope);
    if (!variant) return;

    try {
      const nextMap: Record<string, EdgeVariantOverride> = { ...(variant.edge_overrides || {}) };
      delete nextMap[edgeId];
      await updateVariantOverrides(variantScope, { edge_overrides: nextMap });
      // Drop any STAGED copy of this entry too, or the next canvas Save
      // would resurrect the override that was just reset.
      if (onVariantOverrideCommitted) onVariantOverrideCommitted(variantScope, edgeId);

      // Drop the in-memory entry and clear the dirty flag so a subsequent
      // Save doesn't re-write the deleted key.
      setLocalOverrides((prev) => {
        const { [variantScope]: _removed, ...rest } = prev;
        void _removed;
        return rest;
      });
      dirtyVariantsRef.current.delete(variantScope);

      // Push a fresh resolved edge so the Edge Selection panel reflects
      // Base content. `_selectedEdge` is the canvas-RESOLVED edge — its
      // `data.action_sets` is the variant-patched view (and so is the
      // captured `baseActionSetsRef.current` when the dialog opened in
      // a variant scope). Pull the TRUE base from the raw `edges` array
      // in NavigationContext, which is the canonical pre-resolution
      // store and is what `useResolvedTree` feeds from.
      if (_selectedEdge && initialVariantScope === variantScope) {
        const rawEdge = rawEdges.find((e) => e.id === edgeId);
        const trueBaseActionSets = (rawEdge?.data as any)?.action_sets || [];
        const newResolvedEdge: UINavigationEdge = {
          ..._selectedEdge,
          data: {
            ...(_selectedEdge.data || {}),
            action_sets: deepClone(trueBaseActionSets),
          },
        } as UINavigationEdge;
        setSelectedEdgeInContext(newResolvedEdge);
      }

      showToastSuccess(`Reset '${variantScope}' override on this edge.`);
      onClose();
    } catch (err) {
      showToastError(
        `Failed to reset variant: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  };

  // Filter available verifications for KPI - only show wait functions (same as NodeEditDialog)
  const kpiAvailableVerifications = useMemo(() => {
    const allowedKpiCommands = [
      'waitForImageToAppear',
      'waitForImageToDisappear',
      'waitForImageToAppearThenDisappear',
      'waitForIconToAppear',
      'waitForIconToDisappear',
      'waitForIconToAppearThenDisappear',
      'waitForTextToAppear',
      'waitForTextToDisappear',
      'waitForTextToAppearThenDisappear'
    ];

    const filtered: Record<string, any> = {};

    // Get verifications from edgeEdit verification hook
    const availableTypes = edgeEdit.verification?.availableVerificationTypes || {};

    Object.entries(availableTypes).forEach(([category, verifications]) => {
      if (Array.isArray(verifications)) {
        const filteredVerifications = verifications.filter((v: any) =>
          allowedKpiCommands.includes(v.command)
        );

        if (filteredVerifications.length > 0) {
          filtered[category] = filteredVerifications;
        }
      }
    });

    return filtered;
  }, [edgeEdit.verification]);

  // Check if form has actions - same logic as EdgeSelectionPanel
  const hasActions = (edgeForm?.action_sets?.length || 0) > 0;
  const isRunningActions = edgeHook.actionHook.loading;
  const isDialogLocked = isRunningActions || isCheckingDependencies;

  // Simply check if actions can be run based on control being active, host being available, and actions existing
  const canRunActions = isControlActive && !!selectedHost && hasActions && !isRunningActions;
  const canRunSingleActions = isControlActive && !!selectedHost && !isRunningActions;

  // Topology fields are read-only in a variant scope — EXCEPT for a variant-only
  // edge owned by that scope, which has no base version to protect and so is
  // fully editable (§3.4 + VARIANT.md §5).
  const topologyDisabled = !editsBaseColumns;

  // Conditional badge: conditional applies only to the FORWARD direction.
  // Detect with the shared structural rule over the raw edge list (which always
  // contains the edge, even when freshly drawn and unsaved) so the badge agrees
  // with the canvas colour and the Edge Selection panel.
  const isConditionalForward = useMemo(() => {
    const edgeId = _selectedEdge?.id;
    if (!edgeId) return false;
    const isForward = (edgeForm?.direction || 'forward') === 'forward';
    return isForward && computeConditionalEdgeIds(rawEdges as any).has(edgeId);
  }, [_selectedEdge?.id, edgeForm?.direction, rawEdges]);

  // Conditional ROLE (forward only): 'main' owns the actions (edits propagate to
  // all branches), 'sibling' borrows them (editing unlinks it). Derived from
  // action-ownership so it agrees with the canvas + Edge Selection panel.
  const conditionalRole = useMemo(() => {
    const edgeId = _selectedEdge?.id;
    if (!edgeId || !isConditionalForward) return null;
    return getConditionalRole(edgeId, rawEdges as any);
  }, [_selectedEdge?.id, isConditionalForward, rawEdges]);

  // ─── Copy / Paste action sets across edges ────────────────────────────
  const [actionClipboard, setActionClipboard] = useState<EdgeActionClipboard | null>(null);

  // Refresh the clipboard from sessionStorage whenever the dialog opens, so a
  // copy made on a previous edge surfaces "Paste" here.
  useEffect(() => {
    if (!isOpen) return;
    try {
      const raw = sessionStorage.getItem(EDGE_ACTION_CLIPBOARD_KEY);
      setActionClipboard(raw ? (JSON.parse(raw) as EdgeActionClipboard) : null);
    } catch {
      setActionClipboard(null);
    }
  }, [isOpen]);

  // Index of the action_set for the direction currently shown in the dialog
  // (matches the forward/reverse logic used elsewhere in this component).
  const activeActionSetIndex = useMemo(() => {
    if (!edgeForm?.action_sets || edgeForm.action_sets.length <= 1) return 0;
    return (edgeForm.direction || 'forward') === 'forward' ? 0 : 1;
  }, [edgeForm?.action_sets, edgeForm?.direction]);

  const hasCopyableContent =
    edgeEdit.localActions.length +
      edgeEdit.localRetryActions.length +
      edgeEdit.localFailureActions.length >
    0;

  // True when the open dialog is the exact action set the clipboard came from.
  const isClipboardSource =
    !!actionClipboard &&
    actionClipboard.sourceEdgeId === edgeForm?.edgeId &&
    actionClipboard.sourceActionSetIndex === activeActionSetIndex;

  // Paste is allowed only with a clipboard, a target action set to write into,
  // and when we're NOT on the source action set.
  const canPaste =
    !!actionClipboard &&
    !isClipboardSource &&
    !!edgeForm?.action_sets?.[activeActionSetIndex] &&
    !isDialogLocked;

  const handleCopyActions = () => {
    const activeSet = edgeForm?.action_sets?.[activeActionSetIndex];
    const clip: EdgeActionClipboard = {
      actions: deepClone(edgeEdit.localActions || []),
      retry_actions: deepClone(edgeEdit.localRetryActions || []),
      failure_actions: deepClone(edgeEdit.localFailureActions || []),
      final_wait_time: activeSet?.final_wait_time,
      sourceLabel: activeSet?.label || (fromLabel && toLabel ? `${fromLabel} → ${toLabel}` : undefined),
      sourceEdgeId: edgeForm?.edgeId,
      sourceActionSetIndex: activeActionSetIndex,
    };
    try {
      sessionStorage.setItem(EDGE_ACTION_CLIPBOARD_KEY, JSON.stringify(clip));
    } catch {
      /* sessionStorage may be unavailable (private mode) — keep in-memory copy */
    }
    setActionClipboard(clip);
    showToastSuccess(`Copied actions${clip.sourceLabel ? ` from '${clip.sourceLabel}'` : ''}`);
  };

  const handlePasteActions = () => {
    if (!actionClipboard || !edgeForm?.action_sets?.[activeActionSetIndex]) {
      showToastError('Nothing to paste into on this edge');
      return;
    }
    // Write all three lists (+ final wait in Base scope) in ONE setEdgeForm so
    // the updates don't clobber each other; useEdgeEdit's effect then re-syncs
    // the displayed lists from the new action_sets.
    const next = edgeForm.action_sets.map((set, i) => {
      if (i !== activeActionSetIndex) return set;
      const patched: any = {
        ...set,
        actions: deepClone(actionClipboard.actions || []),
        retry_actions: deepClone(actionClipboard.retry_actions || []),
        failure_actions: deepClone(actionClipboard.failure_actions || []),
      };
      // Final wait is a topology field — read-only outside Base scope.
      if (!topologyDisabled && typeof actionClipboard.final_wait_time === 'number') {
        patched.final_wait_time = actionClipboard.final_wait_time;
      }
      return patched;
    });
    setEdgeForm({ ...edgeForm, action_sets: next });
    showToastSuccess(
      `Pasted actions${actionClipboard.sourceLabel ? ` from '${actionClipboard.sourceLabel}'` : ''} — review and Save`,
    );
  };

  const handleClearClipboard = () => {
    try {
      sessionStorage.removeItem(EDGE_ACTION_CLIPBOARD_KEY);
    } catch {
      /* ignore */
    }
    setActionClipboard(null);
  };

  // Pre-process the edgeForm before save when scope is a variant.
  //
  // The user's form holds the variant's full view. Per the "variant data
  // lives on variant row" rule (VARIANT.md §2), stash the form's
  // action_sets as the active variant's `action_sets` override (committed
  // by commitDirtyVariantOverrides below). The base PUT is skipped in
  // variant scope, so we leave edgeForm untouched — resetting it to base
  // here would flash old content in the dialog body before onClose.
  const routeFormForVariantScope = (): Record<string, EdgeVariantOverride> => {
    // Owned variant-only edges write to base columns (persistBase), not an
    // override — leave the override map untouched.
    if (!edgeForm || editsBaseColumns) return localOverrides;
    const formActionSets = (edgeForm.action_sets as any[]) || [];
    // If the dialog opened before _selectedEdge fully propagated, the base
    // snapshot can be empty. Adopt the form's current action_sets as base
    // so we never POST [] to /edges (would violate check_action_sets_not_empty).
    if (baseActionSetsRef.current.length === 0 && formActionSets.length > 0) {
      baseActionSetsRef.current = deepClone(formActionSets);
    }
    const base = baseActionSetsRef.current;
    const existing = localOverrides[variantScope];
    let nextLocal = localOverrides;
    if (existing?.disabled !== true) {
      // Three cases for what to stash on the variant entry:
      //   1. Form is empty (length 0) → never write `{action_sets: []}` —
      //      self-perpetuating empty bug. Drop the entry entirely.
      //   2. Form deep-equals base → no actual override; drop the entry so
      //      the variant falls through to base.
      //   3. Otherwise → write `{action_sets: formActionSets}`.
      let nextEntry: EdgeVariantOverride | undefined;
      if (formActionSets.length === 0) {
        nextEntry = undefined;
      } else if (JSON.stringify(formActionSets) === JSON.stringify(base)) {
        nextEntry = undefined;
      } else {
        // Spread the existing entry so non-content flags (drawn_reversed)
        // survive a rewrite of the action_sets.
        nextEntry = { ...(existing || {}), action_sets: deepClone(formActionSets) };
      }
      if (nextEntry === undefined) {
        const { [variantScope]: _removed, ...rest } = localOverrides;
        void _removed;
        nextLocal = rest;
      } else {
        nextLocal = { ...localOverrides, [variantScope]: nextEntry };
      }
      dirtyVariantsRef.current.add(variantScope);
    }
    // Don't reset edgeForm back to base here. The base PUT is skipped in
    // variant scope (persistBase early-returns), so the reset only causes a
    // visible "flash" of base content in the dialog body before onClose
    // runs. The variant override already captured formActionSets via
    // nextEntry above, so persistence is unaffected.
    setLocalOverrides(nextLocal);
    return nextLocal;
  };

  // After a variant-scope save, the dialog skips `edgeEdit.handleSave()` —
  // which means `saveEdgeWithStateUpdate` never runs and `selectedEdge` in
  // NavigationContext keeps the pre-save snapshot. The Edge Selection panel
  // reads from `selectedEdge`, so without this refresh the panel re-renders
  // with the OLD action_sets after Save (canvas updates correctly because
  // it goes through useResolvedTree).
  //
  // Build the new resolved edge from the canvas-viewing scope
  // (`initialVariantScope`) and the freshly-saved override map, then push
  // it into selectedEdge. Mirrors what saveEdgeWithStateUpdate does for
  // base saves at NavigationContext.tsx:1449.
  const refreshSelectedEdgeForCanvasScope = (
    finalLocal: Record<string, EdgeVariantOverride>,
  ): void => {
    console.log('[refreshSelectedEdge] called', {
      hasSelectedEdge: !!_selectedEdge,
      initialVariantScope,
      variantScope,
      finalLocalKeys: Object.keys(finalLocal),
    });
    if (!_selectedEdge) return;
    const canvasScope = initialVariantScope;
    let resolvedActionSets: any[];
    if (!canvasScope || canvasScope === 'base') {
      console.log('[refreshSelectedEdge] skipping — canvas viewing base');
      return;
    }
    const entry = finalLocal[canvasScope];
    console.log('[refreshSelectedEdge] entry for canvasScope', canvasScope, ':', entry);
    // True base must come from the raw edges array (canonical pre-resolution
    // store). `baseActionSetsRef.current` was captured from `_selectedEdge` at
    // dialog-open time and reflects the canvas's resolved view — when the
    // canvas opened in variant scope that's variant-patched content, not base.
    const rawEdgeForBase = rawEdges.find((e) => e.id === _selectedEdge.id);
    const trueBaseActionSets = (rawEdgeForBase?.data as any)?.action_sets || [];
    if (entry?.disabled === true) {
      resolvedActionSets = trueBaseActionSets;
    } else if (Array.isArray(entry?.action_sets) && entry.action_sets.length > 0) {
      resolvedActionSets = entry.action_sets;
    } else {
      resolvedActionSets = trueBaseActionSets;
    }
    const newResolvedEdge: UINavigationEdge = {
      ..._selectedEdge,
      data: {
        ...(_selectedEdge.data || {}),
        action_sets: deepClone(resolvedActionSets),
      },
    } as UINavigationEdge;
    console.log('[refreshSelectedEdge] pushing newResolvedEdge', {
      edgeId: newResolvedEdge.id,
      action_sets: newResolvedEdge.data?.action_sets,
    });
    setSelectedEdgeInContext(newResolvedEdge);
  };

  // Post-save commit: write any variants that were edited locally to their
  // userinterface_variants rows. PUTs run in parallel; failures (e.g. the
  // variant was deleted in another tab) surface as a toast.
  const commitDirtyVariantOverrides = async (
    finalLocal: Record<string, EdgeVariantOverride>,
  ): Promise<void> => {
    const edgeId = edgeForm?.edgeId;
    if (!edgeId || dirtyVariantsRef.current.size === 0) return;
    const dirtyNames = Array.from(dirtyVariantsRef.current);
    const tasks = dirtyNames.map((variantName) => {
      const v = registeredVariants.find((x) => x.name === variantName);
      if (!v) return Promise.resolve();
      const newEntry = finalLocal[variantName];
      const nextMap: Record<string, EdgeVariantOverride> = { ...(v.edge_overrides || {}) };
      if (newEntry === undefined) {
        delete nextMap[edgeId];
      } else {
        nextMap[edgeId] = newEntry;
      }
      return updateVariantOverrides(variantName, { edge_overrides: nextMap }, { skipRefresh: true });
    });
    const results = await Promise.allSettled(tasks);
    // The persisted row now carries this edge's entry — tell the canvas to
    // drop its STAGED copy so the next canvas Save can't re-merge stale
    // content over what was just written.
    if (onVariantOverrideCommitted) {
      results.forEach((r, i) => {
        if (r.status === 'fulfilled' && registeredVariants.some((v) => v.name === dirtyNames[i])) {
          onVariantOverrideCommitted(dirtyNames[i], edgeId);
        }
      });
    }
    const failures = results
      .map((r, i) => (r.status === 'rejected' ? dirtyNames[i] : null))
      .filter((n): n is string => n !== null);
    if (failures.length > 0) {
      showToastError(
        `Failed to save on variant${failures.length > 1 ? 's' : ''}: ${failures.join(', ')}`,
      );
    }
    // Single refresh after the batch — without skipRefresh each PUT
    // triggered its own GET (N+1 reads for N writes). Only call it when at
    // least one PUT actually fired.
    if (dirtyNames.length > 0) {
      await refreshVariants();
    }
    dirtyVariantsRef.current = new Set();
  };

  // Enhanced submit handler with dependency checking
  // Variant-scope edits never mutate base columns (topology is disabled,
  // action_sets is reset to base by routeFormForVariantScope), so the base
  // POST + cache-update calls are unconditional wastes. Skip them when scope
  // is a variant — only the variant overrides PUT runs (saves 2 round-trips
  // per save and avoids invalidating the host cache for nothing).
  const persistBase = async () => {
    // Save base columns when in base scope OR editing an owned variant-only edge
    // (its action_sets live on the edge's own columns; hidden_in_base is
    // preserved via currentSelectedEdge.data in saveEdgeWithStateUpdate).
    if (!editsBaseColumns) return;
    await edgeEdit.handleSave();
  };

  const handleSubmitWithDependencyCheck = async () => {
    if (!edgeEdit.isFormValid()) return;

    // Route form for variant scope BEFORE saving so dependency checks see
    // the same base actions the persisted row will have.
    const finalLocal = routeFormForVariantScope();

    // Check for existing actions that might have dependencies
    const allActions = [...edgeEdit.localActions, ...edgeEdit.localRetryActions];

    setIsCheckingDependencies(true);
    try {
      // Use the new checkDependencies function from the hook
      const result = await edgeEdit.checkDependencies(allActions);

      if (result.success && result.has_shared_actions) {
        // Show dependency dialog
        setDependencyEdges(result.edges);
        setPendingSubmit(edgeForm);
        setDependencyDialogOpen(true);
      } else if (result.success && !result.has_shared_actions) {
        // No dependencies found, proceed with saving (self-contained)
        await persistBase();
        await commitDirtyVariantOverrides(finalLocal);
        if (variantScope !== 'base' && !isVariantOnlyOwned) refreshSelectedEdgeForCanvasScope(finalLocal);
        onClose();
      } else {
        // Handle other cases (like API errors)
        console.warn('Unexpected dependency check result:', result);
        await persistBase();
        await commitDirtyVariantOverrides(finalLocal);
        if (variantScope !== 'base' && !isVariantOnlyOwned) refreshSelectedEdgeForCanvasScope(finalLocal);
        onClose();
      }
    } catch (error) {
      console.warn('Failed to check dependencies for actions:', error);
      // Continue with save if dependency check fails
      await persistBase();
      await commitDirtyVariantOverrides(finalLocal);
      if (variantScope !== 'base' && !isVariantOnlyOwned) refreshSelectedEdgeForCanvasScope(finalLocal);
      onClose();
    } finally {
      setIsCheckingDependencies(false);
    }
  };

  // Save click wrapper. Saving a conditional SIBLING whose ACTIONS were edited
  // unlinks it from the group (it gets its own action_set_id + copy of the
  // actions; the main and other branches are untouched). Per-edge fields — KPI
  // display name, threshold, final wait, priority — live on the sibling's own
  // action_set and saving them keeps the link (saveEdge applies the same
  // comparison), so only warn when the action lists actually differ from the
  // borrowed main's. Main / non-conditional edges save directly.
  const handleSaveClick = () => {
    if (conditionalRole === 'sibling') {
      const fwd = (edgeForm?.action_sets as any[])?.[0];
      const ownerFwd = _selectedEdge
        ? findConditionalOwnerForward(_selectedEdge.id, rawEdges as any)
        : null;
      const formEmpty =
        ((fwd?.actions?.length ?? 0) +
          (fwd?.retry_actions?.length ?? 0) +
          (fwd?.failure_actions?.length ?? 0)) === 0;
      const actionsChanged =
        !!fwd && !formEmpty && !(ownerFwd && forwardActionListsEqual(fwd, ownerFwd));
      if (actionsChanged) {
        confirm({
          title: 'Unlink conditional edge?',
          message:
            `You changed this edge's actions, which it currently borrows from the ` +
            `main of its conditional group. Saving will UNLINK it: it gets its own ` +
            `independent copy of the actions and leaves the group. The main and other ` +
            `branches are unaffected, and edits to the main will no longer propagate ` +
            `here. (KPI name / threshold / wait changes alone never unlink.) Continue?`,
          confirmText: 'Unlink & Save',
          cancelText: 'Cancel',
          confirmColor: 'warning',
          onConfirm: () => {
            void handleSubmitWithDependencyCheck();
          },
        });
        return;
      }
    }
    void handleSubmitWithDependencyCheck();
  };

  const handleDependencyConfirm = async () => {
    setDependencyDialogOpen(false);
    if (pendingSubmit) {
      await persistBase();
      await commitDirtyVariantOverrides(localOverrides);
      if (variantScope !== 'base' && !isVariantOnlyOwned) refreshSelectedEdgeForCanvasScope(localOverrides);
      onClose();
    }
    setPendingSubmit(null);
    setDependencyEdges([]);
  };

  const handleDependencyCancel = () => {
    setDependencyDialogOpen(false);
    setPendingSubmit(null);
    setDependencyEdges([]);
  };

  const buildEdgeToExecute = (): UINavigationEdge | null => {
    if (!edgeForm) return null;

    // Prefer using the actual selected edge to preserve source/target metadata
    return _selectedEdge || {
      id: edgeForm.edgeId,
      source: 'unknown',
      target: 'unknown',
      type: 'navigation',
      data: {
        action_sets: edgeForm.action_sets, // Use form data, not empty array
        default_action_set_id: edgeForm.default_action_set_id, // Use form data, not empty string
      },
    } as UINavigationEdge;
  };

  const runActionSubset = async (
    actions: any[],
    retryActions: any[],
    failureActions: any[],
    section: ActionRunSection,
    index: number | null = null,
  ) => {
    if (isRunningActions) return;

    const edgeToExecute = buildEdgeToExecute();
    if (!edgeToExecute) return;

    setRunningAction({ section, index });
    if (section !== 'all' && index !== null) {
      setRunStatusBySection((prev) => {
        const nextSection = { ...prev[section as 'main' | 'retry' | 'failure'] };
        delete nextSection[index];
        return { ...prev, [section]: nextSection };
      });
    }

    try {
      const result = await edgeHook.executeEdgeActions(edgeToExecute, actions, retryActions, failureActions);

      if (section !== 'all' && index !== null) {
        const sectionKey = section as 'main' | 'retry' | 'failure';
        const status: 'success' | 'failure' = result?.success ? 'success' : 'failure';

        setRunStatusBySection((prev) => ({
          ...prev,
          [sectionKey]: {
            ...prev[sectionKey],
            [index]: status,
          },
        }));

        const timeoutId = window.setTimeout(() => {
          setRunStatusBySection((prev) => {
            const nextSection = { ...prev[sectionKey] };
            delete nextSection[index];
            return { ...prev, [sectionKey]: nextSection };
          });
        }, 5000);
        runStatusTimeoutsRef.current.push(timeoutId);
      }
    } catch (error) {
      if (section !== 'all' && index !== null) {
        const sectionKey = section as 'main' | 'retry' | 'failure';
        setRunStatusBySection((prev) => ({
          ...prev,
          [sectionKey]: {
            ...prev[sectionKey],
            [index]: 'failure',
          },
        }));

        const timeoutId = window.setTimeout(() => {
          setRunStatusBySection((prev) => {
            const nextSection = { ...prev[sectionKey] };
            delete nextSection[index];
            return { ...prev, [sectionKey]: nextSection };
          });
        }, 5000);
        runStatusTimeoutsRef.current.push(timeoutId);
      }
      console.error('Failed to run action subset:', error);
    } finally {
      setRunningAction(null);
    }
  };

  useEffect(() => {
    return () => {
      runStatusTimeoutsRef.current.forEach((id) => window.clearTimeout(id));
      runStatusTimeoutsRef.current = [];
    };
  }, []);

  const handleRunActions = async () => {
    // Use the actual selected edge if available, otherwise create edge structure from form data
    await runActionSubset(
      edgeEdit.localActions,
      edgeEdit.localRetryActions,
      edgeEdit.localFailureActions,
      'all',
      null,
    );
  };

  const handleRunSingleAction = async (section: ActionRunSection, index: number) => {
    if (!canRunSingleActions) return;

    if (section === 'main' && edgeEdit.localActions[index]) {
      await runActionSubset([edgeEdit.localActions[index]], [], [], section, index);
      return;
    }

    if (section === 'retry' && edgeEdit.localRetryActions[index]) {
      await runActionSubset([edgeEdit.localRetryActions[index]], [], [], section, index);
      return;
    }

    if (section === 'failure' && edgeEdit.localFailureActions[index]) {
      await runActionSubset([edgeEdit.localFailureActions[index]], [], [], section, index);
    }
  };

  const handleAbortRun = async () => {
    if (!isRunningActions || !edgeHook.actionHook.abortExecution) return;
    try {
      await edgeHook.actionHook.abortExecution();
    } catch (error) {
      console.error('Failed to abort action run:', error);
    }
  };

  const handleDialogClose = (_event?: object, reason?: 'backdropClick' | 'escapeKeyDown') => {
    if (isRunningActions && (reason === 'backdropClick' || reason === 'escapeKeyDown')) {
      return;
    }

    if (!isRunningActions) {
      onClose();
    }
  };

  if (!edgeForm) return null;

  return (
    <>
      <StyledDialog
        open={isOpen}
        onClose={handleDialogClose}
        disableEscapeKeyDown={isRunningActions}
        maxWidth="md"
        fullWidth
        sx={{
          zIndex: getZIndex('NAVIGATION_DIALOGS'),
          ...sx,
        }}
      >
        <DialogTitle sx={{ pb: 0.5 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 1 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexShrink: 0 }}>
              <Typography variant="h6">Edit Edge</Typography>
              {fromLabel && toLabel && (
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Typography
                    variant="body2"
                    sx={{ fontSize: '0.8rem', fontWeight: 'bold', color: '#1976d2' }}
                  >
                    {fromLabel}
                  </Typography>
                  <Typography variant="body1" sx={{ fontSize: '1rem' }}>
                    →
                  </Typography>
                  <Typography
                    variant="body2"
                    sx={{ fontSize: '0.8rem', fontWeight: 'bold', color: '#4caf50' }}
                  >
                    {toLabel}
                  </Typography>
                </Box>
              )}
              {/* 🔗 Conditional Edge Indicator — only on the FORWARD action set.
                  Conditional grouping lives entirely on the forward direction
                  (action_sets[0]); the reverse direction is always independent. */}
              {isConditionalForward && (
                <Box
                  sx={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 0.5,
                    px: 1,
                    py: 0.3,
                    borderRadius: 1,
                    backgroundColor: conditionalRole === 'sibling' ? '#fff3e0' : '#e8f5e9',
                    border: `1px solid ${conditionalRole === 'sibling' ? '#ff9800' : '#4caf50'}`,
                  }}
                >
                  <Typography
                    variant="caption"
                    sx={{
                      fontSize: '0.7rem',
                      fontWeight: 'bold',
                      color: conditionalRole === 'sibling' ? '#ff9800' : '#4caf50',
                    }}
                  >
                    {conditionalRole === 'sibling'
                      ? '🔗 CONDITIONAL · sibling (action edits unlink)'
                      : '🔗 CONDITIONAL · main (edits all branches)'}
                  </Typography>
                </Box>
              )}
            </Box>
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                gap: 1,
                flexWrap: 'nowrap',
                justifyContent: 'flex-end',
                flexShrink: 0,
              }}
            >
              <Navigation_VariantToggle
                registeredVariantNames={registeredVariants.map((v) => v.name)}
                selectedScope={variantScope}
                onSelectedScopeChange={handleVariantScopeChange}
                disabled={isDialogLocked}
                // A variant-only edge has NO base version — Base isn't a valid
                // scope for it. The user links the nodes in Base first if they
                // want a base edge.
                baseDisabled={edgeHiddenInBase}
                baseDisabledReason="This edge exists only on a variant — link the nodes in Base first."
              />
              {/* Replicate button — header top-right, only when editing a variant
                  scope. Hidden for owned variant-only edges: they have no
                  override to replicate (content lives in the edge's base columns). */}
              {variantScope !== 'base' && !isVariantOnlyOwned && replicateTargets.length > 0 && (
                <Tooltip title={`Replicate this edge's '${variantScope}' overrides to another variant`}>
                  <span>
                    <IconButton
                      onClick={openReplicateMenu}
                      size="small"
                      disabled={isDialogLocked}
                      aria-label="Replicate to another variant"
                    >
                      <ContentCopyIcon fontSize="small" />
                    </IconButton>
                  </span>
                </Tooltip>
              )}
              <IconButton onClick={onClose} size="small" disabled={isDialogLocked}>
                <CloseIcon />
              </IconButton>
            </Box>
          </Box>
        </DialogTitle>

        {/* Fixed content height so the dialog doesn't flash/resize when the
            loading spinner is swapped for the (taller) populated form. The
            body scrolls internally instead of growing the dialog. */}
        <DialogContent sx={{ py: 0.5, height: '70vh', overflowY: 'auto' }}>
          {isInitialDataLoading ? (
            <Box
              sx={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 1,
                height: '100%',
              }}
            >
              <CircularProgress size={28} />
              <Typography variant="body2" color="text.secondary">
                Loading actions and references…
              </Typography>
            </Box>
          ) : (
          <Box
            sx={{
              pointerEvents: isDialogLocked ? 'none' : 'auto',
              opacity: isDialogLocked ? 0.75 : 1,
              transition: 'opacity 0.2s',
            }}
          >
          {/* Priority, Threshold, Final wait — threshold + final wait are stored
              per direction on the active action_set, so editing them only affects
              the direction currently shown in the dialog. */}
          {(() => {
            const direction = edgeForm?.direction || 'forward';
            const actionSetIdx =
              !edgeForm?.action_sets || edgeForm.action_sets.length <= 1
                ? 0
                : direction === 'forward'
                  ? 0
                  : 1;
            const activeActionSet = edgeForm?.action_sets?.[actionSetIdx];
            const updateActiveActionSet = (patch: {
              final_wait_time?: number;
              threshold?: number;
              kpi_name?: string;
            }) => {
              if (!edgeForm?.action_sets || !activeActionSet) return;
              const next = edgeForm.action_sets.map((set, i) =>
                i === actionSetIdx ? { ...set, ...patch } : set,
              );
              setEdgeForm({ ...edgeForm, action_sets: next });
            };

            return (
              <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
                <FormControl fullWidth margin="dense" size="small" disabled={topologyDisabled} sx={{ flex: 1.2 }}>
                  <InputLabel>Priority</InputLabel>
                  <Select
                    value={edgeForm?.priority || 'p3'}
                    label="Priority"
                    onChange={(e) =>
                      setEdgeForm({ ...edgeForm, priority: e.target.value as 'p1' | 'p2' | 'p3' })
                    }
                  >
                    <MenuItem value="p1">P1 Critical</MenuItem>
                    <MenuItem value="p2">P2 Major</MenuItem>
                    <MenuItem value="p3">P3 Minor</MenuItem>
                  </Select>
                </FormControl>
                <TextField
                  label="Threshold (ms)"
                  type="number"
                  value={activeActionSet?.threshold ?? 0}
                  onChange={(e) => {
                    const value = parseInt(e.target.value);
                    updateActiveActionSet({ threshold: isNaN(value) ? 0 : value });
                  }}
                  fullWidth
                  margin="dense"
                  size="small"
                  autoComplete="off"
                  inputProps={{ step: 100, min: 0 }}
                  disabled={topologyDisabled || !activeActionSet}
                  sx={{ flex: 0.7 }}
                />
                <TextField
                  label="Final wait (ms)"
                  type="number"
                  value={activeActionSet?.final_wait_time ?? 0}
                  onChange={(e) => {
                    const value = parseInt(e.target.value);
                    updateActiveActionSet({ final_wait_time: isNaN(value) ? 0 : value });
                  }}
                  fullWidth
                  margin="dense"
                  size="small"
                  autoComplete="off"
                  inputProps={{ step: 100, min: 0 }}
                  disabled={topologyDisabled || !activeActionSet}
                  sx={{ flex: 0.7 }}
                />
                {/* Optional friendly KPI name for this direction. Surfaces in the
                    Grafana KPI dashboard + kpi_measurement.py report instead of the
                    raw action_set_id. Per-direction (stored on the active action_set),
                    same as threshold/final_wait. */}
                <TextField
                  label="KPI display name"
                  placeholder="e.g. [TC259] Open TV Guide"
                  value={activeActionSet?.kpi_name ?? ''}
                  onChange={(e) => updateActiveActionSet({ kpi_name: e.target.value })}
                  fullWidth
                  margin="dense"
                  size="small"
                  autoComplete="off"
                  disabled={topologyDisabled || !activeActionSet}
                  sx={{ flex: 2.4 }}
                />
              </Box>
            );
          })()}

          {/* Sibling Shortcuts Checkbox */}
          <Box sx={{ mb: 1 }}>
            <FormControlLabel
              control={
                <Checkbox
                  checked={edgeForm?.enable_sibling_shortcuts ?? false}
                  onChange={(e) =>
                    setEdgeForm({
                      ...edgeForm,
                      enable_sibling_shortcuts: e.target.checked,
                    })
                  }
                  size="small"
                  disabled={topologyDisabled}
                />
              }
              label={
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <Typography variant="body2" sx={{ fontSize: '0.875rem' }}>
                    Enable sibling shortcuts
                  </Typography>
                  <Typography variant="caption" sx={{ fontSize: '0.75rem', color: 'text.secondary', fontStyle: 'italic' }}>
                    (web/mobile: allow direct navigation between sibling nodes)
                  </Typography>
                </Box>
              }
            />
          </Box>

          {/* Main Actions */}
          <Box
            sx={{
              border: '1px solid',
              borderColor: 'divider',
              borderRadius: 1,
              p: 1,
              mb: 1,
            }}
          >
            <Box
              sx={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                mb: 0.5,
              }}
            >
              <Typography variant="h6" sx={{ fontSize: '1rem', m: 0 }}>
                Main Actions
              </Typography>
              <Button
                variant="outlined"
                size="small"
                disabled={isDialogLocked}
                onClick={() => {
                  const newAction: any = {
                    command: '',
                    params: {
                      wait_time: 500
                    },
                  };
                  edgeEdit.handleActionsChange([...edgeEdit.localActions, newAction]);
                }}
                sx={{ fontSize: '0.75rem', px: 1, py: 0.25 }}
              >
                + Add
              </Button>
            </Box>
            {edgeEdit.localActions.length > 0 ? (
              <ActionsList
                actions={edgeEdit.localActions}
                onActionsUpdate={edgeEdit.handleActionsChange}
                onRunAction={(index) => handleRunSingleAction('main', index)}
                runDisabled={!canRunSingleActions}
                runningActionIndex={
                  isRunningActions && runningAction?.section === 'main' ? runningAction.index : null
                }
                runStatusByIndex={runStatusBySection.main}
                disabled={isDialogLocked}
              />
            ) : (
              <Typography
                variant="body2"
                color="text.secondary"
                sx={{ fontStyle: 'italic', textAlign: 'center', py: 0.5 }}
              >
                No actions found
              </Typography>
            )}
          </Box>

          {/* Retry Actions */}
          <Box
            sx={{
              border: '1px solid',
              borderColor: 'divider',
              borderRadius: 1,
              p: 1,
              mb: 1,
            }}
          >
            <Box
              sx={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                mb: 0.5,
              }}
            >
              <Typography variant="h6" sx={{ fontSize: '1rem', m: 0 }}>
                Retry Actions
              </Typography>
              <Button
                variant="outlined"
                size="small"
                disabled={isDialogLocked}
                onClick={() => {
                  const newAction: any = {
                    command: '',
                    params: {
                      wait_time: 500
                    },
                  };
                  edgeEdit.handleRetryActionsChange([...edgeEdit.localRetryActions, newAction]);
                }}
                sx={{ fontSize: '0.75rem', px: 1, py: 0.25 }}
              >
                + Add
              </Button>
            </Box>
            {edgeEdit.localRetryActions.length > 0 ? (
              <ActionsList
                actions={edgeEdit.localRetryActions}
                onActionsUpdate={edgeEdit.handleRetryActionsChange}
                onRunAction={(index) => handleRunSingleAction('retry', index)}
                runDisabled={!canRunSingleActions}
                runningActionIndex={
                  isRunningActions && runningAction?.section === 'retry' ? runningAction.index : null
                }
                runStatusByIndex={runStatusBySection.retry}
                disabled={isDialogLocked}
              />
            ) : (
              <Typography
                variant="body2"
                color="text.secondary"
                sx={{ fontStyle: 'italic', textAlign: 'center', py: 0.5 }}
              >
                No retry actions found
              </Typography>
            )}
          </Box>

          {/* Failure Actions */}
          <Box
            sx={{
              border: '1px solid',
              borderColor: 'divider',
              borderRadius: 1,
              p: 1,
              mb: 1,
            }}
          >
            <Box
              sx={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                mb: 0.5,
              }}
            >
              <Typography variant="h6" sx={{ fontSize: '1rem', m: 0 }}>
                Failure Actions
              </Typography>
              <Button
                variant="outlined"
                size="small"
                disabled={isDialogLocked}
                onClick={() => {
                  const newAction: any = {
                    command: '',
                    params: {
                      wait_time: 500
                    },
                  };
                  edgeEdit.handleFailureActionsChange([...edgeEdit.localFailureActions, newAction]);
                }}
                sx={{ fontSize: '0.75rem', px: 1, py: 0.25 }}
              >
                + Add
              </Button>
            </Box>
            {edgeEdit.localFailureActions.length > 0 ? (
              <ActionsList
                actions={edgeEdit.localFailureActions}
                onActionsUpdate={edgeEdit.handleFailureActionsChange}
                onRunAction={(index) => handleRunSingleAction('failure', index)}
                runDisabled={!canRunSingleActions}
                runningActionIndex={
                  isRunningActions && runningAction?.section === 'failure' ? runningAction.index : null
                }
                runStatusByIndex={runStatusBySection.failure}
                disabled={isDialogLocked}
              />
            ) : (
              <Typography
                variant="body2"
                color="text.secondary"
                sx={{ fontStyle: 'italic', textAlign: 'center', py: 0.5 }}
              >
                No failure actions found
              </Typography>
            )}
          </Box>

          {/* KPI Measurement Section - Only for current action_set */}
          {edgeForm?.action_sets && (() => {
            // Get the current action_set based on direction
            const direction = edgeForm.direction || 'forward';
            const actionSetIndex = edgeForm.action_sets.length === 1 ? 0 : (direction === 'forward' ? 0 : 1);
            const actionSet = edgeForm.action_sets[actionSetIndex];

            if (!actionSet) return null;

            // KPI pass condition ('all'/'any') is resolved server-side from
            // kpi_references[0].verification_pass_condition (see
            // navigation_executor.py's _resolve_kpi_pass_condition) — there is
            // no separate column for it. Read/write it there instead of
            // letting VerificationsList fall back to its own un-persisted
            // internal state (that fallback is what caused the "Any can pass"
            // selection to silently revert to "All must pass" on reopen).
            const kpiPassCondition: 'all' | 'any' =
              (actionSet.kpi_references?.[0] as any)?.verification_pass_condition || 'all';
            const handleKpiPassConditionChange = (condition: 'all' | 'any') => {
              const refs = actionSet.kpi_references || [];
              if (refs.length === 0) return;
              const updatedRefs = refs.map((ref: any) => ({
                ...ref,
                verification_pass_condition: condition,
              }));
              edgeEdit.handleKpiReferencesChange(actionSetIndex, updatedRefs);
            };

            return (
              <Box
                sx={{
                  border: '1px solid',
                  borderColor: 'divider',
                  borderRadius: 1,
                  p: 1,
                  mb: 1,
                }}
              >
                {/* Title and Checkbox on same line */}
                <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 0.5 }}>
                  <Typography variant="h6" sx={{ fontSize: '1rem', m: 0 }}>
                    📊 KPI Measurement - {actionSet.label}
                  </Typography>

                  {/* Checkbox to use verifications for KPI */}
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={actionSet.use_verifications_for_kpi || false}
                        onChange={(e) => edgeEdit.handleUseVerificationsForKpiChange(actionSetIndex, e.target.checked)}
                        size="small"
                      />
                    }
                    label={
                      <Typography variant="body2" sx={{ fontSize: '0.875rem' }}>
                        Use target node verifications
                      </Typography>
                    }
                    sx={{ m: 0 }}
                  />
                </Box>

                {/* Helper text */}
                <Typography variant="caption" sx={{ fontSize: '0.75rem', color: 'text.secondary', mb: 0.5, display: 'block' }}>
                  Measure time from action to visual confirmation
                </Typography>

                {/* KPI References List - disabled when checkbox is checked */}
                <Box
                  sx={{
                    opacity: actionSet.use_verifications_for_kpi ? 0.5 : 1,
                    pointerEvents: actionSet.use_verifications_for_kpi ? 'none' : 'auto',
                    transition: 'opacity 0.2s',
                  }}
                >
                  <VerificationsList
                    verifications={actionSet.kpi_references || []}
                    availableVerifications={kpiAvailableVerifications}
                    onVerificationsChange={(newRefs) => edgeEdit.handleKpiReferencesChange(actionSetIndex, newRefs)}
                    loading={false}
                    model={model}
                    selectedHost={selectedHost || undefined}
                    testResults={[]}
                    onReferenceSelected={() => {}}
                    modelReferences={edgeEdit.modelReferences}
                    referencesLoading={edgeEdit.referencesLoading}
                    showCollapsible={false}
                    title=""
                    passCondition={kpiPassCondition}
                    onPassConditionChange={handleKpiPassConditionChange}
                    onTest={undefined}  // KPI measurements are post-processed, cannot be tested in real-time
                    // Reference content (search text + area) is authored
                    // in VerificationEditor. Editing it here would
                    // silently overwrite the shared asset for every other
                    // node/edge that uses the same reference.
                    referenceReadOnly={true}
                  />
                </Box>
              </Box>
            );
          })()}
          </Box>
          )}

          {/* Linear Progress - shown when running */}
          {isRunningActions && (
            <Box sx={{ mt: 1 }}>
              <LinearProgress sx={{ borderRadius: 1 }} />
            </Box>
          )}

          {/* Action Result Display — header omitted (the green/red box is
              self-explanatory). Color is decided from the summary line:
              "✅ Execution X/Y passed in Xm:YYs" → success;
              "❌ Execution …" or any "❌" without "✅" → error. */}
          {edgeHook.runResult && (
            <Box
              sx={{
                mt: 1,
                p: 1,
                bgcolor: edgeHook.runResult.includes('✅ Execution')
                  ? 'success.light'
                  : edgeHook.runResult.includes('❌ Execution') ||
                      (edgeHook.runResult.includes('❌') && !edgeHook.runResult.includes('✅'))
                    ? 'error.light'
                    : edgeHook.runResult.includes('⚠️')
                      ? 'warning.light'
                      : 'error.light',
                borderRadius: 1,
                maxHeight: '200px',
                overflow: 'auto',
                border: '1px solid rgba(0, 0, 0, 0.12)',
              }}
            >
              <Typography
                variant="caption"
                sx={{
                  fontFamily: 'monospace',
                  whiteSpace: 'pre-line',
                  fontSize: '0.7rem',
                  lineHeight: 1.2,
                }}
              >
                {edgeHook.formatRunResult(edgeHook.runResult)}
              </Typography>
            </Box>
          )}

          {/* Verification report for the repeat_until leg (evidence that drove
              pass/fail) — mirrors goto's "View report" link. */}
          {edgeHook.runReportUrl && (
            <Typography variant="caption" sx={{ display: 'block', mt: 0.5 }}>
              <a
                href={edgeHook.runReportUrl}
                target="_blank"
                rel="noopener noreferrer"
                style={{ color: '#1976d2', textDecoration: 'underline', fontWeight: 'bold' }}
              >
                🔍 View verification report
              </a>
            </Typography>
          )}
        </DialogContent>

        <DialogActions sx={{ pt: 0.5 }}>
          {variantScope !== 'base' && !isVariantOnlyOwned && (
            <Button
              onClick={handleResetVariant}
              variant="outlined"
              color="warning"
              disabled={isDialogLocked}
            >
              Reset variant
            </Button>
          )}
          {/* Copy / Paste action sets between edges. Copy and Paste are always
              rendered so their position never shifts (no flashing); Paste is
              just disabled when there's nothing to paste or we're on the source
              action set. Cancel toggles on the FAR LEFT, so showing/hiding it
              doesn't move Copy / Paste / Save. */}
          {actionClipboard && (
            <Button
              onClick={handleClearClipboard}
              variant="text"
              color="inherit"
              disabled={isDialogLocked}
            >
              Cancel
            </Button>
          )}
          <Tooltip title="Copy this direction's Main / Retry / Failure actions + Final wait">
            <span>
              <Button
                onClick={handleCopyActions}
                variant="outlined"
                startIcon={<ContentCopyIcon />}
                disabled={isDialogLocked || !hasCopyableContent}
              >
                Copy
              </Button>
            </span>
          </Tooltip>
          <Tooltip
            title={
              !actionClipboard
                ? 'Copy an edge’s actions first'
                : isClipboardSource
                  ? 'This is the action set you copied from'
                  : `Paste actions${actionClipboard.sourceLabel ? ` from '${actionClipboard.sourceLabel}'` : ''} into this direction`
            }
          >
            <span>
              <Button
                onClick={handlePasteActions}
                variant="outlined"
                color="secondary"
                startIcon={<ContentPasteIcon />}
                disabled={!canPaste}
              >
                Paste
              </Button>
            </span>
          </Tooltip>
          <Button
            onClick={handleSaveClick}
            variant="contained"
            disabled={!edgeEdit.isFormValid() || isDialogLocked}
            startIcon={isCheckingDependencies ? <CircularProgress size={16} /> : null}
          >
            {isCheckingDependencies ? 'Checking...' : 'Save'}
          </Button>
          {/* Replicate menu — anchor lives in the dialog header (top-right). */}
          <Menu
            anchorEl={replicateAnchor}
            open={replicateMenuOpen}
            onClose={closeReplicateMenu}
            anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
            transformOrigin={{ vertical: 'top', horizontal: 'right' }}
          >
            {replicateTargets.map((name) => (
              <MenuItem key={name} onClick={() => handlePickReplicate(name)}>
                <Typography
                  variant="body2"
                  sx={{
                    fontFamily:
                      'ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace',
                  }}
                >
                  {name}
                </Typography>
              </MenuItem>
            ))}
          </Menu>
          {/* Run/Abort button */}
          {isRunningActions ? (
            <Button
              onClick={handleAbortRun}
              variant="contained"
              color="warning"
            >
              Abort
            </Button>
          ) : hasActions && (
            <Button
              onClick={handleRunActions}
              variant="contained"
              disabled={!canRunActions}
            >
              Run
            </Button>
          )}
        </DialogActions>
      </StyledDialog>

      {/* Confirmation Dialog */}
      <ConfirmDialog
        open={dialogState.open}
        title={dialogState.title}
        message={dialogState.message}
        confirmText={dialogState.confirmText}
        cancelText={dialogState.cancelText}
        confirmColor={dialogState.confirmColor}
        onConfirm={handleConfirm}
        onCancel={handleCancel}
      />

      {/* Dependency Warning Dialog */}
      <ActionDependencyDialog
        isOpen={dependencyDialogOpen}
        edges={dependencyEdges}
        onConfirm={handleDependencyConfirm}
        onCancel={handleDependencyCancel}
      />
    </>
  );
};
