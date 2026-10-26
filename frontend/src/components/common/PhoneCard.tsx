/** One row of a list as a stacked card on a phone: name on top, the useful values under it. */
import { Box } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';

export const PhoneCard: React.FC<{
  title: React.ReactNode;
  /** Small muted line(s) under the title: the 2-3 most useful values. */
  children?: React.ReactNode;
  onClick?: () => void;
  selected?: boolean;
  /** Extra content under the values (a drill-down opened by the tap). */
  footer?: React.ReactNode;
}> = ({ title, children, onClick, selected, footer }) => {
  const P = useAgentChatPalette();
  return (
    <Box
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(); } } : undefined}
      sx={{
        px: 1.5,
        py: 1,
        mb: 1,
        borderRadius: 2,
        bgcolor: P.surface,
        border: `1px solid ${selected ? P.accent : P.borderColor}`,
        cursor: onClick ? 'pointer' : 'default',
        minWidth: 0,
      }}
    >
      <Box sx={{ color: P.textPrimary, fontSize: TYPOGRAPHY.body.size, fontWeight: 600, overflowWrap: 'anywhere' }}>{title}</Box>
      {children != null && (
        <Box sx={{ mt: 0.25, display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', columnGap: 1.5, rowGap: 0.25, fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary }}>
          {children}
        </Box>
      )}
      {footer}
    </Box>
  );
};

export default PhoneCard;
