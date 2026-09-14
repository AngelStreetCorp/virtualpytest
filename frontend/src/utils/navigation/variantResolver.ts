/**
 * Per-variant override resolver — TypeScript port of
 * `shared/src/lib/utils/navigation_graph.py`.
 *
 * Per-variant overrides live ON the variant row in `userinterface_variants`
 * (`node_overrides` / `edge_overrides` JSONB maps keyed by node_id / edge_id).
 * Each entry FULLY OVERRIDES the base row's content for that variant — there
 * is no patch / param-merge layer. Base navigation_nodes / navigation_edges
 * rows stay pure; variant-only rows are flagged via `hidden_in_base`.
 *
 *   - `resolveNodeVariant(node, variantNodeOverrides | null)` — replaces the
 *     node's `verifications` (under `data`) with the variant's `verifications`
 *     if an entry exists, else falls through to base.
 *   - `resolveEdgeVariant(edge, variantEdgeOverrides | null)` — same for
 *     `action_sets`.
 *
 * Used by `useResolvedTree` to filter / replace the canvas data when the
 * `Viewing:` chip is set to a variant.
 *
 * See docs/agent/navigation/VARIANT.md §4 for the canonical spec.
 */
import type {
  EdgeVariantOverride,
  NodeVariantOverride,
  UINavigationEdge,
  UINavigationNode,
  VariantOverridesMap,
} from '../../types/pages/Navigation_Types';

/** Per-row resolution state — node/edge carry this after resolution. */
export interface VariantState {
  active: boolean;
  /** Variant name when the variant supplied an override (or disabled the row),
   *  the literal string `'base-hidden'` when the row was skipped on a base run
   *  due to `hidden_in_base`, or null when the row rendered base data
   *  unchanged. Cosmetic — used only for journal log lines. */
  applied_match: string | null;
}

/** Node returned by the resolver. `verifications` reflects the active scope. */
export type ResolvedNavigationNode = UINavigationNode & {
  __variant_state: VariantState;
};

/** Edge returned by the resolver. `action_sets` reflects the active scope. */
export type ResolvedNavigationEdge = UINavigationEdge & {
  __variant_state: VariantState;
};

/** Deep clone via JSON — override values are plain JSONB so this is safe. */
function deepClone<T>(value: T): T {
  if (value === undefined || value === null) return value;
  return JSON.parse(JSON.stringify(value));
}

// ---------------------------------------------------------------------------
// Composition (apply a LIST of variants) — TS mirror of navigation_graph.py
// ---------------------------------------------------------------------------
// See docs/agent/navigation/VARIANT.md "Composition". The canvas can preview a composition
// of several variants; composition is a PRE-PASS that merges N override maps
// into ONE, which the per-row resolver above then consumes unchanged. The merge
// rules MUST match the Python (`_compose_overrides`):
//   - canonical (sorted) order → order-independent, deterministic last-wins
//   - `disabled` is a hard veto
//   - additive visibility, backward-compatible with the legacy
//     "disable-on-others" convention via `crossDisabledIds`.

/** Normalize a variant selector into an ordered, de-duplicated component list. */
export function parseVariantList(value: string | string[] | null | undefined): string[] {
  if (value === null || value === undefined) return [];
  const raw = Array.isArray(value) ? value.map(String) : String(value).replace(/\+/g, ',').split(',');
  const seen = new Set<string>();
  const out: string[] = [];
  for (const item of raw) {
    const name = item.trim().toLowerCase();
    if (!name || name === 'base') continue;
    if (seen.has(name)) continue;
    seen.add(name);
    out.push(name);
  }
  return out;
}

/** Canonical composite string ('+'-joined, sorted), or null for a base run. */
export function canonicalVariantName(value: string | string[] | null | undefined): string | null {
  const components = parseVariantList(value).sort();
  return components.length ? components.join('+') : null;
}

function composeOverrides(
  appliedMaps: VariantOverridesMap[],
  hiddenIds: Set<string>,
  crossDisabledIds: Set<string>,
  contentKey: 'verifications' | 'action_sets',
): VariantOverridesMap {
  const candidateIds = new Set<string>();
  for (const m of appliedMaps) for (const k of Object.keys(m)) candidateIds.add(k);
  for (const k of hiddenIds) candidateIds.add(k);

  const merged: VariantOverridesMap = {};
  for (const rid of candidateIds) {
    let disabledByAny = false;
    let enabledByAny = false;
    let absentCount = 0;
    let content: any[] | null = null; // last (in canonical order) wins
    // Per-variant canvas position must survive composition — the resolver
    // applies `entry.position`, but the canvas only ever sees the COMPOSED
    // map, so dropping it here made persisted variant positions vanish on
    // reload (the in-session draft overlay masked it). Position does NOT
    // affect visibility: a position-only entry still counts as absent for
    // the legacy fall-through rule, exactly as before.
    let position: { x: number; y: number } | null = null; // last wins
    // Per-variant edge routing (drawn handles) — same survival rule as
    // position: pure canvas display that must reach the composed map, and a
    // handle-only entry still counts as absent for visibility. Node entries
    // never carry these keys.
    let sourceHandle: string | null = null; // last wins
    let targetHandle: string | null = null; // last wins

    for (const m of appliedMaps) {
      const entry: any = m[rid];
      if (!entry) {
        absentCount += 1;
        continue;
      }
      if (entry.disabled) {
        disabledByAny = true;
        continue;
      }
      if (
        entry.position &&
        typeof entry.position.x === 'number' &&
        typeof entry.position.y === 'number'
      ) {
        position = { x: entry.position.x, y: entry.position.y };
      }
      if (typeof entry.sourceHandle === 'string') sourceHandle = entry.sourceHandle;
      if (typeof entry.targetHandle === 'string') targetHandle = entry.targetHandle;
      const candidate = entry[contentKey];
      if (Array.isArray(candidate) && candidate.length > 0) {
        content = candidate;
        enabledByAny = true;
      } else if (entry.enabled === true) {
        enabledByAny = true;
      } else {
        absentCount += 1; // no-op entry behaves like absent
      }
    }

    const isHidden = hiddenIds.has(rid);
    let visible: boolean;
    if (disabledByAny) visible = false;
    else if (enabledByAny) visible = true;
    else if (isHidden) visible = crossDisabledIds.has(rid) && absentCount > 0;
    else visible = true;

    if (!visible) merged[rid] = { disabled: true } as any;
    else {
      const out: any = {};
      if (content !== null) out[contentKey] = content;
      if (position !== null) out.position = position;
      if (sourceHandle !== null) out.sourceHandle = sourceHandle;
      if (targetHandle !== null) out.targetHandle = targetHandle;
      if (Object.keys(out).length > 0) merged[rid] = out;
      // else: visible base content → no entry (resolver falls through)
    }
  }
  return merged;
}

export function composeNodeOverrides(
  appliedMaps: VariantOverridesMap[],
  hiddenNodeIds: Set<string>,
  crossDisabledNodeIds: Set<string>,
): VariantOverridesMap {
  return composeOverrides(appliedMaps, hiddenNodeIds, crossDisabledNodeIds, 'verifications');
}

export function composeEdgeOverrides(
  appliedMaps: VariantOverridesMap[],
  hiddenEdgeIds: Set<string>,
  crossDisabledEdgeIds: Set<string>,
): VariantOverridesMap {
  return composeOverrides(appliedMaps, hiddenEdgeIds, crossDisabledEdgeIds, 'action_sets');
}

export interface CompositionConflict {
  kind: 'content' | 'visibility';
  scope: 'node' | 'edge';
  id: string;
  variants: string[];
}

/** Lint a candidate composition: rows touched by >1 variant with incompatible
 *  intents (content collision → last-wins applies; enable-vs-disable → disable
 *  wins and the enable is dropped). TS mirror of detect_composition_conflicts. */
export function detectCompositionConflicts(
  applied: { name: string; node_overrides?: VariantOverridesMap; edge_overrides?: VariantOverridesMap }[],
): CompositionConflict[] {
  const conflicts: CompositionConflict[] = [];
  const scan = (scope: 'node' | 'edge', key: 'verifications' | 'action_sets') => {
    const ids = new Set<string>();
    for (const v of applied) for (const k of Object.keys(v[`${scope}_overrides`] || {})) ids.add(k);
    for (const rid of ids) {
      const contentOwners: string[] = [];
      const disablers: string[] = [];
      const enablers: string[] = [];
      for (const v of applied) {
        const entry: any = (v[`${scope}_overrides`] || {})[rid];
        if (!entry) continue;
        if (entry.disabled) {
          disablers.push(v.name);
          continue;
        }
        enablers.push(v.name);
        if (Array.isArray(entry[key]) && entry[key].length > 0) contentOwners.push(v.name);
      }
      if (contentOwners.length > 1)
        conflicts.push({ kind: 'content', scope, id: rid, variants: [...contentOwners].sort() });
      if (disablers.length && enablers.length)
        conflicts.push({ kind: 'visibility', scope, id: rid, variants: [...new Set([...disablers, ...enablers])].sort() });
    }
  };
  scan('node', 'verifications');
  scan('edge', 'action_sets');
  return conflicts;
}

/** Shallow copy used to avoid mutating originals. */
function shallowCopyObject<T extends Record<string, any>>(obj: T): T {
  return { ...obj };
}

// ---------------------------------------------------------------------------
// Node resolver
// ---------------------------------------------------------------------------

/**
 * Apply variant resolution to a node. Returns a new object — never mutates
 * the input.
 *
 *   - `variantNodeOverrides === null`     → base run. Respect `hidden_in_base`.
 *   - entry missing                       → fall through to base data.
 *   - `entry.disabled === true`           → inactive (variant hides this row).
 *   - `entry.verifications` array present → replace base `verifications`.
 */
export function resolveNodeVariant(
  node: UINavigationNode,
  variantNodeOverrides: VariantOverridesMap | null,
): ResolvedNavigationNode {
  const out = shallowCopyObject(node) as ResolvedNavigationNode;

  if (variantNodeOverrides === null) {
    if (out.data?.hidden_in_base === true) {
      out.__variant_state = { active: false, applied_match: 'base-hidden' };
      return out;
    }
    out.__variant_state = { active: true, applied_match: null };
    return out;
  }

  const entry = variantNodeOverrides[node.id] as NodeVariantOverride | undefined;
  if (!entry) {
    out.__variant_state = { active: true, applied_match: null };
    return out;
  }
  if (entry.disabled === true) {
    out.__variant_state = { active: false, applied_match: '<variant>' };
    return out;
  }
  // Per-variant CANVAS position override (independent of verifications; a node
  // may carry both). Runtime never reads position, so this is purely a layout
  // overlay for the editor. Apply it over the base position; absence falls
  // through to the base row's coordinates.
  if (
    entry.position &&
    typeof entry.position.x === 'number' &&
    typeof entry.position.y === 'number'
  ) {
    out.position = { x: entry.position.x, y: entry.position.y };
    out.__variant_state = { active: true, applied_match: '<variant>' };
    // fall through to also apply verifications below if present
  }
  // Treat an empty array as fall-through (a node always has SOME base
  // verifications structure, so an empty override is never meaningful and
  // would mask base data — see the variant-test1 self-perpetuating-empty
  // bug fixed 2026-05-12).
  if (Array.isArray(entry.verifications) && entry.verifications.length > 0) {
    out.data = {
      ...(out.data as any),
      verifications: deepClone(entry.verifications),
    };
    out.__variant_state = { active: true, applied_match: '<variant>' };
    return out;
  }
  out.__variant_state = { active: true, applied_match: '<variant>' };
  return out;
}

// ---------------------------------------------------------------------------
// Edge resolver
// ---------------------------------------------------------------------------

/**
 * Apply variant resolution to an edge. Returns a new object — never mutates
 * the input.
 *
 *   - `variantEdgeOverrides === null`    → base run. Respect `hidden_in_base`.
 *   - entry missing                      → fall through to base data.
 *   - `entry.disabled === true`          → inactive (variant hides this row).
 *   - `entry.action_sets` array present  → replace base `action_sets`.
 */
export function resolveEdgeVariant(
  edge: UINavigationEdge,
  variantEdgeOverrides: VariantOverridesMap | null,
): ResolvedNavigationEdge {
  const out = shallowCopyObject(edge) as ResolvedNavigationEdge;

  if (variantEdgeOverrides === null) {
    if (out.data?.hidden_in_base === true) {
      out.__variant_state = { active: false, applied_match: 'base-hidden' };
      return out;
    }
    out.__variant_state = { active: true, applied_match: null };
    return out;
  }

  const entry = variantEdgeOverrides[edge.id] as EdgeVariantOverride | undefined;
  if (!entry) {
    out.__variant_state = { active: true, applied_match: null };
    return out;
  }
  if (entry.disabled === true) {
    out.__variant_state = { active: false, applied_match: '<variant>' };
    return out;
  }
  // Per-variant routing: anchor to the handles this variant drew; the base
  // row keeps its own. Display only — useResolvedTree still sanitizes the
  // result before ReactFlow sees it.
  if (typeof entry.sourceHandle === 'string') out.sourceHandle = entry.sourceHandle;
  if (typeof entry.targetHandle === 'string') out.targetHandle = entry.targetHandle;
  // Empty array → fall-through (same logic as nodes — see resolveNodeVariant).
  if (Array.isArray(entry.action_sets) && entry.action_sets.length > 0) {
    const resolvedActionSets = deepClone(entry.action_sets) as any[];
    // KPI references inherit from base unless the variant EXPLICITLY sets its
    // own. The action_sets override fully replaces base actions/verifications,
    // but a variant override authored (or replicated) before the base gained a
    // KPI reference silently drops it — so KPI measurement disappears for that
    // variant. Per action_set (matched by stable `id`), when the override
    // defines neither a non-empty `kpi_references` nor
    // `use_verifications_for_kpi`, backfill both from the matching base
    // action_set. Mirror of resolve_edge_variant in navigation_graph.py.
    const baseById = new Map<string, any>(
      ((out.data as any)?.action_sets ?? [])
        .filter((a: any) => a?.id)
        .map((a: any) => [a.id, a]),
    );
    for (const actionSet of resolvedActionSets) {
      if (!actionSet || typeof actionSet !== 'object') continue;
      const hasExplicitKpi =
        (Array.isArray(actionSet.kpi_references) && actionSet.kpi_references.length > 0) ||
        actionSet.use_verifications_for_kpi === true;
      if (hasExplicitKpi) continue;
      const baseSet = baseById.get(actionSet.id);
      if (!baseSet) continue;
      if (Array.isArray(baseSet.kpi_references) && baseSet.kpi_references.length > 0) {
        actionSet.kpi_references = deepClone(baseSet.kpi_references);
      }
      if (baseSet.use_verifications_for_kpi === true) {
        actionSet.use_verifications_for_kpi = true;
      }
    }
    out.data = {
      ...(out.data as any),
      action_sets: resolvedActionSets,
    };
    out.__variant_state = { active: true, applied_match: '<variant>' };
    return out;
  }
  out.__variant_state = { active: true, applied_match: '<variant>' };
  return out;
}
