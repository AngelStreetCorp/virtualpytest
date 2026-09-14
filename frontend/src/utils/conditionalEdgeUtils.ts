/**
 * Utilities for handling conditional edges
 * Conditional edges share the same action_set_id (forward actions only)
 */

import { Edge } from 'reactflow';

/**
 * Single source of truth for conditional-edge DETECTION.
 *
 * A "conditional edge" is not a stored flag; it is a structural property of the
 * edge set: an edge's FORWARD action set (`action_sets[0]`, whose id is the
 * edge's `default_action_set_id`) is conditional when **2+ edges leave the same
 * source node sharing that same `default_action_set_id` to DISTINCT targets**.
 * The reverse direction (`action_sets[1]`) is always independent.
 *
 * Deriving it everywhere from this one rule keeps the canvas colour, the Edge
 * Selection panel warning, and the Edit dialog badge in agreement, and means a
 * *duplicate* edge to the same target never false-reads as conditional.
 *
 * @returns the set of edge ids whose forward action set is conditional.
 */
export function computeConditionalEdgeIds(
  edges: Array<{ id: string; source: string; target: string; data?: { default_action_set_id?: string } | null }>,
): Set<string> {
  // Map "<source>|<default_action_set_id>" -> set of distinct target node ids.
  const targetsByGroup = new Map<string, Set<string>>();
  for (const e of edges) {
    const asid = e.data?.default_action_set_id;
    if (!asid) continue;
    const key = `${e.source}|${asid}`;
    let set = targetsByGroup.get(key);
    if (!set) targetsByGroup.set(key, (set = new Set<string>()));
    set.add(e.target);
  }

  const conditionalIds = new Set<string>();
  for (const e of edges) {
    const asid = e.data?.default_action_set_id;
    if (!asid) continue;
    if ((targetsByGroup.get(`${e.source}|${asid}`)?.size ?? 0) > 1) {
      conditionalIds.add(e.id);
    }
  }
  return conditionalIds;
}

/**
 * Within a conditional group, classify an edge as the MAIN (action owner) or a
 * SIBLING (borrower).
 *
 * The MAIN is the edge whose FORWARD action set (`action_sets[0]`) actually
 * holds the actions; SIBLINGS share its `default_action_set_id` but keep EMPTY
 * forward actions and borrow the main's at runtime (backend `navigation_graph`
 * populates them from the owner) and for display (`findSiblingWithActions`).
 *
 * Deriving "main" from action-ownership — a persisted, structural fact — rather
 * than a stored flag means it can never desync from the data and survives
 * save/reload, the same philosophy as `computeConditionalEdgeIds`. Editing the
 * main therefore propagates to every sibling automatically (one source of
 * truth); editing a sibling unlinks it (it gets its own action set id + actions).
 *
 * @returns 'main' | 'sibling' for edges in a conditional group, else null.
 */
export function getConditionalRole(
  edgeId: string,
  edges: Array<{
    id: string;
    source: string;
    target: string;
    data?: { default_action_set_id?: string; action_sets?: Array<{ actions?: any[] }> } | null;
  }>,
): 'main' | 'sibling' | null {
  if (!computeConditionalEdgeIds(edges).has(edgeId)) return null;

  const edge = edges.find((e) => e.id === edgeId);
  if (!edge) return null;
  const asid = edge.data?.default_action_set_id;

  // The conditional group: same source node + same shared forward action_set_id.
  const group = edges.filter(
    (e) => e.source === edge.source && e.data?.default_action_set_id === asid,
  );

  const ownsActions = (e: (typeof group)[number]) =>
    (e.data?.action_sets?.[0]?.actions?.length ?? 0) > 0;

  // Main = the action owner. If several edges own actions (legacy copied data)
  // or none do yet, fall back to a deterministic pick (lowest edge id) so the
  // group always resolves to exactly one main.
  const owners = group.filter(ownsActions).map((e) => e.id).sort();
  const mainId = owners.length > 0 ? owners[0] : group.map((e) => e.id).sort()[0];

  return edgeId === mainId ? 'main' : 'sibling';
}

/**
 * Build a forward action set for a conditional SIBLING that mirrors the MAIN
 * owner's EXECUTABLE parts — main/retry/failure actions — while keeping the
 * sibling's OWN identity and per-edge fields (id, label, threshold, final wait,
 * KPI display name, kpi_references). This mirrors the backend borrow rules
 * (navigation_graph.create_networkx_graph): every branch of a conditional
 * group ends on a DIFFERENT target, so its KPI name / threshold / timing are
 * per-edge and must never be overwritten by the owner's. The one KPI field
 * inherited is `use_verifications_for_kpi` — and only when the sibling has no
 * kpi_references of its own — so the sibling is measured the same WAY as the
 * main while timing against its own target.
 *
 * Used in two places that MUST agree (so "what the dialog shows" equals "what
 * gets persisted on unlink"):
 *   1. openEdgeDialog — pre-fill the form so the sibling dialog displays the
 *      same actions as the main instead of a bare "No actions found".
 *   2. saveEdge (sibling unlink) — materialise the borrowed actions onto the
 *      now-independent edge when the form was left empty.
 */
export function borrowForwardSetFromOwner(siblingFwd: any, ownerFwd: any): any {
  const clone = (v: any) => (v == null ? v : JSON.parse(JSON.stringify(v)));
  const borrowed: any = {
    ...siblingFwd,
    actions: clone(ownerFwd.actions || []),
    retry_actions: clone(ownerFwd.retry_actions || []),
    failure_actions: clone(ownerFwd.failure_actions || []),
  };
  if (!(Array.isArray(siblingFwd?.kpi_references) && siblingFwd.kpi_references.length > 0)) {
    borrowed.use_verifications_for_kpi = Boolean(
      ownerFwd.use_verifications_for_kpi ?? siblingFwd?.use_verifications_for_kpi ?? false,
    );
  }
  return borrowed;
}

/**
 * Deep-equality over the three EXECUTABLE action lists of a forward set. This
 * is the "did the user actually edit the actions?" test that decides whether
 * saving a conditional sibling unlinks it: per-edge fields (kpi_name /
 * threshold / final_wait_time / priority) live on the sibling's own row, so
 * saving them keeps the group intact.
 */
export function forwardActionListsEqual(a: any, b: any): boolean {
  const norm = (v: any) => JSON.stringify(v ?? []);
  return (
    norm(a?.actions) === norm(b?.actions) &&
    norm(a?.retry_actions) === norm(b?.retry_actions) &&
    norm(a?.failure_actions) === norm(b?.failure_actions)
  );
}

/**
 * Find the MAIN owner's forward action set for a conditional edge — the group
 * member (same source + same shared default_action_set_id) that actually holds
 * the actions. Returns null when there is none (edge not conditional, or no
 * owner found).
 */
export function findConditionalOwnerForward(
  edgeId: string,
  edges: Array<{
    id: string;
    source: string;
    target: string;
    data?: { default_action_set_id?: string; action_sets?: Array<{ actions?: any[] }> } | null;
  }>,
): any | null {
  const edge = edges.find((e) => e.id === edgeId);
  const asid = edge?.data?.default_action_set_id;
  if (!edge || !asid) return null;
  const owner = edges.find(
    (e) =>
      e.id !== edgeId &&
      e.source === edge.source &&
      e.data?.default_action_set_id === asid &&
      ((e.data?.action_sets?.[0]?.actions?.length ?? 0) > 0),
  );
  return owner?.data?.action_sets?.[0] ?? null;
}

/**
 * Find sibling edge that has the actual actions for a conditional edge
 * @param edgeId - Current edge ID
 * @param sourceNodeId - Source node ID
 * @param actionSetId - The shared action_set_id
 * @param allEdges - All edges in the graph
 * @returns The sibling edge with actions, or null if not found
 */
export function findSiblingWithActions(
  edgeId: string,
  sourceNodeId: string,
  actionSetId: string,
  allEdges: Edge[]
): Edge | null {
  for (const edge of allEdges) {
    // Skip self
    if (edge.id === edgeId) continue;
    
    // Only check edges from same source
    if (edge.source !== sourceNodeId) continue;
    
    // Check if this edge shares the same action_set_id AND has actions
    const edgeActionSets = edge.data?.action_sets || [];
    if (edgeActionSets.length > 0) {
      const forwardActionSet = edgeActionSets[0]; // Forward is always index 0
      if (forwardActionSet?.id === actionSetId && forwardActionSet.actions?.length > 0) {
        return edge;
      }
    }
  }
  
  return null;
}

