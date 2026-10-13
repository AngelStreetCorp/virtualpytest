import { CheckCircle, Cancel, PlayCircle } from '@mui/icons-material';
import React from 'react';

import { useAgentChatPalette } from '../../../../../frontend/src/constants/agentChatTheme';
import type { RunOutcome } from '../types';

export const RunStatusIcon: React.FC<{ outcome: RunOutcome }> = ({ outcome }) => {
  const P = useAgentChatPalette();
  const sx = { fontSize: 18 };
  if (outcome === 'passed') return <CheckCircle sx={{ ...sx, color: P.success }} />;
  if (outcome === 'failed') return <Cancel sx={{ ...sx, color: P.error }} />;
  return <PlayCircle sx={{ ...sx, color: P.accentText }} />;
};
