/**
 * AIEditPreview — the proposed step list of a prompt edit, with Apply / Cancel (TASK-36 §3).
 *
 * A line not in the open graph is marked "+"; the count of removed lines is shown.
 * Used by the Test Builder's AI tab and the QuickTest Builder.
 */

import React, { useMemo } from 'react';
import { Box, Button, Typography } from '@mui/material';

import { AIGraphEditProposal } from '../../../hooks/testcase/useAIGraphEdit';
import { TYPOGRAPHY } from '../../../constants/typography';

interface AIEditPreviewProps {
  proposal: AIGraphEditProposal;
  onApply: () => void;
  onCancel: () => void;
}

export const AIEditPreview: React.FC<AIEditPreviewProps> = ({ proposal, onApply, onCancel }) => {
  const { added, removed } = useMemo(() => {
    const before = new Set(proposal.stepsBefore);
    const after = new Set(proposal.stepsAfter);
    return {
      added: new Set(proposal.stepsAfter.filter((l) => !before.has(l))),
      removed: proposal.stepsBefore.filter((l) => !after.has(l)),
    };
  }, [proposal]);

  return (
    <Box sx={{ border: 1, borderColor: 'divider', borderRadius: 1, p: 1.5, display: 'flex', flexDirection: 'column', gap: 1 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Typography variant="subtitle2" fontWeight="bold" sx={{ flex: 1 }}>
          Proposed steps
        </Typography>
        <Button size="small" onClick={onCancel}>
          Cancel
        </Button>
        <Button size="small" variant="contained" onClick={onApply}>
          Apply
        </Button>
      </Box>
      {proposal.analysis && (
        <Typography variant="caption" color="text.secondary" sx={{ whiteSpace: 'pre-wrap' }}>
          {proposal.analysis}
        </Typography>
      )}
      <Box component="ol" sx={{ m: 0, pl: 3, fontFamily: 'monospace', fontSize: TYPOGRAPHY.caption.size }}>
        {proposal.stepsAfter.map((line, i) => (
          <Box
            component="li"
            key={`${i}-${line}`}
            sx={added.has(line) ? { color: 'success.main', fontWeight: 600 } : undefined}
          >
            {added.has(line) ? '+ ' : ''}
            {line}
          </Box>
        ))}
      </Box>
      {removed.length > 0 && (
        <Typography variant="caption" color="error.main" sx={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>
          {`Removed (${removed.length}):\n` + removed.map((l) => `- ${l}`).join('\n')}
        </Typography>
      )}
    </Box>
  );
};
