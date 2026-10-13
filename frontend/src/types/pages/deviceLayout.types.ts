/** Device page view (TASK-75): a scrolling grid with a page size, or a layout that fits the screen. */
export type GridViewId = 'grid12' | 'grid24' | 'grid48';
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
  /** Glyph shape only: columns × rows of little cells. */
  glyph: { cols: number; rows: number };
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
