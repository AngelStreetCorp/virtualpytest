import { Box, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { AppIcon } from '../../constants/icons';
import type { EdgeAction } from '../../types/controller/Action_Types';
import { TYPOGRAPHY } from '../../constants/typography';

interface ActionTestResultsProps {
  testResult: EdgeAction;
}

export const ActionTestResults: React.FC<ActionTestResultsProps> = ({ testResult }) => {
  const P = useAgentChatPalette();
  if (!testResult) {
    return null;
  }

  const getResultColor = () => {
    if (testResult.success || testResult.resultType === 'SUCCESS') {
      return P.success; // Passed
    } else if (testResult.resultType === 'ERROR') {
      return P.warning; // Run error / in progress
    } else {
      return P.error; // Failed
    }
  };

  const getResultIcon = () => {
    if (testResult.success || testResult.resultType === 'SUCCESS') {
      return 'success' as const;
    } else if (testResult.resultType === 'ERROR') {
      return 'warning' as const;
    } else {
      return 'error' as const;
    }
  };

  const getResultText = () => {
    if (testResult.message) {
      return testResult.message;
    } else if (testResult.error) {
      return testResult.error;
    } else if (testResult.success) {
      return 'Action executed successfully';
    } else {
      return 'Action failed';
    }
  };

  return (
    <Box
      sx={{
        mt: 0.5,
        p: 1,
        borderRadius: 1,
        backgroundColor: 'rgba(0,0,0,0.05)',
        border: `1px solid ${getResultColor()}`,
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
        <AppIcon name={getResultIcon()} />
        <Typography
          sx={{
            fontSize: TYPOGRAPHY.caption.size,
            color: getResultColor(),
            fontWeight: 500,
          }}
        >
          {getResultText()}
        </Typography>
      </Box>

      {testResult.executionTime && (
        <Typography
          sx={{
            fontSize: TYPOGRAPHY.microMeta.size,
            color: 'text.secondary',
            mt: 0.25,
          }}
        >
          Execution time: {testResult.executionTime}ms
        </Typography>
      )}

      {testResult.executedAt && (
        <Typography
          sx={{
            fontSize: TYPOGRAPHY.microMeta.size,
            color: 'text.secondary',
            mt: 0.25,
          }}
        >
          Executed at: {new Date(testResult.executedAt).toLocaleTimeString()}
        </Typography>
      )}
    </Box>
  );
};
