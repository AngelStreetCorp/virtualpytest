import { createContext } from 'react';

import { Host } from '../types/common/Host_Types';

/**
 * HostControlContext - Dynamic control state that changes frequently
 * This context is for device control operations and UI state.
 * Components that need control state will subscribe to this context.
 */
export interface HostControlContextType {
  // Panel and UI state
  selectedHost: Host | null;
  selectedDeviceId: string | null;
  isControlActive: boolean;
  isRemotePanelOpen: boolean;
  showRemotePanel: boolean;
  showAVPanel: boolean;
  isVerificationActive: boolean;

  // Device control functions
  takeControl: (
    host: Host,
    device_id?: string,
    sessionId?: string,
    tree_id?: string,
  ) => Promise<{
    success: boolean;
    error?: string;
    errorType?: string;
    details?: any;
  }>;

  releaseControl: (
    host: Host,
    device_id?: string,
    sessionId?: string,
  ) => Promise<{
    success: boolean;
    error?: string;
    errorType?: string;
    details?: any;
  }>;

  // Status checking methods
  isDeviceLocked: (host: Host | null, deviceId?: string) => boolean;
  getDeviceLockInfo: (host: Host | null, deviceId?: string) => any | null;
  canLockDevice: (host: Host | null, deviceId?: string) => boolean;
  hasActiveLock: (deviceKey: string) => boolean;

  // Panel and UI handlers
  handleDeviceSelect: (host: Host | null, deviceId: string | null) => void;
  handleControlStateChange: (active: boolean) => void;
  handleToggleRemotePanel: () => void;
  handleConnectionChange: (connected: boolean) => void;
  handleDisconnectComplete: () => void;

  // Panel and control actions
  setSelectedHost: (host: Host | null) => void;
  setSelectedDeviceId: (deviceId: string | null) => void;
  setIsControlActive: (active: boolean) => void;
  setIsRemotePanelOpen: (open: boolean) => void;
  setShowRemotePanel: (show: boolean) => void;
  setShowAVPanel: (show: boolean) => void;
  setIsVerificationActive: (active: boolean) => void;

  // Lock management
  reclaimLocks: () => Promise<boolean>;
}

export const HostControlContext = createContext<HostControlContextType | undefined>(undefined);
