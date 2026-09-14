/**
 * Block Output Handles Component
 * 
 * Shared component for rendering success/failure output handles on blocks.
 * Used by both TestCaseBuilder (UniversalBlock) and CampaignBuilder (CampaignBlock).
 */

import React from 'react';
import { Box, Typography } from '@mui/material';
import { Handle, Position } from 'reactflow';
import CheckIcon from '@mui/icons-material/Check';
import CloseIcon from '@mui/icons-material/Close';

export type OutputType = 'success' | 'failure' | 'true' | 'false' | 'complete' | 'break' | 'pass' | 'fail';

interface BlockOutputHandlesProps {
  /** Array of output types to render */
  outputs: OutputType[];
  /** Currently animating handle (for execution feedback) */
  animatingHandle?: OutputType | null;
  /** Execution state for highlighting active handle */
  executionState?: {
    status: 'pending' | 'executing' | 'success' | 'failure' | 'error';
  } | null;
}

/**
 * Get handle color based on output type
 */
export const getHandleColor = (outputType: OutputType): string => {
  switch (outputType) {
    case 'success':
    case 'true':
    case 'complete':
    case 'pass':
      return '#10b981'; // green
    case 'failure':
    case 'false':
    case 'fail':
      return '#ef4444'; // red
    case 'break':
      return '#eab308'; // yellow
    default:
      return '#6b7280'; // gray
  }
};

/**
 * Check if this handle is the active one based on execution state
 */
const isHandleActive = (
  output: OutputType, 
  executionState?: { status: string } | null
): boolean => {
  if (!executionState || !['success', 'failure', 'error'].includes(executionState.status)) {
    return false;
  }
  
  const successOutputs: OutputType[] = ['success', 'true', 'complete', 'pass'];
  const failureOutputs: OutputType[] = ['failure', 'false', 'fail'];
  
  if (executionState.status === 'success' && successOutputs.includes(output)) {
    return true;
  }
  if ((executionState.status === 'failure' || executionState.status === 'error') && failureOutputs.includes(output)) {
    return true;
  }
  return false;
};

/**
 * Get content (icon/text) for output handle
 */
const getHandleContent = (output: OutputType, isActive: boolean) => {
  const successOutputs: OutputType[] = ['success', 'true', 'complete', 'pass'];
  const failureOutputs: OutputType[] = ['failure', 'false', 'fail'];
  
  if (successOutputs.includes(output)) {
    return <CheckIcon sx={{ fontSize: isActive ? 16 : 14 }} />;
  }
  if (failureOutputs.includes(output)) {
    return <CloseIcon sx={{ fontSize: isActive ? 16 : 14 }} />;
  }
  if (output === 'break') {
    return <Typography fontSize={9} fontWeight="bold">BRK</Typography>;
  }
  return null;
};

export const BlockOutputHandles: React.FC<BlockOutputHandlesProps> = ({
  outputs,
  animatingHandle,
  executionState,
}) => {
  if (outputs.length === 0) {
    return null;
  }

  // Single output - centered at bottom
  if (outputs.length === 1) {
    const output = outputs[0];
    const handleColor = getHandleColor(output);
    const isAnimating = animatingHandle === output;
    const isActive = isHandleActive(output, executionState);

    return (
      <Handle
        type="source"
        position={Position.Bottom}
        id={output}
        style={{
          background: handleColor,
          width: isActive ? 60 : 50,
          height: isActive ? 24 : 20,
          borderRadius: 4,
          border: 'none',
          bottom: isActive ? -26 : -22,
          left: '50%',
          transform: 'translateX(-50%)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'white',
          fontWeight: 'bold',
          fontSize: 12,
          cursor: 'pointer',
          boxShadow: isActive ? `0 0 12px ${handleColor}` : '0 1px 3px rgba(0,0,0,0.2)',
          transition: 'all 0.2s ease',
        }}
      >
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            pointerEvents: 'none',
            animation: isAnimating ? 'pulse 0.5s ease-in-out 3' : 'none',
            '@keyframes pulse': {
              '0%, 100%': { transform: 'scale(1)' },
              '50%': { transform: 'scale(1.15)' },
            },
          }}
        >
          {getHandleContent(output, isActive)}
        </Box>
      </Handle>
    );
  }

  // Multiple outputs - compact, centered with gap
  return (
    <Box
      sx={{
        position: 'absolute',
        bottom: -22,
        left: '50%',
        transform: 'translateX(-50%)',
        display: 'flex',
        gap: 0.5,
      }}
    >
      {outputs.map((output) => {
        const handleColor = getHandleColor(output);
        const isAnimating = animatingHandle === output;
        const isActive = isHandleActive(output, executionState);

        return (
          <Handle
            key={output}
            type="source"
            position={Position.Bottom}
            id={output}
            style={{
              position: 'relative',
              transform: 'none',
              top: 0,
              left: 0,
              background: handleColor,
              width: isActive ? 48 : 40,
              height: isActive ? 22 : 18,
              borderRadius: 4,
              border: 'none',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'white',
              fontWeight: 'bold',
              fontSize: 12,
              cursor: 'pointer',
              boxShadow: isActive ? `0 0 12px ${handleColor}` : '0 1px 3px rgba(0,0,0,0.2)',
              transition: 'all 0.2s ease',
            }}
          >
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                pointerEvents: 'none',
                animation: isAnimating ? 'pulse 0.5s ease-in-out 3' : 'none',
                '@keyframes pulse': {
                  '0%, 100%': { transform: 'scale(1)' },
                  '50%': { transform: 'scale(1.15)' },
                },
              }}
            >
              {getHandleContent(output, isActive)}
            </Box>
          </Handle>
        );
      })}
    </Box>
  );
};

