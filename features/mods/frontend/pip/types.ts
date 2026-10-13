export interface PipSelection {
  hostName: string;
  deviceId: string;
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
}

/** Where the stream sits: bottom-left beside the remote, bottom-right alone. */
export interface StreamPosition {
  left?: string;
  right?: string;
  bottom: string;
}
