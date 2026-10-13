import { VerticalSplit } from '@mui/icons-material';
import { IconButton, Tooltip } from '@mui/material';
import React, { useEffect, useState } from 'react';

import { useAgentChatPalette } from '../../../../../frontend/src/constants/agentChatTheme';
import { useResponsiveMode } from '../../../../../frontend/src/hooks/useResponsiveMode';
import { useI18n } from '../../../../../frontend/src/i18n/useI18n';
import { SHORTCUT_KEY, SHORTCUT_LABEL } from '../constants';
import { useSplitView } from '../hooks/useSplitView';

import { PageMenu } from './PageMenu';

/**
 * Top-bar button. Closed: pick a page to open beside this one. Open: one click closes it.
 * Ctrl + Alt + S toggles it with the last page.
 */
export const SplitViewButton: React.FC = () => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const { isMobile } = useResponsiveMode();
  const { state, open, close, toggle } = useSplitView();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);

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

  return (
    <>
      <Tooltip title={`${state.open ? t('Close split view') : t('Open a page side by side')} (${SHORTCUT_LABEL})`}>
        <IconButton
          size="small"
          onClick={(e) => (state.open ? close() : setAnchor(e.currentTarget))}
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
