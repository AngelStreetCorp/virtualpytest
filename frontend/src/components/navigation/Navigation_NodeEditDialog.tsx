import { AppIcon, StatusText } from '../../constants/icons';
import {
  Close as CloseIcon,
  ContentCopy as ContentCopyIcon,
} from '@mui/icons-material';
import {
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Button,
  Box,
  Typography,
  IconButton,
  LinearProgress,
  CircularProgress,
  Menu,
  Tooltip,
  ToggleButton,
  ToggleButtonGroup,
} from '@mui/material';
import React, { useEffect, useMemo, useRef, useState } from 'react';

import { useNodeEdit } from '../../hooks/navigation/useNodeEdit';
import { useReferenceRecapture } from '../../hooks/verification/useReferenceRecapture';
import { useNavigation } from '../../contexts/navigation/NavigationContext';
import { useDeviceData } from '../../contexts/device/DeviceDataContext';
import { useUserInterfaceVariants } from '../../hooks/userinterface/useUserInterfaceVariants';
import { useToast } from '../../hooks/useToast';
import {
  NodeEditDialogProps,
  NodeVariantOverride,
  UINavigationNode,
} from '../../types/pages/Navigation_Types';
import { getZIndex } from '../../utils/zIndexUtils';
import { VerificationsList } from '../verification/VerificationsList';
import { DetailsSection } from '../common/CompactListRow';
import LocalizeCheckFooter from '../verification/LocalizeCheckFooter';
import NodeDomDialog from './Navigation_NodeDomDialog';
import { buildServerUrl, openHostUrl } from '../../utils/buildUrlUtils';
import { useR2Url } from '../../hooks/storage';
import { useConfirmDialog } from '../../hooks/useConfirmDialog';
import { ConfirmDialog } from '../common/ConfirmDialog';
import { StyledDialog } from '../common/StyledDialog';
import {
  Navigation_VariantToggle,
  type VariantScope,
} from './Navigation_VariantToggle';
import { neutralButtonSx, segmentedSx } from '../common/PageChrome';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';

/** Deep clone via JSON — variant data is plain JSONB so this is safe. */
const deepClone = <T,>(value: T): T =>
  value === undefined || value === null ? value : (JSON.parse(JSON.stringify(value)) as T);

/**
 * The three conditions under which there is no dialog to show. Checked in the
 * wrapper below, so `NodeEditDialogBody` only ever mounts with a non-null
 * `nodeForm` and `selectedHost` — which is what `useNodeEdit` and the variant
 * plumbing require, and what lets every hook in the body run unconditionally.
 *
 * These were three early returns at the top of the body. All three guard props the
 * hooks immediately below them depend on, so they could not simply move down; the
 * branch has to happen before the hooks exist, i.e. in a parent.
 */
type NodeEditDialogBodyProps = Omit<NodeEditDialogProps, 'nodeForm' | 'selectedHost'> & {
  nodeForm: NonNullable<NodeEditDialogProps['nodeForm']>;
  selectedHost: NonNullable<NodeEditDialogProps['selectedHost']>;
};

const NodeEditDialogBody: React.FC<NodeEditDialogBodyProps> = ({
  isOpen,
  nodeForm,
  nodes,
  setNodeForm,
  onSubmit: _onSubmit,
  onClose,
  onResetNode,
  onUpdateNode,
  selectedHost,
  isControlActive = false,
  model,
  initialVariantScope = null,
  sx,
}) => {
  const P = useAgentChatPalette();
  // Use the focused node edit hook
  const nodeEdit = useNodeEdit({
    isOpen,
    nodeForm,
    setNodeForm,
    selectedHost,
    isControlActive,
    onUpdateNode,
  });

  // Initialize confirmation dialog
  const { dialogState, confirm, handleConfirm, handleCancel } = useConfirmDialog();
  const { showSuccess: showToastSuccess, showError: showToastError } = useToast();

  // ─── Variant scope plumbing (per-variant overrides model) ─────────────
  // Per-variant data lives on the variant row, not on the node row. The
  // dialog keeps an in-memory map of `{variant_name -> VariantOverride}`
  // for THIS node only, seeded from the variants registry on open. Scope
  // switches persist the form's diff into the local map; Save calls
  // `updateVariantOverrides` for every variant whose entry changed.
  const {
    userInterface,
    nodes: rawNodes,
    selectedNode,
    setSelectedNode,
  } = useNavigation();
  const userinterfaceId = userInterface?.id || null;
  const { variants: registeredVariants, updateVariantOverrides, refresh: refreshVariants } =
    useUserInterfaceVariants(userinterfaceId);

  // Verification reference dropdowns bind to DeviceDataContext. If the
  // dialog opens before the first fetch lands, reference selects render
  // empty until the data arrives. Gate the form so we show a spinner
  // instead of a half-populated form (matches Navigation_EdgeEditDialog).
  //
  // Only gate on the explicit `*Loading` booleans — do NOT also gate on
  // `Object.keys(availableVerificationTypes).length === 0`. The host can
  // legitimately end up at `*Loading: false` with an empty dict (schemas
  // weren't on the host push, or no schemas exist for this device), and
  // any emptiness-based gate then spins forever. See the matching note in
  // Navigation_EdgeEditDialog.
  const {
    availableVerificationTypesLoading,
    referencesLoading,
  } = useDeviceData();
  const isInitialDataLoading =
    availableVerificationTypesLoading || referencesLoading;

  // Show the full-body loader only on the FIRST load after the dialog opens.
  // Once data has landed, later reloads (e.g. reloadReferences() after a
  // Recapture) must NOT swap the body back to the spinner — that flashes the
  // whole panel. After a recapture only the toast should change.
  const [hasLoadedInitialData, setHasLoadedInitialData] = useState(false);
  useEffect(() => {
    if (isOpen && !isInitialDataLoading) setHasLoadedInitialData(true);
    if (!isOpen) setHasLoadedInitialData(false);
  }, [isOpen, isInitialDataLoading]);
  const showInitialLoader = isInitialDataLoading && !hasLoadedInitialData;

  const [variantScope, setVariantScope] = useState<VariantScope>('base');
  const [localOverrides, setLocalOverrides] = useState<Record<string, NodeVariantOverride>>({});
  const dirtyVariantsRef = useRef<Set<string>>(new Set());

  // A variant-only row (`hidden_in_base`) is OWNED by its variant scope — there
  // is no base version to protect, so it must be fully editable (topology +
  // verifications) exactly like a base row, and its edits write to the row's
  // OWN columns, never a variant override (the owning variant falls through to
  // base data — see VARIANT.md §5). Mirrors useResolvedTree's
  // isOwnedByCurrentScope so the canvas drag-lock and the dialog edit-lock agree.
  const nodeHiddenInBase = (nodeForm as any)?.hidden_in_base === true;
  const isVariantOnlyOwned =
    variantScope !== 'base' &&
    nodeHiddenInBase &&
    localOverrides[variantScope]?.disabled !== true;
  // Owned variant-only rows are edited like base: write base columns, no override.
  const editsBaseColumns = variantScope === 'base' || isVariantOnlyOwned;

  // Stable snapshot of base verifications at dialog open. Used as the canonical
  // base value when toggling scopes or persisting overrides; never written into
  // a variant entry directly.
  const baseVerificationsRef = useRef<any[]>([]);

  // Base screenshot/fingerprint/dom snapshot at open — the canonical base values
  // used to decide whether a variant entry should carry an override for each.
  const baseCaptureRef = useRef<{
    screenshot?: string;
    screenshot_timestamp?: number;
    fingerprint?: any;
    dom?: any;
  }>({});

  // Build a variant override entry from the form: verifications + the capture
  // fields (screenshot/fingerprint/dom), including ONLY fields that differ from
  // base. Returns undefined when nothing differs (so the variant falls through).
  const buildVariantEntry = (form: any, prevEntry?: NodeVariantOverride): NodeVariantOverride | undefined => {
    const entry: NodeVariantOverride = {};
    // Carry forward independent fields the form doesn't own — `position`
    // (per-variant canvas layout, set by dragging) and `enabled` (variant-only
    // ownership marker). Seeding them here means a rebuild from the form can't
    // wipe a drag-set position, and an otherwise-empty entry survives when it
    // carries one of these markers.
    if (prevEntry?.position) entry.position = prevEntry.position;
    if (prevEntry?.enabled) entry.enabled = prevEntry.enabled;
    const fv = (form?.verifications as any[]) || [];
    if (fv.length > 0 && JSON.stringify(fv) !== JSON.stringify(baseVerificationsRef.current)) {
      entry.verifications = deepClone(fv);
    }
    const b = baseCaptureRef.current;
    if (form?.screenshot && form.screenshot !== b.screenshot) {
      entry.screenshot = form.screenshot;
      if (form.screenshot_timestamp) entry.screenshot_timestamp = form.screenshot_timestamp;
    }
    if (form?.fingerprint && JSON.stringify(form.fingerprint) !== JSON.stringify(b.fingerprint)) {
      entry.fingerprint = deepClone(form.fingerprint);
    }
    if (form?.dom && JSON.stringify(form.dom) !== JSON.stringify(b.dom)) {
      entry.dom = deepClone(form.dom);
    }
    return Object.keys(entry).length > 0 ? entry : undefined;
  };

  // The form view for a scope: the variant entry's values (falling back to base)
  // for verifications + screenshot/fingerprint/dom.
  const formForScope = (form: any, scope: VariantScope, entry?: NodeVariantOverride): any => {
    const b = baseCaptureRef.current;
    const ev = entry?.verifications;
    const verifications =
      scope !== 'base' && Array.isArray(ev) && ev.length > 0
        ? deepClone(ev as any[])
        : deepClone(baseVerificationsRef.current);
    const variant = scope !== 'base';
    return {
      ...form,
      verifications,
      screenshot: variant ? entry?.screenshot ?? b.screenshot : b.screenshot,
      screenshot_timestamp: variant ? entry?.screenshot_timestamp ?? b.screenshot_timestamp : b.screenshot_timestamp,
      fingerprint: variant ? entry?.fingerprint ?? b.fingerprint : b.fingerprint,
      dom: variant ? entry?.dom ?? b.dom : b.dom,
    };
  };

  // Initialise local override map + scope when dialog opens / target node changes.
  useEffect(() => {
    if (!isOpen || !nodeForm?.id) return;
    const originalBase = (selectedNode?.data?.verifications as any[]) || [];
    baseVerificationsRef.current = deepClone(originalBase);
    const baseData = (selectedNode?.data as any) || {};
    baseCaptureRef.current = {
      screenshot: baseData.screenshot,
      screenshot_timestamp: baseData.screenshot_timestamp,
      fingerprint: baseData.fingerprint,
      dom: baseData.dom,
    };

    const map: Record<string, NodeVariantOverride> = {};
    for (const v of registeredVariants) {
      const entry = (v.node_overrides as any)?.[nodeForm.id];
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
      // Load the variant's verifications + screenshot/fingerprint/dom into the
      // form (each falls through to base when the variant has no override).
      setNodeForm(formForScope(nodeForm, desiredScope, map[desiredScope]));
    }
    // Intentionally only depends on isOpen + node identity.
  }, [isOpen, nodeForm?.id]);

  // Switch scope: stash the leaving scope's form contents as its full override,
  // then load the entering scope's content into the form.
  const handleVariantScopeChange = (next: VariantScope) => {
    if (next === variantScope) return;
    const currentForm = nodeForm;
    if (!currentForm) {
      setVariantScope(next);
      return;
    }
    // Stash the leaving scope's form contents as its override (capture fields +
    // verifications); drop the entry when nothing differs from base.
    let nextLocal = localOverrides;
    if (variantScope !== 'base') {
      const existing = localOverrides[variantScope];
      if (existing?.disabled !== true) {
        const leavingEntry = buildVariantEntry(currentForm, existing);
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

    setLocalOverrides(nextLocal);
    setNodeForm(formForScope(currentForm, next, next === 'base' ? undefined : nextLocal[next]));
    setVariantScope(next);
  };

  // ─── Replicate ▾ menu (per-row) ───────────────────────────────────────
  const [replicateAnchor, setReplicateAnchor] = useState<HTMLElement | null>(null);

  // Localize: the fingerprint is created automatically on screenshot capture;
  // this is just a manual recompute.
  const [fpBusy, setFpBusy] = useState(false);
  // "Use fingerprint" on (and a fingerprint exists): authored verifications are skipped.
  const fingerprintMode = (nodeForm as any)?.use_fingerprint_for_verification === true;
  const hasFingerprint = !!nodeForm?.fingerprint?.dhash;
  const [domOpen, setDomOpen] = useState(false);

  // Openable R2 URLs for the screenshot and its sibling DOM image (<stem>_dom.jpg).
  const { url: screenshotUrl } = useR2Url(nodeForm?.screenshot || null);
  const domKey = nodeForm?.screenshot
    ? nodeForm.screenshot.replace(/\.(jpe?g|png)$/i, '_dom.$1')
    : null;
  const { url: domUrl } = useR2Url(domKey);
  const nodeDom = (nodeForm as any)?.dom;
  const domCount = Array.isArray(nodeDom?.focusable_elements) ? nodeDom.focusable_elements.length : 0;

  // Regenerate = fingerprint + DOM together, from the stored screenshot (the DOM
  // call is the slow one, ~45-60s). Taking a new screenshot does the same automatically.
  const handleRegenerateFingerprint = async () => {
    if (!nodeForm?.screenshot) return;
    setFpBusy(true);
    const body = JSON.stringify({ host_name: selectedHost?.host_name, screenshot_url: nodeForm.screenshot });
    const post = (path: string) =>
      fetch(buildServerUrl(path), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body })
        .then((r) => r.json())
        .catch(() => ({}));
    try {
      const [fp, dom] = await Promise.all([post('/server/av/regionFingerprint'), post('/server/av/generateDom')]);
      const patch: any = {};
      if (fp?.success && fp.fingerprint) patch.fingerprint = fp.fingerprint;
      if (dom?.success && dom.dom !== undefined) patch.dom = dom.dom;
      if (Object.keys(patch).length === 0) return;
      setNodeForm({ ...nodeForm, ...patch });
      // In a variant scope the form holds the variant view and persistence
      // runs through handleSave's override stash — only write base directly
      // in base scope (else we'd clobber the base fingerprint/dom).
      if (nodeForm.id && variantScope === 'base') onUpdateNode?.(nodeForm.id, patch);
    } finally {
      setFpBusy(false);
    }
  };
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
    const base = baseVerificationsRef.current;
    const formVerifs = (nodeForm.verifications as any[]) || [];

    let newEntry: NodeVariantOverride;
    if (source === 'base') {
      // Copy base's full verifications onto the target variant.
      newEntry = { verifications: deepClone(base) };
    } else {
      const sourceEntry = localOverrides[source];
      if (!sourceEntry) return;
      if (sourceEntry.disabled === true) {
        newEntry = { disabled: true };
      } else {
        // Live form contents reflect the source variant's view.
        newEntry = { verifications: deepClone(formVerifs) };
      }
    }

    setLocalOverrides((m) => ({ ...m, [target]: newEntry }));
    dirtyVariantsRef.current.add(target);
    showToastSuccess(`Replicated to '${target}' on this node.`);
  };

  const handlePickReplicate = (target: string) => {
    closeReplicateMenu();
    const exists = Boolean(localOverrides[target]);
    const sourceLabel = variantScope === 'base' ? 'Base' : variantScope;

    const doConfirm = () => {
      confirm({
        title: 'Replicate variant',
        message: `Replicate this node's '${sourceLabel}' overrides to variant '${target}'?`,
        confirmText: 'Replicate',
        cancelText: 'Cancel',
        confirmColor: 'primary',
        onConfirm: () => performReplicate(target),
      });
    };

    if (exists) {
      confirm({
        title: 'Variant entry already exists',
        message: `Variant '${target}' already has overrides on this node. Replace?`,
        confirmText: 'Replace',
        cancelText: 'Cancel',
        confirmColor: 'warning',
        onConfirm: doConfirm,
      });
    } else {
      doConfirm();
    }
  };

  // ─── Reset variant override (this node only) ──────────────────────────
  // Clear THIS node's entry from the active variant's `node_overrides` map
  // so the node falls through to Base for that variant. Other nodes on the
  // same variant are untouched. Only shown when scope !== 'base'.
  //
  // Executes immediately on click — the toast is the user-visible feedback.
  // No confirm modal (see matching note in Navigation_EdgeEditDialog).
  const handleResetVariant = async () => {
    if (variantScope === 'base' || !nodeForm?.id) return;
    const nodeId = nodeForm.id;
    const variant = registeredVariants.find((v) => v.name === variantScope);
    if (!variant) return;

    try {
      const nextMap: Record<string, NodeVariantOverride> = { ...(variant.node_overrides || {}) };
      delete nextMap[nodeId];
      await updateVariantOverrides(variantScope, { node_overrides: nextMap });

      // Drop the in-memory entry and clear the dirty flag so a subsequent
      // Save doesn't re-write the deleted key.
      setLocalOverrides((prev) => {
        const { [variantScope]: _removed, ...rest } = prev;
        void _removed;
        return rest;
      });
      dirtyVariantsRef.current.delete(variantScope);

      // Push a fresh resolved node so the Node Selection panel reflects
      // Base content. `selectedNode` is the canvas-RESOLVED node — its
      // `data.verifications` is the variant-patched view (and so is
      // `baseVerificationsRef.current` when the dialog opened in a
      // variant scope). Pull the TRUE base from the raw `nodes` array
      // in NavigationContext.
      if (selectedNode && initialVariantScope === variantScope) {
        const rawNode = rawNodes.find((n) => n.id === nodeId);
        const trueBaseVerifications = (rawNode?.data as any)?.verifications || [];
        const newResolvedNode: UINavigationNode = {
          ...selectedNode,
          data: {
            ...(selectedNode.data || {}),
            verifications: deepClone(trueBaseVerifications),
          },
        } as UINavigationNode;
        setSelectedNode(newResolvedNode);
      }

      showToastSuccess(`Reset '${variantScope}' override on this node.`);
      onClose();
    } catch (err) {
      showToastError(
        `Failed to reset variant: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  };

  // ─── Reset per-variant canvas position (this node only) ───────────────
  // Clears just the `position` key from the active variant's entry so the node
  // returns to the base layout for that variant, WITHOUT touching any
  // verifications override on the same entry. If position was the entry's only
  // field, the whole entry is dropped (node falls through to base). Shown only
  // when the active variant actually carries a position for this node.
  const activeVariantEntry =
    variantScope === 'base'
      ? undefined
      : ((registeredVariants.find((v) => v.name === variantScope)?.node_overrides as any)?.[
          nodeForm?.id || ''
        ] as NodeVariantOverride | undefined);
  const hasPositionOverride = !!activeVariantEntry?.position;

  const handleResetPosition = async () => {
    if (variantScope === 'base' || !nodeForm?.id) return;
    const nodeId = nodeForm.id;
    const variant = registeredVariants.find((v) => v.name === variantScope);
    const entry = (variant?.node_overrides as any)?.[nodeId] as NodeVariantOverride | undefined;
    if (!variant || !entry?.position) return;
    try {
      const nextMap: Record<string, NodeVariantOverride> = { ...(variant.node_overrides || {}) };
      const { position: _pos, ...rest } = entry;
      void _pos;
      if (Object.keys(rest).length === 0) {
        delete nextMap[nodeId];
      } else {
        nextMap[nodeId] = rest;
      }
      await updateVariantOverrides(variantScope, { node_overrides: nextMap });
      // Keep the dialog's in-memory override map in sync (strip position).
      setLocalOverrides((prev) => {
        const cur = (prev[variantScope] || {}) as NodeVariantOverride;
        const { position: _p2, ...restCur } = cur;
        void _p2;
        if (Object.keys(restCur).length === 0) {
          const { [variantScope]: _removed, ...others } = prev;
          void _removed;
          return others;
        }
        return { ...prev, [variantScope]: restCur };
      });
      showToastSuccess(`Reset '${variantScope}' position on this node.`);
    } catch (err) {
      showToastError(
        `Failed to reset position: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  };

  // ─── Save: write base columns + dirty variant override entries ───────
  //
  // The user's form holds the variant's full view. Per the "variant data
  // lives on variant row" rule (VARIANT.md §2), stash the form's
  // verifications as the active variant's `verifications` override
  // (committed below). The base PUT is skipped in variant scope, so we
  // leave nodeForm untouched — resetting it to base here would flash old
  // content in the dialog body before onClose.
  const handleSave = async () => {
    let finalLocal = localOverrides;
    // Owned variant-only rows skip the override stash — their content lives in
    // the row's base columns (written by nodeEdit.handleSave below).
    if (variantScope !== 'base' && !isVariantOnlyOwned && nodeForm) {
      const formVerifs = (nodeForm.verifications as any[]) || [];
      if (baseVerificationsRef.current.length === 0 && formVerifs.length > 0) {
        baseVerificationsRef.current = deepClone(formVerifs);
      }
      const existing = localOverrides[variantScope];
      if (existing?.disabled !== true) {
        // Build the variant entry from the form: verifications + the capture
        // fields (screenshot/fingerprint/dom), each kept only when it differs
        // from base. Nothing differs → drop the entry (variant falls through).
        // `existing` is passed so buildVariantEntry carries forward the fields the
        // form doesn't own — `position` (per-variant canvas layout, set by
        // dragging) and `enabled` (variant-only ownership marker) — which a
        // rebuild would otherwise silently wipe.
        const nextEntry = buildVariantEntry(nodeForm, existing);
        if (nextEntry === undefined) {
          const { [variantScope]: _removed, ...rest } = localOverrides;
          void _removed;
          finalLocal = rest;
        } else {
          finalLocal = { ...localOverrides, [variantScope]: nextEntry };
        }
        dirtyVariantsRef.current.add(variantScope);
      }
      // Don't reset nodeForm back to base — the base PUT is skipped in
      // variant scope, so the reset only flashes old content in the dialog
      // body before onClose. finalLocal already captured formVerifs above.
      setLocalOverrides(finalLocal);
    }

    // 2. Save the node row's base columns — when scope is base, OR when this is
    //    a variant-only row owned by the active variant (its topology +
    //    verifications live in the row's own columns; hidden_in_base round-trips
    //    through nodeForm so the row stays variant-only). For a SHARED row in a
    //    variant scope this is skipped (topology disabled, verifications go to
    //    the variant override above) so the POST /nodes + host cache update
    //    would be no-ops.
    if (editsBaseColumns) {
      await nodeEdit.handleSave();
    }

    // 3. Persist any dirty variant overrides to the variant rows. PUTs go
    //    out in parallel with skipRefresh; single refresh at the end (without
    //    skipRefresh each PUT fired its own GET = N+1 reads for N writes).
    const nodeId = nodeForm?.id;
    if (nodeId && dirtyVariantsRef.current.size > 0) {
      const dirtyNames = Array.from(dirtyVariantsRef.current);
      const tasks = dirtyNames.map((variantName) => {
        const v = registeredVariants.find((x) => x.name === variantName);
        if (!v) return Promise.resolve();
        const newEntry = finalLocal[variantName];
        const nextMap: Record<string, NodeVariantOverride> = { ...(v.node_overrides || {}) };
        if (newEntry === undefined) {
          delete nextMap[nodeId];
        } else {
          nextMap[nodeId] = newEntry;
        }
        return updateVariantOverrides(variantName, { node_overrides: nextMap }, { skipRefresh: true });
      });
      const results = await Promise.allSettled(tasks);
      const failures = results
        .map((r, i) => (r.status === 'rejected' ? dirtyNames[i] : null))
        .filter((n): n is string => n !== null);
      if (failures.length > 0) {
        showToastError(
          `Failed to save on variant${failures.length > 1 ? 's' : ''}: ${failures.join(', ')}`,
        );
      }
      await refreshVariants();
      dirtyVariantsRef.current = new Set();
    }

    // After a variant-scope save, `nodeEdit.handleSave()` is skipped so
    // NavigationContext never refreshes `selectedNode`. The Node Selection
    // panel reads from `selectedNode`, so without this push it re-renders
    // with the pre-save verifications. Build the new resolved node from the
    // canvas-viewing scope (`initialVariantScope`) and the freshly-saved
    // override map; mirrors the edge-side refreshSelectedEdgeForCanvasScope
    // and the base-save path in NavigationContext.tsx.
    if (variantScope !== 'base' && !isVariantOnlyOwned && selectedNode) {
      const canvasScope = initialVariantScope;
      if (canvasScope && canvasScope !== 'base') {
        const entry = finalLocal[canvasScope];
        // True base must come from the raw nodes array (canonical
        // pre-resolution store). `baseVerificationsRef.current` was captured
        // from `selectedNode` at dialog-open time and reflects the canvas's
        // resolved view — variant-patched when the canvas opened in variant
        // scope, not base.
        const rawNodeForBase = rawNodes.find((n) => n.id === selectedNode.id);
        const trueBaseVerifs = (rawNodeForBase?.data as any)?.verifications || [];
        let resolvedVerifs: any[];
        if (entry?.disabled === true) {
          resolvedVerifs = trueBaseVerifs;
        } else if (
          Array.isArray(entry?.verifications) &&
          entry.verifications.length > 0
        ) {
          resolvedVerifs = entry.verifications;
        } else {
          resolvedVerifs = trueBaseVerifs;
        }
        const newResolvedNode: UINavigationNode = {
          ...selectedNode,
          data: {
            ...(selectedNode.data || {}),
            verifications: deepClone(resolvedVerifs),
          },
        } as UINavigationNode;
        setSelectedNode(newResolvedNode);
      }
    }
    onClose();
  };

  // Get button visibility from the hook
  const { canTest } = nodeEdit.getButtonVisibility();
  const isRunningVerifications = nodeEdit.verification.loading;
  const isDialogLocked = isRunningVerifications;
  // Which run is in flight, so only ITS control animates: a row's own play button
  // ('single'), the fingerprint button ('fingerprint'), or the footer Run ('all').
  const [runKind, setRunKind] = useState<'single' | 'fingerprint' | 'all' | null>(null);
  useEffect(() => {
    if (!isRunningVerifications) setRunKind(null);
  }, [isRunningVerifications]);
  const runFingerprint = () => {
    setRunKind('fingerprint');
    void nodeEdit.verification.handleFingerprintVerify(
      nodeForm?.fingerprint,
      (nodeForm as any)?.label || (nodeForm as any)?.display_name,
    );
  };

  // Check if there are verifications to run
  const hasVerifications = nodeEdit.verification.verifications.length > 0;

  // ─── Recapture reference (in place, same area) ────────────────────────
  // One-click "the screen changed, retake this reference". Takes a fresh
  // screenshot, crops it with the reference's stored area (box + fuzzy), and
  // overwrites the asset. Needs an active device. Confirmation reuses the
  // dialog's own ConfirmDialog below.
  const { recapture, recapturingIndex } = useReferenceRecapture(userInterface?.name);

  const handleRecaptureReference = (index: number) => {
    const verif = nodeEdit.verification.verifications[index];
    const internalKey = (verif?.params as any)?.reference_name;
    if (!internalKey) return;
    const ref = (nodeEdit.modelReferences as any)[internalKey];
    const displayName = ref?.name || internalKey;
    // Focus intent: explicit per-verification flag, else whether the reference
    // already carries a learned focus accent.
    const checkFocus = Boolean((verif?.params as any)?.check_focus ?? (ref?.area as any)?.focus);
    confirm({
      title: 'Recapture Reference',
      message:
        `Take a new screenshot and overwrite reference "${displayName}" using its current area?\n\n` +
        'This replaces the saved image for every node and edge that uses it. The area and fuzzy area are kept unchanged.' +
        (checkFocus ? '\n\nFocus is on — the selected/focused accent will be re-learned from this capture.' : ''),
      confirmText: 'Recapture',
      confirmColor: 'warning',
      onConfirm: () => {
        void recapture(index, internalKey, checkFocus);
      },
    });
  };

  const handleRunSingleVerification = async (index: number) => {
    if (!canTest || isRunningVerifications) return;
    setRunKind('single');
    await nodeEdit.verification.handleTestSingle(index);
  };

  const handleDialogClose = (_event?: object, reason?: 'backdropClick' | 'escapeKeyDown') => {
    if (isRunningVerifications && (reason === 'backdropClick' || reason === 'escapeKeyDown')) {
      return;
    }
    if (!isRunningVerifications) {
      onClose();
    }
  };

  const formatVerificationDuration = (ms: number): string => {
    const totalSeconds = Math.max(0, Math.round(ms / 1000));
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    if (minutes === 0) return `${seconds}s`;
    return `${minutes}m:${String(seconds).padStart(2, '0')}s`;
  };

  // Pick the most descriptive label for a verification line:
  //   waitForImageToAppear(home_red)   when params.image_path is known
  //   waitForTextToAppear(Home|Startseite) when params.text is known
  //   image: <message> as the fallback
  // Source verification (by index) supplies command/params if the result
  // payload doesn't carry them.
  const buildVerificationLineLabel = (result: any, index: number): string => {
    const sourceVerif = nodeEdit.verification.verifications?.[index];
    const command =
      result.command || sourceVerif?.command || result.verification_type || 'verification';
    const params = result.params || (sourceVerif?.params as any) || {};
    const verificationType = result.verification_type || sourceVerif?.verification_type;
    let value: string | undefined;
    if (verificationType === 'image' && typeof params.image_path === 'string') {
      value = params.image_path;
    } else if (verificationType === 'text' && typeof params.text === 'string') {
      value = params.text;
    } else if (typeof result.message === 'string' && result.message.trim()) {
      value = result.message.replace(/^reference:\s*/i, '');
    }
    return value ? `${command}(${value})` : command;
  };

  // Render a single verification result line, with its own evidence report
  // link inline (success report for passes, debug report for failures) so each
  // link is unambiguously tied to the verification it belongs to.
  const renderVerificationResult = (result: any, index: number) => {
    // 'any can pass' short-circuits: once one leg passes, the executor marks the
    // remaining legs as skipped (neutral — neither pass nor fail) so a
    // never-needed check (e.g. no_signal) doesn't read as a real failure.
    const label = buildVerificationLineLabel(result, index);
    // Show the controller's message on success too. A passing image match can
    // still be borderline (e.g. score 0.81 vs threshold 0.80) and the only way
    // to spot a suspect green tick is to see the score next to it.
    const detail = (result.error || result.message || '').replace(/^reference:\s*/i, '');
    // One report per verification: success report when it passed, debug report
    // when it failed. Only manual verifications generate these.
    const lineText = `${label}${detail && !label.includes(detail) ? `: ${detail}` : ''}`;
    const reportUrl = result.success ? result.success_report_url : result.debug_report_url;
    const reportLabel = result.success ? 'View Success Report' : 'View Debug Report';

    return (
      <Box key={index} sx={{ mb: 0 }}>
        <Typography
          variant="caption"
          sx={{
            fontFamily: 'monospace',
            fontSize: TYPOGRAPHY.caption.size,
            lineHeight: 1.2,
            display: 'block',
          }}
        >
          {result.skipped ? (
            <>
              <AppIcon name="pending" /> {lineText}
            </>
          ) : (
            <StatusText ok={!!result.success}>{lineText}</StatusText>
          )}
        </Typography>
        {!result.skipped && reportUrl && (
          <Typography
            variant="caption"
            sx={{
              fontFamily: 'monospace',
              fontSize: TYPOGRAPHY.microMeta.size,
              lineHeight: 1.2,
              display: 'block',
              pl: 2,
            }}
          >
            <a
              href={reportUrl}
              onClick={(e) => {
                e.preventDefault();
                void openHostUrl(reportUrl);
              }}
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: 'inherit', textDecoration: 'underline' }}
            >
              {reportLabel}
            </a>
          </Typography>
        )}
      </Box>
    );
  };

  // Topology fields are read-only in a variant scope — EXCEPT for a variant-only
  // row owned by that scope, which has no base version to protect and so is
  // fully editable (§3.4 + VARIANT.md §5).
  const topologyDisabled = !editsBaseColumns;

  // Enforce unique node labels (base scope only — variant scope can't rename).
  // action_set ids are derived from source/target labels, so a duplicate label
  // would make two edges collide on the same id. Compare case-insensitively
  // against every OTHER node; subtree-root mirror placeholders share the same
  // node id and so are excluded by the id check, not flagged as duplicates.
  const trimmedLabel = (nodeForm.label || '').trim().toLowerCase();
  const isDuplicateLabel =
    !topologyDisabled &&
    !!trimmedLabel &&
    (nodes || []).some(
      (n) => n.id !== nodeForm.id && (n.data?.label || '').trim().toLowerCase() === trimmedLabel,
    );

  return (
    <StyledDialog
      open={isOpen}
      onClose={handleDialogClose}
      disableEscapeKeyDown={isRunningVerifications}
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
            <Typography variant="h6">Edit Node</Typography>
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
            />
            {/* Replicate button — header top-right, only when editing a variant
                scope. Hidden for owned variant-only rows: they have no override
                to replicate (their content is the row's base columns). */}
            {variantScope !== 'base' && !isVariantOnlyOwned && replicateTargets.length > 0 && (
              <Tooltip title={`Replicate this node's '${variantScope}' overrides to another variant`}>
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

      <DialogContent sx={{ py: 0.5 }}>
        {showInitialLoader ? (
          <Box
            sx={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 1,
              minHeight: 280,
            }}
          >
            <CircularProgress size={28} />
            <Typography variant="body2" color="text.secondary">
              Loading verifications and references…
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
        {/* Node Name and Type in columns */}
        <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
          <TextField
            label="Node Name"
            value={nodeForm?.label || ''}
            onChange={(e) => setNodeForm({ ...nodeForm, label: e.target.value })}
            fullWidth
            required
            error={!nodeForm?.label?.trim() || isDuplicateLabel}
            helperText={isDuplicateLabel ? 'A node with this name already exists — names must be unique' : undefined}
            margin="dense"
            size="small"
            autoComplete="off"
            disabled={topologyDisabled}
          />
          <FormControl fullWidth margin="dense" size="small" disabled={topologyDisabled}>
            <InputLabel>Type</InputLabel>
            <Select
              value={nodeForm?.type || 'screen'}
              label="Type"
              onChange={(e) => setNodeForm({ ...nodeForm, type: e.target.value as any })}
            >
              <MenuItem value="menu">Menu</MenuItem>
              <MenuItem value="screen">Screen</MenuItem>
              <MenuItem value="action">Action</MenuItem>
            </Select>
          </FormControl>
          {/* Optional friendly display name. Top row, after Type — surfaces in
              the node picker + reports (e.g. standby_measurement names the run by
              the standby mode node) when the raw label isn't descriptive enough.
              Lives in data.display_name. Mirrors the edge "KPI display name". */}
          <TextField
            label="Display name"
            placeholder="e.g. [TC266] Eco (ColdStandby)"
            value={nodeForm?.display_name || ''}
            onChange={(e) => setNodeForm({ ...nodeForm, display_name: e.target.value })}
            fullWidth
            margin="dense"
            size="small"
            autoComplete="off"
            disabled={topologyDisabled}
          />
        </Box>

        {/* Details — depth, priority, parent, live and description are secondary:
            collapsed by default, one summary line keeps the values readable. */}
        <DetailsSection
          summary={[
            `depth ${nodeForm?.depth || 0}`,
            (nodeForm?.priority || 'p3').toUpperCase(),
            `parent ${nodeEdit.getParentNames(nodeForm?.parent || [], nodes) || '—'}`,
            nodeForm?.description ? nodeForm.description : 'no description',
          ]
            .filter(Boolean)
            .join(' · ')}
        >
          <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
            <TextField
              label="Depth"
              value={nodeForm?.depth || 0}
              InputProps={{ readOnly: true }}
              variant="outlined"
              margin="dense"
              size="small"
              autoComplete="off"
              disabled={topologyDisabled}
              sx={{ width: 90, flexShrink: 0 }}
            />
            <FormControl fullWidth margin="dense" size="small" disabled={topologyDisabled}>
              <InputLabel>Priority</InputLabel>
              <Select
                value={nodeForm?.priority || 'p3'}
                label="Priority"
                onChange={(e) =>
                  setNodeForm({ ...nodeForm, priority: e.target.value as 'p1' | 'p2' | 'p3' })
                }
              >
                <MenuItem value="p1">P1 Critical</MenuItem>
                <MenuItem value="p2">P2 Major</MenuItem>
                <MenuItem value="p3">P3 Minor</MenuItem>
              </Select>
            </FormControl>
            <TextField
              label="Parent"
              value={nodeEdit.getParentNames(nodeForm?.parent || [], nodes)}
              fullWidth
              InputProps={{ readOnly: true }}
              variant="outlined"
              margin="dense"
              size="small"
              autoComplete="off"
              disabled={topologyDisabled}
            />
          </Box>
          <TextField
            label="Description"
            value={nodeForm?.description || ''}
            onChange={(e) => setNodeForm({ ...nodeForm, description: e.target.value })}
            fullWidth
            multiline
            minRows={1}
            maxRows={4}
            margin="dense"
            size="small"
            autoComplete="off"
          />
        </DetailsSection>

        {/* Screenshot — collapsible like Details: thumbnail shown directly (click = open in a new tab),
            URL with ✕ delete underneath. Collapsed, one summary line shows the file name. */}
        {(nodeForm?.type as string) !== 'entry' && (
          <DetailsSection
            title="Screenshot"
            defaultOpen
            summary={nodeForm?.screenshot ? String(nodeForm.screenshot).split('/').pop() || '' : 'none'}
          >
            <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1.5 }}>
              {screenshotUrl ? (
                <Tooltip title="Open screenshot in new tab">
                  <Box
                    component="img"
                    src={screenshotUrl}
                    alt="Screenshot"
                    onClick={() => void openHostUrl(screenshotUrl)}
                    sx={{
                      width: 150,
                      aspectRatio: '16 / 9',
                      objectFit: 'cover',
                      borderRadius: 1,
                      flex: 'none',
                      cursor: 'pointer',
                      bgcolor: 'common.black',
                    }}
                  />
                </Tooltip>
              ) : (
                <Box
                  sx={{ width: 150, aspectRatio: '16 / 9', borderRadius: 1, flex: 'none', border: `1px dashed ${P.borderColor}` }}
                />
              )}
              <TextField
                label="URL"
                value={nodeForm?.screenshot || ''}
                onChange={(e) => setNodeForm({ ...nodeForm, screenshot: e.target.value })}
                margin="dense"
                size="small"
                autoComplete="off"
                sx={{ flexGrow: 1, mt: 0, '& input': { textOverflow: 'ellipsis' } }}
                InputProps={{
                  endAdornment: nodeForm?.screenshot && (
                    <IconButton
                      size="small"
                      sx={{ color: 'error.main' }}
                      onClick={() => {
                        confirm({
                          title: 'Delete Screenshot',
                          message: 'Are you sure you want to delete this screenshot from R2 storage?',
                          confirmColor: 'error',
                          onConfirm: async () => {
                            try {
                              await nodeEdit.handleDeleteScreenshot();
                            } catch (error) {
                              alert('Failed to delete screenshot: ' + error);
                            }
                          },
                        });
                      }}
                    >
                      <CloseIcon fontSize="small" />
                    </IconButton>
                  ),
                }}
              />
            </Box>
          </DetailsSection>
        )}

        {/* Verification Section */}
        <Box
          sx={{
            border: '1px solid',
            borderColor: 'divider',
            borderRadius: 1,
            p: 1,
            mb: 1,
          }}
        >
          {/* One mode switch: the node is verified by its authored checks OR by its
              fingerprint; the other is hidden. Run (bottom right) runs whichever is on. */}
          <Box sx={{ display: 'flex', alignItems: 'center', mb: 0.75 }}>
            <ToggleButtonGroup
              exclusive
              size="small"
              value={fingerprintMode ? 'fingerprint' : 'verifications'}
              onChange={(_e, v) => {
                if (!v) return;
                setNodeForm({ ...nodeForm, use_fingerprint_for_verification: v === 'fingerprint' } as any);
              }}
              disabled={isDialogLocked}
              sx={segmentedSx(P, 'sm')}
            >
              <ToggleButton value="verifications">
                Verifications
                <Typography component="span" sx={{ ml: 0.75, fontSize: TYPOGRAPHY.caption.size, opacity: 0.7 }}>
                  {nodeEdit.verification.verifications.length}
                </Typography>
              </ToggleButton>
              <ToggleButton value="fingerprint">
                Fingerprint
                <Box
                  component="span"
                  sx={{
                    ml: 0.75,
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 0.5,
                    fontSize: TYPOGRAPHY.caption.size,
                    color: hasFingerprint ? P.success : P.textMuted,
                  }}
                >
                  <Box
                    component="span"
                    sx={{
                      width: 7,
                      height: 7,
                      borderRadius: '50%',
                      bgcolor: hasFingerprint ? P.success : 'transparent',
                      border: `1px solid ${hasFingerprint ? P.success : P.textMuted}`,
                    }}
                  />
                  {hasFingerprint ? 'ready' : 'none'}
                </Box>
              </ToggleButton>
            </ToggleButtonGroup>
          </Box>
          {fingerprintMode ? (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, py: 0.5 }}>
              {screenshotUrl && (
                <Box
                  component="img"
                  src={screenshotUrl}
                  alt="Screenshot"
                  sx={{ width: 150, aspectRatio: '16 / 9', objectFit: 'cover', borderRadius: 1, flex: 'none' }}
                />
              )}
              <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 1 }}>
                <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary }}>
                  {!nodeForm?.screenshot
                    ? 'Take a screenshot first: the fingerprint is built from it.'
                    : hasFingerprint
                      ? `Fingerprint v${nodeForm?.fingerprint?.v ?? '?'} · DOM ${nodeDom ? `${domCount} elements` : 'not captured (optional)'}`
                      : 'Built from the screenshot above (~1 min with the DOM).'}
                </Typography>
                {hasFingerprint && (
                  <Box
                    sx={{
                      fontFamily: 'monospace',
                      fontSize: TYPOGRAPHY.caption.size,
                      color: P.textSecondary,
                      lineHeight: 1.5,
                      wordBreak: 'break-all',
                    }}
                  >
                    {[
                      ['dHash', (nodeForm.fingerprint as any).dhash],
                      ['title', (nodeForm.fingerprint as any).title || '—'],
                      ['focus', JSON.stringify((nodeForm.fingerprint as any).focus ?? null)],
                      [
                        'regions',
                        Object.keys((nodeForm.fingerprint as any).regions || {}).join(', ') || '—',
                      ],
                      ['crop', (nodeForm.fingerprint as any).crop || '—'],
                      ['captured', (nodeForm.fingerprint as any).captured_at || '—'],
                    ].map(([k, v]) => (
                      <Box key={k}>
                        <Box component="span" sx={{ color: P.textMuted }}>
                          {k}{' '}
                        </Box>
                        {v}
                      </Box>
                    ))}
                  </Box>
                )}
                <Box sx={{ display: 'flex', gap: 1 }}>
                  {hasFingerprint && (
                    <Button
                      size="small"
                      variant="outlined"
                      sx={neutralButtonSx(P)}
                      onClick={() => void navigator.clipboard.writeText(JSON.stringify(nodeForm.fingerprint, null, 2))}
                    >
                      Copy JSON
                    </Button>
                  )}
                  <Button
                    size="small"
                    variant="outlined"
                    sx={neutralButtonSx(P)}
                    disabled={!nodeForm?.screenshot || fpBusy || isDialogLocked}
                    onClick={handleRegenerateFingerprint}
                    startIcon={fpBusy ? <CircularProgress size={14} /> : undefined}
                  >
                    {hasFingerprint ? 'Regenerate' : 'Create'}
                  </Button>
                  {nodeDom && (
                    <Button size="small" variant="outlined" sx={neutralButtonSx(P)} onClick={() => setDomOpen(true)}>
                      Open DOM
                    </Button>
                  )}
                </Box>
              </Box>
            </Box>
          ) : (
          <Box>
          <VerificationsList
            verifications={nodeEdit.verification.verifications}
            availableVerifications={nodeEdit.verification.availableVerificationTypes}
            onVerificationsChange={nodeEdit.handleVerificationsChange}
            // Keep NodeEdit loading visuals aligned with EdgeEdit:
            // we use dialog-level LinearProgress + per-item spinner only.
            loading={false}
            model={model || 'android_mobile'}
            selectedHost={selectedHost}
            testResults={[]} // Don't show individual results, only show consolidated results below
            onReferenceSelected={() => {}}
            modelReferences={nodeEdit.modelReferences}
            referencesLoading={nodeEdit.referencesLoading}
            showCollapsible={false}
            title=""
            // Dialog-level Run button is the single source of batch test execution.
            onTest={undefined}
            passCondition={nodeForm?.verification_pass_condition || 'all'}
            onPassConditionChange={(condition) => setNodeForm({ ...nodeForm, verification_pass_condition: condition })}
            onRunVerification={handleRunSingleVerification}
            runDisabled={!canTest}
            runningVerificationIndex={nodeEdit.verification.runningVerificationIndex}
            disabled={isDialogLocked}
            // Image reference content (the stored crop) is authored in
            // VerificationEditor — that has the capture/preview/overwrite
            // confirmation flow. Editing an image's area here can't re-crop
            // the stored asset, so image references stay locked (use the
            // Recapture button, which keeps the area and refreshes the crop).
            referenceReadOnly={true}
            // TEXT references, however, are just text + area (no stored crop),
            // so they're safe to edit inline. allowReferenceEdit unlocks the
            // Search Text field + X/Y/W/H for text verifications; handleSave
            // (useNodeEdit) writes the edit back to the reference row so the
            // node's inline snapshot and verifications_references stay in sync.
            // NOTE: this overwrites the shared text reference for every other
            // node/edge that uses it — same blast radius as a VerificationEditor
            // save (intended: keep all consumers in lockstep).
            allowReferenceEdit={true}
            // Recapture overwrites the image in place with the SAME area, so
            // it's safe (and useful) here even though area editing is locked.
            // Needs a live device — only wired when control is active.
            onRecaptureReference={
              isControlActive ? handleRecaptureReference : undefined
            }
            recapturingIndex={recapturingIndex}
            compact
          />
          </Box>
          )}
        </Box>

        </Box>
        )}

        {/* Linear Progress - shown when running (outside locked Box so it
            doesn't shift content above it like EdgeEditDialog) */}
        {runKind === 'all' && (
          <Box sx={{ mt: 1 }}>
            <LinearProgress sx={{ borderRadius: 1 }} />
          </Box>
        )}

        {/* Verification Test Results — outside the locked Box so the
            colored pass/fail panel renders crisply at the bottom (mirrors
            EdgeEditDialog). Format unified with edge dialog:
            "✅ command(value)" per line, then a summary line
            "✅ Execution X/Y passed in Xm:YYs". */}
        {nodeEdit.verification.testResults && nodeEdit.verification.testResults.length > 0 && (() => {
          const results = nodeEdit.verification.testResults as any[];
          const passCondition = nodeForm?.verification_pass_condition || 'all';
          const batchPassed =
            passCondition === 'all'
              ? results.every((r) => r.success)
              : results.some((r) => r.success);
          const passed = results.filter((r) => r.success).length;
          const total = results.length;
          const durationMs = nodeEdit.verification.lastTestDurationMs;
          const durationStr =
            typeof durationMs === 'number' ? formatVerificationDuration(durationMs) : null;
          const summaryText = durationStr
            ? `Execution ${passed}/${total} passed in ${durationStr}`
            : `Execution ${passed}/${total} passed`;

          return (
            <Box
              sx={{
                p: 1,
                bgcolor: batchPassed ? `${P.success}1f` : `${P.error}1f`,
                color: P.textPrimary,
                borderRadius: 1,
                maxHeight: 200,
                overflow: 'auto',
                mt: 1,
                border: `1px solid ${batchPassed ? P.success : P.error}`,
              }}
            >
              {results.map((result: any, index: number) =>
                renderVerificationResult(result, index),
              )}
              <Typography
                variant="caption"
                sx={{
                  fontFamily: 'monospace',
                  fontSize: TYPOGRAPHY.caption.size,
                  lineHeight: 1.2,
                  display: 'block',
                }}
              >
                <StatusText ok={batchPassed}>{summaryText}</StatusText>
              </Typography>
            </Box>
          );
        })()}

        {/* A run that produced NO results — a timeout, or a host that could not
            run it at all — used to leave nothing here: the spinner stopped, the
            panel stayed empty and the only explanation was a toast that faded.
            The cause now renders where the results would have been. */}
        {nodeEdit.verification.error &&
          !(nodeEdit.verification.testResults && nodeEdit.verification.testResults.length > 0) && (
            <Box
              sx={{
                p: 1,
                mt: 1,
                bgcolor: `${P.error}1f`,
                color: P.textPrimary,
                borderRadius: 1,
                maxHeight: 200,
                overflow: 'auto',
                border: `1px solid ${P.error}`,
              }}
            >
              <Typography
                variant="caption"
                sx={{
                  fontFamily: 'monospace',
                  fontSize: TYPOGRAPHY.caption.size,
                  lineHeight: 1.2,
                  display: 'block',
                  whiteSpace: 'pre-line',
                }}
              >
                {`${nodeEdit.verification.error}`}
              </Typography>
            </Box>
          )}

        {/* Independent Localize cross-check (true/false/unknown that the live
            screen is on this node) — surfaced under the verification result. */}
        <LocalizeCheckFooter check={nodeEdit.verification.localizeCheck} />
      </DialogContent>

      <DialogActions sx={{ pt: 0.5, display: 'flex', gap: 1 }}>
        {onResetNode && (
          <Button onClick={() => onResetNode()} variant="outlined" disabled={isDialogLocked} sx={neutralButtonSx(P)}>
            Reset node
          </Button>
        )}
        {variantScope !== 'base' && !isVariantOnlyOwned && (
          <Button
            onClick={handleResetVariant}
            variant="outlined"
            disabled={isDialogLocked}
            sx={neutralButtonSx(P)}
          >
            Reset variant
          </Button>
        )}
        {variantScope !== 'base' && !isVariantOnlyOwned && hasPositionOverride && (
          <Tooltip title="Clear this variant's canvas position for this node (returns it to the base layout)">
            <Button
              onClick={handleResetPosition}
              variant="outlined"
              disabled={isDialogLocked}
              sx={neutralButtonSx(P)}
            >
              Reset position
            </Button>
          </Tooltip>
        )}
        <Box sx={{ flex: 1 }} />
        <Button onClick={handleSave} variant="contained" disabled={!nodeEdit.isFormValid(nodeForm) || isDialogLocked || isDuplicateLabel}>
          {nodeEdit.saveSuccess ? <AppIcon name="success" /> : 'Save'}
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
        {/* Run — runs whichever mode is selected: the authored checks, or the fingerprint match. */}
        {(hasVerifications || fingerprintMode) && (
          <Button
            onClick={() => {
              if (fingerprintMode) {
                runFingerprint();
              } else {
                void nodeEdit.verification.handleTest();
              }
              setRunKind('all');
            }}
            variant="outlined"
            sx={neutralButtonSx(P)}
            disabled={
              isDialogLocked || nodeEdit.verification.loading || (fingerprintMode ? !hasFingerprint : !canTest)
            }
          >
            {runKind === 'all' ? 'Running...' : 'Run'}
          </Button>
        )}
      </DialogActions>

      <NodeDomDialog
        open={domOpen}
        onClose={() => setDomOpen(false)}
        nodeLabel={nodeForm?.label}
        dom={nodeDom}
        screenshotUrl={screenshotUrl}
        overlayUrl={domUrl}
      />

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
    </StyledDialog>
  );
};

export const NodeEditDialog: React.FC<NodeEditDialogProps> = (props) => {
  const { nodeForm, selectedHost } = props;

  // No form, an entry node (not editable), or no host yet: nothing to render, and
  // none of the body's hooks should run.
  if (!nodeForm || (nodeForm.type as string) === 'entry' || !selectedHost) {
    return null;
  }

  return <NodeEditDialogBody {...props} nodeForm={nodeForm} selectedHost={selectedHost} />;
};
