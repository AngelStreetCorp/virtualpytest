import { useCallback } from 'react';

import {
  NODE_TYPE_COLORS,
  EDGE_COLORS,
  HANDLE_COLORS,
  VALIDATION_STATUS_COLORS,
  type NodeType,
  type HandlePosition,
  getValidationStatusFromConfidence,
} from '../../config/validationColors';
import { UINavigationEdge } from '../../types/pages/Navigation_Types';
import { MetricData } from '../../types/navigation/Metrics_Types';

interface NodeColorResult {
  background: string;
  border: string;
  textColor: string;
  badgeColor: string;
  boxShadow?: string;
  className?: string;
}

interface EdgeColorResult {
  stroke: string;
  strokeWidth: number;
  strokeDasharray: string;
  opacity: number;
  className?: string;
}

interface HandleColorResult {
  background: string;
  boxShadow?: string;
  className?: string;
}

export const useValidationColors = (_edges?: UINavigationEdge[]) => {
  // Get node colors with optional metrics override
  const getNodeColors = useCallback((nodeType: NodeType, metrics?: MetricData | null): NodeColorResult => {
    const baseColors = NODE_TYPE_COLORS[nodeType] || NODE_TYPE_COLORS.screen;

    // If no metrics, return base colors
    if (!metrics) {
      return {
        background: baseColors.background,
        border: baseColors.border,
        textColor: baseColors.textColor,
        badgeColor: baseColors.badgeColor,
        // boxShadow removed to eliminate all shadows in nested tree
      };
    }

    // Override border color based on confidence level and volume
    const validationStatus = getValidationStatusFromConfidence(metrics.confidence, metrics.volume);
    const statusColors = VALIDATION_STATUS_COLORS[validationStatus];

    return {
      background: baseColors.background,
      border: statusColors.border, // Override with confidence-based border
      textColor: baseColors.textColor,
      badgeColor: baseColors.badgeColor,
      className: `validation-status-${validationStatus}`,
    };
  }, []);

  // Get edge colors with optional metrics override
  const getEdgeColors = useCallback((_edgeId: string, metrics?: MetricData | null): EdgeColorResult => {
    // If no metrics, return default untested colors
    if (!metrics) {
      return {
        stroke: EDGE_COLORS.untested.stroke,
        strokeWidth: EDGE_COLORS.untested.strokeWidth,
        strokeDasharray: EDGE_COLORS.untested.strokeDasharray,
        opacity: EDGE_COLORS.untested.opacity,
      };
    }

    // Use confidence-based colors
    const validationStatus = getValidationStatusFromConfidence(metrics.confidence, metrics.volume);
    const statusColors = EDGE_COLORS[validationStatus];

    return {
      stroke: statusColors.stroke,
      strokeWidth: statusColors.strokeWidth,
      strokeDasharray: statusColors.strokeDasharray,
      opacity: statusColors.opacity,
      className: `edge-validation-${validationStatus}`,
    };
  }, []);

  // Get handle colors
  const getHandleColors = useCallback((position: HandlePosition): HandleColorResult => {
    const colors = HANDLE_COLORS[position] || HANDLE_COLORS.leftTop;

    return {
      background: colors.untested, // Use untested status as default
      // boxShadow removed to eliminate all shadows in nested tree
    };
  }, []);

  // Simplified functions for navigation feedback (no complex validation tracking)
  const setNavigationEdgesSuccess = useCallback((_transitions: any[]) => {
    // Could implement simple edge highlighting here if needed
    console.log('Navigation successful for transitions:', _transitions.length);
  }, []);

  const setNavigationEdgesFailure = useCallback((_transitions: any[], failedIndex?: number) => {
    // Could implement simple edge highlighting here if needed
    if (failedIndex !== undefined) {
      console.log(`Navigation failed at transition: ${failedIndex + 1} (0-based: ${failedIndex})`);
    } else {
      console.log('Navigation failed (transition index unknown)');
    }
  }, []);

  const resetNavigationEdgeColors = useCallback(() => {
    // Reset any edge highlighting
    console.log('Reset navigation edge colors');
  }, []);

  const setNodeVerificationSuccess = useCallback((nodeId: string) => {
    // Could implement simple node highlighting here if needed
    console.log('Node verification successful:', nodeId);
  }, []);

  const setNodeVerificationFailure = useCallback((nodeId: string) => {
    // Could implement simple node highlighting here if needed
    console.log('Node verification failed:', nodeId);
  }, []);

  const resetNodeVerificationColors = useCallback((nodeId?: string) => {
    // Reset any node highlighting
    console.log('Reset node verification colors:', nodeId);
  }, []);

  return {
    // Core color functions
    getNodeColors,
    getEdgeColors,
    getHandleColors,

    // Navigation feedback (simplified)
    setNavigationEdgesSuccess,
    setNavigationEdgesFailure,
    resetNavigationEdgeColors,
    setNodeVerificationSuccess,
    setNodeVerificationFailure,
    resetNodeVerificationColors,
  };
};
