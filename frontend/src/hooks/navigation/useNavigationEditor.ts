import { useMemo, useCallback, useContext } from 'react';
import { MarkerType, addEdge, Connection } from 'reactflow';

import { useNavigationConfig } from '../../contexts/navigation/NavigationConfigContext';
import NavigationContext from '../../contexts/navigation/NavigationContext';
import { useHostData, useHostControl } from '../useHostManager';
import { useConfirmDialog } from '../useConfirmDialog';
import { UINavigationEdge, UINavigationNode } from '../../types/pages/Navigation_Types';

import { buildServerUrl } from '../../utils/buildUrlUtils';
import { api } from '../../utils/apiClient';
import { mapNodesToFrontend, mapEdgesToFrontend } from '../../utils/navigation/navigationMappers';
import { DEFAULT_NODE_FORM } from '../../utils/navigation/navigationFormDefaults';
import { reanchorEdgeToDrawnHandles } from '../../utils/navigation/navigationUtils';

const normalizeAccents = (text: string) => {
  return text.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
};

export const useNavigationEditor = () => {
  // Get the navigation config context (save/load functionality)
  const navigationConfig = useNavigationConfig();

  // Get the unified navigation context (state management)
  const navigation = useContext(NavigationContext);
  if (!navigation) {
    throw new Error('useNavigationEditor must be used within a NavigationProvider');
  }

  // Get host data & control
  const hostData = useHostData();
  const hostControl = useHostControl();

  // Confirmation dialog for replacing window.confirm
  const { dialogState, confirm, handleConfirm, handleCancel } = useConfirmDialog();

  // Edge hook will be initialized when needed for edge operations

  // New normalized API functions
  const loadTreeData = useCallback(
    async (treeId: string) => {
      try {
        navigation.setIsLoading(true);
        navigation.setError(null);

        // Load complete tree data using new API
        const treeData = await navigationConfig.loadTreeData(treeId);
        
        const frontendNodes = mapNodesToFrontend(treeData.nodes) as unknown as UINavigationNode[];
        console.log(`[@useNavigationEditor:loadTreeData] 📋 Loaded ${frontendNodes.length} nodes from database:`);
        frontendNodes.forEach((node: any) => {
          console.log(`[@useNavigationEditor:loadTreeData]   • ${node.id} (label: '${node.data.label}', type: '${node.type}')`);
        });

        const frontendEdges = mapEdgesToFrontend(treeData.edges) as unknown as UINavigationEdge[];

        navigation.setNodes(frontendNodes);
        navigation.setEdges(frontendEdges);
        navigation.setInitialState({ nodes: [...frontendNodes], edges: [...frontendEdges] });
        navigation.setHasUnsavedChanges(false);

        // Restore viewport if saved and ReactFlow is ready
        if (treeData.tree) {
          const { viewport_x, viewport_y, viewport_zoom } = treeData.tree;
          console.log(`[@useNavigationEditor:loadTreeData] Tree has viewport data:`, { viewport_x, viewport_y, viewport_zoom });
          
          if (viewport_x !== undefined && viewport_y !== undefined && viewport_zoom !== undefined) {
            // Use setTimeout to ensure React Flow is fully initialized
            setTimeout(() => {
              if (navigation.reactFlowInstance) {
                console.log(`[@useNavigationEditor:loadTreeData] Restoring viewport:`, { x: viewport_x, y: viewport_y, zoom: viewport_zoom });
                navigation.reactFlowInstance.setViewport({ x: viewport_x, y: viewport_y, zoom: viewport_zoom });
              } else {
                console.warn(`[@useNavigationEditor:loadTreeData] ReactFlow instance not available for viewport restoration`);
              }
            }, 100);
          } else {
            console.log(`[@useNavigationEditor:loadTreeData] No viewport data to restore`);
          }
        }

        console.log(`[@useNavigationEditor:loadTreeData] Loaded ${frontendNodes.length} nodes and ${frontendEdges.length} edges`);
        console.log('[@useNavigationEditor:loadTreeData] Set initialState with node IDs:', frontendNodes.map((n: any) => n.id));
      } catch (error) {
        navigation.setError(`Failed to load tree: ${error instanceof Error ? error.message : 'Unknown error'}`);
      } finally {
        navigation.setIsLoading(false);
      }
    },
    [navigationConfig, navigation],
  );

  const loadTreeByUserInterface = useCallback(
    async (
      userInterfaceId: string,
      options?: { includeMetrics?: boolean; includeNested?: boolean; variant?: string | null },
    ) => {
      try {
        navigation.setIsLoading(true);
        navigation.setError(null);

        // Load tree data by user interface using new API with metrics included (reduces 2 API calls to 1).
        // Caller can override metrics/nested/variant; defaults preserve the
        // pre-variant behavior (base scope, metrics included).
        const result = await navigationConfig.loadTreeByUserInterface(userInterfaceId, {
          includeMetrics: options?.includeMetrics ?? true,
          includeNested: options?.includeNested ?? false,
          variant: options?.variant ?? null,
        });
        
        if (result.success && result.tree) {
          const treeData = result.tree;
          const frontendNodes = mapNodesToFrontend(treeData.metadata?.nodes || []) as unknown as UINavigationNode[];
          const frontendEdges = mapEdgesToFrontend(treeData.metadata?.edges || []) as unknown as UINavigationEdge[];

          navigation.setNodes(frontendNodes);
          navigation.setEdges(frontendEdges);
          navigation.setInitialState({ nodes: [...frontendNodes], edges: [...frontendEdges] });
          navigation.setHasUnsavedChanges(false);
          
          if (navigation.parentChain.length === 0) {
            navigation.addToParentChain({
              treeId: result.tree.id,
              treeName: result.tree.name || userInterfaceId,
              nodes: frontendNodes,
              edges: frontendEdges,
            });
          }

          if (result.metrics) {
            console.log(`[@useNavigationEditor:loadTreeByUserInterface] ✅ Received metrics in combined call - NO separate fetch needed!`, {
              nodeCount: Object.keys(result.metrics.nodes || {}).length,
              edgeCount: Object.keys(result.metrics.edges || {}).length,
              globalConfidence: result.metrics.global_confidence
            });
          }

          return result; // Return full result including metrics
        } else {
          throw new Error(result.error || 'Failed to load tree for user interface');
        }
      } catch (error) {
        navigation.setError(`Failed to load tree by user interface: ${error instanceof Error ? error.message : 'Unknown error'}`);
        throw error;
      } finally {
        navigation.setIsLoading(false);
      }
    },
    [navigationConfig, navigation],
  );









  // Simple event handlers.
  // Returns the ids of the edge(s) actually created ([] when the connection
  // was rejected) so callers (NavigationEditor.wrappedOnConnect) can act on
  // the new rows SYNCHRONOUSLY — reading ids back out of a setEdges updater
  // does not work (React runs updaters at flush, not inline).
  const onConnect = useCallback(
    async (connection: Connection): Promise<string[]> => {
      console.log('Connection attempt:', connection);

      // Validate connection parameters
      if (!connection.source || !connection.target) {
        console.error(
          '[@useNavigationEditor:onConnect] Invalid connection: missing source or target',
        );
        return [];
      }

      // Find source and target nodes
      const sourceNode = navigation.nodes.find((n) => n.id === connection.source);
      const targetNode = navigation.nodes.find((n) => n.id === connection.target);

      if (!sourceNode || !targetNode) {
        console.error('[@useNavigationEditor:onConnect] Source or target node not found');
        return [];
      }

      // Prevent self-connections
      if (connection.source === connection.target) {
        console.warn('[@useNavigationEditor:onConnect] Cannot connect node to itself');
        return [];
      }

      // Root node's left handle is reserved for the entry→root edge
      // (handles are also disabled on the node; server rejects it too)
      if (
        connection.targetHandle === 'left-target' &&
        targetNode.data.is_root === true &&
        sourceNode.data.type !== 'entry'
      ) {
        console.warn(
          '[@useNavigationEditor:onConnect] Left handle of the root node is reserved for the entry edge',
        );
        return [];
      }
      if (connection.sourceHandle === 'left-source' && sourceNode.data.is_root === true) {
        console.warn(
          '[@useNavigationEditor:onConnect] Left handle of the root node is reserved for the entry edge',
        );
        return [];
      }

      // Check if edge already exists in either direction to prevent duplicates
      const existingEdge = navigation.edges.find(
        (e) =>
          (e.source === connection.source && e.target === connection.target) ||
          (e.source === connection.target && e.target === connection.source)
      );

      if (existingEdge) {
        // A hidden (hidden_in_base=true) existing edge is intercepted upstream
        // in NavigationEditor.wrappedOnConnect, which reveals it in a
        // scope-aware way (Base un-hides only true orphans; a variant reveals
        // within itself). By the time we reach here the existing edge is a
        // VISIBLE duplicate. Edges are bidirectional so a second row is never
        // created — instead RE-ANCHOR the existing edge to the handles the
        // user just drew (they're redrawing to fix the routing). When drawn
        // against the stored direction, the handles swap roles but keep their
        // sides, so the line still touches the sides the user connected.
        const anchor = reanchorEdgeToDrawnHandles(existingEdge, connection);
        if (anchor) {
          const { sourceHandle: nextSourceHandle, targetHandle: nextTargetHandle } = anchor;
          console.log(
            '[@useNavigationEditor:onConnect] Edge already exists — re-anchoring to drawn handles',
            { edgeId: existingEdge.id, nextSourceHandle, nextTargetHandle },
          );
          const updated = navigation.edges.map((e) =>
            e.id === existingEdge.id
              ? {
                  ...e,
                  sourceHandle: nextSourceHandle,
                  targetHandle: nextTargetHandle,
                  data: {
                    ...(e.data || {}),
                    sourceHandle: nextSourceHandle,
                    targetHandle: nextTargetHandle,
                  },
                }
              : e,
          );
          navigation.setEdges(updated as any);
          navigation.setHasUnsavedChanges(true);
        } else {
          console.warn('[@useNavigationEditor:onConnect] Edge already exists between these nodes');
        }
        return [];
      }

      // 🔄 CONDITIONAL EDGE DETECTION: MANUAL ONLY (requires holding modifier key)
      // Conditional edges = same actions executed to multiple targets
      // User must hold Shift/Ctrl/Cmd while connecting to create conditional edge
      
      // Check if modifier key was held during connection (passed via connection object)
      const isConditionalEdge = (connection as any).isConditional || false;
      
      let conditionalActionSetId: string | null = null;
      let siblingEdges: any[] = [];

      if (isConditionalEdge) {
        // MANUAL CONDITIONAL: reuse the existing sibling's FORWARD action_set_id
        // so this new edge JOINS the conditional group. The new edge is a SIBLING
        // (borrower): it keeps EMPTY forward actions and inherits the MAIN (owner)
        // edge's actions at runtime (backend navigation_graph populates them) and
        // for display (findSiblingWithActions). We never copy actions onto the new
        // sibling, so "main = the action owner" stays unambiguous and survives
        // reload. CRITICAL: only FORWARD edges (same source + sourceHandle).
        siblingEdges = navigation.edges.filter(
          (e) =>
            e.source === connection.source &&
            e.sourceHandle === connection.sourceHandle &&
            e.target !== connection.target,
        );

        if (siblingEdges.length > 0) {
          // Only the FIRST action set (forward direction) is shared; reverse is
          // always independent.
          const siblingActionSets = siblingEdges[0].data?.action_sets || [];
          if (siblingActionSets.length > 0) {
            conditionalActionSetId = siblingActionSets[0].id;
            console.log(`[@useNavigationEditor:onConnect] 🔗 CONDITIONAL sibling - sharing FORWARD action_set_id: ${conditionalActionSetId} (empty actions, borrows from main owner)`);
          }
        }
      } else {
        console.log(`[@useNavigationEditor:onConnect] ✅ Regular edge - creating unique action sets`);
      }

      // Helper function to create bidirectional edge data
      const createEdgeData = (sourceLabel: string, targetLabel: string, conditionalSetId?: string | null) => {
        // Clean labels for ID format
        const cleanSourceLabel = normalizeAccents(sourceLabel).toLowerCase().replace(/[^a-z0-9]/g, '_');
        const cleanTargetLabel = normalizeAccents(targetLabel).toLowerCase().replace(/[^a-z0-9]/g, '_');

        // CONDITIONAL EDGES: Only FORWARD action uses shared action_set_id
        // Reverse action ALWAYS gets unique ID (not part of conditional group)
        const forwardActionSetId = conditionalSetId || `${cleanSourceLabel}_to_${cleanTargetLabel}`;
        const reverseActionSetId = `${cleanTargetLabel}_to_${cleanSourceLabel}`; // Always unique

        return {
          label: `${sourceLabel}→${targetLabel}`,
          action_sets: [
            // FORWARD direction - may share action_set_id with sibling edges.
            // A new conditional SIBLING starts with EMPTY actions and borrows the
            // MAIN (owner) edge's actions; the owner keeps the only real copy.
            {
              id: forwardActionSetId,  // ✅ Shared ID for conditional edges
              label: `${sourceLabel} → ${targetLabel}`,
              actions: [],
              retry_actions: [],
              failure_actions: [],
              final_wait_time: 0,
            },
            // REVERSE direction - always unique (NOT part of conditional group)
            {
              id: reverseActionSetId,  // ✅ Always unique - reverse is independent
              label: `${targetLabel} → ${sourceLabel}`,
              actions: [],
              retry_actions: [],
              failure_actions: [],
              final_wait_time: 0,
            }
          ],
          default_action_set_id: forwardActionSetId,  // ✅ Use conditional ID as default
          is_conditional: !!conditionalSetId,  // ✅ Mark as conditional edge (shares forward action only)
        };
      };

      // Simplified: no special handling needed since edges are now bidirectional by default

      const timestamp = Date.now();

      // Create single bidirectional edge (with conditional action_set_id if applicable)
      const newEdge: UINavigationEdge = {
        id: `edge-${connection.source}-${connection.target}-${timestamp}`,
        source: connection.source,
        target: connection.target,
        sourceHandle: connection.sourceHandle || undefined,
        targetHandle: connection.targetHandle || undefined,
        type: 'navigation',
        animated: false,
        style: {
          stroke: conditionalActionSetId ? '#2196f3' : '#555',  // 🎨 BLUE for conditional, gray for normal
          strokeWidth: 2,
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: conditionalActionSetId ? '#2196f3' : '#555',  // 🎨 Match marker color
        },
        data: createEdgeData(
          sourceNode?.data?.label || 'unknown',
          targetNode?.data?.label || 'unknown',
          conditionalActionSetId,
        ),
      };

      console.log('[@useNavigationEditor:onConnect] Creating edge:', newEdge);
      if (conditionalActionSetId) {
        console.log('[@useNavigationEditor:onConnect] 🔗 Edge is conditional - will verify all siblings on failure');
      }

      const edgesToAdd = [newEdge];

      // No flag-marking needed: main vs sibling is DERIVED from action-ownership
      // (getConditionalRole) — the pre-existing edge owns the actions so it is the
      // main; this new empty edge is the sibling. The main's canvas colour is
      // recomputed structurally on render.

      // Bidirectional logic lives inside the single edge's action_sets (forward =
      // index 0, reverse = index 1) — we never create a separate reverse edge.
      // A long-disabled "reverse edge" block used to mint `edge-<target>-<source>`
      // with naively suffix-swapped handles (`-source`↔`-target`), which produced
      // INVALID handle ids (e.g. `bottom-left-menu-source`) that ReactFlow drops
      // → invisible edges. Removed entirely 2026-06-02 so it can never be
      // re-enabled. (useResolvedTree still sanitizes any legacy bad-handle rows.)

      // Handle parent inheritance based on handle direction and ROOT NODE PRIORITY
      // 
      // ROOT NODE RULE: Root nodes are ALWAYS parents, never children
      // This includes:
      // 1. Main tree root nodes (is_root=true) - the home/entry node
      // 2. Nested tree root nodes (isParentReference=true) - parent node displayed in nested tree
      // 
      // This ensures that when linking to/from any root node, the root node is always 
      // treated as the parent, maintaining the navigation hierarchy correctly in both
      // main trees and nested subtrees.
      //
      // Standard logic (when no root nodes involved):
      // - Vertical handles = parent-child relationship (inherit parent + source node)
      // - Horizontal handles = sibling relationship (inherit same parent)
      let updatedNodes = navigation.nodes;
      const sourceParent = sourceNode.data.parent;
      const targetParent = targetNode.data.parent;
      
      // Check if either node is a root/home node
      // This includes:
      // 1. Main tree root nodes (is_root === true)
      // 2. Nested tree root nodes (isParentReference === true - parent node displayed in nested tree)
      const isSourceRoot = sourceNode.data.is_root === true || sourceNode.data.isParentReference === true;
      const isTargetRoot = targetNode.data.is_root === true || targetNode.data.isParentReference === true;
      
      // Determine if this is a vertical connection (top/bottom handles)
      const isVerticalConnection = connection.sourceHandle?.includes('top') || 
                                   connection.sourceHandle?.includes('bottom') ||
                                   connection.targetHandle?.includes('top') || 
                                   connection.targetHandle?.includes('bottom');

      // ROOT NODE PRIORITY: If either node is root, it becomes the parent
      if (isSourceRoot && !isTargetRoot) {
        // Source is root - it becomes parent of target
        const newParent = isVerticalConnection 
          ? [sourceNode.id] // Root becomes direct parent
          : (sourceParent || []); // For horizontal, target keeps same level as root
          
        const rootType = sourceNode.data.is_root ? 'main tree root' : 'nested tree root';
        console.log(`[@useNavigationEditor:onConnect] ROOT NODE: '${sourceNode.data.label}' (${rootType}) becomes parent of '${targetNode.data.label}':`, newParent);
        updatedNodes = navigation.nodes.map(node => 
          node.id === targetNode.id 
            ? { ...node, data: { ...node.data, parent: newParent } }
            : node
        );
        navigation.setNodes(updatedNodes);
      } else if (isTargetRoot && !isSourceRoot) {
        // Target is root - it becomes parent of source
        const newParent = isVerticalConnection 
          ? [targetNode.id] // Root becomes direct parent
          : (targetParent || []); // For horizontal, source keeps same level as root
          
        const rootType = targetNode.data.is_root ? 'main tree root' : 'nested tree root';
        console.log(`[@useNavigationEditor:onConnect] ROOT NODE: '${targetNode.data.label}' (${rootType}) becomes parent of '${sourceNode.data.label}':`, newParent);
        updatedNodes = navigation.nodes.map(node => 
          node.id === sourceNode.id 
            ? { ...node, data: { ...node.data, parent: newParent } }
            : node
        );
        navigation.setNodes(updatedNodes);
      } else if (isSourceRoot && isTargetRoot) {
        // Both are root nodes - no parent relationship changes
        console.log(`[@useNavigationEditor:onConnect] Both nodes are root nodes - no parent-child relationship established`);
      } else if (!sourceParent && targetParent) {
        // STANDARD LOGIC: Source node has no parent, inherit from target
        const newParent = isVerticalConnection 
          ? [...targetParent, targetNode.id] // Vertical: parent + target node (child relationship)
          : [...targetParent]; // Horizontal: same parent (sibling relationship)
          
        console.log(`[@useNavigationEditor:onConnect] Source node '${sourceNode.data.label}' inheriting ${isVerticalConnection ? 'child' : 'sibling'} relationship from '${targetNode.data.label}':`, newParent);
        updatedNodes = navigation.nodes.map(node => 
          node.id === sourceNode.id 
            ? { ...node, data: { ...node.data, parent: newParent } }
            : node
        );
        navigation.setNodes(updatedNodes);
      } else if (!targetParent && sourceParent) {
        // STANDARD LOGIC: Target node has no parent, inherit from source
        const newParent = isVerticalConnection 
          ? [...sourceParent, sourceNode.id] // Vertical: parent + source node (child relationship)
          : [...sourceParent]; // Horizontal: same parent (sibling relationship)
          
        console.log(`[@useNavigationEditor:onConnect] Target node '${targetNode.data.label}' inheriting ${isVerticalConnection ? 'child' : 'sibling'} relationship from '${sourceNode.data.label}':`, newParent);
        updatedNodes = navigation.nodes.map(node => 
          node.id === targetNode.id 
            ? { ...node, data: { ...node.data, parent: newParent } }
            : node
        );
        navigation.setNodes(updatedNodes);
      } else if (!sourceParent && !targetParent) {
        // Both nodes have no parent
        if (isVerticalConnection) {
          // For vertical connections, create parent-child relationship even without existing parents
          console.log(`[@useNavigationEditor:onConnect] Creating parent-child relationship: '${targetNode.data.label}' becomes parent of '${sourceNode.data.label}'`);
          updatedNodes = navigation.nodes.map(node => 
            node.id === sourceNode.id 
              ? { ...node, data: { ...node.data, parent: [targetNode.id] } }
              : node
          );
          navigation.setNodes(updatedNodes);
        } else {
          console.log(`[@useNavigationEditor:onConnect] Both nodes have no parent - no inheritance needed for horizontal connection`);
        }
      } else {
        console.log(`[@useNavigationEditor:onConnect] Both nodes already have parents - no inheritance needed`);
      }

      // Add all edges to current edges using ReactFlow's addEdge utility
      let updatedEdges = navigation.edges;

      // Add new edges
      for (const edge of edgesToAdd) {
        updatedEdges = addEdge(edge, updatedEdges) as UINavigationEdge[];
      }

      // Update edges in navigation context
      navigation.setEdges(updatedEdges);

      // Mark as having unsaved changes
      navigation.setHasUnsavedChanges(true);

      console.log(
        `[@useNavigationEditor:onConnect] ${edgesToAdd.length} edge(s) created successfully - manual save required`,
      );

      return edgesToAdd.map((e) => e.id);
    },
    [navigation],
  );

  const onNodeClick = useCallback(
    (_event: React.MouseEvent, node: any) => {
      navigation.setSelectedNode(node);
      navigation.setSelectedEdge(null); // Clear edge selection when node is selected
    },
    [navigation],
  );

  const onEdgeClick = useCallback(
    (_event: React.MouseEvent, edge: any) => {
      // Find bidirectional edge (opposite direction) - DISABLED after migration
      // After migration, all edges contain both directions as action sets
      const oppositeEdge = null; // navigation.edges.find(
      //   (e) => e.source === edge.target && e.target === edge.source && e.id !== edge.id,
      // );

      if (oppositeEdge) {
        // Simple check: if any edge involves an action or entry node, don't treat as bidirectional
        const sourceNode = navigation.nodes.find((n) => n.id === edge.source);
        const targetNode = navigation.nodes.find((n) => n.id === edge.target);
        const isUnidirectionalInvolved = (
          sourceNode?.type === 'action' || 
          targetNode?.type === 'action' ||
          sourceNode?.type === 'entry' || 
          targetNode?.type === 'entry'
        );
        
        if (isUnidirectionalInvolved) {
          // Action/entry edges are unidirectional - just select the clicked edge
          navigation.setSelectedEdge(edge);
        } else {
          // Regular edges can be bidirectional
          const edgeWithBidirectional = {
            ...edge,
            bidirectionalEdge: oppositeEdge,
          };
          navigation.setSelectedEdge(edgeWithBidirectional);
        }
      } else {
        // No opposite edge found - proceed with normal single edge selection
        navigation.setSelectedEdge(edge);
        

      }

      navigation.setSelectedNode(null); // Clear node selection when edge is selected
    },
    [navigation],
  );

  const onNodeDoubleClick = useCallback(
    (_event: React.MouseEvent, node: any) => {
      // Simple double-click opens edit dialog (nested navigation handled separately)
      navigation.openNodeDialog(node);
    },
    [navigation],
  );

  const onPaneClick = useCallback(() => {
    navigation.resetSelection();
  }, [navigation]);

  // Node and edge action handlers
  const handleNodeFormSubmit = useCallback(
    async (nodeForm: any) => {
      await navigation.saveNodeWithStateUpdate(nodeForm);
    },
    [navigation],
  );

  const handleEdgeFormSubmit = useCallback(
    async (edgeForm: any) => {
      await navigation.saveEdgeWithStateUpdate(edgeForm);
      // After save, update selectedEdge if this was the selected one
      const updatedEdge = navigation.edges.find(e => e.id === edgeForm.edgeId);
      if (updatedEdge && navigation.selectedEdge?.id === edgeForm.edgeId) {
        navigation.setSelectedEdge(updatedEdge);
      }
    },
    [navigation],
  );

  const addNewNode = useCallback(
    (
      type: string = 'screen',
      position: { x: number; y: number } = { x: 250, y: 250 },
      // Optional initial flags written into the new node's `data`. Used by
      // the canvas's variant-scope Add Node wrapper to set
      // `hidden_in_base: true` synchronously — no setTimeout race.
      initialFlags?: { hidden_in_base?: boolean },
    ): string => {
      const validType = type as 'screen' | 'menu' | 'entry' | 'action';
      const newId = `node-${Date.now()}`;
      const newNode = {
        id: newId,
        type: validType, // Use the node type directly as ReactFlow type
        position,
        data: {
          type: validType,
          label: `new_${type}`,
          description: '',
          verifications: [],
          ...(initialFlags?.hidden_in_base ? { hidden_in_base: true } : {}),
        },
      };
      navigation.setNodes([...navigation.nodes, newNode as any]);
      navigation.markUnsavedChanges();
      return newId;
    },
    [navigation],
  );

  const cancelNodeChanges = useCallback(() => {
    navigation.setIsNodeDialogOpen(false);
    navigation.setNodeForm({ ...DEFAULT_NODE_FORM });
  }, [navigation]);

  const closeSelectionPanel = useCallback(() => {
    navigation.resetSelection();
  }, [navigation]);

  const deleteSelected = useCallback(async () => {
    console.log('[@useNavigationEditor:deleteSelected] Starting deletion process', {
      selectedNode: navigation.selectedNode?.id,
      selectedEdge: navigation.selectedEdge?.id,
      currentNodeCount: navigation.nodes.length,
      currentEdgeCount: navigation.edges.length
    });

    // Handle node deletion
    if (navigation.selectedNode) {
      const nodeId = navigation.selectedNode.id;
      const node = navigation.selectedNode;
      
      // ✅ PROTECTION: Prevent deletion of essential nodes (silently)
      if (nodeId === 'entry-node' || nodeId === 'home') {
        console.log(`[@useNavigationEditor:deleteSelected] Cannot delete protected node: ${nodeId}`);
        return;
      }
      
      // Check if node has nested trees and warn user
      if (node.data?.has_subtree && (node.data?.subtree_count || 0) > 0) {
        const subtreeCount = node.data?.subtree_count || 0;
        const confirmMessage = `This node has ${subtreeCount} nested tree(s). Deleting it will also delete all nested navigation trees. Are you sure?`;
        
        // Use custom confirm dialog instead of window.confirm
        return new Promise<void>((resolve) => {
          confirm({
            title: 'Delete Node with Nested Trees',
            message: confirmMessage,
            confirmColor: 'error',
            confirmText: 'Delete',
            cancelText: 'Cancel',
            onConfirm: () => {
              console.log(`[@useNavigationEditor:deleteSelected] User confirmed deletion of node with ${subtreeCount} nested trees`);
              const filteredNodes = navigation.nodes.filter((n) => n.id !== nodeId);
              // Also delete edges connected to this node
              const filteredEdges = navigation.edges.filter((e) => e.source !== nodeId && e.target !== nodeId);
              console.log('[@useNavigationEditor:deleteSelected] Deleting node:', nodeId, 
                'Nodes before:', navigation.nodes.length, 'Nodes after:', filteredNodes.length,
                'Edges before:', navigation.edges.length, 'Edges after:', filteredEdges.length);
              navigation.setNodes(filteredNodes);
              navigation.setEdges(filteredEdges);
              navigation.setSelectedNode(null);
              navigation.markUnsavedChanges();
              resolve();
            },
          });
        });
      }
      
      const filteredNodes = navigation.nodes.filter((n) => n.id !== nodeId);
      // Also delete edges connected to this node
      const filteredEdges = navigation.edges.filter((e) => e.source !== nodeId && e.target !== nodeId);
      console.log('[@useNavigationEditor:deleteSelected] Deleting node:', nodeId, 
        'Nodes before:', navigation.nodes.length, 'Nodes after:', filteredNodes.length,
        'Edges before:', navigation.edges.length, 'Edges after:', filteredEdges.length);
      navigation.setNodes(filteredNodes);
      navigation.setEdges(filteredEdges);
      navigation.setSelectedNode(null);
      navigation.markUnsavedChanges();
    }

    // Handle edge deletion - DELEGATED TO useEdge
    if (navigation.selectedEdge) {
      const selectedEdge = navigation.selectedEdge;
      
      // ✅ PROTECTION: Prevent deletion of essential edge (silently)
      if (selectedEdge.id === 'edge-entry-node-to-home') {
        console.log(`[@useNavigationEditor:deleteSelected] Cannot delete protected edge: ${selectedEdge.id}`);
        return;
      }
      
      // Use custom confirm dialog instead of window.confirm
      return new Promise<void>((resolve) => {
        confirm({
          title: 'Delete Edge',
          message: 'Delete this entire edge and all its directions?',
          confirmColor: 'error',
          confirmText: 'Delete',
          cancelText: 'Cancel',
          onConfirm: () => {
            // Handle edge deletion directly without using the hook
            // Always delete the entire edge for simplicity in this context
            const deletionResult = { action: 'delete_entire_edge', edgeId: selectedEdge.id };
            
            console.log('[@useNavigationEditor:deleteSelected] Edge deletion result:', deletionResult);
            
            // Always delete the entire edge (simplified logic)
            if (deletionResult.action === 'delete_entire_edge') {
              const filteredEdges = navigation.edges.filter(e => e.id !== selectedEdge.id);
              navigation.setEdges(filteredEdges);
              navigation.setSelectedEdge(null);
              navigation.markUnsavedChanges();
              console.log('[@useNavigationEditor:deleteSelected] Edge deleted successfully');
            }
            resolve();
          },
        });
      });
    }
  }, [navigation, confirm]);

  const resetNode = useCallback(
    (nodeId: string) => {
      console.log('Reset node:', nodeId);
      navigation.setIsNodeDialogOpen(false);
    },
    [navigation],
  );

  const discardChanges = useCallback(() => {
    navigation.setIsDiscardDialogOpen(true);
  }, [navigation]);

  const performDiscardChanges = useCallback(() => {
    navigation.resetToInitialState();
    navigation.setIsDiscardDialogOpen(false);
  }, [navigation]);

  const fitView = useCallback(() => {
    navigation.fitViewToNodes();
  }, [navigation]);

  const navigateToParent = useCallback(() => {
    // Simple fallback
    console.log('Navigate to parent');
  }, []);

  const setUserInterfaceFromProps = useCallback(
    (userInterface: any) => {
      navigation.setUserInterface(userInterface);
    },
    [navigation],
  );

  // Combine all functionality into the same interface as the original useNavigationEditor
  return useMemo(
    () => ({
      // State (filtered views for ReactFlow display)
      nodes: navigation.nodes,
      edges: navigation.edges,

      // Raw data (single source of truth)
      allNodes: navigation.nodes, // In unified context, nodes are already the source of truth
      allEdges: navigation.edges,

      // Tree and interface state
      treeName: navigation.currentTreeName,
      treeId: navigation.currentTreeId,
      interfaceId: navigation.interfaceId,
      currentTreeId: navigation.currentTreeId,
      currentTreeName: navigation.currentTreeName,
      navigationPath: navigation.navigationPath,
      navigationNamePath: navigation.navigationNamePath,
      userInterface: navigation.userInterface,
      rootTree: navigation.rootTree,
      viewPath: navigation.viewPath,

      // Loading states
      isLoadingInterface: navigation.isLoadingInterface,
      isLoading: navigation.isLoading,

      // Selection state
      selectedNode: navigation.selectedNode,
      selectedEdge: navigation.selectedEdge,

      // Dialog states
      isNodeDialogOpen: navigation.isNodeDialogOpen,
      isEdgeDialogOpen: navigation.isEdgeDialogOpen,
      isDiscardDialogOpen: navigation.isDiscardDialogOpen,

      // Form states
      isNewNode: navigation.isNewNode,
      nodeForm: navigation.nodeForm,
      edgeForm: navigation.edgeForm,

      // Error and success states
      error: navigation.error,
      success: navigation.success,
      hasUnsavedChanges: navigation.hasUnsavedChanges,

      // Focus and filtering
      focusNodeId: navigation.focusNodeId,
      maxDisplayDepth: navigation.maxDisplayDepth,
      availableFocusNodes: navigation.availableFocusNodes,

      // React Flow refs and state
      reactFlowWrapper: navigation.reactFlowWrapper,
      reactFlowInstance: navigation.reactFlowInstance,
      pendingConnection: null, // Not used in unified context

      // Setters (maintain compatibility)
      setNodes: navigation.setNodes,
      setEdges: navigation.setEdges,
      setHasUnsavedChanges: navigation.setHasUnsavedChanges,
      setTreeName: navigation.setCurrentTreeName,
      setIsLoadingInterface: navigation.setIsLoadingInterface,
      setSelectedNode: navigation.setSelectedNode,
      setSelectedEdge: navigation.setSelectedEdge,
      setIsNodeDialogOpen: navigation.setIsNodeDialogOpen,
      setIsEdgeDialogOpen: navigation.setIsEdgeDialogOpen,
      setIsNewNode: navigation.setIsNewNode,
      setNodeForm: navigation.setNodeForm,
      setEdgeForm: navigation.setEdgeForm,
      setIsLoading: navigation.setIsLoading,
      setError: navigation.setError,
      setSuccess: navigation.setSuccess,
      setPendingConnection: () => {}, // Not used
      setReactFlowInstance: navigation.setReactFlowInstance,
      setIsDiscardDialogOpen: navigation.setIsDiscardDialogOpen,

      // Event handlers
      onNodesChange: navigation.onNodesChange,
      onEdgesChange: navigation.onEdgesChange,
      onConnect,
      onNodeClick,
      onEdgeClick,
      onNodeDoubleClick,
      onPaneClick,

      // Focus management
      setFocusNode: navigation.setFocusNodeId,
      setDisplayDepth: navigation.setMaxDisplayDepth,
      resetFocus: () => {
        navigation.setFocusNodeId(null);
        navigation.setMaxDisplayDepth(5);
      },
      isNodeDescendantOf: () => false, // Not implemented in unified context

      // New normalized API operations
      loadTreeData,
      loadTreeByUserInterface,
      
      // Centralized save methods from NavigationContext
      saveNodeWithStateUpdate: navigation.saveNodeWithStateUpdate,
      saveEdgeWithStateUpdate: navigation.saveEdgeWithStateUpdate,
      saveTreeWithStateUpdate: navigation.saveTreeWithStateUpdate,



      // Interface operations
      listAvailableTrees: async () => {
        try {
          return await api.get(buildServerUrl('/server/userinterface/getAllUserInterfaces'));
        } catch (error) {
          console.error('Error fetching user interfaces:', error);
          return [];
        }
      },

      // Lock management - from NavigationContext
      isLocked: navigation.isLocked,
      lockNavigationTree: navigation.lockNavigationTree,
      unlockNavigationTree: navigation.unlockNavigationTree,

      // Node/Edge management actions
      handleNodeFormSubmit,
      handleEdgeFormSubmit,
      handleDeleteNode: deleteSelected,
      handleDeleteEdge: deleteSelected,
      addNewNode,
      cancelNodeChanges,
      closeSelectionPanel,
      deleteSelected,
      resetNode,

      // Additional actions
      discardChanges,
      performDiscardChanges,
      fitView,

      // Navigation actions
      navigateToTreeLevel: () => {}, // Not implemented
      goBackToParent: navigateToParent,
      navigateToParentView: navigateToParent,
      navigateToParent,

      // Configuration
      defaultEdgeOptions: {
        type: 'navigation',
        animated: false,
        style: { strokeWidth: 2, stroke: '#b1b1b7' },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          width: 20,
          height: 20,
          color: '#b1b1b7',
        },
      },

      // Connection rules
      getConnectionRulesSummary: () => 'No specific connection rules defined',

      // User interface management
      setUserInterfaceFromProps,

      // Device control state - from HostControl
      selectedHost: hostControl.selectedHost,
      isControlActive: hostControl.isControlActive,
      isRemotePanelOpen: hostControl.isRemotePanelOpen,
      showRemotePanel: hostControl.showRemotePanel,
      showAVPanel: hostControl.showAVPanel,
      isVerificationActive: false, // Not implemented

      // Device control handlers - from HostControl
      handleDeviceSelect: hostControl.handleDeviceSelect,
      handleControlStateChange: hostControl.handleControlStateChange,
      handleToggleRemotePanel: hostControl.handleToggleRemotePanel,
      handleConnectionChange: () => {}, // Not implemented
      handleDisconnectComplete: hostControl.handleDisconnectComplete,

      // Host data - from HostData (filtered by userInterface models)
      availableHosts: hostData.getHostsByModel(navigation.userInterface?.models || []),
      getHostByName: hostData.getHostByName,

      // Confirmation dialog state and handlers
      confirmDialogState: dialogState,
      confirmDialogHandleConfirm: handleConfirm,
      confirmDialogHandleCancel: handleCancel,
    }),
    [
      navigation,
      navigationConfig,
      hostData,
      hostControl,
      loadTreeData,
      onConnect,
      onNodeClick,
      onEdgeClick,
      onNodeDoubleClick,
      onPaneClick,
      handleNodeFormSubmit,
      handleEdgeFormSubmit,
      addNewNode,
      cancelNodeChanges,
      closeSelectionPanel,
      deleteSelected,
      resetNode,
      discardChanges,
      performDiscardChanges,
      fitView,
      navigateToParent,
      setUserInterfaceFromProps,
      dialogState,
      handleConfirm,
      handleCancel,
    ],
  );
};
