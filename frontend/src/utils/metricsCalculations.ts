/**
 * Metrics Calculations Utilities
 * Functions for calculating confidence levels and processing metrics data
 */

import {
  RawNodeMetrics,
  RawEdgeMetrics,
  NodeMetricData,
  EdgeMetricData,
  LowConfidenceItem,
  LowConfidenceItems,
  CONFIDENCE_THRESHOLDS,
  MetricsNotificationData,
} from '../types/navigation/Metrics_Types';
import { UINavigationNode, UINavigationEdge } from '../types/pages/Navigation_Types';

/**
 * Calculate confidence based on volume and success rate
 * Your requirements: volume + test success = confidence
 */
export const calculateConfidence = (
  totalExecutions: number,
  successRate: number,
): number => {
  // Volume weight: reaches 1.0 at 10 executions, caps at 1.0
  const volumeWeight = Math.min(totalExecutions / 10, 1.0);
  
  // Success rate weight: direct mapping 0.0-1.0
  const successWeight = successRate;
  
  // Combined confidence: 25% volume importance, 75% success importance
  const confidence = (volumeWeight * 0.25) + (successWeight * 0.75);
  
  return Math.min(confidence, 1.0); // Cap at 1.0
};

/**
 * Determine confidence level from confidence score
 */
export const getConfidenceLevel = (confidence: number): 'high' | 'medium' | 'low' => {
  if (confidence >= CONFIDENCE_THRESHOLDS.HIGH) return 'high';
  if (confidence >= CONFIDENCE_THRESHOLDS.MEDIUM) return 'medium';
  return 'low';
};

/**
 * Convert confidence (0.0-1.0) to integer 0-5 score.
 */
export const getConfidenceScore = (confidence: number): number => {
  return Math.max(0, Math.min(5, Math.round(confidence * 5)));
};

/**
 * Convert raw node metrics to processed NodeMetricData.
 * Node measurement is verify_node duration.
 */
export const processNodeMetrics = (rawMetrics: RawNodeMetrics): NodeMetricData => {
  const confidence = calculateConfidence(rawMetrics.total_executions, rawMetrics.success_rate);

  return {
    id: rawMetrics.node_id,
    volume: rawMetrics.total_executions,
    success_rate: rawMetrics.success_rate,
    avg_verification_time: rawMetrics.avg_verification_time_ms,
    confidence,
    confidence_level: getConfidenceLevel(confidence),
  };
};

/**
 * Convert raw edge metrics to processed EdgeMetricData.
 * Edge measurement is action time (action calls + final_wait).
 */
export const processEdgeMetrics = (rawMetrics: RawEdgeMetrics): EdgeMetricData => {
  const confidence = calculateConfidence(rawMetrics.total_executions, rawMetrics.success_rate);

  return {
    id: rawMetrics.edge_id,
    volume: rawMetrics.total_executions,
    success_rate: rawMetrics.success_rate,
    avg_action_time: rawMetrics.avg_action_time_ms,
    confidence,
    confidence_level: getConfidenceLevel(confidence),
  };
};

/**
 * Calculate global confidence from all metrics
 */
export const calculateGlobalConfidence = (
  nodeMetrics: Map<string, NodeMetricData>,
  edgeMetrics: Map<string, EdgeMetricData>,
): number => {
  const allMetrics = [...nodeMetrics.values(), ...edgeMetrics.values()];
  
  if (allMetrics.length === 0) return 0;
  
  // Weighted average based on execution volume
  let totalWeightedConfidence = 0;
  let totalWeight = 0;
  
  for (const metric of allMetrics) {
    const weight = Math.max(metric.volume, 1); // Minimum weight of 1
    totalWeightedConfidence += metric.confidence * weight;
    totalWeight += weight;
  }
  
  return totalWeight > 0 ? totalWeightedConfidence / totalWeight : 0;
};

/**
 * Get low confidence items for modal display
 */
export const getLowConfidenceItems = (
  nodeMetrics: Map<string, NodeMetricData>,
  edgeMetrics: Map<string, EdgeMetricData>,
  nodes: UINavigationNode[],
  edges: UINavigationEdge[],
  threshold: number = CONFIDENCE_THRESHOLDS.MEDIUM,
): LowConfidenceItems => {
  const lowConfidenceNodes: LowConfidenceItem[] = [];
  const lowConfidenceEdges: LowConfidenceItem[] = [];

  // Process nodes — node measurement is verify_node duration.
  for (const [nodeId, metrics] of nodeMetrics.entries()) {
    if (metrics.confidence < threshold) {
      const node = nodes.find(n => n.id === nodeId);
      if (node) {
        lowConfidenceNodes.push({
          id: nodeId,
          type: 'node',
          label: node.data.label,
          confidence: metrics.confidence,
          confidence_score: getConfidenceScore(metrics.confidence),
          volume: metrics.volume,
          success_rate: metrics.success_rate,
          avg_execution_time: metrics.avg_verification_time,
        });
      }
    }
  }

  // Process edges — edge measurement is action time (action calls + final_wait).
  for (const [edgeKey, metrics] of edgeMetrics.entries()) {
    if (metrics.confidence < threshold) {
      // Extract edge_id from compound key (format: edge_id#action_set_id)
      const edgeId = edgeKey.includes('#') ? edgeKey.split('#')[0] : edgeKey;
      const actionSetId = edgeKey.includes('#') ? edgeKey.split('#')[1] : null;

      const edge = edges.find(e => e.id === edgeId);
      if (edge) {
        const sourceNode = nodes.find(n => n.id === edge.source);
        const targetNode = nodes.find(n => n.id === edge.target);
        const edgeLabel = edge.label ||
          `${sourceNode?.data.label || 'Unknown'} → ${targetNode?.data.label || 'Unknown'}`;
        const fullLabel = actionSetId ? `${edgeLabel} [${actionSetId}]` : edgeLabel;

        lowConfidenceEdges.push({
          id: edgeKey,
          type: 'edge',
          label: fullLabel,
          confidence: metrics.confidence,
          confidence_score: getConfidenceScore(metrics.confidence),
          volume: metrics.volume,
          success_rate: metrics.success_rate,
          avg_execution_time: metrics.avg_action_time,
        });
      }
    }
  }
  
  // Sort by confidence (lowest first)
  lowConfidenceNodes.sort((a, b) => a.confidence - b.confidence);
  lowConfidenceEdges.sort((a, b) => a.confidence - b.confidence);
  
  return {
    nodes: lowConfidenceNodes,
    edges: lowConfidenceEdges,
    total_count: lowConfidenceNodes.length + lowConfidenceEdges.length,
  };
};

/**
 * Generate notification data based on global confidence and metrics
 */
export const generateNotificationData = (
  globalConfidence: number,
  lowConfidenceCount: number,
  nodeMetrics?: Map<string, NodeMetricData>,
  edgeMetrics?: Map<string, EdgeMetricData>,
): MetricsNotificationData => {
  // Calculate global success rate from all metrics
  const allMetrics = [...(nodeMetrics?.values() || []), ...(edgeMetrics?.values() || [])];
  const metricsWithData = allMetrics.filter(m => m.volume > 0);
  
  let globalSuccessRate = 0;
  let totalVolume = 0;
  if (metricsWithData.length > 0) {
    const totalWeightedSuccess = metricsWithData.reduce((sum, m) => sum + (m.success_rate * m.volume), 0);
    totalVolume = metricsWithData.reduce((sum, m) => sum + m.volume, 0);
    globalSuccessRate = totalVolume > 0 ? totalWeightedSuccess / totalVolume : 0;
  }
  
  // Calculate confidence distribution
  const confidenceDistribution = {
    high: allMetrics.filter(m => m.confidence >= 0.85).length,
    medium: allMetrics.filter(m => m.confidence >= 0.65 && m.confidence < 0.85).length,
    low: allMetrics.filter(m => m.confidence < 0.65 && m.volume > 0).length,
    untested: allMetrics.filter(m => m.volume === 0).length,
  };
  
  // Don't show notification if there are no metrics at all (0.0% with 0 items)
  if (globalConfidence === 0 && lowConfidenceCount === 0) {
    return {
      show: false,
      severity: 'info',
      message: '',
      global_confidence: globalConfidence,
      low_confidence_count: lowConfidenceCount,
      global_success_rate: globalSuccessRate,
      total_items: allMetrics.length,
      total_volume: totalVolume,
      confidence_distribution: confidenceDistribution,
    };
  }
  
  const confidenceScore = Math.round(globalConfidence * 10); // Convert to 0-10 scale, whole number

  // No notification if global confidence is in HIGH band (>=0.85)
  if (globalConfidence >= CONFIDENCE_THRESHOLDS.HIGH) {
    return {
      show: false,
      severity: 'success',
      message: '',
      global_confidence: globalConfidence,
      low_confidence_count: lowConfidenceCount,
      global_success_rate: globalSuccessRate,
      total_items: allMetrics.length,
      total_volume: totalVolume,
      confidence_distribution: confidenceDistribution,
    };
  }
  const successRatePercent = (globalSuccessRate * 100).toFixed(0);

  // Error notification when global confidence is in LOW band (<0.65)
  if (globalConfidence < CONFIDENCE_THRESHOLDS.MEDIUM && lowConfidenceCount > 0) {
    return {
      show: true,
      severity: 'error',
      message: `Confidence Score: ${confidenceScore}/10 • Success Rate: ${successRatePercent}% • ${lowConfidenceCount} items need attention`,
      global_confidence: globalConfidence,
      low_confidence_count: lowConfidenceCount,
      global_success_rate: globalSuccessRate,
      total_items: allMetrics.length,
      total_volume: totalVolume,
      confidence_distribution: confidenceDistribution,
    };
  }

  // Warning notification for MEDIUM band (0.65-0.85)
  if (globalConfidence < CONFIDENCE_THRESHOLDS.HIGH && lowConfidenceCount > 0) {
    return {
      show: true,
      severity: 'warning',
      message: `Confidence Score: ${confidenceScore}/10 • Success Rate: ${successRatePercent}% • ${lowConfidenceCount} items could be improved`,
      global_confidence: globalConfidence,
      low_confidence_count: lowConfidenceCount,
      global_success_rate: globalSuccessRate,
      total_items: allMetrics.length,
      total_volume: totalVolume,
      confidence_distribution: confidenceDistribution,
    };
  }
  
  // No notification needed - good confidence or no problematic items
  return {
    show: false,
    severity: 'success',
    message: '',
    global_confidence: globalConfidence,
    low_confidence_count: lowConfidenceCount,
    global_success_rate: globalSuccessRate,
    total_items: allMetrics.length,
    total_volume: totalVolume,
    confidence_distribution: confidenceDistribution,
  };
};

/**
 * Format execution time for display
 */
export const formatExecutionTime = (timeMs: number): string => {
  if (timeMs < 1000) return `${timeMs}ms`;
  if (timeMs < 60000) return `${(timeMs / 1000).toFixed(1)}s`;
  return `${(timeMs / 60000).toFixed(1)}m`;
};

/**
 * Format success rate for display
 */
export const formatSuccessRate = (rate: number): string => {
  return `${(rate * 100).toFixed(1)}%`;
};

/**
 * Get confidence color for UI elements
 */
export const getConfidenceColor = (confidence: number): string => {
  if (confidence >= CONFIDENCE_THRESHOLDS.HIGH) return '#4caf50'; // Green
  if (confidence >= CONFIDENCE_THRESHOLDS.MEDIUM) return '#ff9800'; // Orange
  return '#f44336'; // Red
};
