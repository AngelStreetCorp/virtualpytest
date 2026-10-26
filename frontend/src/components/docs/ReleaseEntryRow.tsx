import { Box, Collapse, Typography } from '@mui/material';
import { ExpandMore } from '@mui/icons-material';
import React, { useState } from 'react';
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';
import type { Entry } from './releaseNotesParser';
import { TYPOGRAPHY } from '../../constants/typography';

export const urlTransform = (url: string) => (url.startsWith('data:image/') ? url : defaultUrlTransform(url));

export const Chip: React.FC<{ children: React.ReactNode; accent?: boolean }> = ({ children, accent }) => {
  const P = useAgentChatPalette();
  return (
    <Box
      component="span"
      sx={{
        px: 0.6,
        borderRadius: 0.75,
        border: 1,
        borderColor: accent ? P.accent : P.borderColor,
        color: accent ? P.accentText : P.textMuted,
        fontSize: TYPOGRAPHY.microMeta.size,
        fontWeight: 600,
        whiteSpace: 'nowrap',
      }}
    >
      {children}
    </Box>
  );
};

/** One line: bug id column, title (ellipsis), TASK / migration chips; the row opens the write-up. */
export const EntryRow: React.FC<{ entry: Entry; components: Record<string, any> }> = ({ entry, components }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const { bug, task, commit, migration, summary, details } = entry;
  const canOpen = Boolean(details);
  return (
    <Box>
      <Box
        role={canOpen ? 'button' : undefined}
        tabIndex={canOpen ? 0 : undefined}
        aria-expanded={canOpen ? open : undefined}
        onClick={canOpen ? () => setOpen((v) => !v) : undefined}
        onKeyDown={
          canOpen
            ? (e: React.KeyboardEvent) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  setOpen((v) => !v);
                }
              }
            : undefined
        }
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          px: 1,
          py: 0.25,
          borderRadius: 0.5,
          cursor: canOpen ? 'pointer' : 'default',
          fontSize: TYPOGRAPHY.body.size,
          '&:hover': { bgcolor: P.hoverBg },
          '&:focus-visible': { outline: '1px solid', outlineColor: P.accent },
        }}
      >
        {bug && (
          <Box component="span" sx={{ color: P.textSecondary, fontFamily: 'monospace', fontSize: TYPOGRAPHY.caption.size, minWidth: 64 }}>
            {bug}
          </Box>
        )}
        <Box component="span" sx={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {summary.replace(/[*`]/g, '').replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')}
        </Box>
        {(task || commit || migration) && (
          <Box component="span" sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary, whiteSpace: 'nowrap' }}>
            {task || commit}
            {(task || commit) && migration && ' · '}
            {migration && <Box component="span" sx={{ color: P.accentText }}>{t('migration')}</Box>}
          </Box>
        )}
        {canOpen && (
          <ExpandMore sx={{ fontSize: TYPOGRAPHY.navbarItem.size, color: P.textMuted, transform: open ? 'rotate(180deg)' : 'none' }} />
        )}
      </Box>
      {canOpen && (
        <Collapse in={open} unmountOnExit>
          <Box sx={{ pl: 1, pr: 1, pb: 1, fontSize: TYPOGRAPHY.caption.size, lineHeight: 1.5, color: P.textPrimary, '& p': { my: 0.5 }, '& p, & li, & span, & a, & strong, & em': { fontSize: 'inherit', lineHeight: 'inherit' }, '& code': { fontSize: TYPOGRAPHY.caption.size } }}>
            <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]} urlTransform={urlTransform} components={components}>
              {details
                .split(' · ')
                .filter((seg) => !/DB migration/.test(seg))
                .join(' · ')}
            </ReactMarkdown>
          </Box>
        </Collapse>
      )}
    </Box>
  );
};

/** A titled list of rows, cut to `limit` with a "Show all N" link. */
export const EntryList: React.FC<{
  heading: React.ReactNode | null;
  entries: Entry[];
  components: Record<string, any>;
  limit?: number;
}> = ({ heading, entries, components, limit = 5 }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [count, setCount] = useState(limit);
  const [folded, setFolded] = useState(false);
  if (entries.length === 0) return null;
  const shown = entries.slice(0, count);
  return (
    <Box sx={{ mt: 1.25 }}>
      {heading !== null && (
      <Typography
        role="button"
        tabIndex={0}
        aria-expanded={!folded}
        onClick={() => setFolded((v) => !v)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setFolded((v) => !v);
          }
        }}
        sx={{ cursor: 'pointer', userSelect: 'none', fontWeight: 600, fontSize: TYPOGRAPHY.caption.size, letterSpacing: '0.04em', textTransform: 'uppercase', color: P.textSecondary, display: 'flex', alignItems: 'center', gap: 0.75, mb: 0.25 }}>
        <ExpandMore sx={{ fontSize: TYPOGRAPHY.navbarItem.size, transform: folded ? 'rotate(-90deg)' : 'none' }} />
        {heading}
        <Box component="span">· {entries.length}</Box>
      </Typography>
      )}
      {!folded && shown.map((e, i) => (
        <EntryRow key={i} entry={e} components={components} />
      ))}
      {!folded && entries.length > limit && (
        <Box sx={{ display: 'flex', gap: 2, px: 1, py: 0.5 }}>
          {count < entries.length && entries.length - count > 50 && (
            <Box component="button" onClick={() => setCount((c) => c + 50)} sx={{ border: 0, background: 'none', color: P.accentText, cursor: 'pointer', fontSize: TYPOGRAPHY.caption.size, p: 0 }}>
              {t('Show 50 more')}
            </Box>
          )}
          {count < entries.length && (
            <Box component="button" onClick={() => setCount(entries.length)} sx={{ border: 0, background: 'none', color: P.accentText, cursor: 'pointer', fontSize: TYPOGRAPHY.caption.size, p: 0 }}>
              {t('Show all {count}', { count: entries.length })}
            </Box>
          )}
          {count > limit && (
            <Box component="button" onClick={() => setCount(limit)} sx={{ border: 0, background: 'none', color: P.accentText, cursor: 'pointer', fontSize: TYPOGRAPHY.caption.size, p: 0 }}>
              {t('Show fewer')}
            </Box>
          )}
        </Box>
      )}
    </Box>
  );
};
