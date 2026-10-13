import type { DeviceView, GridView, LayoutView, ViewId } from '../types/pages/deviceLayout.types';

/** Device page views (TASK-75). A new layout is one row here: a CSS grid, nothing else. */
export const GRID_VIEWS: GridView[] = [
  { kind: 'grid', id: 'grid12', label: '12 per page', pageSize: 12, glyph: { cols: 3, rows: 2 } },
  { kind: 'grid', id: 'grid24', label: '24 per page', pageSize: 24, glyph: { cols: 4, rows: 2 } },
  { kind: 'grid', id: 'grid48', label: '48 per page', pageSize: 48, glyph: { cols: 4, rows: 3 } },
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
