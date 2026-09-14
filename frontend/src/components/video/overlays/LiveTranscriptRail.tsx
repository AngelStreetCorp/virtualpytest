import { Close } from '@mui/icons-material';
import { Box, Typography, IconButton } from '@mui/material';
import React, { useEffect, useRef } from 'react';

import { LiveTranscriptLine } from '../hooks/useLiveTranscriptFeed';

interface LiveTranscriptRailProps {
  lines: LiveTranscriptLine[];
  show: boolean;
  onClose?: () => void;
}

/**
 * Right-rail live transcript feed — a running, timestamped history of what was
 * said, newest at the TOP so the latest line is visible without scrolling;
 * scroll down for older lines.
 *
 * Lines arrive from `useLiveTranscriptFeed`, which polls the host's per-10-min
 * chunk JSON. The accumulator transcribes a minute at a time, so lines land in
 * minute-sized batches roughly a minute behind live.
 */
export const LiveTranscriptRail: React.FC<LiveTranscriptRailProps> = ({ lines, show, onClose }) => {
  const scrollRef = useRef<HTMLDivElement>(null);
  const pinnedToTopRef = useRef(true);

  // Only snap back to the newest (top) while the user is already near the top,
  // so scrolling down through history isn't yanked away when the next batch lands.
  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    pinnedToTopRef.current = el.scrollTop < 40;
  };

  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !pinnedToTopRef.current) return;
    el.scrollTop = 0;
  }, [lines]);

  // Newest first: the feed appends chronologically, so reverse for display.
  const orderedLines = React.useMemo(() => lines.slice().reverse(), [lines]);

  if (!show) return null;

  return (
    <Box
      sx={{
        position: 'absolute',
        top: 0,
        right: 0,
        bottom: 0,
        width: 280,
        display: 'flex',
        flexDirection: 'column',
        backgroundColor: 'rgba(0, 0, 0, 0.85)',
        color: 'white',
        borderLeft: '1px solid rgba(255, 255, 255, 0.2)',
        zIndex: 1250,
      }}
    >
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          px: 1.5,
          py: 0.75,
          borderBottom: '1px solid rgba(255, 255, 255, 0.15)',
          flexShrink: 0,
        }}
      >
        <Typography sx={{ fontSize: '0.75rem', fontWeight: 600, letterSpacing: 0.5 }}>
          TRANSCRIPT
        </Typography>
        {onClose && (
          <IconButton size="small" onClick={onClose} sx={{ color: 'white', p: 0.25 }}>
            <Close sx={{ fontSize: '1rem' }} />
          </IconButton>
        )}
      </Box>

      <Box
        ref={scrollRef}
        onScroll={handleScroll}
        sx={{
          flex: 1,
          overflowY: 'auto',
          px: 1.5,
          py: 1,
          '&::-webkit-scrollbar': { width: 6 },
          '&::-webkit-scrollbar-thumb': {
            backgroundColor: 'rgba(255, 255, 255, 0.25)',
            borderRadius: 3,
          },
        }}
      >
        {lines.length === 0 ? (
          <Typography sx={{ fontSize: '0.75rem', color: 'rgba(255, 255, 255, 0.5)' }}>
            Waiting for speech…
          </Typography>
        ) : (
          orderedLines.map((line) => (
            <Box key={line.id} sx={{ mb: 1 }}>
              <Typography
                sx={{ fontSize: '0.65rem', color: 'rgba(255, 255, 255, 0.5)', lineHeight: 1.2 }}
              >
                {line.timestamp}
              </Typography>
              <Typography sx={{ fontSize: '0.8rem', lineHeight: 1.35 }}>{line.text}</Typography>
            </Box>
          ))
        )}
      </Box>
    </Box>
  );
};
