import DragIndicatorIcon from '@mui/icons-material/DragIndicator';
import { Box, Tooltip, Typography } from '@mui/material';
import React, { useState } from 'react';

import { useAgentChatPalette } from '../../../constants/agentChatTheme';
import { LAYOUT_STAGE_HEIGHT, LAYOUT_STAGE_MIN_HEIGHT } from '../../../constants/deviceLayouts';
import { useI18n } from '../../../i18n/useI18n';
import type { LayoutView } from '../../../types/pages/deviceLayout.types';
import { TYPOGRAPHY } from '../../../constants/typography';

export interface LayoutItem {
  key: string;
  node: React.ReactNode;
}

interface DeviceLayoutProps {
  view: LayoutView;
  /** At most view.slots items, already in slot order. */
  items: LayoutItem[];
  onSwap?: (from: string, to: string) => void;
  height?: string | number;
}

/**
 * One CSS grid per layout (TASK-75). Each slot stretches its tile to fill it; dragging a
 * tile onto another swaps the two. Tiles are keyed by device so a swap moves the card
 * instead of re-creating its stream player.
 */
export const DeviceLayout: React.FC<DeviceLayoutProps> = ({
  view,
  items,
  onSwap,
  height = LAYOUT_STAGE_HEIGHT,
}) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [dragKey, setDragKey] = useState<string | null>(null);
  const [overKey, setOverKey] = useState<string | null>(null);
  const area = (i: number) => (view.areas ? `s${i}` : undefined);

  return (
    <Box
      sx={{
        display: 'grid',
        gap: 1,
        gridTemplateColumns: view.columns,
        gridTemplateRows: view.rows,
        gridTemplateAreas: view.areas,
        height,
        minHeight: LAYOUT_STAGE_MIN_HEIGHT,
      }}
    >
      {items.map((item, i) => (
        <Box
          key={item.key}
          data-slot={i}
          draggable={Boolean(onSwap)}
          onDragStart={(e) => {
            setDragKey(item.key);
            e.dataTransfer.effectAllowed = 'move';
          }}
          onDragEnd={() => {
            setDragKey(null);
            setOverKey(null);
          }}
          onDragOver={(e) => {
            if (!dragKey) return;
            e.preventDefault();
            setOverKey(item.key);
          }}
          onDragLeave={() => setOverKey((k) => (k === item.key ? null : k))}
          onDrop={(e) => {
            e.preventDefault();
            if (dragKey && onSwap) onSwap(dragKey, item.key);
            setDragKey(null);
            setOverKey(null);
          }}
          sx={{
            gridArea: area(i),
            minWidth: 0,
            minHeight: 0,
            borderRadius: 1,
            outline: overKey === item.key && dragKey !== item.key ? `2px solid ${P.accent}` : 'none',
            outlineOffset: 1,
            opacity: dragKey === item.key ? 0.6 : 1,
            position: 'relative',
            // The preview card sizes itself from its 16:9 stream area, but the
            // grid layout here still wants the card to fill the slot exactly
            // (TASK-75). Keep the override so the slot dimensions still drive
            // the card — the inner 16:9 stream area then has whatever empty
            // space below the stream that the slot leaves. TASK-116.
            '& > .MuiCard-root, & > * > .MuiCard-root': { height: '100%' },
            // The drag handle shows on the hovered tile only: the gesture, without any text on the page.
            '&:hover .layout-drag-handle': { opacity: 1 },
          }}
        >
          {item.node}
          {onSwap && (
            <Tooltip title={t('Drag onto another stream to swap them')} placement="top">
              <Box
                className="layout-drag-handle"
                aria-label={t('Drag onto another stream to swap them')}
                sx={{
                  position: 'absolute',
                  top: 4,
                  left: '50%',
                  transform: 'translateX(-50%)',
                  zIndex: 2,
                  display: 'flex',
                  px: 0.5,
                  borderRadius: 1,
                  bgcolor: P.surface,
                  border: `1px solid ${P.borderColor}`,
                  color: P.accent,
                  cursor: 'grab',
                  opacity: 0,
                  transition: 'opacity 120ms',
                  '&:active': { cursor: 'grabbing' },
                }}
              >
                <DragIndicatorIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size, transform: 'rotate(90deg)' }} />
              </Box>
            </Tooltip>
          )}
        </Box>
      ))}
      {Array.from({ length: Math.max(0, view.slots - items.length) }, (_, j) => (
        <Box
          key={`empty-${j}`}
          sx={{
            gridArea: area(items.length + j),
            border: `1px dashed ${P.borderColor}`,
            borderRadius: 1,
            display: 'grid',
            placeItems: 'center',
          }}
        >
          <Typography variant="caption" sx={{ color: P.textMuted }}>
            {t('Empty slot')}
          </Typography>
        </Box>
      ))}
    </Box>
  );
};
