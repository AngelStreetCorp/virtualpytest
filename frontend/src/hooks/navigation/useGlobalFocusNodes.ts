import { useCallback, useEffect, useMemo, useState } from 'react';

import { useNavigation } from '../../contexts/navigation/NavigationContext';
import { useNavigationConfig } from '../../contexts/navigation/NavigationConfigContext';
import { useNavigationStack } from '../../contexts/navigation/NavigationStackContext';
import { api } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { mapEdgesToFrontend, mapNodesToFrontend } from '../../utils/navigation/navigationMappers';

/**
 * A single tree in the complete hierarchy returned by
 * getTreeByUserInterfaceId?include_nested=true (`all_trees_data`).
 */
interface HierarchyTree {
  tree_id: string;
  tree_info: {
    name: string;
    is_root_tree: boolean;
    tree_depth: number;
    parent_tree_id: string | null;
    parent_node_id: string | null;
  };
  nodes: any[];
  edges: any[];
}

/** A focus-dropdown entry spanning the whole interface (root + every subtree). */
export interface GlobalFocusNode {
  /** Composite, dropdown-unique value: `${treeId}::${nodeId}`. */
  value: string;
  nodeId: string;
  treeId: string;
  label: string;
  /** Human breadcrumb of the owning tree, e.g. "root" or "apps › Netflix". */
  groupLabel: string;
  isRoot: boolean;
  depth: number;
}

const VALUE_SEP = '::';

const isEntryNode = (node: any): boolean => {
  const type = (node?.node_type || node?.type || '').toLowerCase();
  const label = (node?.label || '').toLowerCase();
  const id = (node?.node_id || node?.id || '').toLowerCase();
  return type === 'entry' || label === 'entry' || id === 'entry' || id.includes('entry');
};

/**
 * Cross-tree focus support for the navigation editor.
 *
 * The plain focus dropdown only knows the currently displayed tree. This hook
 * fetches the complete tree hierarchy for the interface and exposes:
 *   - `globalFocusNodes`: every node across root + all subtrees (deduped,
 *     entry/parent-reference rows excluded), grouped by owning tree.
 *   - `focusSelectValue`: the composite value to bind the dropdown to.
 *   - `selectFocusNode`: redirects into the owning subtree (rebuilding the
 *     breadcrumb stack) when needed, then focuses the node on the canvas.
 */
export const useGlobalFocusNodes = (userInterfaceId: string | null | undefined) => {
  const navigation = useNavigation();
  const { actualTreeId, setActualTreeId } = useNavigationConfig();
  const { jumpToRoot, pushLevel } = useNavigationStack();

  const [hierarchy, setHierarchy] = useState<HierarchyTree[]>([]);

  // Fetch the full hierarchy whenever the interface changes. Calling the
  // endpoint directly (rather than navigationConfig.loadTreeByUserInterface)
  // avoids its setActualTreeId side effect, which would snap the canvas back to
  // the root tree.
  useEffect(() => {
    if (!userInterfaceId) {
      setHierarchy([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const url = buildServerUrl(
          `/server/navigationTrees/getTreeByUserInterfaceId/${userInterfaceId}?include_nested=true`,
        );
        const result = await api.get<any>(url);
        if (!cancelled && result?.success && Array.isArray(result.all_trees_data)) {
          setHierarchy(result.all_trees_data as HierarchyTree[]);
        }
      } catch (err) {
        console.warn('[@useGlobalFocusNodes] Failed to load hierarchy for focus dropdown:', err);
      }
    })();
    return () => {
      cancelled = true;
    };
    // Fetch once per interface. The hierarchy endpoint is uncached server-side,
    // so we deliberately do NOT refetch on every cross-tree focus jump; nodes
    // added during the session appear after the next interface (re)load.
  }, [userInterfaceId]);

  const treesById = useMemo(() => {
    const map = new Map<string, HierarchyTree>();
    hierarchy.forEach((t) => map.set(t.tree_id, t));
    return map;
  }, [hierarchy]);

  // Human breadcrumb for a tree: the chain of parent-node labels from the root
  // down to the node that spawned this tree. Root → "root".
  const groupLabelFor = useCallback(
    (tree: HierarchyTree): string => {
      if (tree.tree_info.is_root_tree) return 'root';
      const parts: string[] = [];
      let current: HierarchyTree | undefined = tree;
      while (current && !current.tree_info.is_root_tree) {
        const parentId: string | null = current.tree_info.parent_tree_id;
        const parent: HierarchyTree | undefined = parentId ? treesById.get(parentId) : undefined;
        const spawnNodeId = current.tree_info.parent_node_id;
        const spawnNode = parent?.nodes.find((n: any) => n.node_id === spawnNodeId);
        parts.unshift(spawnNode?.label || spawnNodeId || current.tree_info.name);
        current = parent;
      }
      return parts.join(' › ') || tree.tree_info.name;
    },
    [treesById],
  );

  // Flat, deduped list of every focusable node across the interface. Root tree
  // comes first so a node owned by a parent tree wins over its parent-reference
  // copy inside a subtree.
  const globalFocusNodes = useMemo<GlobalFocusNode[]>(() => {
    const seen = new Set<string>();
    const out: GlobalFocusNode[] = [];
    hierarchy.forEach((tree) => {
      const groupLabel = groupLabelFor(tree);
      (tree.nodes || []).forEach((node) => {
        if (isEntryNode(node)) return;
        if (node?.data?.isParentReference) return;
        if (seen.has(node.node_id)) return;
        seen.add(node.node_id);
        out.push({
          value: `${tree.tree_id}${VALUE_SEP}${node.node_id}`,
          nodeId: node.node_id,
          treeId: tree.tree_id,
          label: node.label || node.node_id,
          groupLabel,
          isRoot: tree.tree_info.is_root_tree,
          depth: tree.tree_info.tree_depth,
        });
      });
    });
    return out;
  }, [hierarchy, groupLabelFor]);

  // Composite value for the dropdown, reflecting the currently focused node in
  // whatever tree is displayed.
  const focusSelectValue = useMemo(() => {
    if (!navigation.focusNodeId) return '';
    // Bind to the node's OWNING tree, not the displayed tree: focusNodeId can be a SUBTREE node
    // while actualTreeId is still the root, which produced a composite value matching no dropdown
    // option (MUI "out-of-range value" warning). globalFocusNodes already carries the owning treeId.
    const owned = globalFocusNodes.find((n) => n.nodeId === navigation.focusNodeId);
    if (owned) return owned.value;
    return actualTreeId ? `${actualTreeId}${VALUE_SEP}${navigation.focusNodeId}` : '';
  }, [navigation.focusNodeId, actualTreeId, globalFocusNodes]);

  // Redirect the canvas into `targetTreeId` by rebuilding the breadcrumb stack
  // and parent chain from the root down. Mirrors what double-click + breadcrumb
  // navigation produce, but reconstructed from the cached hierarchy so we can
  // jump to any tree directly.
  const navigateToTree = useCallback(
    (targetTreeId: string) => {
      const target = treesById.get(targetTreeId);
      if (!target) {
        console.warn(`[@useGlobalFocusNodes] Target tree ${targetTreeId} not in hierarchy`);
        return false;
      }

      // Build the chain root..target.
      const chain: HierarchyTree[] = [];
      let current: HierarchyTree | undefined = target;
      while (current) {
        chain.unshift(current);
        const parentId: string | null = current.tree_info.parent_tree_id;
        current = parentId ? treesById.get(parentId) : undefined;
      }

      // Convert every tree in the chain to frontend format once.
      const converted = chain.map((t) => ({
        tree: t,
        nodes: mapNodesToFrontend(t.nodes || []),
        edges: mapEdgesToFrontend(t.edges || []),
      }));

      // Parent chain (includes root at index 0).
      const parentChain = converted.map((c) => ({
        treeId: c.tree.tree_id,
        treeName: c.tree.tree_info.name,
        nodes: c.nodes as any[],
        edges: c.edges as any[],
      }));
      navigation.setParentChain(parentChain);

      // Stack levels exclude the root tree.
      jumpToRoot();
      for (let i = 1; i < converted.length; i++) {
        const c = converted[i];
        const parent = converted[i - 1];
        const spawnNodeId = c.tree.tree_info.parent_node_id || '';
        const spawnNode = parent.tree.nodes.find((n) => n.node_id === spawnNodeId);
        pushLevel(
          c.tree.tree_id,
          spawnNodeId,
          c.tree.tree_info.name,
          spawnNode?.label || spawnNodeId,
          c.tree.tree_info.tree_depth,
          parent.tree.tree_id,
        );
      }

      const targetConverted = converted[converted.length - 1];
      navigation.setNodes(targetConverted.nodes as any[]);
      navigation.setEdges(targetConverted.edges as any[]);
      navigation.setInitialState({
        nodes: [...(targetConverted.nodes as any[])],
        edges: [...(targetConverted.edges as any[])],
      });
      navigation.setHasUnsavedChanges(false);
      setActualTreeId(targetTreeId);
      return true;
    },
    [treesById, navigation, jumpToRoot, pushLevel, setActualTreeId],
  );

  /**
   * Handle a focus-dropdown selection. `value` is the composite
   * `${treeId}::${nodeId}` (or '' / null to clear focus).
   */
  const selectFocusNode = useCallback(
    (value: string | null) => {
      if (!value) {
        navigation.setFocusNodeId(null);
        return;
      }
      const [treeId, nodeId] = value.split(VALUE_SEP);
      if (!treeId || !nodeId) return;

      if (treeId === actualTreeId) {
        // Already on the owning tree — just focus.
        navigation.setFocusNodeId(nodeId);
        return;
      }

      // Redirect into the owning tree, then focus. The canvas pan effect in
      // NavigationEditor re-runs once nodes + focusNodeId update.
      const ok = navigateToTree(treeId);
      if (ok) {
        navigation.setFocusNodeId(nodeId);
      }
    },
    [actualTreeId, navigateToTree, navigation],
  );

  return { globalFocusNodes, focusSelectValue, selectFocusNode };
};
