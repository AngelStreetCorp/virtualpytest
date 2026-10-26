import { Box } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';
import type { TimelineCell } from '../../hooks/useTimeline';
import { TYPOGRAPHY } from '../../constants/typography';

export const fmtTod = (sec: number, withSeconds: boolean): string => {
  const h = Math.floor(sec / 3600) % 24;
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  const hm = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
  return withSeconds ? `${hm}:${String(s).padStart(2, '0')}` : hm;
};

type Flag = 'ad' | 'freeze' | 'blackscreen' | null;

export const flagOf = (c: TimelineCell | undefined): Flag => {
  if (!c?.flags) return null;
  if (c.flags.freeze > 0.5) return 'freeze';
  if (c.flags.blackscreen > 0.5) return 'blackscreen';
  if (c.flags.ad > 0.5) return 'ad';
  return null;
};

/** Event filter: 'all' shows everything; a state dims every tile that is not in that state. */
export type FlagFilter = 'all' | 'freeze' | 'blackscreen' | 'ad';
export const matchesFilter = (c: TimelineCell | undefined, only: FlagFilter): boolean =>
  only === 'all' || (!!c?.flags && c.flags[only] > 0.5);

interface TileProps {
  cell: TimelineCell;
  prev?: TimelineCell;
  selected: boolean;
  withSeconds: boolean;
  onSelect: (key: string) => void;
  onZoom: (key: string) => void;
  dim?: boolean;
  /** strip layout: a fixed size instead of the grid's 16:9 cell */
  width?: number;
}

/**
 * One thumbnail: the frame AT its time (a tile of the host's sprite as a CSS background, so one image request
 * serves a whole chunk). A coloured edge + the word marks a state (AD, FREEZE, BLACK), never colour alone.
 * Hatched = no picture for that slot.
 */
export const TimelineTile: React.FC<TileProps> = React.memo(({ cell: c, prev, selected, withSeconds, onSelect, onZoom, dim, width }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const f = flagOf(c);
  const edge = f === 'ad' ? P.warning : f ? P.error : 'transparent';
  const word = f === 'ad' ? t('AD') : f === 'freeze' ? t('FREEZE') : f === 'blackscreen' ? t('BLACK') : '';
  const runStart = f !== null && flagOf(prev) !== f;
  const sprite = c.sprite;
  return (
    <Box
      role="gridcell"
      data-key={c.key}
      aria-selected={selected}
      aria-label={fmtTod(c.tod, true)}
      onClick={() => onSelect(c.key)}
      onDoubleClick={() => onZoom(c.key)}
      sx={{
        position: 'relative',
        ...(width ? { width, flex: 'none', aspectRatio: String(c.aspect) } : { aspectRatio: String(c.aspect) }),
        borderRadius: '3px',
        cursor: 'pointer',
        border: `2px solid ${edge}`,
        outline: selected ? `2px solid ${P.accent}` : 'none',
        outlineOffset: '1px',
        bgcolor: P.hoverBg,
        ...(dim ? { opacity: 0.25 } : {}),
        ...(sprite
          ? {
              backgroundImage: `url("${sprite.url}")`,
              backgroundRepeat: 'no-repeat',
              backgroundSize: `${sprite.cols * 100}% ${sprite.rows * 100}%`,
              backgroundPosition: `${sprite.cols > 1 ? (sprite.col / (sprite.cols - 1)) * 100 : 0}% ${
                sprite.rows > 1 ? (sprite.row / (sprite.rows - 1)) * 100 : 0
              }%`,
            }
          : {
              backgroundImage: `repeating-linear-gradient(45deg, ${P.borderColor}, ${P.borderColor} 4px, transparent 4px, transparent 8px)`,
            }),
      }}
    >
      <Box
        component="span"
        sx={{ position: 'absolute', right: 3, top: 1, fontSize: TYPOGRAPHY.microMeta.size, color: '#fff', textShadow: '0 0 3px #000', fontVariantNumeric: 'tabular-nums' }}
      >
        {fmtTod(c.tod, withSeconds)}
      </Box>
      {runStart && (
        <Box
          component="span"
          sx={{ position: 'absolute', left: 2, bottom: 1, fontSize: TYPOGRAPHY.microMeta.size, fontWeight: 700, px: '3px', borderRadius: '2px', bgcolor: edge, color: f === 'ad' ? '#1a1a1a' : '#fff' }}
        >
          {word}
        </Box>
      )}
    </Box>
  );
});
TimelineTile.displayName = 'TimelineTile';

interface GridProps {
  cells: TimelineCell[];
  columns: number;
  selectedKey: string | null;
  withSeconds: boolean;
  onSelect: (key: string) => void;
  onZoom: (key: string) => void;
  only?: FlagFilter;
}

/** The thumbnail mosaic of one range (24 h and 1 h levels, and one chunk of the 10 min grid). */
export const TimelineGrid: React.FC<GridProps> = ({ cells, columns, selectedKey, withSeconds, onSelect, onZoom, only = 'all' }) => (
  <Box role="grid" sx={{ display: 'grid', gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`, gap: '3px' }}>
    {cells.map((c, i) => (
      <TimelineTile key={c.key} cell={c} prev={cells[i - 1]} selected={selectedKey === c.key} withSeconds={withSeconds} onSelect={onSelect} onZoom={onZoom} dim={!matchesFilter(c, only)} />
    ))}
  </Box>
);

export default TimelineGrid;
