import { Box } from '@mui/material';
import React, { useRef } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';
import type { TimelineSlot } from '../../hooks/useTimeline';
import { TYPOGRAPHY } from '../../constants/typography';

interface Props {
  slots: TimelineSlot[];
  /** the slots on screen (inclusive indexes) */
  frame: { from: number; to: number } | null;
  onJump: (slotIndex: number) => void;
  /** vertical = a column down the right of a vertical (grid) layout; horizontal = a row above a horizontal (strip) layout */
  orientation?: 'horizontal' | 'vertical';
  /** vertical only: the height of the column (it follows the scrolling area beside it) */
  height?: string | number;
}

/**
 * Where you are in the 24 h: one cell per 10 minutes, coloured by what dominates it (AD, FREEZE / BLACK, hatched =
 * no archive), the frame is what is on screen. Click or drag to jump. Hour marks every 3 h.
 */
export const TimelinePositionBar: React.FC<Props> = ({ slots, frame, onJump, orientation = 'horizontal', height = 320 }) => {
  const vertical = orientation === 'vertical';
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const ref = useRef<HTMLDivElement>(null);
  const down = useRef(false);
  const last = useRef(-1);
  const n = slots.length;
  if (!n) return null;

  const at = (clientX: number, clientY: number) => {
    const r = ref.current?.getBoundingClientRect();
    if (!r || !r.width || !r.height) return;
    const f = vertical ? (clientY - r.top) / r.height : (clientX - r.left) / r.width;
    const i = Math.max(0, Math.min(n - 1, Math.floor(f * n)));
    if (i !== last.current) {
      last.current = i;
      onJump(i);
    }
  };
  // unknown (tracks not loaded or not built yet) is neutral grey, never the green of "checked and fine"
  const colour = (s: TimelineSlot) =>
    !s.has ? null : s.flag === null ? P.textMuted : s.flag === 'ok' ? P.success : s.flag === 'ad' ? P.warning : P.error;

  return (
    <Box sx={vertical ? { display: 'flex', flexDirection: 'row-reverse', gap: 0.75, height, flexShrink: 0 } : { mb: 1.5 }}>
      <Box
        ref={ref}
        role="slider"
        aria-label={t('Position in the last 24 h')}
        aria-valuemin={0}
        aria-valuemax={n - 1}
        aria-orientation={vertical ? 'vertical' : 'horizontal'}
        aria-valuenow={frame?.from ?? 0}
        onPointerDown={(e) => {
          down.current = true;
          last.current = -1;
          try {
            (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
          } catch {
            /* a drag that leaves the bar just stops following */
          }
          at(e.clientX, e.clientY);
        }}
        onPointerMove={(e) => down.current && at(e.clientX, e.clientY)}
        onPointerUp={() => (down.current = false)}
        onPointerCancel={() => (down.current = false)}
        sx={{ position: 'relative', display: 'flex', flexDirection: vertical ? 'column' : 'row', ...(vertical ? { width: 22, height: '100%' } : { height: 22 }), borderRadius: 1, overflow: 'hidden', bgcolor: P.hoverBg, border: `1px solid ${P.borderColor}`, cursor: 'pointer', touchAction: 'none' }}
      >
        {slots.map((s, i) => {
          const c = colour(s);
          return (
            <Box
              key={i}
              sx={{
                flex: 1,
                ...(vertical ? { width: '100%' } : { height: '100%' }),
                bgcolor: c ?? 'transparent',
                opacity: c ? (c === P.textMuted ? 0.35 : 0.8) : 1,
                backgroundImage: c ? 'none' : `repeating-linear-gradient(45deg, ${P.borderColor}, ${P.borderColor} 2px, transparent 2px, transparent 4px)`,
              }}
            />
          );
        })}
        {frame && (
          <Box
            sx={{
              position: 'absolute',
              ...(vertical
                ? { left: 0, right: 0, top: `${(frame.from / n) * 100}%`, height: `${((frame.to - frame.from + 1) / n) * 100}%`, minHeight: 10 }
                : { top: 0, bottom: 0, left: `${(frame.from / n) * 100}%`, width: `${((frame.to - frame.from + 1) / n) * 100}%`, minWidth: 10 }),
              border: `2px solid ${P.accent}`,
              boxShadow: `0 0 0 2px ${P.surface}, inset 0 0 0 1px ${P.surface}`,
              boxSizing: 'border-box',
              pointerEvents: 'none',
            }}
          />
        )}
      </Box>
      <Box sx={{ position: 'relative', ...(vertical ? { width: 38, height: '100%' } : { height: 16 }), fontSize: TYPOGRAPHY.microMeta.size, color: P.textSecondary, fontVariantNumeric: 'tabular-nums' }}>
        {slots.map((s, i) =>
          s.chunkIndex === 0 && s.hour % 3 === 0 ? (
            <Box key={i} component="span" sx={{ position: 'absolute', ...(vertical ? { top: `${(i / n) * 100}%`, right: 0, transform: 'translateY(-1px)' } : { left: `${(i / n) * 100}%`, transform: 'translateX(-1px)' }) }}>
              {String(s.hour).padStart(2, '0')}:00
            </Box>
          ) : null,
        )}
      </Box>
    </Box>
  );
};

export default TimelinePositionBar;
