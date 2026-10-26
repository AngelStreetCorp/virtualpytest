import { Download as DownloadIcon, OpenInNew as OpenInNewIcon } from '@mui/icons-material';
import { Box, IconButton } from '@mui/material';
import React, { useCallback, useLayoutEffect, useRef, useState } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { useI18n } from '../../i18n/useI18n';
import type { TimelineCell, TimelineSlot } from '../../hooks/useTimeline';
import { FlagFilter, flagOf, fmtTod, matchesFilter } from './TimelineGrid';
import { TYPOGRAPHY } from '../../constants/typography';

export type TimelineLayout = 'grid' | 'strip';
export interface SlotWindow {
  from: number;
  to: number;
}

/** Chunks kept in the page at once: each is 100 tiles (a sprite each), so the window slides instead of growing. */
export const MAX_WINDOW = 6;
const EDGE_PX = 300;
/** A portrait chunk sheet is capped in width: 10 columns of full-width tiles would be a screen and a half tall. */
const PORTRAIT_SHEET_MAX_W = 560;

interface Props {
  slots: TimelineSlot[];
  win: SlotWindow;
  layout: TimelineLayout;
  cellsFor: (slot: TimelineSlot) => TimelineCell[];
  selectedKey: string | null;
  onSelect: (key: string) => void;
  only: FlagFilter;
  onWindow: (win: SlotWindow) => void;
  onVisible: (slotIndex: number) => void;
  /** scroll this slot to the start (the window must already contain it) */
  jump: { slot: number; nonce: number } | null;
}


interface SheetProps {
  cells: TimelineCell[];
  selectedKey: string | null;
  onSelect: (key: string) => void;
  only: FlagFilter;
}

/**
 * One 10-minute chunk as ONE picture: the 10x10 sheet the host's vpt-timeline service already built (a tile per 6 s),
 * shown as it is. Click, selection, hover time and the AD / FREEZE marks are drawn over it, so the page holds one
 * image and a few boxes per chunk instead of 100 cut-up cells.
 */
const ChunkSheet: React.FC<SheetProps> = ({ cells, selectedKey, onSelect, only }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const [hover, setHover] = useState<number | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const sprite = cells[0]?.sprite?.url;
  // not built yet (the service backfills newest first): a missing file is the hatched "no picture", never a blank card
  const url = sprite && sprite !== failed ? sprite : undefined;
  const indexAt = (e: React.MouseEvent<HTMLElement>): number => {
    const r = e.currentTarget.getBoundingClientRect();
    const col = Math.min(9, Math.max(0, Math.floor(((e.clientX - r.left) / r.width) * 10)));
    const row = Math.min(9, Math.max(0, Math.floor(((e.clientY - r.top) / r.height) * 10)));
    return row * 10 + col;
  };
  const box = (i: number) => ({ position: 'absolute' as const, left: `${(i % 10) * 10}%`, top: `${Math.floor(i / 10) * 10}%`, width: '10%', height: '10%', boxSizing: 'border-box' as const });
  const selectedIndex = selectedKey ? cells.findIndex((c) => c.key === selectedKey) : -1;
  const flagged = cells.filter((c) => flagOf(c) !== null);
  const uniform = flagged.length >= cells.length * 0.9 && new Set(flagged.map((c) => flagOf(c))).size === 1;
  const aspect = cells[0]?.aspect ?? 16 / 9;
  return (
    <Box
      onClick={(e) => cells[indexAt(e)] && onSelect(cells[indexAt(e)].key)}
      onMouseMove={(e) => setHover(indexAt(e))}
      onMouseLeave={() => setHover(null)}
      sx={{
        position: 'relative', aspectRatio: String(aspect), cursor: 'pointer', bgcolor: P.hoverBg, lineHeight: 0,
        ...(aspect < 1 ? { maxWidth: PORTRAIT_SHEET_MAX_W, width: '100%' } : {}),
      }}
    >
      {url ? (
        <img src={url} alt="" draggable={false} onError={() => setFailed(sprite ?? null)} style={{ display: 'block', width: '100%', height: '100%' }} />
      ) : (
        <Box sx={{ position: 'absolute', inset: 0, backgroundImage: `repeating-linear-gradient(45deg, ${P.borderColor}, ${P.borderColor} 6px, transparent 6px, transparent 12px)` }} />
      )}
      {cells.map((c, i) => {
        if (only !== 'all' && !matchesFilter(c, only)) {
          return <Box key={c.key} sx={{ ...box(i), bgcolor: 'rgba(0,0,0,0.72)', pointerEvents: 'none' }} />;
        }
        const f = only !== 'all' ? only : flagOf(c);
        // The same state on (almost) the whole chunk is said once, in the card header; boxing every tile is noise
        // (an idle phone is "frozen" on all 100 tiles).
        if (!f || (uniform && only === 'all')) return null;
        const colour = f === 'ad' ? P.warning : P.error;
        const runStart = (only !== 'all' ? !matchesFilter(cells[i - 1], only) : flagOf(cells[i - 1]) !== f) || i % 10 === 0;
        return (
          <Box key={c.key} sx={{ ...box(i), border: `2px solid ${colour}`, pointerEvents: 'none' }}>
            {runStart && (
              <Box component="span" sx={{ position: 'absolute', left: 0, bottom: 0, fontSize: TYPOGRAPHY.microMeta.size, lineHeight: 1.3, fontWeight: 700, px: '3px', bgcolor: colour, color: f === 'ad' ? '#1a1a1a' : '#fff' }}>
                {f === 'ad' ? t('AD') : f === 'freeze' ? t('FREEZE') : t('BLACK')}
              </Box>
            )}
          </Box>
        );
      })}
      {selectedIndex >= 0 && <Box data-key={selectedKey} sx={{ ...box(selectedIndex), outline: `2px solid ${P.accent}`, outlineOffset: '-2px', pointerEvents: 'none' }} />}
      {hover !== null && cells[hover] && (
        <Box component="span" sx={{ ...box(hover), pointerEvents: 'none', fontSize: TYPOGRAPHY.microMeta.size, lineHeight: 1.4, color: '#fff', textShadow: '0 0 3px #000, 0 0 3px #000', fontVariantNumeric: 'tabular-nums', textAlign: 'right', pr: '3px' }}>
          {fmtTod(cells[hover].tod, true)}
        </Box>
      )}
    </Box>
  );
};

/**
 * The 10 min level as one continuous scroll through time: the chunks of the window follow each other (vertical
 * grid, or the same cards side by side); near an edge the previous / next 10 min is added and the far end dropped, and the
 * scroll position is kept on the chunk you were looking at.
 */
/** The chunk's sprite image (the 10x10 sheet): in a new tab, or saved as a file. */
const openSheet = (url: string) => window.open(url, '_blank', 'noopener');
const downloadSheet = async (url: string, name: string) => {
  try {
    const res = await fetch(url, { credentials: 'include' });
    if (!res.ok) throw new Error(String(res.status));
    const href = URL.createObjectURL(await res.blob());
    const a = document.createElement('a');
    a.href = href;
    a.download = name;
    a.click();
    URL.revokeObjectURL(href);
  } catch {
    openSheet(url);
  }
};

export const TimelineScroller: React.FC<Props> = ({ slots, win, layout, cellsFor, selectedKey, onSelect, only, onWindow, onVisible, jump }) => {
  const P = useAgentChatPalette();
  const { t } = useI18n();
  const box = useRef<HTMLDivElement>(null);
  const anchor = useRef<{ slot: number; offset: number } | null>(null);
  const lastVisible = useRef(-1);
  const lastJump = useRef(-1);
  const horizontal = layout === 'strip';
  const wasHorizontal = useRef(horizontal);

  const chunkEl = (slot: number) => box.current?.querySelector<HTMLElement>(`[data-slot="${slot}"]`) ?? null;
  const posOf = (el: HTMLElement) => (horizontal ? el.offsetLeft : el.offsetTop);
  const scrollPos = () => (box.current ? (horizontal ? box.current.scrollLeft : box.current.scrollTop) : 0);

  const firstVisible = useCallback((): number => {
    const el = box.current;
    if (!el) return -1;
    const at = horizontal ? el.scrollLeft : el.scrollTop;
    let best = -1;
    el.querySelectorAll<HTMLElement>('[data-slot]').forEach((c) => {
      const start = horizontal ? c.offsetLeft : c.offsetTop;
      const size = horizontal ? c.offsetWidth : c.offsetHeight;
      if (best < 0 && start + size > at + 4) best = Number(c.dataset.slot);
    });
    return best;
  }, [horizontal]);

  const onScroll = () => {
    const el = box.current;
    if (!el) return;
    const v = firstVisible();
    if (v >= 0 && v !== lastVisible.current) {
      lastVisible.current = v;
      onVisible(v);
    }
    const pos = horizontal ? el.scrollLeft : el.scrollTop;
    const size = horizontal ? el.clientWidth : el.clientHeight;
    const total = horizontal ? el.scrollWidth : el.scrollHeight;
    const keep = v >= 0 ? chunkEl(v) : null;
    const remember = () => {
      if (keep && v >= 0) anchor.current = { slot: v, offset: posOf(keep) - scrollPos() };
    };
    if (pos < EDGE_PX && win.from > 0) {
      remember();
      const from = win.from - 1;
      onWindow({ from, to: Math.min(win.to, from + MAX_WINDOW - 1) });
    } else if (pos + size > total - EDGE_PX && win.to < slots.length - 1) {
      remember();
      const to = win.to + 1;
      onWindow({ from: Math.max(win.from, to - MAX_WINDOW + 1), to });
    }
  };

  // Grid <-> strip: stay on the chunk you were looking at.
  useLayoutEffect(() => {
    if (wasHorizontal.current === horizontal) return;
    wasHorizontal.current = horizontal;
    const el = box.current;
    const target = lastVisible.current >= 0 ? chunkEl(lastVisible.current) : null;
    if (!el || !target) return;
    el.scrollTop = horizontal ? 0 : target.offsetTop;
    el.scrollLeft = horizontal ? target.offsetLeft : 0;
  }, [horizontal]);

  // After the window changed: jump to the requested slot, or keep the chunk we were looking at where it was.
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    if (jump && jump.nonce !== lastJump.current) {
      const target = chunkEl(jump.slot);
      if (target) {
        lastJump.current = jump.nonce;
        if (horizontal) el.scrollLeft = target.offsetLeft;
        else el.scrollTop = target.offsetTop;
        lastVisible.current = jump.slot;
        onVisible(jump.slot);
        anchor.current = null;
        return;
      }
    }
    if (anchor.current) {
      const a = chunkEl(anchor.current.slot);
      if (a) {
        if (horizontal) el.scrollLeft = a.offsetLeft - anchor.current.offset;
        else el.scrollTop = a.offsetTop - anchor.current.offset;
      }
      anchor.current = null;
    }
  }, [win.from, win.to, jump, horizontal]);

  // Keep the selected tile in view when the keyboard moves it.
  useLayoutEffect(() => {
    if (!selectedKey) return;
    box.current?.querySelector<HTMLElement>(`[data-key="${selectedKey}"]`)?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }, [selectedKey]);

  const blocks: React.ReactNode[] = [];
  for (let i = win.from; i <= win.to; i++) {
    const slot = slots[i];
    if (!slot) continue;
    const cells = cellsFor(slot);
    const start = slot.hour * 3600 + slot.chunkIndex * 600;
    const sheetUrl = cells.find((c) => c.sprite)?.sprite?.url;
    const range = `${fmtTod(start, false)} – ${fmtTod(start + 600, false)}`;
    const word = slot.flag === 'ad' ? t('AD') : slot.flag === 'freeze' ? t('FREEZE') : slot.flag === 'blackscreen' ? t('BLACK') : '';  // 'ok' / null: no word
    // Each 10 minutes is its own card: border, header with the range (and what dominates it), space around.
    const header = (
      <Box
        sx={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1, px: 1.5, py: 0.6,
          bgcolor: P.hoverBg, borderBottom: `1px solid ${P.borderColor}`, fontVariantNumeric: 'tabular-nums',
          ...(horizontal ? {} : { position: 'sticky', top: 0, zIndex: 2 }),
        }}
      >
        <Box component="span" sx={{ fontWeight: 600, fontSize: TYPOGRAPHY.body.size }}>{range}</Box>
        <Box component="span" sx={{ display: 'inline-flex', gap: 1, fontSize: TYPOGRAPHY.microMeta.size, color: P.textSecondary }}>
          {word && (
            <Box component="span" sx={{ fontWeight: 700, px: '5px', borderRadius: '3px', bgcolor: slot.flag === 'ad' ? P.warning : P.error, color: slot.flag === 'ad' ? '#1a1a1a' : '#fff' }}>
              {word}
            </Box>
          )}
          {!slot.has && <span>{'—'}</span>}
          {sheetUrl && (
            <>
              <IconButton size="small" sx={{ p: 0.25, color: P.textSecondary }} title={t('Open the grid image in a new tab')} aria-label={t('Open the grid image in a new tab')} onClick={() => openSheet(sheetUrl)}>
                <OpenInNewIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} />
              </IconButton>
              <IconButton size="small" sx={{ p: 0.25, color: P.textSecondary }} title={t('Download the grid image')} aria-label={t('Download the grid image')} onClick={() => downloadSheet(sheetUrl, `timeline_${range.replace(/[^0-9]/g, '').slice(0, 4)}.jpg`)}>
                <DownloadIcon sx={{ fontSize: TYPOGRAPHY.navbarItem.size }} />
              </IconButton>
            </>
          )}
        </Box>
      </Box>
    );
    blocks.push(
      <Box
        key={i}
        data-slot={i}
        sx={{
          border: `1px solid ${P.borderColor}`, borderRadius: '8px', bgcolor: P.surface, mb: horizontal ? 0 : 2.5,
          ...(horizontal ? { flex: 'none', mr: 2, width: 'calc(100% - 16px)' } : {}),
        }}
      >
        {header}
        <Box sx={{ display: 'grid', gridTemplateColumns: '44px 1fr', gap: 0.75, p: 0.75 }}>
          <Box sx={{ display: 'grid', gridTemplateRows: 'repeat(10, 1fr)', fontSize: TYPOGRAPHY.microMeta.size, color: P.textSecondary, fontVariantNumeric: 'tabular-nums', lineHeight: 1 }}>
            {Array.from({ length: 10 }, (_, r) => <Box key={r}>{fmtTod(start + r * 60, false)}</Box>)}
          </Box>
          <ChunkSheet cells={cells} selectedKey={selectedKey} onSelect={onSelect} only={only} />
        </Box>
      </Box>,
    );
  }

  return (
    <Box
      ref={box}
      onScroll={onScroll}
      sx={{
        position: 'relative',
        ...(horizontal
          ? { display: 'flex', overflowX: 'auto', overflowY: 'hidden', pb: 1 }
          : { overflowY: 'auto', height: 'calc(100vh - 380px)', minHeight: 320 }),
      }}
    >
      {blocks}
    </Box>
  );
};

export default TimelineScroller;
