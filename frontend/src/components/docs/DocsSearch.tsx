import { Box, Dialog, InputBase } from '@mui/material';
import { ArticleOutlined, SearchOutlined } from '@mui/icons-material';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useI18n } from '../../i18n/useI18n';
import { stripEmoji } from './docsText';
import { highlightParts, loadSearchIndex, queryTokens, searchDocs, type SearchEntry } from './docsSearchIndex';

/** "⌘K" on Apple platforms, "Ctrl K" elsewhere. */
export const searchShortcutLabel = (): string =>
  typeof navigator !== 'undefined' && /Mac|iPhone|iPad/i.test(navigator.platform || navigator.userAgent) ? '⌘K' : 'Ctrl K';

const Highlighted: React.FC<{ text: string; tokens: string[] }> = ({ text, tokens }) => {
  const P = useAgentChatPalette();
  return (
    <>
      {highlightParts(text, tokens).map((p, i) =>
        p.hit ? (
          <Box key={i} component="mark" sx={{ bgcolor: `${P.accent}40`, color: 'inherit', borderRadius: 0.5, px: 0.25 }}>
            {p.text}
          </Box>
        ) : (
          <React.Fragment key={i}>{p.text}</React.Fragment>
        ),
      )}
    </>
  );
};

/**
 * Full-text docs search. Opens with Cmd/Ctrl+K or "/" (the page binds the keys), arrows move,
 * Enter opens, Esc closes. Titles, headings and the body excerpt are searched client-side.
 */
const DocsSearch: React.FC<{ open: boolean; onClose: () => void }> = ({ open, onClose }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [index, setIndex] = useState<SearchEntry[] | null>(null);
  const [cursor, setCursor] = useState(0);
  const listRef = useRef<HTMLUListElement | null>(null);

  useEffect(() => {
    if (!open || index) return;
    let alive = true;
    void loadSearchIndex().then((r) => alive && setIndex(r));
    return () => { alive = false; };
  }, [open, index]);

  const tokens = useMemo(() => queryTokens(query), [query]);
  const hits = useMemo(() => (index ? searchDocs(index, query) : []), [index, query]);

  useEffect(() => setCursor(0), [query]);
  useEffect(() => {
    listRef.current?.children[cursor]?.scrollIntoView({ block: 'nearest' });
  }, [cursor]);

  const go = (i: number) => {
    const hit = hits[i];
    if (!hit) return;
    onClose();
    navigate(hit.entry.p);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setCursor((c) => Math.min(c + 1, Math.max(hits.length - 1, 0)));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setCursor((c) => Math.max(c - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      go(cursor);
    }
  };

  let status: string | null = null;
  if (!index) status = t('Loading…');
  else if (!tokens.length) status = t('Search {count} pages', { count: index.length });
  else if (!hits.length) status = t('No page matches "{query}"', { query: query.trim() });

  return (
    <Dialog
      open={open}
      onClose={onClose}
      fullWidth
      maxWidth="sm"
      TransitionProps={{ onExited: () => setQuery('') }}
      PaperProps={{ sx: { alignSelf: 'flex-start', mt: { xs: 2, sm: '10vh' }, mx: 2, width: 'calc(100% - 32px)', maxHeight: '70vh' } }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 2, borderBottom: `1px solid ${P.borderColor}` }}>
        <SearchOutlined sx={{ color: P.textMuted }} />
        <InputBase
          autoFocus
          fullWidth
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={t('Search docs, FAQ, API, release notes…')}
          inputProps={{ 'aria-label': t('Search documentation'), role: 'combobox', 'aria-expanded': hits.length > 0, 'aria-controls': 'docs-search-results' }}
          sx={{ py: 1.5, fontSize: TYPOGRAPHY.navbarItem.size, color: P.textPrimary }}
        />
        {/* i18n-ignore: key cap label */}
        <Box sx={{ border: `1px solid ${P.borderColor}`, borderRadius: 1, px: 0.75, fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>Esc</Box>
      </Box>
      {status && <Box sx={{ px: 2, py: 2, color: P.textMuted, fontSize: TYPOGRAPHY.body.size }}>{status}</Box>}
      {hits.length > 0 && (
        <Box component="ul" id="docs-search-results" role="listbox" ref={listRef} sx={{ m: 0, p: 0.5, listStyle: 'none', overflowY: 'auto' }}>
          {hits.map((h, i) => {
            const on = i === cursor;
            return (
              <Box
                component="li"
                key={h.entry.p}
                role="option"
                aria-selected={on}
                onMouseMove={() => setCursor(i)}
                onClick={() => go(i)}
                sx={{
                  display: 'flex',
                  gap: 1.25,
                  px: 1.25,
                  py: 1,
                  borderRadius: 1.5,
                  cursor: 'pointer',
                  bgcolor: on ? P.hoverBg : 'transparent',
                }}
              >
                <ArticleOutlined sx={{ fontSize: TYPOGRAPHY.navbarItem.size, mt: 0.25, color: on ? P.accentText : P.textMuted, flex: 'none' }} />
                <Box sx={{ minWidth: 0 }}>
                  <Box sx={{ fontSize: TYPOGRAPHY.body.size, fontWeight: 600, color: P.textPrimary, overflowWrap: 'anywhere' }}>
                    <Highlighted text={stripEmoji(h.entry.t)} tokens={tokens} />
                  </Box>
                  <Box sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>
                    {h.entry.s}
                    {h.heading ? ` › ${stripEmoji(h.heading)}` : ''}
                  </Box>
                  {h.snippet && (
                    <Box sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, mt: 0.25, overflowWrap: 'anywhere' }}>
                      <Highlighted text={stripEmoji(h.snippet)} tokens={tokens} />
                    </Box>
                  )}
                </Box>
              </Box>
            );
          })}
        </Box>
      )}
    </Dialog>
  );
};

export default DocsSearch;
