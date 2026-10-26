import { ChevronLeft as PrevIcon, ChevronRight as NextIcon } from '@mui/icons-material';
import { Box, IconButton, Typography } from '@mui/material';
import React, { useCallback, useContext, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { FONT_SIZE_SCALE, TYPOGRAPHY } from '../../constants/typography';
import { useI18n } from '../../i18n/useI18n';

import { CardHeaderSlot } from './DashCard';

export const PAGED_LIST_ROW_HEIGHT = 26;
export const PAGED_LIST_ROWS = 3;

interface PagedListProps<T> {
  rows: T[];
  getKey: (row: T, index: number) => string;
  renderRow: (row: T) => React.ReactNode;
  /** Shown instead of the rows when the list is empty; a muted dash by default. */
  emptyText?: string;
}

/**
 * The one list inside a dashboard card: exactly three rows tall, whatever the count. Longer lists
 * snap three rows at a time (scroll or the ‹ › buttons); the "1–3 of 12" counter and arrows sit in the card header
 * (inline above the rows when the list is used outside a card), so a card never grows and the grid stays aligned.
 */
export function PagedList<T>({ rows, getKey, renderRow, emptyText = '—' }: PagedListProps<T>) {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const slot = useContext(CardHeaderSlot);
  const scroller = useRef<HTMLDivElement | null>(null);
  const [first, setFirst] = useState(0);
  const total = rows.length;
  const pageHeight = PAGED_LIST_ROW_HEIGHT * PAGED_LIST_ROWS;

  const onScroll = useCallback(() => {
    const el = scroller.current;
    if (el) setFirst(Math.round(el.scrollTop / PAGED_LIST_ROW_HEIGHT));
  }, []);

  const page = (direction: -1 | 1) => {
    const el = scroller.current;
    if (!el) return;
    const top = Math.max(0, el.scrollTop + direction * pageHeight);
    if (typeof el.scrollTo === 'function') el.scrollTo({ top, behavior: 'smooth' });
    else el.scrollTop = top;
  };

  if (total === 0) {
    return <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, alignSelf: 'center' }}>{emptyText}</Typography>;
  }

  const last = Math.min(first + PAGED_LIST_ROWS, total);
  const paged = total > PAGED_LIST_ROWS;

  const pager = (
    <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.25 }}>
      <Typography data-testid="paged-list-counter" sx={{ fontSize: TYPOGRAPHY.microMeta.size, color: P.textMuted }}>
        {t('{from}–{to} of {total}', { from: first + 1, to: last, total })}
      </Typography>
      <IconButton size="small" aria-label={t('Previous rows')} disabled={first <= 0} onClick={() => page(-1)} sx={{ p: 0 }}>
        <PrevIcon sx={{ fontSize: FONT_SIZE_SCALE.lg }} />
      </IconButton>
      <IconButton size="small" aria-label={t('Next rows')} disabled={last >= total} onClick={() => page(1)} sx={{ p: 0 }}>
        <NextIcon sx={{ fontSize: FONT_SIZE_SCALE.lg }} />
      </IconButton>
    </Box>
  );

  return (
    <>
      {paged && (slot ? createPortal(pager, slot) : <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>{pager}</Box>)}
      <Box
        ref={scroller}
        data-testid="paged-list-scroller"
        onScroll={onScroll}
        sx={{
          height: Math.min(total, PAGED_LIST_ROWS) * PAGED_LIST_ROW_HEIGHT,
          overflowY: paged ? 'auto' : 'hidden',
          scrollSnapType: 'y mandatory',
          overscrollBehavior: 'contain',
          scrollbarWidth: 'none',
          '&::-webkit-scrollbar': { display: 'none' },
        }}
      >
        {rows.map((row, i) => (
          <Box
            key={getKey(row, i)}
            sx={{
              height: PAGED_LIST_ROW_HEIGHT,
              boxSizing: 'border-box',
              display: 'flex',
              alignItems: 'center',
              gap: 1,
              borderTop: `1px solid ${P.borderColor}`,
              scrollSnapAlign: 'start',
              fontSize: TYPOGRAPHY.caption.size,
              minWidth: 0,
            }}
          >
            {renderRow(row)}
          </Box>
        ))}
      </Box>
    </>
  );
}
