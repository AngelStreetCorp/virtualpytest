import { Box } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';

export type StatusDotTone = 'success' | 'error' | 'warning' | 'muted';

/**
 * Status = a small fixed-colour dot + (optionally) a word. UI_STYLE.md "Status" — the
 * default call site is "dot + word", but dense rows (Dashboard host card services)
 * can pass `word` empty and put the word in a surrounding MUI Tooltip. Colours come
 * from the palette's fixed status colours; `muted` is the neutral grey (idle, off).
 * Never a filled or outlined pill.
 */
export const StatusDot: React.FC<{ tone: StatusDotTone; word?: string; title?: string }> = ({ tone, word, title }) => {
  const P = useAgentChatPalette();
  const color = tone === 'success' ? P.success : tone === 'error' ? P.error : tone === 'warning' ? P.warning : P.textMuted;
  return (
    <Box component="span" title={title} sx={{ display: 'inline-flex', alignItems: 'center', gap: word ? 0.75 : 0, color, fontSize: TYPOGRAPHY.caption.size, lineHeight: 1 }}>
      <Box component="span" sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: color, flexShrink: 0 }} />
      {word}
    </Box>
  );
};
