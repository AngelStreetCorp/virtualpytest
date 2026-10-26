import { Box, Popover } from '@mui/material';
import React, { useLayoutEffect, useRef, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { StatusDot, type StatusDotTone } from '../common/StatusDot';

export interface FavouriteChip {
  key: string;
  label: string;
  tone: StatusDotTone;
  /** The status word printed next to the dot (colour is never alone). */
  word: string;
  to?: string;
}

export const CHIP_GAP = 8;
/** Width reserved for the "+N" badge when some chips do not fit. */
export const BADGE_WIDTH = 44;

/** How many chips fit on one line of `available` px; when not all fit, room is kept for the "+N" badge. */
export const fitCount = (widths: number[], available: number, badge = BADGE_WIDTH, gap = CHIP_GAP): number => {
  const sum = (n: number) => widths.slice(0, n).reduce((a, w) => a + w, 0) + gap * Math.max(0, n - 1);
  if (sum(widths.length) <= available) return widths.length;
  let n = widths.length - 1;
  while (n > 0 && sum(n) + gap + badge > available) n -= 1;
  return n;
};

const Chip: React.FC<{ chip: FavouriteChip; plain?: boolean }> = ({ chip, plain }) => {
  const P = useAgentChatPalette();
  return (
    <Box
      component={chip.to && !plain ? RouterLink : 'span'}
      {...(chip.to && !plain ? { to: chip.to, target: '_blank', rel: 'noopener noreferrer' } : {})}
      data-testid="favourite-chip"
      sx={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 0.75,
        flexShrink: 0,
        border: `1px solid ${P.borderColor}`,
        borderRadius: 2,
        bgcolor: P.surface,
        color: P.textPrimary,
        textDecoration: 'none',
        px: 1,
        height: 20,
        fontSize: TYPOGRAPHY.caption.size,
        whiteSpace: 'nowrap',
        '&:hover': chip.to ? { borderColor: P.accentText } : undefined,
      }}
    >
      <StatusDot tone={chip.tone} word={chip.word} />
      <span>{chip.label}</span>
    </Box>
  );
};

/**
 * Starred devices on ONE line, never wrapping or scrolling: as many chips as fit, the rest collapse into a "+N"
 * badge that opens a small list. Widths are measured on a hidden copy of the chips, so a resize re-fits at once.
 */
export const FavouriteChips: React.FC<{ chips: FavouriteChip[] }> = ({ chips }) => {
  const P = useAgentChatPalette();
  const host = useRef<HTMLDivElement | null>(null);
  const measure = useRef<HTMLDivElement | null>(null);
  const [visible, setVisible] = useState(chips.length);
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);

  useLayoutEffect(() => {
    const refit = () => {
      if (!host.current || !measure.current) return;
      const widths = Array.from(measure.current.children).map((c) => (c as HTMLElement).offsetWidth);
      const available = host.current.clientWidth;
      // jsdom and hidden tabs measure 0: show everything rather than collapse to "+N".
      setVisible(available > 0 ? fitCount(widths, available) : chips.length);
    };
    refit();
    if (typeof ResizeObserver === 'undefined' || !host.current) return undefined;
    const ro = new ResizeObserver(refit);
    ro.observe(host.current);
    return () => ro.disconnect();
  }, [chips]);

  if (chips.length === 0) return null;
  const shown = chips.slice(0, visible);
  const hidden = chips.slice(visible);

  return (
    <Box sx={{ position: 'relative', minWidth: 0, flex: 1 }} data-testid="favourite-chips">
      <Box ref={host} sx={{ display: 'flex', alignItems: 'center', gap: `${CHIP_GAP}px`, flexWrap: 'nowrap', overflow: 'hidden', minWidth: 0 }}>
        {shown.map((chip) => (
          <Chip key={chip.key} chip={chip} />
        ))}
        {hidden.length > 0 && (
          <Box
            component="button"
            type="button"
            data-testid="favourite-more"
            aria-label={`+${hidden.length}`}
            onClick={(e: React.MouseEvent<HTMLElement>) => setAnchor(e.currentTarget)}
            sx={{
              flexShrink: 0,
              width: BADGE_WIDTH,
              height: 20,
              border: `1px solid ${P.borderColor}`,
              borderRadius: 2,
              bgcolor: 'transparent',
              color: P.textSecondary,
              fontSize: TYPOGRAPHY.caption.size,
              fontWeight: 600,
              cursor: 'pointer',
              '&:hover': { borderColor: P.accentText, color: P.accentText },
            }}
          >
            +{hidden.length}
          </Box>
        )}
      </Box>
      <Box ref={measure} aria-hidden="true" sx={{ position: 'absolute', visibility: 'hidden', pointerEvents: 'none', display: 'flex', gap: `${CHIP_GAP}px`, whiteSpace: 'nowrap', height: 0, overflow: 'hidden' }}>
        {chips.map((chip) => (
          <Chip key={chip.key} chip={chip} plain />
        ))}
      </Box>
      <Popover
        open={Boolean(anchor)}
        anchorEl={anchor}
        onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
      >
        <Box data-testid="favourite-more-list" sx={{ p: 1, display: 'flex', flexDirection: 'column', gap: 0.75, alignItems: 'flex-start' }}>
          {hidden.map((chip) => (
            <Chip key={chip.key} chip={chip} />
          ))}
        </Box>
      </Popover>
    </Box>
  );
};
