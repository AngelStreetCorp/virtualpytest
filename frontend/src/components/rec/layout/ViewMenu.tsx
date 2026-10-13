import { Box, Button, Popover, Tooltip, Typography } from '@mui/material';
import React, { useState } from 'react';

import { useAgentChatPalette } from '../../../constants/agentChatTheme';
import { GRID_VIEWS, LAYOUT_VIEWS, layoutsForCount } from '../../../constants/deviceLayouts';
import { useI18n } from '../../../i18n/useI18n';
import type { DeviceView, ViewId } from '../../../types/pages/deviceLayout.types';

import { LayoutGlyph } from './LayoutGlyph';

interface ViewMenuProps {
  view: DeviceView;
  onChange: (id: ViewId) => void;
  onResetOrder?: () => void;
  /** Phones: only the scrolling grid sizes. */
  gridOnly?: boolean;
  /** Group tile: only the layouts (no page size). */
  layoutsOnly?: boolean;
  /** Group tile: offer only the layouts that suit this many devices. */
  itemCount?: number;
}

/** One View control (TASK-75): Grid 12/24/48 (scrolls) and the layouts that fit the screen. */
export const ViewMenu: React.FC<ViewMenuProps> = ({ view, onChange, onResetOrder, gridOnly, layoutsOnly, itemCount }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const pick = (id: ViewId) => {
    onChange(id);
    setAnchor(null);
  };

  const option = (v: DeviceView, caption: React.ReactNode, shortcut?: number) => (
    <Tooltip key={v.id} title={t(v.label)} placement="top">
      <Box
        component="button"
        role="menuitemradio"
        aria-checked={v.id === view.id}
        aria-label={t(v.label)}
        onClick={() => pick(v.id)}
        sx={{
          display: 'grid',
          justifyItems: 'center',
          gap: 0.5,
          p: 1,
          cursor: 'pointer',
          color: 'inherit',
          font: 'inherit',
          borderRadius: 1,
          border: `1px solid ${v.id === view.id ? P.accent : P.borderColor}`,
          bgcolor: v.id === view.id ? `${P.accent}26` : P.background,
          '&:hover': { borderColor: P.accent },
          '&:focus-visible': { outline: `2px solid ${P.accent}`, outlineOffset: 2 },
        }}
      >
        <LayoutGlyph view={v} active={v.id === view.id} />
        {caption}
        {shortcut !== undefined && (
          <Typography component="span" sx={{ fontFamily: 'monospace', fontSize: '0.6rem', color: P.textMuted }}>
            {shortcut}
          </Typography>
        )}
      </Box>
    </Tooltip>
  );

  const sectionTitle = (text: string) => (
    <Typography sx={{ fontSize: '0.7rem', fontWeight: 600, color: P.textMuted, mb: 0.75 }}>{text}</Typography>
  );

  return (
    <>
      <Button
        size="small"
        variant="outlined"
        onClick={(e) => setAnchor(e.currentTarget)}
        aria-haspopup="menu"
        aria-expanded={Boolean(anchor)}
        aria-label={t('View')}
        sx={{ height: 32, flexShrink: 0, gap: 1, textTransform: 'none', whiteSpace: 'nowrap' }}
      >
        <Typography component="span" sx={{ fontSize: '0.8rem', color: P.textMuted }}>
          {t('View')}
        </Typography>
        <LayoutGlyph view={view} active width={28} />
        <Typography component="span" sx={{ fontSize: '0.8rem', color: P.textPrimary }}>
          {t(view.label)}
        </Typography>
      </Button>
      <Popover
        open={Boolean(anchor)}
        anchorEl={anchor}
        onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
        slotProps={{ paper: { sx: { p: 1.5, width: 'min(470px, calc(100vw - 32px))' } } }}
      >
        <Box role="menu" aria-label={t('View')}>
          {!layoutsOnly && (
            <Box sx={{ mb: gridOnly ? 0 : 1.5 }}>
              {sectionTitle(t('Grid · scrolls · devices per page'))}
              <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 1 }}>
                {GRID_VIEWS.map((v) =>
                  option(
                    v,
                    <Typography component="span" sx={{ fontFamily: 'monospace', fontWeight: 600, fontSize: '0.8rem' }}>
                      {v.pageSize}
                    </Typography>,
                  ),
                )}
              </Box>
            </Box>
          )}
          {!gridOnly && (
            <Box sx={{ pt: layoutsOnly ? 0 : 1.5, borderTop: layoutsOnly ? 0 : `1px solid ${P.borderColor}` }}>
              {sectionTitle(t('Layout · fits the screen'))}
              <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 1 }}>
                {(itemCount ? layoutsForCount(itemCount) : LAYOUT_VIEWS.filter((v) => !v.focus)).map((v, i) =>
                  option(
                    v,
                    <Typography component="span" sx={{ fontSize: '0.62rem', color: P.textSecondary, textAlign: 'center' }}>
                      {t(v.label)}
                    </Typography>,
                    layoutsOnly ? undefined : i + 1,
                  ),
                )}
              </Box>
            </Box>
          )}
          {onResetOrder && view.kind === 'layout' && (
            <Box sx={{ display: 'flex', justifyContent: 'flex-end', mt: 1 }}>
              <Tooltip title={t('Drag a stream onto another to swap them. Reset puts them back in their default order.')}>
                <Button
                  size="small"
                  onClick={() => {
                    onResetOrder();
                    setAnchor(null);
                  }}
                  sx={{ textTransform: 'none', color: P.accentText }}
                >
                  {t('Reset order')}
                </Button>
              </Tooltip>
            </Box>
          )}
        </Box>
      </Popover>
    </>
  );
};
