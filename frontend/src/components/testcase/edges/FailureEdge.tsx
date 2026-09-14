import React from 'react';
import {
  BaseEdge,
  EdgeProps,
  getBezierPath,
} from 'reactflow';

/**
 * Failure Edge - Animated connection showing execution flow
 * 
 * States:
 * - idle: Default grey (no execution)
 * - active: Blue with pulsing animation (currently executing)
 * - success: Green (successfully traversed)
 * - failure: Red (traversed but source block failed)
 */
export const FailureEdge: React.FC<EdgeProps & { 
  animated?: boolean;
  data?: {
    executionState?: 'idle' | 'active' | 'success' | 'failure';
  };
}> = ({
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style = {},
  markerEnd,
  selected,
  data,
}) => {
  const [edgePath] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  const executionState = data?.executionState || 'idle';

  // Determine edge color and style based on execution state
  const getEdgeStyle = () => {
    switch (executionState) {
      case 'active':
        return {
          stroke: '#3b82f6', // Blue
          strokeWidth: 4,
          opacity: 1,
          animation: 'edgePulse 1.5s ease-in-out infinite, flowDots 1s linear infinite',
          strokeDasharray: '8, 4',
          filter: 'drop-shadow(0 0 6px #3b82f6)',
        };
      case 'success':
        return {
          stroke: '#10b981', // Green
          strokeWidth: 3,
          opacity: 1,
          strokeDasharray: undefined,
          filter: 'drop-shadow(0 0 4px #10b981)',
        };
      case 'failure':
        return {
          stroke: '#ef4444', // Red
          strokeWidth: 3,
          opacity: 1,
          strokeDasharray: undefined,
          filter: 'drop-shadow(0 0 4px #ef4444)',
        };
      default: // idle
        return {
          stroke: selected ? '#64748b' : '#94a3b8',
          strokeWidth: selected ? 2.5 : 2,
          opacity: 0.6,
          strokeDasharray: undefined,
        };
    }
  };

  const edgeStyle = getEdgeStyle();

  return (
    <>
      <BaseEdge
        path={edgePath}
        markerEnd={markerEnd}
        style={{
          ...style,
          ...edgeStyle,
        }}
      />
      
      {/* Global CSS for edge animations */}
      <style>{`
        @keyframes flowDots {
          to {
            stroke-dashoffset: -12;
          }
        }
        
        @keyframes edgePulse {
          0%, 100% {
            stroke-width: 4;
            opacity: 1;
          }
          50% {
            stroke-width: 5;
            opacity: 0.8;
          }
        }
      `}</style>
    </>
  );
};
