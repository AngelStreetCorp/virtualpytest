import React, { useState } from 'react';
import { Box } from '@mui/material';
import { useNavigate } from 'react-router-dom';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { TYPOGRAPHY } from '../../constants/typography';
import { notificationStore } from '../../contexts/notificationStore';
import { useI18n } from '../../i18n/useI18n';
import { formatAgo } from '../dashboard/dashboardFormat';
import type { DigestSelection } from './notificationDigestLogic';

/**
 * The body of the 24 h digest toast (TASK-166).
 *
 * Presentational only: the toast itself is raised by the toast context (contract #43 — no bare
 * react-hot-toast call outside it). One line of plain text, the colour says the severity, and a
 * small caret opens the three problems, each one click from the page that shows the cause.
 */
export const DigestToastBody: React.FC<{ selection: DigestSelection; onDismiss: () => void }> = ({ selection, onDismiss }) => {
  const P = useAgentChatPalette();
  const { t, tn } = useI18n();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const countText =
    selection.severity === 'error'
      ? tn(selection.total, '{count} error', '{count} errors', { count: selection.total })
      : tn(selection.total, '{count} warning', '{count} warnings', { count: selection.total });
  const oldest = selection.items[selection.items.length - 1];
  const ageText = t('{ago} ago', { ago: formatAgo(new Date(oldest.ts).toISOString(), Date.now(), t) });

  const openItem = (id: string, to?: string) => {
    notificationStore.markRead(id);
    onDismiss();
    if (to) navigate(to);
  };

  return (
    // z-index: the toasts are painted in DOM order, so without this the next toast in the stack
    // covers the list the caret opens. The wrapper is positioned, so the z-index applies.
    <Box data-vpt-digest="1" sx={{ position: 'relative', display: 'flex', alignItems: 'center', gap: 1 }}>
      <Box
        role="link"
        tabIndex={0}
        onClick={() => {
          onDismiss();
          navigate('/notifications');
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onDismiss();
            navigate('/notifications');
          }
        }}
        sx={{ cursor: 'pointer', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', '&:hover': { textDecoration: 'underline' }, '&:focus-visible': { outline: `2px solid ${P.accentText}`, outlineOffset: 2 } }}
      >
        <Box component="span" sx={{ fontWeight: 700 }}>
          {countText}
        </Box>{' '}
        <Box component="span" sx={{ opacity: 0.7 }}>
          {ageText}
        </Box>
      </Box>
      <Box
        role="button"
        tabIndex={0}
        aria-label={t('Show the problems')}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setOpen((v) => !v);
          }
        }}
        sx={{ cursor: 'pointer', display: 'flex', alignItems: 'center', opacity: 0.7, '&:hover': { opacity: 1 }, '&:focus-visible': { outline: `2px solid ${P.accentText}`, outlineOffset: 2 } }}
      >
        <Box
          component="span"
          sx={{
            width: 6,
            height: 6,
            borderRight: '1.5px solid currentColor',
            borderBottom: '1.5px solid currentColor',
            transform: open ? 'rotate(-135deg) translateY(-2px)' : 'rotate(45deg) translateY(-2px)',
          }}
        />
      </Box>
      {open && (
        <Box
          sx={{
            position: 'absolute',
            top: 'calc(100% + 6px)',
            right: 0,
            minWidth: 280,
            maxWidth: 'min(92vw, 380px)',
            bgcolor: P.surfaceSolid,
            color: P.textPrimary,
            border: `1px solid ${P.borderColor}`,
            borderRadius: '8px',
            boxShadow: '0 6px 18px rgba(0, 0, 0, 0.35)',
            zIndex: 10,
            overflow: 'hidden',
          }}
        >
          {selection.items.map((n) => (
            <Box
              key={n.id}
              role={n.to ? 'link' : undefined}
              tabIndex={0}
              onClick={() => openItem(n.id, n.to)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  openItem(n.id, n.to);
                }
              }}
              sx={{
                display: 'flex',
                alignItems: 'baseline',
                gap: 1,
                px: 1.5,
                py: 0.75,
                borderBottom: `1px solid ${P.borderColor}`,
                cursor: n.to ? 'pointer' : 'default',
                '&:hover': { bgcolor: P.hoverBg },
                '&:focus-visible': { outline: `2px solid ${P.accentText}` },
              }}
            >
              <Box sx={{ flex: 1, minWidth: 0, fontSize: TYPOGRAPHY.caption.size, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {n.message}
              </Box>
              <Box sx={{ flexShrink: 0, fontSize: TYPOGRAPHY.microMeta.size, color: P.textMuted }}>
                {formatAgo(new Date(n.ts).toISOString(), Date.now(), t)}
              </Box>
            </Box>
          ))}
        </Box>
      )}
    </Box>
  );
};

export default DigestToastBody;
