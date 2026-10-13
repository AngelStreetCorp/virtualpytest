import { Box } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../../constants/agentChatTheme';
import type { DeviceView } from '../../../types/pages/deviceLayout.types';

/** Mini diagram of a view: grey cells in the slot shape, gold when active. */
export const LayoutGlyph: React.FC<{ view: DeviceView; active?: boolean; width?: number }> = ({
  view,
  active = false,
  width = 48,
}) => {
  const P = useAgentChatPalette();
  const color = active ? P.accent : P.textMuted;
  const isGrid = view.kind === 'grid';
  const cells = isGrid ? view.glyph.cols * view.glyph.rows : view.slots;

  return (
    <Box
      aria-hidden
      sx={{
        width,
        aspectRatio: '16 / 10',
        display: 'grid',
        gap: '2px',
        gridTemplateColumns: isGrid ? `repeat(${view.glyph.cols}, 1fr)` : view.columns,
        gridTemplateRows: isGrid ? `repeat(${view.glyph.rows}, 1fr)` : view.rows,
        gridTemplateAreas: !isGrid && view.areas ? view.areas : undefined,
        flexShrink: 0,
      }}
    >
      {Array.from({ length: cells }, (_, i) => (
        <Box
          key={i}
          sx={{
            gridArea: !isGrid && view.areas ? `s${i}` : undefined,
            bgcolor: color,
            opacity: !isGrid && view.focus && i === 0 ? 0.95 : 0.55,
            borderRadius: '2px',
          }}
        />
      ))}
    </Box>
  );
};
