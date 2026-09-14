/**
 * Device Panels Hook
 *
 * Provides unified device control + panel visibility for any page.
 * Wraps useHostControl and useDeviceControlWithForceUnlock to avoid duplication.
 *
 * Usage:
 *   const panels = useDevicePanels({
 *     sessionId: 'my-page-session',
 *     tree_id: currentTreeId,
 *     requireTreeId: true,
 *   });
 *
 *   <DeviceControlPanels {...panels.panelProps} />
 */

import { useMemo } from 'react';
import { useHostControl } from './useHostManager';
import { useDeviceControlWithForceUnlock } from './useDeviceControlWithForceUnlock';

interface UseDevicePanelsOptions {
  sessionId: string;
  tree_id?: string;
  requireTreeId?: boolean;
  autoCleanup?: boolean;
  onControlStateChange?: (active: boolean) => void;
}

interface UseDevicePanelsReturn {
  // Device selection & control
  selectedHost: any;
  selectedDeviceId: string | null;
  isControlActive: boolean;
  isControlLoading: boolean;
  
  // Panel visibility (from HostControl)
  showRemotePanel: boolean;
  showAVPanel: boolean;
  isRemotePanelOpen: boolean;
  
  // Control methods
  handleDeviceControl: () => Promise<void>;
  handleToggleRemotePanel: () => void;
  handleDisconnectComplete: () => void;
  
  // Ready-to-use props for DeviceControlPanels component
  panelProps: {
    showRemotePanel: boolean;
    showAVPanel: boolean;
    selectedHost: any;
    selectedDeviceId: string | null;
    isControlActive: boolean;
    handleDisconnectComplete: () => void;
  };
}

/**
 * Hook that provides device control + panel visibility.
 *
 * This hook combines:
 * - useHostControl (for host/device selection and panel visibility state)
 * - useDeviceControlWithForceUnlock (for take/release control logic)
 *
 * Panel visibility is automatically managed by HostControl when control state changes.
 */
export const useDevicePanels = (options: UseDevicePanelsOptions): UseDevicePanelsReturn => {
  const {
    sessionId,
    tree_id,
    requireTreeId = false,
    autoCleanup = true,
    onControlStateChange,
  } = options;
  
  // Get host/device selection and panel visibility from HostControl
  const {
    selectedHost,
    selectedDeviceId,
    showRemotePanel,
    showAVPanel,
    isRemotePanelOpen,
    handleControlStateChange,
    handleToggleRemotePanel,
    handleDisconnectComplete,
  } = useHostControl();
  
  // Get device control logic with force unlock
  const {
    isControlActive,
    isControlLoading,
    handleDeviceControl,
  } = useDeviceControlWithForceUnlock({
    host: selectedHost,
    device_id: selectedDeviceId,
    sessionId,
    autoCleanup,
    tree_id,
    requireTreeId,
    onControlStateChange: (active: boolean) => {
      // Trigger HostManager's panel visibility logic
      handleControlStateChange(active);
      // Also call user's callback if provided
      onControlStateChange?.(active);
    },
  });
  
  // Memoize panel props to avoid unnecessary re-renders
  const panelProps = useMemo(() => ({
    showRemotePanel,
    showAVPanel,
    selectedHost,
    selectedDeviceId,
    isControlActive,
    handleDisconnectComplete,
  }), [showRemotePanel, showAVPanel, selectedHost, selectedDeviceId, isControlActive, handleDisconnectComplete]);
  
  return {
    // Device selection & control
    selectedHost,
    selectedDeviceId,
    isControlActive,
    isControlLoading,
    
    // Panel visibility
    showRemotePanel,
    showAVPanel,
    isRemotePanelOpen,
    
    // Control methods
    handleDeviceControl,
    handleToggleRemotePanel,
    handleDisconnectComplete,
    
    // Ready-to-use props for DeviceControlPanels
    panelProps,
  };
};

