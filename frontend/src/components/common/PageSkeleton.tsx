/**
 * Neutral page placeholder for the window between "the app frame has painted" and "the
 * protected content has its permissions".
 *
 * Why this exists: AuthContext only clears `isLoading` after a PROFILE round trip, so for the
 * first ~130–260 ms of every cold load the protected area had nothing in it. A blank content area
 * under a real navigation bar reads as a broken page. This draws the shape of a page instead —
 * no text, no spinner, no "loading" wording — so the arrival of the real content is a swap of
 * grey blocks for real content rather than a switch from nothing to something.
 *
 * Deliberately generic: it is mounted above the route, before any page's data is known, so it
 * must not pretend to know the layout. Per UI_STYLE §S6 a loading state is the size of the
 * content it replaces, so it fills the viewport rather than a guessed card.
 */
import React from 'react';
import { Box, Skeleton } from '@mui/material';
import { useAgentChatPalette } from '../../constants/agentChatTheme';

const PageSkeleton: React.FC = () => {
  const P = useAgentChatPalette();

  return (
    <Box
      aria-busy="true"
      aria-live="polite"
      sx={{
        flex: 1,
        minHeight: '60vh',
        display: 'flex',
        flexDirection: 'column',
        gap: 2,
        p: 2,
      }}
    >
      {/* Title row — a heading line and the action it usually carries. */}
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 2 }}>
        <Skeleton variant="text" width={220} height={28} />
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Skeleton variant="rounded" width={104} height={32} />
          <Skeleton variant="rounded" width={88} height={32} />
        </Box>
      </Box>

      {/* Stat tiles — four, the shape most pages open with. */}
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2 }}>
        {[0, 1, 2, 3].map((i) => (
          <Box
            key={i}
            sx={{
              flex: '1 1 180px',
              minWidth: 160,
              p: 2,
              border: `1px solid ${P.borderColor}`,
              borderRadius: 2,
              display: 'flex',
              flexDirection: 'column',
              gap: 1,
            }}
          >
            <Skeleton variant="text" width={72} height={18} />
            <Skeleton variant="text" width={96} height={30} />
          </Box>
        ))}
      </Box>

      {/* Body block — the card most pages end on. */}
      <Box
        sx={{
          flex: 1,
          minHeight: 220,
          p: 2,
          border: `1px solid ${P.borderColor}`,
          borderRadius: 2,
          display: 'flex',
          flexDirection: 'column',
          gap: 1.5,
        }}
      >
        {[92, 78, 86, 64].map((w, i) => (
          <Skeleton key={i} variant="rounded" height={14} sx={{ width: `${w}%` }} />
        ))}
      </Box>
    </Box>
  );
};

export default PageSkeleton;