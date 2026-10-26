import { Box } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';

const LINES = ['100%', '96%', '88%', '100%', '72%', '94%', '100%', '58%'];

/**
 * Stand-in for the reader body while the next page's markdown loads: a title bar and a few text
 * lines in the palette's quiet tone. Static on purpose (no pulse, no fade): the card keeps its size
 * and the swap to the real text is one paint (UI_STYLE S6).
 */
const DocsSkeleton: React.FC = () => {
  const P = useAgentChatPalette();
  const bar = (width: string, height: number, mb: number) => (
    <Box sx={{ width, height, mb: `${mb}px`, borderRadius: 1, bgcolor: P.hoverBg }} />
  );
  return (
    <Box aria-busy="true" data-testid="docs-skeleton" sx={{ minHeight: '60vh' }}>
      {bar('55%', 30, 22)}
      {LINES.map((w, i) => (
        <React.Fragment key={i}>{bar(w, 14, i === 3 ? 28 : 12)}</React.Fragment>
      ))}
    </Box>
  );
};

export default DocsSkeleton;
