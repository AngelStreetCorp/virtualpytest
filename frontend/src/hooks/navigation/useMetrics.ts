/**
 * Navigation Metrics Hook
 * Fetches and manages database-driven confidence metrics for nodes and edges
 */

import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  EdgeMetricData,
  NodeMetricData,
  TreeMetrics,
  LowConfidenceItems,
  MetricsNotificationData,
} from '../../types/navigation/Metrics_Types';
import { UINavigationNode, UINavigationEdge } from '../../types/pages/Navigation_Types';
import {
  calculateGlobalConfidence,
  getLowConfidenceItems,
  generateNotificationData,
} from '../../utils/metricsCalculations';
import { api } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';

const CONFIDENCE_HIGH_THRESHOLD = 0.7;
const CONFIDENCE_MEDIUM_THRESHOLD = 0.49;

export interface UseMetricsProps {
  treeId?: string | null;
  nodes?: UINavigationNode[];
  edges?: UINavigationEdge[];
  enabled?: boolean; // Allow disabling metrics fetching
  preloadedMetrics?: any; // Metrics already loaded from combined endpoint
}

export const useMetrics = (props?: UseMetricsProps) => {
  const { treeId, nodes = [], edges = [], enabled = true, preloadedMetrics = null } = props || {};

  // State
  // Distinct types per side: nodes carry verify time, edges carry action time + KPI.
  const [nodeMetrics, setNodeMetrics] = useState<Map<string, NodeMetricData>>(new Map());
  const [edgeMetrics, setEdgeMetrics] = useState<Map<string, EdgeMetricData>>(new Map());
  const [treeMetrics, setTreeMetrics] = useState<TreeMetrics | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastFetchedTreeId, setLastFetchedTreeId] = useState<string | null>(null);

  /**
   * Fetch metrics from backend API
   */
  const fetchMetrics = useCallback(async (targetTreeId: string) => {
    if (!targetTreeId || !enabled) return;

    setIsLoading(true);
    setError(null);

    try {
      console.log(`[@useMetrics] Fetching metrics for tree: ${targetTreeId}`);
      
      const data = await api.get(buildServerUrl(`/server/metrics/tree/${targetTreeId}`));

      if (!data.success) {
        throw new Error(data.error || 'Failed to fetch metrics');
      }

      console.log(`[@useMetrics] Received metrics:`, {
        nodeCount: Object.keys(data.nodes || {}).length,
        edgeCount: Object.keys(data.edges || {}).length,
        globalConfidence: data.global_confidence || 0,
        distribution: data.confidence_distribution || {},
        hierarchyInfo: data.hierarchy_info || null
      });
      
      // Log hierarchy information if present
      if (data.hierarchy_info) {
        console.log(`[@useMetrics] Hierarchy: ${data.hierarchy_info.total_trees} trees, max depth: ${data.hierarchy_info.max_depth}, nested: ${data.hierarchy_info.has_nested_trees}`);
        if (data.hierarchy_info.trees) {
          data.hierarchy_info.trees.forEach((tree: any) => {
            console.log(`[@useMetrics] - Tree: ${tree.name} (depth: ${tree.depth}, root: ${tree.is_root})`);
          });
        }
      }

      // Convert backend format to frontend node/edge types.
      const processedNodeMetrics = new Map<string, NodeMetricData>();
      if (data.nodes) {
        for (const [nodeId, nodeMetric] of Object.entries(data.nodes)) {
          const metric = nodeMetric as any;
          processedNodeMetrics.set(nodeId, {
            id: nodeId,
            volume: metric.volume,
            success_rate: metric.success_rate,
            avg_verification_time: metric.avg_verification_time,
            confidence: metric.confidence,
            confidence_level: metric.confidence >= CONFIDENCE_HIGH_THRESHOLD ? 'high' : metric.confidence >= CONFIDENCE_MEDIUM_THRESHOLD ? 'medium' : 'low'
          });
        }
      }

      const processedEdgeMetrics = new Map<string, EdgeMetricData>();
      if (data.edges) {
        for (const [edgeId, edgeMetric] of Object.entries(data.edges)) {
          const metric = edgeMetric as any;
          processedEdgeMetrics.set(edgeId, {
            id: edgeId,
            volume: metric.volume,
            success_rate: metric.success_rate,
            avg_action_time: metric.avg_action_time,
            avg_kpi_ms: metric.avg_kpi_ms,
            kpi_volume: metric.kpi_volume,
            kpi_report_url: metric.kpi_report_url ?? null,
            confidence: metric.confidence,
            confidence_level: metric.confidence >= CONFIDENCE_HIGH_THRESHOLD ? 'high' : metric.confidence >= CONFIDENCE_MEDIUM_THRESHOLD ? 'medium' : 'low'
          });
        }
      }

      // Update state
      setNodeMetrics(processedNodeMetrics);
      setEdgeMetrics(processedEdgeMetrics);
      
      // Set tree metrics from backend global confidence
      const treeMetrics = data.global_confidence !== undefined ? {
        tree_id: targetTreeId,
        global_confidence: data.global_confidence,
        confidence_distribution: data.confidence_distribution || {
          high: 0,
          medium: 0,
          low: 0,
          untested: 0
        },
        total_nodes: Object.keys(data.nodes || {}).length,
        total_edges: Object.keys(data.edges || {}).length,
        nodes_with_metrics: Object.values(data.nodes || {}).filter((n: any) => n.volume > 0).length,
        edges_with_metrics: Object.values(data.edges || {}).filter((e: any) => e.volume > 0).length
      } : null;
      
      setTreeMetrics(treeMetrics);
      setLastFetchedTreeId(targetTreeId);

      console.log(`[@useMetrics] Metrics processed successfully for tree: ${targetTreeId}`);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Unknown error';
      console.error(`[@useMetrics] Failed to fetch metrics:`, errorMessage);
      setError(errorMessage);
      
      // Clear metrics on error
      setNodeMetrics(new Map());
      setEdgeMetrics(new Map());
      setTreeMetrics(null);
    } finally {
      setIsLoading(false);
    }
  }, [enabled]);

  /**
   * Process preloaded metrics (from combined tree endpoint)
   */
  useEffect(() => {
    if (preloadedMetrics && treeId) {
      console.log(`[@useMetrics] Using preloaded metrics from combined endpoint for tree: ${treeId}`);
      
      const processedNodeMetrics = new Map<string, NodeMetricData>();
      if (preloadedMetrics.nodes) {
        for (const [nodeId, nodeMetric] of Object.entries(preloadedMetrics.nodes)) {
          const metric = nodeMetric as any;
          processedNodeMetrics.set(nodeId, {
            id: nodeId,
            volume: metric.volume,
            success_rate: metric.success_rate,
            avg_verification_time: metric.avg_verification_time,
            confidence: metric.confidence,
            confidence_level: metric.confidence >= CONFIDENCE_HIGH_THRESHOLD ? 'high' : metric.confidence >= CONFIDENCE_MEDIUM_THRESHOLD ? 'medium' : 'low'
          });
        }
      }

      const processedEdgeMetrics = new Map<string, EdgeMetricData>();
      if (preloadedMetrics.edges) {
        for (const [edgeKey, edgeMetric] of Object.entries(preloadedMetrics.edges)) {
          const metric = edgeMetric as any;
          processedEdgeMetrics.set(edgeKey, {
            id: edgeKey,
            volume: metric.volume,
            success_rate: metric.success_rate,
            avg_action_time: metric.avg_action_time,
            avg_kpi_ms: metric.avg_kpi_ms,
            kpi_volume: metric.kpi_volume,
            kpi_report_url: metric.kpi_report_url ?? null,
            confidence: metric.confidence,
            confidence_level: metric.confidence >= CONFIDENCE_HIGH_THRESHOLD ? 'high' : metric.confidence >= CONFIDENCE_MEDIUM_THRESHOLD ? 'medium' : 'low'
          });
        }
      }

      setNodeMetrics(processedNodeMetrics);
      setEdgeMetrics(processedEdgeMetrics);
      setTreeMetrics({
        tree_id: treeId,
        global_confidence: preloadedMetrics.global_confidence || 0,
        confidence_distribution: preloadedMetrics.confidence_distribution || {
          high: 0, medium: 0, low: 0, untested: 0
        },
        total_nodes: processedNodeMetrics.size,
        total_edges: processedEdgeMetrics.size,
        nodes_with_metrics: Array.from(processedNodeMetrics.values()).filter(m => m.volume > 0).length,
        edges_with_metrics: Array.from(processedEdgeMetrics.values()).filter(m => m.volume > 0).length
      });
      setLastFetchedTreeId(treeId); // Mark as fetched to prevent auto-fetch
      setIsLoading(false);
      setError(null);
    }
  }, [preloadedMetrics, treeId]);

  /**
   * Calculate global confidence from current metrics
   */
  const globalConfidence = useMemo(() => {
    if (treeMetrics?.global_confidence !== undefined) {
      return treeMetrics.global_confidence;
    }
    
    // Fallback: calculate from current metrics
    return calculateGlobalConfidence(nodeMetrics, edgeMetrics);
  }, [nodeMetrics, edgeMetrics, treeMetrics]);

  /**
   * Get low confidence items for modal display
   */
  const lowConfidenceItems = useMemo((): LowConfidenceItems => {
    return getLowConfidenceItems(nodeMetrics, edgeMetrics, nodes, edges);
  }, [nodeMetrics, edgeMetrics, nodes, edges]);

  /**
   * Generate notification data
   */
  const notificationData = useMemo((): MetricsNotificationData => {
    return generateNotificationData(globalConfidence, lowConfidenceItems.total_count, nodeMetrics, edgeMetrics);
  }, [globalConfidence, lowConfidenceItems.total_count, nodeMetrics, edgeMetrics]);

  /**
   * Get metrics for a specific node
   */
  const getNodeMetrics = useCallback((nodeId: string): NodeMetricData | null => {
    return nodeMetrics.get(nodeId) || null;
  }, [nodeMetrics]);

  /**
   * Get metrics for a specific edge (legacy - returns first found direction)
   */
  const getEdgeMetrics = useCallback((edgeId: string): EdgeMetricData | null => {
    // First try direct lookup (legacy)
    const directMetric = edgeMetrics.get(edgeId);
    if (directMetric) return directMetric;

    // Then try direction-specific lookup (find first matching direction)
    for (const [key, metric] of edgeMetrics.entries()) {
      if (key.startsWith(`${edgeId}#`)) {
        return metric;
      }
    }

    return null;
  }, [edgeMetrics]);

  /**
   * Get metrics for a specific edge direction (edge_id + action_set_id)
   */
  const getEdgeDirectionMetrics = useCallback((edgeId: string, actionSetId: string): EdgeMetricData | null => {
    const key = `${edgeId}#${actionSetId}`;
    return edgeMetrics.get(key) || null;
  }, [edgeMetrics]);

  /**
   * Get all direction metrics for an edge
   */
  const getAllEdgeDirectionMetrics = useCallback((edgeId: string): Map<string, EdgeMetricData> => {
    const directionMetrics = new Map<string, EdgeMetricData>();

    for (const [key, metric] of edgeMetrics.entries()) {
      if (key.startsWith(`${edgeId}#`)) {
        const actionSetId = key.split('#')[1];
        directionMetrics.set(actionSetId, metric);
      }
    }

    return directionMetrics;
  }, [edgeMetrics]);

  /**
   * Check if metrics are available for a node
   */
  const hasNodeMetrics = useCallback((nodeId: string): boolean => {
    return nodeMetrics.has(nodeId);
  }, [nodeMetrics]);

  /**
   * Check if metrics are available for an edge
   */
  const hasEdgeMetrics = useCallback((edgeId: string): boolean => {
    return edgeMetrics.has(edgeId);
  }, [edgeMetrics]);

  /**
   * Refresh metrics for current tree
   */
  const refreshMetrics = useCallback(() => {
    if (treeId) {
      fetchMetrics(treeId);
    }
  }, [treeId, fetchMetrics]);

  /**
   * Clear all metrics data
   */
  const clearMetrics = useCallback(() => {
    setNodeMetrics(new Map());
    setEdgeMetrics(new Map());
    setTreeMetrics(null);
    setError(null);
    setLastFetchedTreeId(null);
  }, []);

  /**
   * Get metrics summary for debugging
   */
  const getMetricsSummary = useCallback(() => {
    return {
      treeId: lastFetchedTreeId,
      nodeMetricsCount: nodeMetrics.size,
      edgeMetricsCount: edgeMetrics.size,
      globalConfidence,
      lowConfidenceCount: lowConfidenceItems.total_count,
      isLoading,
      error,
    };
  }, [
    lastFetchedTreeId,
    nodeMetrics.size,
    edgeMetrics.size,
    globalConfidence,
    lowConfidenceItems.total_count,
    isLoading,
    error,
  ]);

  return {
    // Core metrics data
    nodeMetrics,
    edgeMetrics,
    treeMetrics,
    globalConfidence,
    lowConfidenceItems,
    notificationData,

    // State
    isLoading,
    error,
    lastFetchedTreeId,

    // Getter functions
    getNodeMetrics,
    getEdgeMetrics,
    getEdgeDirectionMetrics,
    getAllEdgeDirectionMetrics,
    hasNodeMetrics,
    hasEdgeMetrics,

    // Actions
    fetchMetrics,
    refreshMetrics,
    clearMetrics,

    // Utilities
    getMetricsSummary,
  };
};
