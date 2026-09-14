import React from 'react';
import { NodeProps } from 'reactflow';
import { TerminalBlock } from './TerminalBlock';

/**
 * Success Block - Terminal node for successful testcase completion
 * Only has input handle (no outputs)
 */
export const SuccessBlock: React.FC<NodeProps> = (props) => {
  return <TerminalBlock {...props} label="PASS" color="#10b981" />;
};


