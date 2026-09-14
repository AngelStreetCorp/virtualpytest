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
}

export interface UserInterfaceCreatePayload {
  name: string;
  models: string[];
  min_version?: string;
  max_version?: string;
}

export interface ApiResponse<T> {
  status: string;
  userinterface?: T;
  error?: string;
}
