export interface PipSelection {
  hostName: string;
  deviceId: string;
}

/**
 * Drag offset from the panel's default anchor (bottom-left or bottom-right, depending on
 * the remote). `x` is pixels right (negative = left), `y` is pixels up (negative = down).
 * null = the user has not dragged; the panel sits at its anchor. Persisted in localStorage
 * alongside the selection so the placement survives a reload.
 */
export interface PipPosition {
  x: number;
  y: number;
}

export interface PipState {
  /** The device shown, or null when PiP is closed. Kept in the browser. */
  selection: PipSelection | null;
  /** Remote shown while PiP holds control. Kept in the browser. */
  remoteVisible: boolean;
  /** PiP took control itself (and so must release it). */
  ownsControl: boolean;
  controlBusy: boolean;
  /** Devices a page in this browser controls right now, by `host:device`. */
  pageControls: Record<string, PipSelection>;
  /** User-collapsed state (independent of the panel's internal minimize). */
  collapsed: boolean;
  /** User drag offset; null = panel sits at its default anchor. */
  position: PipPosition | null;
}

/** Where the stream sits: bottom-left beside the remote, bottom-right alone. */
export interface StreamPosition {
  left?: string;
  right?: string;
  bottom: string;
}