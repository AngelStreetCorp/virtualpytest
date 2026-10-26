import { Box, IconButton, Tooltip, Typography, useMediaQuery, useTheme } from '@mui/material';
import { ChevronRight } from '@mui/icons-material';
import React, { useEffect, useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';
import { docsRailStickySx } from './docsLayout';
import type { DocsHeading } from './docsPageOptions';
import { TYPOGRAPHY } from '../../constants/typography';

/** A heading counts as "current" once its top is within this many px of the viewport top. */
const ACTIVE_OFFSET = 100;
/** Clears the fixed top bar when a heading is jumped to. */
const JUMP_MARGIN = 80;

/**
 * Sticky "On this page" panel, automatic for docs with 3 or more h2 headings (`<!-- toc: off -->` opts out). Lists the page's h2
 * headings, highlights the one being read and jumps instantly on click. Collapsible; below the lg breakpoint
 * it is a small "On this page" button that opens the same list.
 */
interface Props {
  headings: DocsHeading[];
  /** Wide screens: panel shown (true) or collapsed to a thin strip (false). */
  open: boolean;
  onToggle: () => void;
}

const DocsOnThisPage: React.FC<Props> = ({ headings, open, onToggle }) => {
  const P = useAgentChatPalette();
  const theme = useTheme();
  const { t } = useI18n();
  const narrow = useMediaQuery(theme.breakpoints.down('lg'));
  const [popup, setPopup] = useState(false);
  const [active, setActive] = useState(headings[0]?.id ?? '');

  useEffect(() => {
    let frame = 0;
    const update = () => {
      frame = 0;
      let cur = headings[0]?.id ?? '';
      for (const h of headings) {
        const el = document.getElementById(h.id);
        if (el && el.getBoundingClientRect().top <= ACTIVE_OFFSET) cur = h.id;
      }
      setActive(cur);
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    update();
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll);
    return () => {
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [headings]);

  const jump = (id: string) => (e: React.MouseEvent) => {
    e.preventDefault();
    const el = document.getElementById(id);
    if (el) {
      el.style.scrollMarginTop = `${JUMP_MARGIN}px`;
      el.scrollIntoView({ behavior: 'auto', block: 'start' });
    }
    setActive(id);
    setPopup(false);
  };

  const list = (
    <Box component="nav" aria-label={t('On this page')} sx={{ display: 'flex', flexDirection: 'column', gap: 0.25 }}>
      {headings.map((h) => {
        const on = h.id === active;
        return (
          <Box
            key={h.id}
            component="a"
            href={`#${h.id}`}
            onClick={jump(h.id)}
            aria-current={on ? 'location' : undefined}
            sx={{
              display: 'block',
              px: 1,
              py: 0.5,
              borderRadius: 1,
              borderLeft: '2px solid',
              borderColor: on ? P.accent : 'transparent',
              bgcolor: on ? P.hoverBg : 'transparent',
              color: on ? P.accentText : P.textSecondary,
              fontWeight: on ? 600 : 400,
              fontSize: TYPOGRAPHY.body.size,
              textDecoration: 'none',
              '&:hover': { bgcolor: P.hoverBg },
            }}
          >
            {h.label}
          </Box>
        );
      })}
    </Box>
  );

  const panelSx = {
    bgcolor: P.surface,
    border: `1px solid ${P.borderColor}`,
    borderRadius: 2,
    p: 1,
  };

  if (narrow) {
    return (
      <>
        {popup && (
          <Box sx={{ ...panelSx, position: 'fixed', right: 16, bottom: 120, width: 'min(260px, calc(100vw - 32px))', zIndex: 1090 }}>
            {list}
          </Box>
        )}
        <Box
          component="button"
          type="button"
          onClick={() => setPopup((v) => !v)}
          aria-expanded={popup}
          sx={{
            position: 'fixed',
            right: 16,
            // Above the app's bottom tab bar on phones.
            bottom: 72,
            zIndex: 1091,
            border: 0,
            borderRadius: 5,
            px: 2,
            py: 1,
            cursor: 'pointer',
            bgcolor: P.accent,
            color: P.onAccent,
            fontSize: TYPOGRAPHY.body.size,
            fontWeight: 600,
          }}
        >
          {t('On this page')}
        </Box>
      </>
    );
  }

  const toggleTip = t('Hide outline');

  // Collapsed = gone: no strip. The reader's header bar holds the toggle that brings it back.
  if (!open) return null;

  return (
    <Box
      component="aside"
      sx={{
        ...panelSx,
        width: 210,
        flex: 'none',
        ...docsRailStickySx,
        overflow: 'auto',
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', pl: 1, pb: 0.5 }}>
        <Typography sx={{ fontSize: TYPOGRAPHY.body.size, fontWeight: 600, color: P.textPrimary }}>{t('On this page')}</Typography>
        <Tooltip title={toggleTip}>
          <IconButton size="small" onClick={onToggle} aria-label={toggleTip} aria-expanded sx={{ color: P.textSecondary }}>
            <ChevronRight fontSize="small" />
          </IconButton>
        </Tooltip>
      </Box>
      {list}
    </Box>
  );
};

export default DocsOnThisPage;
