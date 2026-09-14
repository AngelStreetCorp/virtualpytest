import React, { useCallback, useRef } from 'react';

import { useNavigation } from '../../contexts/navigation/NavigationContext';
import { useNavigationConfig } from '../../contexts/navigation/NavigationConfigContext';
import { useNavigationStack } from '../../contexts/navigation/NavigationStackContext';

interface NestedNavigationHookParams {
  setNodes: (nodes: any[]) => void;
  setEdges: (edges: any[]) => void;
  openNodeDialog: (node: any) => void;
}

export const useNestedNavigation = ({
  setNodes,
  setEdges,
  openNodeDialog,
}: NestedNavigationHookParams) => {
  const { pushLevel, stack, loadBreadcrumb } = useNavigationStack();
  const { actualTreeId } = useNavigationConfig();
  const navigationConfig = useNavigationConfig();
  const navigation = useNavigation();

  // Synchronous re-entry guard. The stack-based `isAlreadyInThisNode` check
  // below reads React state from this render's closure, so two rapid
  // double-clicks both see the pre-push stack and both call pushLevel,
  // producing duplicated breadcrumb entries (e.g. root > apps > apps > apps).
  // A ref blocks further clicks the moment one starts, regardless of render.
  const inFlightRef = useRef(false);

  const loadTreeData = useCallback(async (treeId: string) => {
    const treeData = await navigationConfig.loadTreeData(treeId);
    
    if (!treeData.success) {
      throw new Error(treeData.error || 'Failed to load tree');
    }

    // Convert to frontend format (same logic as NavigationEditor)
    const frontendNodes = (treeData.nodes || []).map((dbNode: any) => ({
      id: dbNode.node_id,
      type: dbNode.node_type || 'screen', // Use top-level node_type column
      position: { x: dbNode.position_x, y: dbNode.position_y },
      data: {
        label: dbNode.label,
        description: dbNode.description,
        verifications: dbNode.verifications,
        has_subtree: dbNode.has_subtree,
        subtree_count: dbNode.subtree_count,
        // Per-variant model: surface the top-level hidden_in_base column so
        // variant-only rows created INSIDE a subtree keep their flag after a
        // reload. Without this the row is mis-read as a shared base row (shown
        // in base, no "v" badge) AND a re-save from the subtree would clobber
        // hidden_in_base back to false. Mirrors mapNodeToFrontend.
        hidden_in_base: dbNode.hidden_in_base === true,
        ...dbNode.data, // ✅ Spread data object which contains verification_pass_condition
      }
    }));

    const frontendEdges = (treeData.edges || []).map((edge: any) => ({
      id: edge.edge_id,
      source: edge.source_node_id,
      target: edge.target_node_id,
      type: 'navigation',
      label: edge.label, // Move label to top-level (ReactFlow standard)
      sourceHandle: edge.data?.sourceHandle,
      targetHandle: edge.data?.targetHandle,
      data: {
        // Remove label from data - now in top-level field.
        // final_wait_time + threshold live per-direction inside action_sets.
        action_sets: edge.action_sets,
        default_action_set_id: edge.default_action_set_id,
        // Per-variant model: surface hidden_in_base (same reason as nodes
        // above). Mirrors mapEdgeToFrontend.
        hidden_in_base: edge.hidden_in_base === true,
        ...edge.data
      }
    }));

    return { nodes: frontendNodes, edges: frontendEdges };
  }, [navigationConfig]);

  /**
   * Enter `subTree` (a child of `parentNode`, which lives in `parentTreeId`),
   * loading its nodes/edges, pushing the breadcrumb level and switching the
   * canvas into it. Shared by the double-click handler AND the post-goto reveal
   * so both paths build the nested view identically.
   *
   * `centerNodeId` selects which node to center after the switch: the goto
   * reveal centers the node the device landed on; the double-click centers the
   * subtree's entry node (default).
   */
  const enterSubtree = useCallback(
    async (
      node: any,
      parentTreeId: string,
      subTree: { id: string; name: string; tree_depth: number },
      centerNodeId?: string,
    ) => {
      // Load nested tree data using unified approach
      const { nodes: frontendNodes, edges: frontendEdges } = await loadTreeData(subTree.id);

      // Add parent node context to nested tree
      const parentWithContext = {
        id: node.id, // Use original parent node ID
        type: node.type || 'screen', // Use ReactFlow type field
        position: { x: 200, y: 200 },
        data: {
          label: node.data.label,
          description: node.data.description || `Navigation for ${node.data.label}`,
          verifications: node.data.verifications || [],
          // ADD NESTED TREE CONTEXT
          isParentReference: true,
          originalTreeId: parentTreeId, // Original tree where this node lives
          currentTreeId: subTree.id, // Current nested tree we're viewing
          depth: subTree.tree_depth, // Depth in nested structure
          parentNodeId: node.data.parent?.[node.data.parent.length - 1], // Immediate parent
          parent: node.data.parent || [], // Full parent chain from original tree
          ...node.data,
        },
      };

      // Ensure parent node is included in nested tree
      const finalNodes = frontendNodes.some((n: any) => n.id === node.id)
        ? frontendNodes.map((n: any) =>
            n.id === node.id ? { ...n, data: { ...n.data, ...parentWithContext.data } } : n,
          )
        : [parentWithContext, ...frontendNodes];

      // Push to navigation stack with depth and parent tree tracking
      pushLevel(subTree.id, node.id, subTree.name, node.data.label, subTree.tree_depth, parentTreeId);

      // Update actualTreeId to the nested tree ID
      navigationConfig.setActualTreeId(subTree.id);
      console.log(`[@useNestedNavigation] Updated actualTreeId to nested tree: ${subTree.id}`);

      // Load breadcrumb for the new tree
      await loadBreadcrumb(subTree.id);

      navigation.addToParentChain({
        treeId: subTree.id,
        treeName: subTree.name,
        nodes: finalNodes,
        edges: frontendEdges,
      });

      navigation.setInitialState({ nodes: [...finalNodes], edges: [...frontendEdges] });
      navigation.setHasUnsavedChanges(false);

      // Focus on the requested node (goto landing) or the entry node (first node).
      setTimeout(() => {
        if (finalNodes.length > 0 && navigation.reactFlowInstance) {
          const target =
            (centerNodeId && finalNodes.find((n: any) => n.id === centerNodeId)) || finalNodes[0];
          navigation.reactFlowInstance.setCenter(target.position.x, target.position.y, { zoom: 1 });
          console.log(`[@useNestedNavigation] Focused on node: ${target.data.label}`);
        }
      }, 10);

      console.log(
        `[@useNestedNavigation] Switched into sub-tree: ${subTree.name} with ${finalNodes.length} nodes and ${frontendEdges.length} edges`,
      );

      return { nodes: finalNodes, edges: frontendEdges };
    },
    [loadTreeData, pushLevel, navigationConfig, loadBreadcrumb, navigation],
  );

  const handleNodeDoubleClick = useCallback(async (_event: React.MouseEvent, node: any) => {
    // 1. Skip action nodes - they don't have sub-navigation
    if (node.data?.type === 'action') {
      return;
    }

    // 2. Synchronous in-flight guard — prevents stacking duplicate breadcrumb
    // entries when the user double-clicks again while a previous load is
    // still resolving.
    if (inFlightRef.current) {
      console.warn(
        `[@useNestedNavigation] Ignoring double-click on "${node.data?.label}" — previous subtree load still in flight`,
      );
      return;
    }

    // 3. Infinite loop protection
    const nodeId = node.id;
    const isAlreadyInThisNode = stack.some((level) => level.parentNodeId === nodeId);

    if (isAlreadyInThisNode) {
      console.warn(
        `[@useNestedNavigation] Prevented infinite loop: Already in sub-tree of node "${node.data.label}" (ID: ${nodeId})`,
      );
      openNodeDialog(node);
      return;
    }

    inFlightRef.current = true;

    // 4. Check for existing sub-trees
    try {
      console.log(`[@useNestedNavigation] Checking for existing subtrees for node: ${node.id} in tree: ${actualTreeId}`);
      const subTrees = await navigationConfig.loadNodeSubTrees(actualTreeId!, node.id);
      console.log(`[@useNestedNavigation] Found ${subTrees.length} existing subtrees:`, subTrees);

      if (subTrees.length > 0) {
        // 4a. Load existing sub-tree (center on its entry node)
        await enterSubtree(node, actualTreeId!, subTrees[0]);
      } else {
        // 4b. Create new sub-tree
        await createNewSubTree(node);
      }
    } catch (error) {
      console.error('[@useNestedNavigation] Error handling node double-click:', error);
      // Fallback to node dialog
      openNodeDialog(node);
    } finally {
      inFlightRef.current = false;
    }

  }, [stack, actualTreeId, navigationConfig, enterSubtree, openNodeDialog]);

  const createNewSubTree = useCallback(async (parentNode: any) => {
    try {
      const newTreeData = {
        name: `${parentNode.data.label} - Subtree`,
        userinterface_id: navigationConfig.currentTree?.userinterface_id, // Use the already loaded tree's userinterface_id
        description: `Sub-navigation for ${parentNode.data.label}`,
      };

      const newTree = await navigationConfig.createSubTree(actualTreeId!, parentNode.id, newTreeData);

      // CRITICAL: Save parent node to subtree database (required for pathfinding)
      const parentNodeData = {
        node_id: parentNode.id,
        label: parentNode.data.label,
        position_x: 200, // Default position in subtree
        position_y: 200,
        node_type: parentNode.type || 'screen', // Use ReactFlow type field
        style: {},
        data: {
          description: parentNode.data.description || `Navigation for ${parentNode.data.label}`,
          screenshot: parentNode.data.screenshot,
          isParentReference: true,
          originalTreeId: actualTreeId,
          depth: newTree.tree_depth,
          parent: parentNode.data.parent || [],
          ...parentNode.data
        },
        verifications: parentNode.data.verifications || [],
        has_subtree: true,
        subtree_count: 1
      };
      
      await navigationConfig.saveNode(newTree.id, parentNodeData);
      console.log(`[@useNestedNavigation] Saved parent node to subtree database for pathfinding`);
      
      // Always start new subtree with parent node displayed graphically with context
      const frontendNodes = [{
        id: parentNode.id, // Use original parent node ID
        type: parentNode.type || 'screen', // Use ReactFlow type field
        position: { x: 200, y: 200 },
        data: {
          label: parentNode.data.label,
          description: parentNode.data.description || `Navigation for ${parentNode.data.label}`,
          verifications: parentNode.data.verifications || [],
          // ADD NESTED TREE CONTEXT
          isParentReference: true,
          originalTreeId: actualTreeId, // Original tree where this node lives
          currentTreeId: newTree.id, // Current nested tree we're viewing
          depth: newTree.tree_depth, // Depth in nested structure
          parentNodeId: parentNode.data.parent?.[parentNode.data.parent.length - 1], // Immediate parent
          parent: parentNode.data.parent || [], // Full parent chain from original tree
          ...parentNode.data
        }
      }];

      // Push to navigation stack with parent tree tracking
      pushLevel(newTree.id, parentNode.id, newTree.name, parentNode.data.label, newTree.tree_depth, actualTreeId || undefined);

      // CRITICAL: Update actualTreeId to the new nested tree ID
      navigationConfig.setActualTreeId(newTree.id);
      console.log(`[@useNestedNavigation] Updated actualTreeId to new nested tree: ${newTree.id}`);

      // Load breadcrumb
      await loadBreadcrumb(newTree.id);

      navigation.addToParentChain({ 
        treeId: newTree.id, 
        treeName: newTree.name,
        nodes: frontendNodes, 
        edges: [] 
      });
      
      setTimeout(() => {
        if (navigation.reactFlowInstance) {
          navigation.reactFlowInstance.setCenter(frontendNodes[0].position.x, frontendNodes[0].position.y, { zoom: 1 });
          console.log(`[@useNestedNavigation] Focused on parent node: ${frontendNodes[0].data.label}`);
        }
      }, 10);

      console.log(`[@useNestedNavigation] Created new sub-tree: ${newTree.name} starting with parent node`);
    } catch (error) {
      console.error('[@useNestedNavigation] Error creating sub-tree:', error);
      throw error;
    }
  }, [actualTreeId, navigationConfig, pushLevel, loadBreadcrumb, setNodes, setEdges]);

  return {
    handleNodeDoubleClick,
    createNewSubTree,
  };
};
