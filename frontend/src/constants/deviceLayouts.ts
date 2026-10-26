import type { DeviceView, GridView, LayoutView, ViewId } from '../types/pages/deviceLayout.types';

/** A custom grid page holds at most this many devices. Further devices are the next page. */
export const CUSTOM_PAGE_MAX = 100;

/**
 * Density-aware gap for a custom grid whose visible columns-per-row is `cols`.
 *
 * Returns a pixel string because the value is consumed by MUI's `sx={{ gap }}`
 * prop, which multiplies a unitless number by the theme spacing scale
 * (`gap: 2` ⇒ 2 × 8 px = 16 px). To get an actual 2 px gap, the value has to
 * arrive as a string. Without the suffix, every band would render at 8× the
 * intended size — the wall feel at `> 8 cols` would be a 16 px gap and the
 * `≤ 4` band would balloon to 96 px.
 *
 *   - cols <= 4  -> 12 px (generous; tiles breathe, titles stay readable)
 *   - cols 5-7   -> 6  px (halved; the row already feels dense)
 *   - cols >= 8  -> 2  px (near-zero wall; the borders do the separating)
 *
 * BUG-0578: the custom grid used to hardcode `gap: 2` regardless of cols, which
 * was fine at very high densities but felt cramped at 3-4 cols. Preset views
 * (grid12 / grid24) only expose 3 or 4 cols, so they stay on the default MUI
 * `spacing={2}` and are not affected by this rule.
 */
export const previewGridGapPx = (cols: number): string => {
  if (cols <= 4) return '12px';
  if (cols < 8) return '6px';
  return '2px';
};

export const DEFAULT_CUSTOM_SHAPE = { cols: 4, rows: 4 };

/** Columns × rows, or null when the pair is not a whole-number page of 1–100 devices. */
export const customPageSize = (cols: number, rows: number): number | null => {
  if (!Number.isInteger(cols) || !Number.isInteger(rows)) return null;
  if (cols < 1 || rows < 1 || cols > CUSTOM_PAGE_MAX || rows > CUSTOM_PAGE_MAX) return null;
  const size = cols * rows;
  return size <= CUSTOM_PAGE_MAX ? size : null;
};

export const sanitizeCustomShape = (
  shape: { cols?: number; rows?: number } | null | undefined,
): { cols: number; rows: number } =>
  customPageSize(Number(shape?.cols), Number(shape?.rows)) !== null
    ? { cols: shape!.cols as number, rows: shape!.rows as number }
    : DEFAULT_CUSTOM_SHAPE;

export const GRID_VIEWS: GridView[] = [
  { kind: 'grid', id: 'grid12', label: '12 per page', pageSize: 12, glyph: { cols: 3, rows: 2 } },
  { kind: 'grid', id: 'grid24', label: '24 per page', pageSize: 24, glyph: { cols: 4, rows: 2 } },
  {
    kind: 'grid',
    id: 'gridCustom',
    label: 'Custom',
    pageSize: DEFAULT_CUSTOM_SHAPE.cols * DEFAULT_CUSTOM_SHAPE.rows,
    glyph: { ...DEFAULT_CUSTOM_SHAPE },
    custom: true,
  },
];

export const LAYOUT_VIEWS: LayoutView[] = [
  { kind: 'layout', id: 'side', label: 'Side by side', slots: 2, columns: '1fr 1fr', rows: '1fr' },
  { kind: 'layout', id: 'stack', label: 'Stacked', slots: 2, columns: '1fr', rows: '1fr 1fr' },
  { kind: 'layout', id: 'row3', label: '3 in a row', slots: 3, columns: 'repeat(3, 1fr)', rows: '1fr' },
  { kind: 'layout', id: 'grid2x2', label: 'Grid 2×2', slots: 4, columns: '1fr 1fr', rows: '1fr 1fr' },
  { kind: 'layout', id: 'grid3x2', label: 'Grid 3×2', slots: 6, columns: 'repeat(3, 1fr)', rows: '1fr 1fr' },
  { kind: 'layout', id: 'grid4x2', label: 'Grid 4×2', slots: 8, columns: 'repeat(4, 1fr)', rows: '1fr 1fr' },
  {
    kind: 'layout',
    id: 'focusBelow',
    label: 'Focus + below',
    slots: 4,
    columns: 'repeat(3, 1fr)',
    rows: '3fr 1fr',
    areas: "'s0 s0 s0' 's1 s2 s3'",
    focus: true,
  },
  {
    kind: 'layout',
    id: 'focusRight',
    label: 'Focus + right',
    slots: 4,
    columns: '3fr 1fr',
    rows: 'repeat(3, 1fr)',
    areas: "'s0 s1' 's0 s2' 's0 s3'",
    focus: true,
  },
  { kind: 'layout', id: 'one', label: 'One full', slots: 1, columns: '1fr', rows: '1fr' },
];

/** Device-page layouts. The fixed grids stay available to the group tile, which has no custom size. */
const DEVICE_PAGE_LAYOUT_IDS = ['side', 'stack', 'row3', 'one'] as const;

export const devicePageLayouts = (): LayoutView[] =>
  DEVICE_PAGE_LAYOUT_IDS.map((id) => LAYOUT_VIEWS.find((v) => v.id === id)!);

export const DEVICE_VIEWS: DeviceView[] = [...GRID_VIEWS, ...LAYOUT_VIEWS];
export const DEFAULT_VIEW_ID: ViewId = 'grid24';

export const findView = (id: string): DeviceView | undefined => DEVICE_VIEWS.find((v) => v.id === id);

/** Smallest layout that holds `count` devices — the group tile's default (TASK-76). */
export const layoutForCount = (count: number): LayoutView =>
  LAYOUT_VIEWS.find((v) => !v.focus && v.id !== 'stack' && v.slots >= count) ?? LAYOUT_VIEWS[5];

/**
 * Layouts worth offering for `count` devices (group tile View menu): every one that holds them
 * with at most count/3 slots left empty — 2 devices get Side by side / Stacked, not 3 in a row or
 * One full. Falls back to the default layout when none fits.
 */
export const layoutsForCount = (count: number): LayoutView[] => {
  const fits = LAYOUT_VIEWS.filter(
    (v) => !v.focus && v.slots >= count && v.slots - count <= Math.floor(count / 3),
  );
  return fits.length ? fits : [layoutForCount(count)];
};

/** Layout area height: the viewport minus the app bar, page header and pager. */
export const LAYOUT_STAGE_HEIGHT = 'calc(100vh - 220px)';
export const LAYOUT_STAGE_MIN_HEIGHT = 360;

/** A focus layout stretched to `count` slots (1 big + count-1 thumbnails); other layouts unchanged. */
export const fitLayout = (view: LayoutView, count: number): LayoutView => {
  if (!view.focus || count <= 1) return view;
  const thumbs = Array.from({ length: count - 1 }, (_, i) => `s${i + 1}`);
  return view.id === 'focusRight'
    ? { ...view, slots: count, rows: `repeat(${count - 1}, 1fr)`, areas: thumbs.map((s) => `'s0 ${s}'`).join(' ') }
    : {
        ...view,
        slots: count,
        columns: `repeat(${count - 1}, 1fr)`,
        areas: `'${Array(count - 1).fill('s0').join(' ')}' '${thumbs.join(' ')}'`,
      };
};
