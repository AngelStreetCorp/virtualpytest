import { Close, ExpandMore, SwapHoriz } from '@mui/icons-material';
import { Box, Button, IconButton, Tooltip } from '@mui/material';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useHref, useLocation, useNavigate } from 'react-router-dom';

import { useAgentChatPalette } from '../../../../../frontend/src/constants/agentChatTheme';
import { useResponsiveMode } from '../../../../../frontend/src/hooks/useResponsiveMode';
import { useI18n } from '../../../../../frontend/src/i18n/useI18n';
import { DEFAULT_WIDTH_PCT, PATH_READ_MS } from '../constants';
import { routerPath, widthFromPointer } from '../actions';
import { usePageOptions } from '../hooks/usePageOptions';
import { useSplitView } from '../hooks/useSplitView';

import { PageMenu } from './PageMenu';

/** The second page beside the current one: a frame of this app (it hides its own chrome). */
export const SplitPane: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { isMobile } = useResponsiveMode();
  const navigate = useNavigate();
  const location = useLocation();
  const { state, open, close, follow, resize } = useSplitView();
  const options = usePageOptions();
  const frameRef = useRef<HTMLIFrameElement>(null);
  const paneRef = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState(false);
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);

  // Router basename (e.g. /pi4 behind a proxy): the frame needs the full URL.
  const basename = useHref('/').replace(/\/$/, '');
  const src = useHref(state.path);
  // Only reload the frame when the user picks a page, not when we follow its own navigation.
  const [frameSrc, setFrameSrc] = useState(src);
  const lastPickRef = useRef(state.path);

  const title = useMemo(() => {
    const bare = state.path.split('?')[0];
    const match = options.find((o) => o.path === bare);
    return match ? t(match.label) : bare;
  }, [options, state.path, t]);

  // Follow the page the frame navigated to (same origin, so its location is readable).
  useEffect(() => {
    if (!state.open) return undefined;
    const id = window.setInterval(() => {
      try {
        const loc = frameRef.current?.contentWindow?.location;
        if (loc) {
          const path = routerPath(loc.pathname, loc.search, basename);
          lastPickRef.current = path;
          follow(path);
        }
      } catch {
        // Not readable (still loading): try again next tick.
      }
    }, PATH_READ_MS);
    return () => window.clearInterval(id);
  }, [state.open, basename, follow]);

  // A new pick (menu, swap, shortcut): load it.
  useEffect(() => {
    if (state.path !== lastPickRef.current) {
      lastPickRef.current = state.path;
      setFrameSrc(src);
    }
  }, [state.path, src]);

  // Divider drag: the frame would swallow the pointer, so it ignores the mouse while dragging.
  useEffect(() => {
    if (!dragging) return undefined;
    const row = paneRef.current?.parentElement;
    const onMove = (e: PointerEvent) => {
      if (!row) return;
      const box = row.getBoundingClientRect();
      resize(widthFromPointer(e.clientX, box.left, box.width));
    };
    const onUp = () => setDragging(false);
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
  }, [dragging, resize]);

  if (!state.open || isMobile) return null;

  const swap = () => {
    const main = `${location.pathname}${location.search}`;
    navigate(state.path);
    open(main);
  };

  return (
    <Box ref={paneRef} sx={{ display: 'flex', width: `${state.widthPct}%`, minWidth: 0, flexShrink: 0 }}>
      <Tooltip title={t('Drag to resize, double-click to reset')} placement="left">
        <Box
          role="separator"
          aria-orientation="vertical"
          onPointerDown={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDoubleClick={() => resize(DEFAULT_WIDTH_PCT)}
          sx={{
            width: 6,
            cursor: 'col-resize',
            flexShrink: 0,
            bgcolor: dragging ? P.accent : P.borderColor,
            '&:hover': { bgcolor: P.accent },
          }}
        />
      </Tooltip>
      <Box sx={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', bgcolor: P.background }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, px: 1, py: 0.5, borderBottom: `1px solid ${P.borderColor}`, bgcolor: P.surface }}>
          <Button
            size="small"
            endIcon={<ExpandMore />}
            onClick={(e) => setAnchor(e.currentTarget)}
            sx={{ color: P.textPrimary, fontWeight: 600, minWidth: 0, maxWidth: '70%', justifyContent: 'flex-start' }}
          >
            <Box component="span" sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {title}
            </Box>
          </Button>
          <Box sx={{ flex: 1 }} />
          <Tooltip title={t('Swap sides')}>
            <IconButton size="small" onClick={swap} sx={{ color: P.textSecondary }}>
              <SwapHoriz fontSize="small" />
            </IconButton>
          </Tooltip>
          <Tooltip title={t('Close split view')}>
            <IconButton size="small" onClick={close} sx={{ color: P.textSecondary }}>
              <Close fontSize="small" />
            </IconButton>
          </Tooltip>
        </Box>
        <Box
          component="iframe"
          ref={frameRef}
          src={frameSrc}
          title={title}
          sx={{ flex: 1, width: '100%', border: 0, pointerEvents: dragging ? 'none' : 'auto', bgcolor: P.background }}
        />
      </Box>
      <PageMenu anchor={anchor} onClose={() => setAnchor(null)} onPick={open} current={state.path.split('?')[0]} recent={state.recent} />
    </Box>
  );
};
