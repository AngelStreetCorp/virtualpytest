/**
 * Auto-layout utility using dagre for React Flow nodes
 * Calculates optimal positioning for test case flow graphs
 */

import dagre from 'dagre';
import { Node, Edge } from 'reactflow';

export interface LayoutOptions {
  direction?: 'TB' | 'LR' | 'BT' | 'RL'; // Top-Bottom, Left-Right, etc.
  nodeWidth?: number;
  nodeHeight?: number;
  rankSeparation?: number; // Vertical spacing between ranks
  nodeSeparation?: number; // Horizontal spacing between nodes
}

const DEFAULT_OPTIONS: Required<LayoutOptions> = {
  direction: 'TB',
  nodeWidth: 250,
  nodeHeight: 100,
  rankSeparation: 100,
  nodeSeparation: 80,
};

/**
 * Calculates optimal layout positions for nodes using dagre algorithm
 * @param nodes - React Flow nodes to layout
 * @param edges - React Flow edges defining connections
 * @param options - Layout configuration options
 * @returns Object with layouted nodes and original edges
 */
export const getLayoutedElements = (
  nodes: Node[],
  edges: Edge[],
  options: LayoutOptions = {}
): { nodes: Node[]; edges: Edge[] } => {
  const opts = { ...DEFAULT_OPTIONS, ...options };

  // Create dagre graph
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  dagreGraph.setGraph({
    rankdir: opts.direction,
    ranksep: opts.rankSeparation,
    nodesep: opts.nodeSeparation,
  });

  // Add nodes to dagre graph
  nodes.forEach((node) => {
    dagreGraph.setNode(node.id, {
      width: opts.nodeWidth,
      height: opts.nodeHeight,
    });
  });

  // Add edges to dagre graph
  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  // Calculate layout
  dagre.layout(dagreGraph);

  // Apply calculated positions to React Flow nodes
  const layoutedNodes = nodes.map((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);
    
    return {
      ...node,
      position: {
        x: nodeWithPosition.x - opts.nodeWidth / 2,
        y: nodeWithPosition.y - opts.nodeHeight / 2,
      },
    };
  });

  return {
    nodes: layoutedNodes,
    edges,
  };
};

/**
 * Quick layout helper with common presets
 */
export const layoutPresets = {
  /** Vertical flow (top to bottom) - default */
  vertical: (nodes: Node[], edges: Edge[]) =>
    getLayoutedElements(nodes, edges, { direction: 'TB' }),

  /** Horizontal flow (left to right) */
  horizontal: (nodes: Node[], edges: Edge[]) =>
    getLayoutedElements(nodes, edges, { direction: 'LR' }),

  /** Compact layout - reduced spacing */
  compact: (nodes: Node[], edges: Edge[]) =>
    getLayoutedElements(nodes, edges, {
      rankSeparation: 60,
      nodeSeparation: 50,
    }),

  /** Wide layout - increased spacing */
  wide: (nodes: Node[], edges: Edge[]) =>
    getLayoutedElements(nodes, edges, {
      rankSeparation: 150,
      nodeSeparation: 120,
    }),
};

