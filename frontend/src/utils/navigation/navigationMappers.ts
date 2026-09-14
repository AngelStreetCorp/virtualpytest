/**
 * Node and edge mapping utilities for navigation editor.
 * Converts between backend (API) format and frontend (ReactFlow) format.
 */

/** Backend node shape (from API) */
export interface BackendNode {
  node_id: string;
  node_type?: string;
  position_x: number;
  position_y: number;
  label: string;
  description?: string;
  verifications?: any[];
  // Per-variant model: top-level boolean flagging variant-only rows.
  hidden_in_base?: boolean;
  data?: Record<string, unknown>;
}

/** Backend edge shape (from API) */
export interface BackendEdge {
  edge_id: string;
  source_node_id: string;
  target_node_id: string;
  label?: string;
  action_sets?: any[];
  default_action_set_id?: string;
  // final_wait_time + threshold live per-direction on each action_set entry.
  // Per-variant model: top-level boolean flagging variant-only edges.
  hidden_in_base?: boolean;
  data?: Record<string, unknown>;
}

/** Frontend node shape (ReactFlow) */
export interface FrontendNode {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: Record<string, unknown>;
}

/** Frontend edge shape (ReactFlow) */
export interface FrontendEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  label?: string;
  sourceHandle?: string;
  targetHandle?: string;
  style?: { stroke: string; strokeWidth: number };
  markerEnd?: { type: 'arrowclosed'; color: string };
  data: Record<string, unknown>;
}

const CONDITIONAL_STYLE = { stroke: '#2196f3', strokeWidth: 2 };
const DEFAULT_STYLE = { stroke: '#555', strokeWidth: 2 };
const CONDITIONAL_MARKER = { type: 'arrowclosed' as const, color: '#2196f3' };
const DEFAULT_MARKER = { type: 'arrowclosed' as const, color: '#555' };

/** Map backend node to frontend ReactFlow format */
export function mapNodeToFrontend(node: BackendNode): FrontendNode {
  return {
    id: node.node_id,
    type: node.node_type || 'screen',
    position: { x: node.position_x, y: node.position_y },
    data: {
      label: node.label,
      type: node.node_type || 'screen',
      description: node.description,
      verifications: node.verifications,
      // Per-variant model: hidden_in_base flag on base data.
      hidden_in_base: node.hidden_in_base === true,
      ...node.data,
    },
  };
}

/** Map backend edge to frontend ReactFlow format */
export function mapEdgeToFrontend(edge: BackendEdge): FrontendEdge {
  const isConditional = !!(edge.data?.is_conditional || edge.data?.is_conditional_primary);
  return {
    id: edge.edge_id,
    source: edge.source_node_id,
    target: edge.target_node_id,
    type: 'navigation',
    label: edge.label,
    sourceHandle: edge.data?.sourceHandle as string | undefined,
    targetHandle: edge.data?.targetHandle as string | undefined,
    style: isConditional ? CONDITIONAL_STYLE : DEFAULT_STYLE,
    markerEnd: isConditional ? CONDITIONAL_MARKER : DEFAULT_MARKER,
    data: {
      action_sets: edge.action_sets,
      default_action_set_id: edge.default_action_set_id,
      // Per-variant model: hidden_in_base flag on base data.
      hidden_in_base: edge.hidden_in_base === true,
      ...edge.data,
    },
  };
}

/** Map array of backend nodes to frontend format */
export function mapNodesToFrontend(nodes: BackendNode[]): FrontendNode[] {
  return nodes.map(mapNodeToFrontend);
}

/** Map array of backend edges to frontend format */
export function mapEdgesToFrontend(edges: BackendEdge[]): FrontendEdge[] {
  return edges.map(mapEdgeToFrontend);
}
