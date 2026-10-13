import React from 'react';
import {
  BaseEdge,
  EdgeProps,
  getBezierPath,
} from 'reactflow';
import { AGENT_CHAT_PALETTE } from '../../../constants/agentChatTheme';

/**
 * Data Edge - Dashed connection showing data flow between blocks
 * 
 * Visual: muted steel dashed line (distinct from FLOW edges)
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

  // Data edges are always steel dashed
  const edgeStyle = {
    stroke: selected ? AGENT_CHAT_PALETTE.accent : AGENT_CHAT_PALETTE.series[1],
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

