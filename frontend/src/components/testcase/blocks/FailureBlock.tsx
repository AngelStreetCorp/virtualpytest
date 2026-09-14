import React from 'react';
import { NodeProps } from 'reactflow';
import { TerminalBlock } from './TerminalBlock';

/**
 * Failure Block - Terminal node for failed testcase
 * Only has input handle (no outputs)
 */
export const FailureBlock: React.FC<NodeProps> = (props) => {
  return <TerminalBlock {...props} label="FAIL" color="#ef4444" />;
};


