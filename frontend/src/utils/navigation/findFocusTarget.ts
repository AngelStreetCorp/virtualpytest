/** Minimal shape of a cross-tree focus entry (see useGlobalFocusNodes). */
export interface FocusTargetCandidate {
  value: string;
  nodeId: string;
  treeId: string;
}

/**
 * Resolve a `?node=<node_id>` link to the focus entry that owns it, searching
 * the root tree and every subtree. Returns null when no tree holds the node.
 */
export const findFocusTarget = <T extends FocusTargetCandidate>(
  candidates: readonly T[],
  nodeId: string | null | undefined,
): T | null => {
  if (!nodeId) return null;
  return candidates.find((c) => c.nodeId === nodeId) ?? null;
};
