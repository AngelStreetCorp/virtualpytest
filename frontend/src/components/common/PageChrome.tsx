/**
 * PageChrome — the shared look of list/report pages, in the app's gold palette
 * (useAgentChatPalette, light + dark): a plain page title, stat tiles, a segmented
 * switch style, and one `pageSurfaceSx` that gives every card and table on a page
 * the same hairline border, a theme-following table header and palette hover.
 *
 * Pages adopting it: wrap the page in <Box sx={pageSurfaceSx(P)}>, use <PageTitle>
 * for the heading and <StatTiles> instead of inline "label: value" stat rows.
 */
import { Box, SxProps, Theme, Typography } from '@mui/material';
import React from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';

export type Palette = ReturnType<typeof useAgentChatPalette>;

/** ≥80 green, ≥50 amber, else red — for rates given in percent (0–100). */
export const rateColor = (pct: number, P: Palette) => (pct >= 80 ? P.success : pct >= 50 ? P.warning : P.error);

/**
 * Cards: hairline border, no shadow. Tables: palette header and borders, hover tint.
 * The global table theme forces its own header and row colours, hence !important.
 * Status icons coloured `success` / `error` / `warning` take the palette tones.
 */
export const pageSurfaceSx = (P: Palette): SxProps<Theme> => ({
  '& .MuiCard-root': { borderRadius: 3, border: `1px solid ${P.borderColor}`, boxShadow: 'none' },
  '& .MuiCard-root .MuiTypography-h6': { fontSize: '1rem', fontWeight: 600 },
  '& .MuiTableContainer-root': { borderRadius: 2, borderColor: P.borderColor },
  '& .MuiTableCell-root': { borderColor: P.borderColor },
  '& thead .MuiTableCell-root': {
    fontSize: '0.75rem',
    color: `${P.textSecondary} !important`,
    bgcolor: `${P.hoverBg} !important`,
  },
  '& tbody .MuiTableRow-root:hover > .MuiTableCell-root': { bgcolor: `${P.hoverBg} !important` },
  '& tbody .MuiSvgIcon-colorSuccess': { color: P.success },
  '& tbody .MuiSvgIcon-colorError': { color: P.error },
  '& tbody .MuiSvgIcon-colorWarning': { color: P.warning },
  // Decorative row icons (type markers) in gold instead of MUI blue/pink.
  '& tbody .MuiSvgIcon-colorPrimary, & tbody .MuiSvgIcon-colorSecondary': { color: P.accentText },
  // Primary buttons, tabs, switches, links and dialogs get the gold accent from the theme
  // (contexts/ThemeContext.tsx); this only flattens elevated papers to the card look.
  '& .MuiPaper-root.MuiPaper-elevation:not(.MuiCard-root):not(.MuiAccordion-root)': { boxShadow: 'none', border: `1px solid ${P.borderColor}`, borderRadius: '12px' },
});

/** Page title text style (same as <PageTitle>), for pages that keep their own header layout. */
export const PAGE_TITLE_SX = { fontSize: '1.5rem', fontWeight: 600, lineHeight: 1.3 } as const;

/** Segmented ToggleButtonGroup: muted track, the selected option raised in gold text. */
export const segmentedSx = (P: Palette, size: 'sm' | 'md' = 'md'): SxProps<Theme> => ({
  bgcolor: P.hoverBg,
  p: 0.375,
  borderRadius: 2,
  gap: 0.375,
  '& .MuiToggleButton-root': {
    border: '1px solid transparent !important',
    borderRadius: '6px !important',
    textTransform: 'none',
    fontSize: size === 'sm' ? 12 : 13,
    fontWeight: 500,
    color: P.textSecondary,
    py: size === 'sm' ? 0.25 : 0.4,
    px: size === 'sm' ? 1.25 : 2,
  },
  '& .MuiToggleButton-root.Mui-selected': {
    bgcolor: P.surface,
    color: P.accentText,
    fontWeight: 600,
    borderColor: `${P.borderColor} !important`,
    '&:hover': { bgcolor: P.surface },
  },
});

/** The gold filled primary action of a page (Run, Save…). */
export const goldButtonSx = (P: Palette): SxProps<Theme> => ({
  fontWeight: 600,
  textTransform: 'none',
  boxShadow: 'none',
  bgcolor: P.accent,
  color: '#1a1a1a',
  '&:hover': { bgcolor: P.accentHover, boxShadow: 'none' },
  '&.Mui-disabled': { bgcolor: P.hoverBg, color: P.textMuted },
});

/** Page heading with an optional subtitle and a right-aligned slot (switches, actions). */
export const PageTitle: React.FC<{ title: React.ReactNode; subtitle?: React.ReactNode; right?: React.ReactNode }> = ({
  title,
  subtitle,
  right,
}) => {
  const P = useAgentChatPalette();
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1, flexWrap: 'wrap', mb: 1.5 }}>
      <Box sx={{ minWidth: 0 }}>
        <Typography component="h1" sx={{ fontSize: '1.5rem', fontWeight: 600, lineHeight: 1.3 }}>{title}</Typography>
        {subtitle && <Typography sx={{ fontSize: '0.8rem', color: P.textMuted }}>{subtitle}</Typography>}
      </Box>
      {right && <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>{right}</Box>}
    </Box>
  );
};

export interface StatTile {
  label: string;
  value: React.ReactNode;
  /** Value colour; defaults to the primary text colour. */
  color?: string;
  /** Small muted text after the value (e.g. a percentage). */
  extra?: React.ReactNode;
  onClick?: () => void;
  active?: boolean;
  title?: string;
  /** Small lines under the value (a comparison, a cause, a link). */
  footer?: React.ReactNode;
}

/** A row of stat tiles (label over a large value) that wraps on narrow screens. */
export const StatTiles: React.FC<{ tiles: StatTile[]; sx?: SxProps<Theme>; large?: boolean; columns?: number }> = ({ tiles, sx, large, columns }) => {
  const P = useAgentChatPalette();
  // `columns` fills the row evenly (2 per row on a phone); without it tiles wrap at their minimum width.
  const template = columns
    ? { xs: 'repeat(2, minmax(0, 1fr))', md: `repeat(${columns}, minmax(0, 1fr))` }
    : 'repeat(auto-fill, minmax(' + (large ? 220 : 140) + 'px, 1fr))';
  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: template, gap: large ? 1.5 : 1, mb: 1.5, ...(sx as object) }}>
      {tiles.map((t) => (
        <Box
          key={t.label}
          onClick={t.onClick}
          title={t.title}
          sx={{
            px: large ? 2.5 : 1.5,
            py: large ? 1.75 : 0.9,
            borderRadius: 2,
            bgcolor: P.surface,
            border: `1px solid ${t.active ? t.color || P.accent : P.borderColor}`,
            cursor: t.onClick ? 'pointer' : 'default',
            transition: 'none',
            '&:hover': t.onClick ? { borderColor: t.color || P.accent } : undefined,
          }}
        >
          <Typography noWrap sx={{ fontSize: large ? '0.9rem' : '0.72rem', color: P.textMuted }}>{t.label}</Typography>
          <Typography sx={{ overflowWrap: 'anywhere', fontSize: large ? (typeof t.value === 'string' && t.value.length > 8 ? '1.35rem' : '2rem') : '1.25rem', fontWeight: 600, lineHeight: 1.3, fontVariantNumeric: 'tabular-nums', color: t.color || P.textPrimary }}>
            {t.value}
            {t.extra != null && (
              <Box component="span" sx={{ fontSize: '0.75rem', fontWeight: 400, color: P.textMuted, ml: 0.75 }}>{t.extra}</Box>
            )}
          </Typography>
          {t.footer != null && <Box sx={{ mt: 0.25 }}>{t.footer}</Box>}
        </Box>
      ))}
    </Box>
  );
};
