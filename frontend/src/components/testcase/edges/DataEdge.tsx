import React from 'react';
import {
  BaseEdge,
  EdgeProps,
  getBezierPath,
} from 'reactflow';

/**
 * Data Edge - Dashed connection showing data flow between blocks
 * 
 * Visual: Blue dashed line (distinct from FLOW edges)
 * Used for: Variable passing between blocks (IN/OUT connections)
 */
export const DataEdge: React.FC<EdgeProps & { 
  animated?: boolean;
  data?: {
    variableName?: string;
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
}) => {
  const [edgePath] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  // Data edges are always blue dashed
  const edgeStyle = {
    stroke: selected ? '#3b82f6' : '#60a5fa', // Blue (lighter when not selected)
    strokeWidth: selected ? 3 : 2,
    strokeDasharray: '8, 4', // Dashed line
    opacity: 0.8,
  };

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
    </>
  );
};

