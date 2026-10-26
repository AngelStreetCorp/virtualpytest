/** Device page view (TASK-75): a scrolling grid with a page size, or a layout that fits the screen. */
export type GridViewId = 'grid12' | 'grid24' | 'gridCustom';
export type LayoutViewId =
  | 'side'
  | 'stack'
  | 'row3'
  | 'grid2x2'
  | 'grid3x2'
  | 'grid4x2'
  | 'focusBelow'
  | 'focusRight'
  | 'one';
export type ViewId = GridViewId | LayoutViewId;

export interface GridView {
  kind: 'grid';
  id: GridViewId;
  label: string;
  pageSize: number;
  /** Glyph shape only: columns × rows of little cells. For a custom grid it is the real shape. */
  glyph: { cols: number; rows: number };
  /** The operator types the columns and rows. Page size is their product, at most 100. */
  custom?: boolean;
}

export interface LayoutView {
  kind: 'layout';
  id: LayoutViewId;
  label: string;
  slots: number;
  columns: string;
  rows: string;
  /** CSS grid-template-areas; slot i sits in area `s${i}`. Omitted = slots flow in order. */
  areas?: string;
  /** Slot 0 is the big live stream; the others are snapshot thumbnails. */
  focus?: boolean;
}

export type DeviceView = GridView | LayoutView;
