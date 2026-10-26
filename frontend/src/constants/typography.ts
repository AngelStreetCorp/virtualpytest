/**
 * Centralised typography scale (TASK-100). One number per slot, every place in the UI reads
 * from the same source — change a size in `typography.ts` and every consuming surface updates.
 *
 * The scale is rem-based so the whole UI follows the html root size (and any future OS
 * "bigger text" setting). Three layers:
 *
 *   1. `FONT_SIZE_SCALE`, `FONT_WEIGHT_SCALE`, `LINE_HEIGHT_SCALE` — the raw scale.
 *   2. `TYPOGRAPHY` — role → slot table: every named place a label can live (navbar item,
 *      card title, dialog title, table row, body paragraph, kpi value...) has one entry.
 *      Consumers do `fontSize: TYPOGRAPHY.cardTitle.size` or `sx={{ ...pageTitleSx(P) }}`.
 *   3. `SIZE_IDS` + `sizeMultiplier` — the user knob. Three steps (sm/md/lg). The user's
 *      choice multiplies each role's size in one place (the CSS custom prop `--app-font-scale`)
 *      so the whole UI moves together without touching each `sx={{ fontSize }}`.
 *
 * `useTypography()` (in `contexts/ThemeContext.tsx`) reads the active size and exposes it.
 * `TypographyContext.tsx` mirrors that and re-publishes a `pageTitleSx(P)` / `cardTitleSx(P)` /
 * etc. shorthand so a `<Box sx={pageTitleSx(P)}>` does not pay a hook call.
 *
 * MUI's `theme.typography` is wired to the scale, so `<Typography variant="h5">` etc. follow
 * it automatically. The `ui-check no-literal-font-size` ratchet forbids new literal sizes in
 *     `frontend/src/**`; migrate new code by reading a slot from this file.
 */
import type { SxProps, Theme } from '@mui/material';

// ---- raw scales --------------------------------------------------------------------------------

/** rem values. 1 rem = the html root font-size (MUI default = 16 px). */
export const FONT_SIZE_SCALE = {
  xxs:  '0.625rem',  // 10 px  – only the smallest KPIs / timestamps get this
  xs:   '0.6875rem', // 11 px  – micro meta, status row timestamps, MUI overline
  sm:   '0.75rem',   // 12 px  – chip, list metadata, toolbar label, MUI caption, MUI tooltip
  body: '0.8125rem', // 13 px  – the one default for table rows, list items, form labels, button text
  md:   '0.875rem',  // 14 px  – body paragraph, modal title, dropdown items, navbar label
  lg:   '1rem',      // 16 px  – section / card title, page subtitle, dialog title (small)
  xl:   '1.125rem',  // 18 px  – page subtitle, dialog title (default)
  h1:   '1.5rem',    // 24 px  – <PageTitle>, the page heading
  h2:   '1.75rem',   // 28 px  – KPI value, dialog title (large)
  h3:   '2rem',      // 32 px  – large KPI value, hero number
  h4:   '2.5rem',    // 40 px  – display KPI value, hero metric
  h5:   '3rem',      // 48 px  – brand-display
  mono: '0.8125rem', // 13 px  – inline values, code
} as const;

/** Per MUI default conventions. */
export const FONT_WEIGHT_SCALE = {
  light:    300,
  regular:  400,
  medium:   500,
  semibold: 600,
  bold:     700,
} as const;

export const LINE_HEIGHT_SCALE = {
  tight:  1.2,
  snug:   1.3,
  normal: 1.5,
  loose:  1.7,
} as const;

// ---- role → slot table -------------------------------------------------------------------------

/** Every named place a label can live in the UI. Read this in `sx={{ fontSize }}`, NOT a literal.
 *  When a new slot is needed, add it here (and explain it in docs/agent/platform/UI_STYLE.md). */
export interface TypeRole {
  size: string;        // FONT_SIZE_SCALE
  weight: number;      // FONT_WEIGHT_SCALE
  lineHeight: number;  // LINE_HEIGHT_SCALE
}

export const TYPOGRAPHY = {
  navbarItem:        { size: FONT_SIZE_SCALE.md,    weight: FONT_WEIGHT_SCALE.medium,   lineHeight: LINE_HEIGHT_SCALE.snug  },
  navbarDropdown:    { size: FONT_SIZE_SCALE.body,  weight: FONT_WEIGHT_SCALE.medium,   lineHeight: LINE_HEIGHT_SCALE.snug  },
  pageTitle:         { size: FONT_SIZE_SCALE.h1,    weight: FONT_WEIGHT_SCALE.semibold, lineHeight: LINE_HEIGHT_SCALE.snug  },
  pageSubtitle:      { size: FONT_SIZE_SCALE.xl,    weight: FONT_WEIGHT_SCALE.regular,  lineHeight: LINE_HEIGHT_SCALE.snug  },
  sectionTitle:      { size: FONT_SIZE_SCALE.lg,    weight: FONT_WEIGHT_SCALE.semibold, lineHeight: LINE_HEIGHT_SCALE.snug  },
  cardTitle:         { size: FONT_SIZE_SCALE.md,    weight: FONT_WEIGHT_SCALE.semibold, lineHeight: LINE_HEIGHT_SCALE.snug  },
  dialogTitle:       { size: FONT_SIZE_SCALE.xl,    weight: FONT_WEIGHT_SCALE.semibold, lineHeight: LINE_HEIGHT_SCALE.snug  },
  buttonLabel:       { size: FONT_SIZE_SCALE.body,  weight: FONT_WEIGHT_SCALE.semibold, lineHeight: LINE_HEIGHT_SCALE.tight },
  tableHeader:       { size: FONT_SIZE_SCALE.sm,    weight: FONT_WEIGHT_SCALE.semibold, lineHeight: LINE_HEIGHT_SCALE.tight },
  tableBody:         { size: FONT_SIZE_SCALE.body,  weight: FONT_WEIGHT_SCALE.regular,  lineHeight: LINE_HEIGHT_SCALE.normal},
  listItem:          { size: FONT_SIZE_SCALE.body,  weight: FONT_WEIGHT_SCALE.regular,  lineHeight: LINE_HEIGHT_SCALE.normal},
  body:              { size: FONT_SIZE_SCALE.body,  weight: FONT_WEIGHT_SCALE.regular,  lineHeight: LINE_HEIGHT_SCALE.normal},
  caption:           { size: FONT_SIZE_SCALE.sm,    weight: FONT_WEIGHT_SCALE.regular,  lineHeight: LINE_HEIGHT_SCALE.snug  },
  microMeta:         { size: FONT_SIZE_SCALE.xs,    weight: FONT_WEIGHT_SCALE.regular,  lineHeight: LINE_HEIGHT_SCALE.snug  },
  kpiValue:          { size: FONT_SIZE_SCALE.h3,    weight: FONT_WEIGHT_SCALE.semibold, lineHeight: LINE_HEIGHT_SCALE.tight },
  displayKpi:        { size: FONT_SIZE_SCALE.h5,    weight: FONT_WEIGHT_SCALE.semibold, lineHeight: LINE_HEIGHT_SCALE.tight },
  code:              { size: FONT_SIZE_SCALE.mono,  weight: FONT_WEIGHT_SCALE.regular,  lineHeight: LINE_HEIGHT_SCALE.normal},
  tooltip:           { size: FONT_SIZE_SCALE.sm,    weight: FONT_WEIGHT_SCALE.regular,  lineHeight: LINE_HEIGHT_SCALE.snug  },
  menuItem:          { size: FONT_SIZE_SCALE.md,    weight: FONT_WEIGHT_SCALE.regular,  lineHeight: LINE_HEIGHT_SCALE.tight },
  toolbar:           { size: FONT_SIZE_SCALE.sm,    weight: FONT_WEIGHT_SCALE.regular,  lineHeight: LINE_HEIGHT_SCALE.snug  },
} as const;

export type TypographyRole = keyof typeof TYPOGRAPHY;

/** All role names for runtime iteration (size picker preview, doc). */
export const TYPOGRAPHY_ROLES = Object.keys(TYPOGRAPHY) as TypographyRole[];

// ---- user knob ---------------------------------------------------------------------------------

/**
 * Three size steps the user picks in Settings: S / M / L = -2 / 0 / +2 px on the 16 px html root.
 * The multiplier is applied ONCE, centrally: `--app-font-scale` sets `:root { font-size }` (index.css),
 * so every rem size in the app (TYPOGRAPHY, MUI variants, rem literals) follows. Never multiply again.
 */
export const SIZE_IDS = ['sm', 'md', 'lg'] as const;
export type SizeId = (typeof SIZE_IDS)[number];
export const DEFAULT_SIZE: SizeId = 'md';
export const SIZE_NAMES: Record<SizeId, string> = { sm: 'Small', md: 'Medium', lg: 'Large' };
export const SIZE_LABELS: Record<SizeId, string> = { sm: 'S', md: 'M', lg: 'L' };
export const SIZE_SCALE: Record<SizeId, number> = { sm: 0.875, md: 1, lg: 1.125 };

export const isSizeId = (v: unknown): v is SizeId => typeof v === 'string' && (SIZE_IDS as readonly string[]).includes(v);

// ---- Sx helpers (one call site) ---------------------------------------------------------------

/** Multiply a rem string by `m` (e.g. `'1rem'` * 0.875 → `'0.875rem'`). */
const multRem = (size: string, m: number): string => {
  if (m === 1) return size;
  const m1 = /^(-?\d+(?:\.\d+)?)rem$/.exec(size);
  if (!m1) return size;
  const n = parseFloat(m1[1]) * m;
  return `${parseFloat(n.toFixed(4))}rem`;
};

/** Convert a rem size string to its px value at the html 16-px root. Used by MUI numeric slots. */
export const remToPx = (size: string): number => {
  const m = /^(-?\d+(?:\.\d+)?)rem$/.exec(size);
  if (!m) return parseFloat(size) || 0;
  return parseFloat(m[1]) * 16;
};

/** Build a slot's Sx with the size baked in: `slotSx('pageTitle', 1)` -> `pageTitle.size`. */
export const slotSx = (role: TypographyRole, m: number = 1): SxProps<Theme> => {
  const t = TYPOGRAPHY[role];
  return {
    fontSize: multRem(t.size, m),
    fontWeight: t.weight,
    lineHeight: t.lineHeight,
  };
};

/** Same idea as `slotSx`, returned as an object consumable via `<Box sx={...}>`. */
export const slotStyle = (role: TypographyRole, m: number = 1): { fontSize: string; fontWeight: number; lineHeight: number } => {
  const t = TYPOGRAPHY[role];
  return { fontSize: multRem(t.size, m), fontWeight: t.weight, lineHeight: t.lineHeight };
};
