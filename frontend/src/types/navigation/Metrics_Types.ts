/**
 * Navigation Metrics Types
 * Type definitions for database-driven confidence metrics
 */

// Raw metrics data from database
export interface RawNodeMetrics {
  node_id: string;
  tree_id: string;
  team_id: string;
  total_executions: number;
  successful_executions: number;
  success_rate: number; // decimal 0.0-1.0
  avg_verification_time_ms: number; // verify_node duration
  created_at: string;
  updated_at: string;
}

export interface RawEdgeMetrics {
  edge_id: string;
  tree_id: string;
  team_id: string;
  total_executions: number;
  successful_executions: number;
  success_rate: number; // decimal 0.0-1.0
  avg_action_time_ms: number; // action calls + final_wait, no verification
  created_at: string;
  updated_at: string;
}

// Shared metric fields — common to edges and nodes.
export interface MetricCommon {
  id: string;
  volume: number; // total_executions
  success_rate: number; // 0.0-1.0
  confidence: number; // calculated confidence 0.0-1.0
  confidence_level: 'high' | 'medium' | 'low';
}

// Edge metric: average traversal time (action + final_wait, never verification).
// + KPI fields (pixel-perfect on-screen time).
export interface EdgeMetricData extends MetricCommon {
  /**
   * Average wall-clock duration of TRAVERSING this edge in ms:
   * action calls (initial + retry) + final_wait_time. Never includes
   * verification time. Combine with the destination node's
   * `avg_verification_time` to get full navigation step time.
   */
  avg_action_time: number;
  avg_kpi_ms?: number;
  kpi_volume?: number;
  /**
   * Latest kpi_report_url for this (edge, action_set, variant). Set by the
   * RPC from the most recent execution_results row that has a report.
   * Used by the Edge Selection panel KPI chip to deep-link.
   */
  kpi_report_url?: string | null;
}

// Node metric: average verify_node duration.
export interface NodeMetricData extends MetricCommon {
  /**
   * Average wall-clock duration of verify_node() calls on this node, in ms.
   * Only updated when verify_node actually ran for a step landing here.
   */
  avg_verification_time: number;
}

// Backward-compat alias for code that doesn't care which kind it is.
// Discriminated as the union; prefer the specific types.
export type MetricData = EdgeMetricData | NodeMetricData;

// Global tree metrics
export interface TreeMetrics {
  tree_id: string;
  total_nodes: number;
  total_edges: number;
  nodes_with_metrics: number;
  edges_with_metrics: number;
  global_confidence: number; // weighted average
  confidence_distribution: {
    high: number; // count of high confidence items
    medium: number; // count of medium confidence items
    low: number; // count of low confidence items
    untested: number; // count of items without metrics
  };
}

// API response types
export interface MetricsApiResponse {
  success: boolean;
  error?: string;
  tree_metrics: TreeMetrics;
  node_metrics: RawNodeMetrics[];
  edge_metrics: RawEdgeMetrics[];
}

// Low confidence items for modal display
export interface LowConfidenceItem {
  id: string;
  type: 'node' | 'edge';
  label: string;
  confidence: number;
  confidence_score: number; // integer 0-5 (Math.round(confidence * 5))
  volume: number;
  success_rate: number;
  avg_execution_time: number;
}

export interface LowConfidenceItems {
  nodes: LowConfidenceItem[];
  edges: LowConfidenceItem[];
  total_count: number;
}

// Confidence thresholds
export const CONFIDENCE_THRESHOLDS = {
  HIGH: 0.85, // >=85% = high confidence (green)
  MEDIUM: 0.65, // 65-85% = medium confidence (orange)
  // <65% = low confidence (red)
} as const;

// Notification severity levels
export type NotificationSeverity = 'error' | 'warning' | 'info' | 'success';

export interface MetricsNotificationData {
  show: boolean;
  severity: NotificationSeverity;
  message: string;
  global_confidence: number;
  low_confidence_count: number;
  // Additional metrics for better display
  global_success_rate?: number;
  total_items?: number;
  total_volume?: number; // Total executions across all items
  confidence_distribution?: {
    high: number;
    medium: number;
    low: number;
    untested: number;
  };
}
