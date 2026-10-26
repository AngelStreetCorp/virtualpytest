import { VerticalSplit } from '@mui/icons-material';
import { IconButton, Tooltip } from '@mui/material';
import React, { useEffect, useState } from 'react';

import { useAgentChatPalette } from '../../../../../frontend/src/constants/agentChatTheme';
import { useResponsiveMode } from '../../../../../frontend/src/hooks/useResponsiveMode';
import { useI18n } from '../../../../../frontend/src/i18n/useI18n';
import { DEFAULT_PATH, SHORTCUT_KEY, SHORTCUT_LABEL } from '../constants';
import { useSplitView } from '../hooks/useSplitView';

import { PageMenu } from './PageMenu';

/**
 * Top-bar button.
 *  - Open: click closes.
 *  - Closed AND never been used (path is still the default `/`): click opens the
 *    page picker — that's the one and only time we need a menu, the user has to
 *    pick something.
 *  - Closed AND the user has opened one before: click goes straight to the last
 *    page — no menu, no recent list, no "where did I leave it?". `state.path` is
 *    persisted in `localStorage`, so it survives a reload and the next click
 *    just resumes.
 *
 * To change page once a session is going, the user opens the title bar in the
 * split pane (SplitPane) — that menu keeps the section list (Top, AI, Test › …)
 * and the auto-focused current page.
 *
 * Ctrl + Alt + S still toggles open/close with the last page, same as before.
 */
export const SplitViewButton: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { isMobile } = useResponsiveMode();
  const { state, open, close, toggle } = useSplitView();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  // Has this browser session ever picked a page? `state.path` is the persisted
  // pane URL, so it stays at the default `/` until the user actually chooses.
  const hasLastPage = state.path !== DEFAULT_PATH;

  useEffect(() => {
    if (isMobile) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.altKey && e.key.toLowerCase() === SHORTCUT_KEY) {
        e.preventDefault();
        toggle();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isMobile, toggle]);

  if (isMobile) return null;

  const tooltipLabel = state.open
    ? `${t('Close split view')} (${SHORTCUT_LABEL})`
    : hasLastPage
      ? `${t('Reopen last page side by side')} (${SHORTCUT_LABEL})`
      : `${t('Open a page side by side')} (${SHORTCUT_LABEL})`;

  return (
    <>
      <Tooltip title={tooltipLabel}>
        <IconButton
          size="small"
          onClick={(e) => {
            if (state.open) {
              close();
            } else if (hasLastPage) {
              // Skip the menu: the user picked a page before, just open it.
              open(state.path);
            } else {
              setAnchor(e.currentTarget);
            }
          }}
          sx={{ color: state.open ? P.accentText : P.textSecondary }}
          aria-pressed={state.open}
        >
          <VerticalSplit fontSize="small" />
        </IconButton>
      </Tooltip>
      <PageMenu anchor={anchor} onClose={() => setAnchor(null)} onPick={open} recent={state.recent} />
    </>
  );
};
