import { ChevronRight as GoIcon } from '@mui/icons-material';
import { Box, CircularProgress, Typography } from '@mui/material';
import React, { createContext, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { AppIcon, type AppIconName } from '../../constants/icons';
import { FONT_SIZE_SCALE, TYPOGRAPHY } from '../../constants/typography';

/** The two height tokens: list / chart cards, and KPI tiles (also the slim band). Rows align and a card never grows. */
export const DASH_CARD_HEIGHT = 128;
export const DASH_KPI_HEIGHT = 64;
/** Header row of a card; header + body is ONE block, centred in the card (UI_STYLE 16). A chart card gives its body DASH_CHART_BODY. */
export const DASH_CARD_HEADER = 22;
export const DASH_CHART_BODY = 86;

/** A dashboard is the cockpit: a link that leaves it opens a new tab. Tab switches are the only in-app navigation. */
export const NEW_TAB = { target: '_blank', rel: 'noopener noreferrer' } as const;
/** Gap between cards, in theme spacing units (1.25 = 10 px). */
export const DASH_GRID_GAP = 1.25;

/** The right-hand end of a card header: a PagedList puts its counter and arrows there. */
export const CardHeaderSlot = createContext<HTMLElement | null>(null);

interface DashCardProps {
  title: string;
  /** Where the title leads (the page that answers the follow-up question). */
  href: string;
  /** Source block state: loading spinner, or a plain "no data" line, instead of the body. */
  state: 'ready' | 'loading' | 'error';
  children: React.ReactNode;
  testId?: string;
  /** Short shell for a band (a slim full-width card). */
  slim?: boolean;
  /** A fixed body height (a chart, which has no natural height); every other body is as tall as its content. */
  bodyHeight?: number;
  /** Overrides the card height (a `table` card sizes itself to its rows). */
  height?: number;
  /** One short line for a source that failed; omitted = a muted dash. */
  errorText?: string;
}

/** Shell of one card: fixed height, hairline, title that is a link, honest loading / no-data states. */
export const DashCard: React.FC<DashCardProps> = ({ title, href, state, children, testId, slim, errorText, height, bodyHeight }) => {
  const P = useAgentChatPalette();
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  return (
    <Box
      data-testid={testId}
      sx={{
        height: height ?? (slim ? DASH_KPI_HEIGHT : DASH_CARD_HEIGHT),
        boxSizing: 'border-box',
        bgcolor: P.surface,
        border: `1px solid ${P.borderColor}`,
        borderRadius: 3,
        px: 1.25,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        overflow: 'hidden',
        minWidth: 0,
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1, height: DASH_CARD_HEADER, flexShrink: 0 }}>
        <Box
          component={RouterLink}
          to={href}
          {...NEW_TAB}
          sx={{
            display: 'inline-flex',
            alignItems: 'center',
            minWidth: 0,
            color: P.textSecondary,
            textDecoration: 'none',
            fontSize: TYPOGRAPHY.caption.size,
            fontWeight: 600,
            '&:hover': { color: P.accentText },
          }}
        >
          <span>{title}</span>
          <GoIcon sx={{ fontSize: FONT_SIZE_SCALE.md }} />
        </Box>
        <Box ref={setSlot} sx={{ display: 'inline-flex', alignItems: 'center' }} />
      </Box>
      <Box sx={{ flex: 'none', height: bodyHeight, minHeight: 0, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
        {state === 'loading' && (
          <Box sx={{ m: 'auto' }}>
            <CircularProgress size={16} />
          </Box>
        )}
        {state === 'error' && <NoData text={errorText} />}
        <CardHeaderSlot.Provider value={slot}>{state === 'ready' && children}</CardHeaderSlot.Provider>
      </Box>
    </Box>
  );
};

/** Empty state, centred in the card: one muted dash by default; a short line only where the caller says so (a system card with no source). */
export const NoData: React.FC<{ text?: string }> = ({ text = '—' }) => {
  const P = useAgentChatPalette();
  return <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted, alignSelf: 'center' }}>{text}</Typography>;
};

interface KpiTileProps {
  to: string;
  /** Already translated. One or two words. */
  label: string;
  icon: AppIconName;
  value: React.ReactNode;
  /** Value colour; default primary text. */
  color?: string;
  /** Tiny one-line detail beside the number; leave out when there is nothing to say. */
  sub?: string;
  /** Pass-rate style history, 0-100. */
  spark?: number[];
  testId?: string;
}

/** Quarter-width KPI tile: label row and value row are ONE block (label above value, a small fixed gap) centred in the tile both ways: vertically AND horizontally (UI_STYLE §16); the whole tile is the link and opens in a new tab. */
export const KpiTile: React.FC<KpiTileProps> = ({ to, label, icon, value, color, sub, spark, testId }) => {
  const P = useAgentChatPalette();
  return (
    <Box
      component={RouterLink}
      to={to}
      {...NEW_TAB}
      data-testid={testId}
      sx={{
        height: DASH_KPI_HEIGHT,
        boxSizing: 'border-box',
        bgcolor: P.surface,
        border: `1px solid ${P.borderColor}`,
        borderRadius: 3,
        px: 1.25,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        alignItems: 'center',
        textAlign: 'center',
        gap: 0.5,
        minWidth: 0,
        color: P.textPrimary,
        textDecoration: 'none',
        '&:hover': { borderColor: P.accentText },
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, color: P.textSecondary, fontSize: TYPOGRAPHY.caption.size, fontWeight: 600 }}>
        <Box sx={{ width: 20, height: 20, borderRadius: 1, bgcolor: P.hoverBg, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
          <AppIcon name={icon} color={P.accentText} />
        </Box>
        <span>{label}</span>
      </Box>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 1, minWidth: 0, maxWidth: '100%' }}>
        <Box component="span" sx={{ fontSize: FONT_SIZE_SCALE.h1, fontWeight: 600, lineHeight: 1.1, color: color ?? P.textPrimary }}>
          {value}
        </Box>
        {spark && spark.length >= 2 ? (
          <Sparkline points={spark} />
        ) : sub ? (
          <Box component="span" sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textMuted }}>
            {sub}
          </Box>
        ) : null}
      </Box>
    </Box>
  );
};

/** Tiny trend line for a tile: no axes, the number next to it carries the meaning. */
export const Sparkline: React.FC<{ points: number[] }> = ({ points }) => {
  const P = useAgentChatPalette();
  const step = 100 / (points.length - 1);
  const poly = points.map((p, i) => `${(i * step).toFixed(1)},${(28 - (p / 100) * 26).toFixed(1)}`).join(' ');
  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" width="44%" height="22" aria-hidden="true" style={{ flexShrink: 0 }}>
      <polyline fill="none" stroke={P.accentText} strokeWidth="1.5" vectorEffect="non-scaling-stroke" points={poly} />
    </svg>
  );
};

/** A number that is a deep link: it leads to the page filtered to what the number counts. */
export const StatLink: React.FC<{ to: string; value: React.ReactNode; label?: string; color?: string; big?: boolean }> = ({
  to,
  value,
  label,
  color,
  big,
}) => {
  const P = useAgentChatPalette();
  return (
    <Box
      component={RouterLink}
      to={to}
      {...NEW_TAB}
      sx={{
        color: color ?? P.textPrimary,
        textDecoration: 'none',
        display: 'inline-flex',
        alignItems: 'baseline',
        gap: 0.5,
        '&:hover .stat-value': { textDecoration: 'underline' },
      }}
    >
      <Box component="span" className="stat-value" sx={{ fontSize: big ? FONT_SIZE_SCALE.xl : FONT_SIZE_SCALE.md, fontWeight: 600, lineHeight: 1.2 }}>
        {value}
      </Box>
      {label && <Box component="span" sx={{ fontSize: TYPOGRAPHY.caption.size, color: color ?? P.textSecondary }}>{label}</Box>}
    </Box>
  );
};

/** Equal columns of one number over one word; each number is a deep link. */
export const NumberRow: React.FC<{ items: Array<{ to: string; value: React.ReactNode; label: string; color?: string }> }> = ({ items }) => {
  const P = useAgentChatPalette();
  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: `repeat(${items.length}, minmax(0, 1fr))`, gap: 1 }}>
      {items.map((it) => (
        <Box key={it.label} sx={{ minWidth: 0 }}>
          <StatLink to={it.to} value={it.value} color={it.color} big />
          <Typography sx={{ fontSize: TYPOGRAPHY.caption.size, color: P.textSecondary }}>{it.label}</Typography>
        </Box>
      ))}
    </Box>
  );
};

/** Horizontal meter. The caller passes the tone colour AND prints the value next to it (colour is never alone). */
export const Meter: React.FC<{ pct: number; color: string }> = ({ pct, color }) => {
  const P = useAgentChatPalette();
  return (
    <Box data-measure sx={{ height: 4, borderRadius: 2, bgcolor: P.hoverBg, overflow: 'hidden' }}>
      <Box sx={{ height: '100%', width: `${Math.max(0, Math.min(100, pct))}%`, bgcolor: color }} />
    </Box>
  );
};

/** One row: leading shape, name (link), right-hand detail. */
export const RowLink: React.FC<{ to: string; lead?: React.ReactNode; name: string; detail?: string; mono?: boolean }> = ({
  to,
  lead,
  name,
  detail,
  mono,
}) => {
  const P = useAgentChatPalette();
  return (
    <Box
      component={RouterLink}
      to={to}
      {...NEW_TAB}
      sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%', minWidth: 0, color: P.textPrimary, textDecoration: 'none', '&:hover': { color: P.accentText } }}
    >
      {lead}
      <Typography noWrap sx={{ flex: 1, minWidth: 0, fontSize: TYPOGRAPHY.caption.size, fontFamily: mono ? 'monospace' : undefined }}>
        {name}
      </Typography>
      {detail && (
        <Typography noWrap sx={{ fontSize: TYPOGRAPHY.microMeta.size, color: P.textMuted, maxWidth: '55%' }}>
          {detail}
        </Typography>
      )}
    </Box>
  );
};
