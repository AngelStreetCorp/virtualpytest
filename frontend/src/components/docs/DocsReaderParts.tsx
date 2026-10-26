import { Box, Typography } from '@mui/material';
import { CheckOutlined, ContentCopyOutlined, LinkOutlined } from '@mui/icons-material';
import React, { useEffect, useRef, useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { useI18n } from '../../i18n/useI18n';
import { stripEmojiNode } from './docsText';

/** Copies text; true when the clipboard accepted it. Falls back to execCommand on insecure origins. */
export const copyText = async (text: string): Promise<boolean> => {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand('copy');
      ta.remove();
      return ok;
    } catch {
      return false;
    }
  }
};

/** True for a short while after `flash()`; the "Copied" tick on copy buttons. */
export const useFlash = (ms = 1500): [boolean, () => void] => {
  const [on, setOn] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  return [
    on,
    () => {
      setOn(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setOn(false), ms);
    },
  ];
};

/** Fenced code block with a Copy button in the corner (visible on hover, always on touch). */
export const DocsCodeBlock: React.FC<{ text: string; children: React.ReactNode }> = ({ text, children }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [copied, flash] = useFlash();
  return (
    <Box sx={{ position: 'relative', my: 1.5, minWidth: 0, maxWidth: '100%', '&:hover .docs-copy, &:focus-within .docs-copy': { opacity: 1 } }}>
      <Box
        component="pre"
        sx={{ backgroundColor: 'action.hover', p: 1.5, pr: 9, borderRadius: 1, overflowX: 'auto', maxWidth: '100%', m: 0, border: 1, borderColor: 'divider' }}
      >
        {children}
      </Box>
      <Box
        component="button"
        type="button"
        className="docs-copy"
        aria-label={t('Copy code')}
        onClick={async () => { if (await copyText(text)) flash(); }}
        sx={{
          position: 'absolute',
          top: 6,
          right: 6,
          display: 'inline-flex',
          alignItems: 'center',
          gap: 0.5,
          px: 0.75,
          py: 0.25,
          minWidth: 64,
          justifyContent: 'center',
          border: `1px solid ${P.borderColor}`,
          borderRadius: 1,
          bgcolor: P.surface,
          color: copied ? P.accentText : P.textSecondary,
          fontSize: TYPOGRAPHY.caption.size,
          cursor: 'pointer',
          // Hover-only on a pointer device, always there on touch where there is no hover.
          opacity: 0,
          '@media (hover: none)': { opacity: 1 },
          '&:focus-visible': { opacity: 1, outline: `2px solid ${P.accent}` },
          '&:hover': { bgcolor: P.hoverBg },
        }}
      >
        {copied ? <CheckOutlined sx={{ fontSize: TYPOGRAPHY.body.size }} /> : <ContentCopyOutlined sx={{ fontSize: TYPOGRAPHY.body.size }} />}
        {copied ? t('Copied') : t('Copy')}
      </Box>
    </Box>
  );
};

/** A heading with a link icon that appears on hover and copies the deep link to it. */
export const DocsHeading: React.FC<{
  id: string;
  variant: 'h4' | 'h5' | 'h6' | 'subtitle1';
  component: 'h1' | 'h2' | 'h3' | 'h4';
  sx: object;
  children: React.ReactNode;
}> = ({ id, variant, component, sx, children }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [copied, flash] = useFlash();
  const copy = async (e: React.MouseEvent) => {
    e.preventDefault();
    const url = `${window.location.origin}${window.location.pathname}${window.location.search}#${id}`;
    window.history.replaceState(null, '', `#${id}`);
    if (await copyText(url)) flash();
  };
  return (
    <Typography id={id} variant={variant} component={component} gutterBottom sx={{ ...sx, '&:hover .docs-anchor, &:focus-within .docs-anchor': { opacity: 1 } }}>
      {stripEmojiNode(children)}
      {id && (
        <Box
          component="a"
          href={`#${id}`}
          className="docs-anchor"
          onClick={copy}
          aria-label={t('Copy link to this section')}
          title={copied ? t('Copied') : t('Copy link to this section')}
          sx={{
            display: 'inline-flex',
            verticalAlign: 'middle',
            ml: 0.75,
            color: copied ? P.accentText : P.textMuted,
            opacity: copied ? 1 : 0,
            '@media (hover: none)': { opacity: 0.6 },
            '&:focus-visible': { opacity: 1 },
            '&:hover': { color: P.accentText },
          }}
        >
          {copied ? <CheckOutlined sx={{ fontSize: 'inherit' }} /> : <LinkOutlined sx={{ fontSize: 'inherit' }} />}
        </Box>
      )}
    </Typography>
  );
};

/** A `<div data-technical>` block of a docs page: shown only when the reader's switch is on, marked so it reads as technical. */
export const DocsTechnicalBlock: React.FC<{ children?: React.ReactNode }> = ({ children }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  return (
    <Box sx={{ borderLeft: `3px solid ${P.borderColor}`, pl: 1.5, py: 0.5, my: 1.5 }}>
      <Typography component="div" sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, fontWeight: 600, mb: 0.5 }}>
        {t('Technical')}
      </Typography>
      {children}
    </Box>
  );
};
