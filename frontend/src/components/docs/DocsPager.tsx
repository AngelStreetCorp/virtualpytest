import { Box } from '@mui/material';
import { ArrowBack, ArrowForward, EditOutlined } from '@mui/icons-material';
import React from 'react';
import { Link as RouterLink } from 'react-router-dom';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useI18n } from '../../i18n/useI18n';
import type { DocsPageRef } from './docsManifest';

/** Where "Edit on GitHub" points: the public repo, main branch, the markdown source under docs/. */
const GITHUB_EDIT_BASE = 'https://github.com/AngelStreetCorp/virtualpytest/edit/main/docs';

/** End of a page: Previous / Next cards in manifest order (none when the page is not in the manifest) and the edit link. */
const DocsPager: React.FC<{ prev: DocsPageRef | null; next: DocsPageRef | null; mdPath: string }> = ({ prev, next, mdPath }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();

  const card = (ref: DocsPageRef | null, dir: 'prev' | 'next') => {
    if (!ref) return <Box sx={{ flex: 1, display: { xs: 'none', sm: 'block' } }} />;
    const Arrow = dir === 'prev' ? ArrowBack : ArrowForward;
    return (
      <Box
        component={RouterLink}
        to={ref.path}
        rel={dir}
        sx={{
          flex: 1,
          minWidth: 0,
          border: `1px solid ${P.borderColor}`,
          borderRadius: 2.5,
          px: 1.75,
          py: 1.25,
          color: P.textPrimary,
          textDecoration: 'none',
          textAlign: dir === 'next' ? 'right' : 'left',
          '&:hover': { bgcolor: P.hoverBg, borderColor: P.accent },
          '&:focus-visible': { outline: `2px solid ${P.accent}`, outlineOffset: 2 },
        }}
      >
        <Box
          component="span"
          sx={{ display: 'flex', alignItems: 'center', gap: 0.5, justifyContent: dir === 'next' ? 'flex-end' : 'flex-start', fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}
        >
          {dir === 'prev' && <Arrow sx={{ fontSize: TYPOGRAPHY.body.size }} />}
          {dir === 'prev' ? t('Previous') : t('Next')}
          {dir === 'next' && <Arrow sx={{ fontSize: TYPOGRAPHY.body.size }} />}
        </Box>
        <Box component="span" sx={{ display: 'block', fontSize: TYPOGRAPHY.body.size, fontWeight: 600, color: P.accentText, overflowWrap: 'anywhere' }}>
          {ref.title}
        </Box>
      </Box>
    );
  };

  return (
    <>
      {(prev || next) && (
        <Box component="nav" aria-label={t('Previous and next page')} sx={{ display: 'flex', gap: 1.5, mt: 5, flexDirection: { xs: 'column', sm: 'row' } }}>
          {card(prev, 'prev')}
          {card(next, 'next')}
        </Box>
      )}
      {mdPath && (
        <Box
          component="a"
          href={`${GITHUB_EDIT_BASE}${mdPath}`}
          target="_blank"
          rel="noopener noreferrer"
          sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5, mt: 2.5, fontSize: TYPOGRAPHY.caption.size, color: P.accentText, textDecoration: 'none', '&:hover': { textDecoration: 'underline' } }}
        >
          <EditOutlined sx={{ fontSize: TYPOGRAPHY.body.size }} />
          {t('Edit on GitHub')}
        </Box>
      )}
    </>
  );
};

export default DocsPager;
