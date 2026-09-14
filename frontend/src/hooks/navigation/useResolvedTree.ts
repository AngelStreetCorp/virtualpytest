/**
 * useResolvedTree — apply variant resolution to canvas data.
 *
 * Per-variant overrides live on the active variant row in
 * `userinterface_variants`. The caller (NavigationEditor) looks up the active
 * variant from the variants list and forwards its `node_overrides` and
 * `edge_overrides` maps here. Pass `null` for both to render base.
 *
 * Output: `{ nodes, edges }` where:
 *   - Nodes/edges with `__variant_state.active === false` for the current
 *     scope are filtered OUT entirely.
 *   - Edges whose source or target node was filtered out are also dropped
 *     (mirrors `create_networkx_graph` edge auto-skip in Python).
 *   - Active nodes/edges have their per-variant override applied so the card can
 *     render the patched verifications/action_sets.
 *
 * The hook is purely transformational and never writes back. Edits inside
 * any open dialog operate on the variant's override JSONB via the hook
 * `useUserInterfaceVariants.updateVariantOverrides`.
 */
import { useMemo } from 'react';

import type {
  UINavigationEdge,
  UINavigationNode,
  VariantOverridesMap,
} from '../../types/pages/Navigation_Types';
import { computeConditionalEdgeIds, getConditionalRole } from '../../utils/conditionalEdgeUtils';
import {
  resolveEdgeVariant,
  resolveNodeVariant,
} from '../../utils/navigation/variantResolver';

export interface UseResolvedTreeOutput {
  nodes: UINavigationNode[];
  edges: UINavigationEdge[];
}

// The handle ids rendered by Navigation_NavigationNode. ReactFlow SILENTLY DROPS
// an edge whose sourceHandle/targetHandle isn't one of these (console error #008
// "Couldn't create edge for source handle id …") → the edge becomes invisible.
// Legacy/corrupted edges can carry stale ids from an older handle scheme (e.g.
// "bottom-left-menu-source", which is now a TARGET position), or have their
// source/target swapped without updating the handles. Remap any invalid handle
// to a valid one of the same type by position so the edge always renders.
const VALID_SOURCE_HANDLES = new Set([
  'entry-source', 'left-source', 'right-source', 'top-left-menu-source', 'bottom-right-menu-source',
]);
const VALID_TARGET_HANDLES = new Set([
  'left-target', 'right-target', 'top-right-menu-target', 'bottom-left-menu-target',
]);

function sanitizeHandle(handle: string | null | undefined, type: 'source' | 'target'): string | undefined {
  if (!handle) return undefined;
  if ((type === 'source' ? VALID_SOURCE_HANDLES : VALID_TARGET_HANDLES).has(handle)) return handle;
  const h = handle.toLowerCase();
  if (type === 'source') {
    if (h.includes('bottom')) return 'bottom-right-menu-source';
    if (h.includes('top')) return 'top-left-menu-source';
    if (h.includes('left')) return 'left-source';
    if (h.includes('right')) return 'right-source';
  } else {
    if (h.includes('top')) return 'top-right-menu-target';
    if (h.includes('bottom')) return 'bottom-left-menu-target';
    if (h.includes('left')) return 'left-target';
    if (h.includes('right')) return 'right-target';
  }
  return undefined; // unknown → let ReactFlow fall back to the node's default handle
}

/**
 * A node is "owned" by the variant view (and therefore draggable / connectable)
 * when:
 *   - the active variant has overrides loaded, AND
 *   - the row is variant-only on this scope: `data.hidden_in_base === true`
 *     AND no entry in the active variant's overrides has `disabled: true`
 *     for this node id.
 *
 * In Base view, a row is owned iff `!data.hidden_in_base` (variant-only rows
 * don't render at all in Base view, they're filtered out below).
 */
function isOwnedByCurrentScope(
  rawNode: UINavigationNode,
  isVariantView: boolean,
  variantNodeOverrides: VariantOverridesMap | null,
): boolean {
  const hiddenInBase = (rawNode.data as any)?.hidden_in_base === true;
  if (!isVariantView) {
    // Base view: owned iff not variant-only.
    return !hiddenInBase;
  }
  if (!hiddenInBase) {
    // Shared row in variant view — never draggable from variant scope.
    return false;
  }
  // Variant view + variant-only row → check the row is visible on this scope.
  const entry = variantNodeOverrides ? variantNodeOverrides[rawNode.id] : undefined;
  return !entry || entry.disabled !== true;
}

export function useResolvedTree(
  rawNodes: UINavigationNode[],
  rawEdges: UINavigationEdge[],
  variantNodeOverrides: VariantOverridesMap | null,
  variantEdgeOverrides: VariantOverridesMap | null,
  // When the canvas is previewing a COMPOSITION of >1 variant, the maps passed
  // in are already merged and there is no single owning variant to edit. Force
  // every row non-draggable / non-connectable so the preview is read-only.
  // See docs/agent/navigation/VARIANT.md "Composition".
  readOnly: boolean = false,
  // When true (single-variant scope only), rows DISABLED on the active variant
  // are not filtered out — they render ghosted (grey + transparent, not
  // draggable) so the author can re-select one and hit "Reset variant" to
  // un-hide it. Default false keeps the canvas clean. A disabled row is
  // otherwise unreachable: the resolver drops it, so there's no card to click.
  showDisabled: boolean = false,
): UseResolvedTreeOutput {
  return useMemo(() => {
    const isVariantView =
      variantNodeOverrides !== null || variantEdgeOverrides !== null;
    // Ghosting only makes sense in a single editable variant scope — a
    // composition has no single owning variant to reset against.
    const ghost = showDisabled && isVariantView && !readOnly;

    // Build a quick lookup of the original node by id so we can read the raw
    // hidden_in_base flag for ownership detection (the resolved node may have
    // patched data but ownership is determined by the base columns).
    const rawById = new Map<string, UINavigationNode>();
    for (const n of rawNodes) rawById.set(n.id, n);

    // Resolve nodes; drop disabled ones (or ghost them when `showDisabled`).
    const visibleNodeIds = new Set<string>();
    // Ghosted (disabled-on-this-variant) node ids — used below to also ghost
    // any edge touching one of them, so a dimmed node never has a full-colour
    // edge hanging off it.
    const disabledNodeIds = new Set<string>();
    const resolvedNodes: UINavigationNode[] = [];
    for (const node of rawNodes) {
      const resolved = resolveNodeVariant(node, variantNodeOverrides);
      const isDisabled = !resolved.__variant_state.active;
      if (isDisabled && !ghost) {
        // Disabled in the currently-viewed scope — filter out.
        continue;
      }
      if (isDisabled) disabledNodeIds.add(node.id);
      visibleNodeIds.add(node.id);
      // Strip the synthesized __variant_state before handing back to ReactFlow —
      // it's an internal marker, not a real node prop.
      const { __variant_state: _ignored, ...node_for_render } = resolved as any;
      void _ignored;
      // Per-node draggable / connectable: only nodes owned by the current
      // scope can be moved or have new edges drawn from them. ReactFlow's
      // per-node `draggable` overrides the global `nodesDraggable` setting
      // (which we keep `true` so this hook is the single decision point).
      const owned =
        !readOnly &&
        !isDisabled &&
        isOwnedByCurrentScope(node, isVariantView, variantNodeOverrides);
      // Position is the ONE topology field that legitimately differs per
      // variant (e.g. two menu screens whose on-screen order is swapped between
      // variants). A visible SHARED row in a single-variant scope is therefore
      // draggable — the drag persists to the variant's node_overrides[id].
      // position, never the base row. Composition (readOnly) is excluded: no
      // single owning variant to write to. Connect stays gated on `owned` —
      // edge endpoints / re-routing remain base-only.
      const positionEditable =
        isVariantView && !readOnly && !isDisabled && !owned;
      (node_for_render as any).draggable = owned || positionEditable;
      (node_for_render as any).connectable = owned;
      // Ghost a disabled-on-variant row: grey + transparent. ReactFlow applies
      // `node.style` to the node wrapper, so this dims the whole card (and its
      // children) without touching the node component. Still selectable —
      // clicking opens its Edit dialog where "Reset variant" lives.
      if (isDisabled) {
        (node_for_render as any).style = {
          ...((node_for_render as any).style || {}),
          opacity: 0.4,
          filter: 'grayscale(1)',
        };
      }
      // Scope-aware "v" chip flag — shown in variant view when the active
      // variant has an entry on this row OR the row is variant-only
      // (hidden_in_base=true falls through with no entry on its own variant).
      // Base view never shows the chip.
      const hiddenInBase = (node.data as any)?.hidden_in_base === true;
      const showChip =
        isVariantView &&
        (hiddenInBase ||
          (variantNodeOverrides !== null &&
            variantNodeOverrides[node.id] !== undefined));
      const data = node_for_render.data || {};
      node_for_render.data = {
        ...data,
        _show_variant_chip: showChip,
        _variant_disabled: isDisabled,
        // True for a shared row draggable ONLY to set its per-variant canvas
        // position (see `positionEditable` above). The drag handler routes such
        // a drop into node_overrides[id].position instead of the base row.
        _variant_position_editable: positionEditable,
      };
      resolvedNodes.push(node_for_render as UINavigationNode);
    }

    // Resolve edges; auto-skip when an endpoint was filtered out.
    const resolvedEdges: UINavigationEdge[] = [];
    for (const edge of rawEdges) {
      if (!visibleNodeIds.has(edge.source) || !visibleNodeIds.has(edge.target)) {
        continue;
      }
      const resolved = resolveEdgeVariant(edge, variantEdgeOverrides);
      const edgeDisabled = !resolved.__variant_state.active;
      if (edgeDisabled && !ghost) {
        continue;
      }
      // An edge is ghosted when it's disabled on this variant OR it touches a
      // ghosted (disabled) node — so a dimmed node never sprouts a live edge.
      const isGhostEdge =
        edgeDisabled ||
        disabledNodeIds.has(edge.source) ||
        disabledNodeIds.has(edge.target);
      const { __variant_state: _ignored, ...edge_for_render } = resolved as any;
      void _ignored;
      // An edge is "owned" iff both endpoint nodes are owned by the current
      // scope. Endpoints can only be re-routed when this is true.
      const sourceNode = rawById.get(edge.source);
      const targetNode = rawById.get(edge.target);
      const ownedEdge =
        !readOnly &&
        !!sourceNode &&
        !!targetNode &&
        isOwnedByCurrentScope(sourceNode, isVariantView, variantNodeOverrides) &&
        isOwnedByCurrentScope(targetNode, isVariantView, variantNodeOverrides);
      (edge_for_render as any).updatable = ownedEdge;
      // Scope-aware "v" chip on edges — same rule as nodes (variant-only
      // edges have hidden_in_base=true and no entry on their own variant).
      const edgeHiddenInBase = (edge.data as any)?.hidden_in_base === true;
      const showEdgeChip =
        isVariantView &&
        (edgeHiddenInBase ||
          (variantEdgeOverrides !== null &&
            variantEdgeOverrides[edge.id] !== undefined));
      const eData = edge_for_render.data || {};
      edge_for_render.data = {
        ...eData,
        _show_variant_chip: showEdgeChip,
        _variant_disabled: isGhostEdge,
      };
      if (isGhostEdge) (edge_for_render as any).updatable = false;
      // Repair stale/invalid handles so ReactFlow never silently drops the edge
      // (edge_for_render is a fresh rest-spread object, so this doesn't mutate
      // the canvas source or trigger a save on its own).
      edge_for_render.sourceHandle = sanitizeHandle(edge_for_render.sourceHandle, 'source');
      edge_for_render.targetHandle = sanitizeHandle(edge_for_render.targetHandle, 'target');
      resolvedEdges.push(edge_for_render as UINavigationEdge);
    }

    // Stamp the structural conditional-edge flag over the full (visible) edge
    // set. Re-run by this memo on any edge change, so the canvas recolours
    // every group member the instant a conditional group forms — no refresh.
    // See utils/navigation/conditionalEdge for the single detection rule.
    const conditionalIds = computeConditionalEdgeIds(resolvedEdges);
    for (const e of resolvedEdges) {
      const isCond = conditionalIds.has(e.id);
      (e.data as any)._conditional = isCond;
      // Stamp the derived role so the canvas can distinguish the action-owning
      // main (solid) from a borrowing sibling (dashed) without re-deriving per edge.
      (e.data as any)._conditionalRole = isCond ? getConditionalRole(e.id, resolvedEdges) : null;
    }

    return { nodes: resolvedNodes, edges: resolvedEdges };
  }, [rawNodes, rawEdges, variantNodeOverrides, variantEdgeOverrides, readOnly, showDisabled]);
}
