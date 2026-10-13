export type ScreenViewMode = 'stream' | 'screenshot' | 'capture';
export type StreamStatus = 'running' | 'stopped' | 'unknown';

export interface LayoutConfig {
  minHeight: string;
  aspectRatio: string;
  objectFit: 'cover';
  isMobileModel: boolean;
}

export interface DeviceResolution {
  width: number;
  height: number;
}

export interface ResolutionInfo {
  device: { width: number; height: number } | null;
  capture: string | null;
  stream: string | null;
}

export interface SelectedArea {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface CaptureImageState {
  ref?: React.RefObject<HTMLImageElement>;
  dimensions?: { width: number; height: number };
  sourcePath?: string;
}

export interface RecordingTimerProps {
  isCapturing: boolean;
}

export interface OverlayProps {
  isCapturing?: boolean;
  isScreenshotLoading?: boolean;
  streamStatus?: StreamStatus;
  recordingTime?: number;
}

// User Interface Types
export interface UserInterface {
  id: string;
  name: string;
  models: string[];
  min_version: string;
  max_version: string;
  created_at: string;
  updated_at: string;
  // Dev/prod lifecycle: 'dev' = editable working copy (default), 'prod' =
  // published read-only snapshot sharing the dev row's name.
  mode?: 'dev' | 'prod';
  dev_userinterface_id?: string | null;
  published_at?: string | null;
  published_version?: number | null;
  root_tree?: {
    id: string;
    name: string;
  } | null;
  // Free-text company label, surfaced in the editor as an optional input and
  // consumed by the monitor to boost brand-specific OCR keywords. NULL =
  // unknown company, treated as today (no boost, no behaviour change).
  company?: string | null;
  // Boolean media-surface flag. TRUE marks the UI as a media surface (TV
  // channels, streaming apps, HDMI inputs) — the monitor's Tier-2 `playback`
  // arm can answer 'playing' / 'paused' / 'stopped' on it. FALSE marks it as
  // explicitly not media (settings pages, app grids, game UIs) — playback
  // answers 'not_applicable'. NULL = editor has not made a choice; the
  // monitor abstains to 'unknown' and behaviour is identical to today.
  is_media?: boolean | null;
}

export interface UserInterfaceCreatePayload {
  name: string;
  models: string[];
  min_version?: string;
  max_version?: string;
  // Optional, free-text. Sent verbatim; the backend persists it (NULL when
  // absent or empty) and the monitor reads it through the userinterface
  // record. No enum, no normalisation, no vendor registry.
  company?: string;
  // Optional, boolean. Explicit 'is this UI a media surface?' choice. NULL
  // is the safe default (never set on a pre-existing row); TRUE opts the UI
  // into the 'playing' / 'paused' / 'stopped' arm; FALSE opts it into
  // 'not_applicable'. A missing key leaves the row unchanged on update; an
  // explicit `null` clears the column.
  is_media?: boolean | null;
}

export interface ApiResponse<T> {
  status: string;
  userinterface?: T;
  error?: string;
}
