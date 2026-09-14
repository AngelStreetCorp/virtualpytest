import { useState, useCallback, useEffect, useRef } from 'react';

import { Host } from '../types/common/Host_Types';

import { useHostControl } from './useHostManager';
import { useUserSession } from './useUserSession';

// ========================================
// TYPES
// ========================================

interface UseDeviceControlProps {
  host: Host | null;
  device_id?: string;
  sessionId?: string;
  autoCleanup?: boolean; // Auto-release control on unmount
  tree_id?: string; // Navigation tree ID for cache population
}

interface UseDeviceControlReturn {
  // Control state
  isControlActive: boolean;
  isControlLoading: boolean;
  controlError: string | null;

  // Control actions (now return full result object for immediate error checking)
  handleToggleControl: () => Promise<void>;
  handleTakeControl: () => Promise<{
    success: boolean;
    errorType?: string;
    error?: string;
    details?: any;
  }>;
  handleReleaseControl: () => Promise<boolean>;

  // Utility functions
  clearError: () => void;
}

// ========================================
// HOOK
// ========================================

export const useDeviceControl = ({
  host,
  device_id,
  sessionId,
  autoCleanup = true,
  tree_id,
}: UseDeviceControlProps): UseDeviceControlReturn => {
  // ========================================
  // STATE
  // ========================================

  const [isControlActive, setIsControlActive] = useState(false);
  const [isControlLoading, setIsControlLoading] = useState(false);
  const [controlError, setControlError] = useState<string | null>(null);

  // Track if we need to cleanup on unmount
  const needsCleanupRef = useRef(false);
  
  // Track control parameters at time of taking control for cleanup
  const controlParamsRef = useRef<{
    host: Host | null;
    device_id: string | undefined;
    sessionId: string | undefined;
  }>({
    host: null,
    device_id: undefined,
    sessionId: undefined,
  });

  // Get control functions from HostManager
  const { takeControl, releaseControl, hasActiveLock } = useHostControl();
  const { sessionId: browserSessionId } = useUserSession();

  // ========================================
  // CONTROL HANDLERS
  // ========================================

  const handleTakeControl = useCallback(async (): Promise<{
    success: boolean;
    errorType?: string;
    error?: string;
    details?: any;
  }> => {
    if (!host) {
      setControlError('No host selected');
      return { success: false, error: 'No host selected' };
    }

    setIsControlLoading(true);
    setControlError(null);

    try {
      console.log(
        `[useDeviceControl] Taking control of device: ${host.host_name}, device_id: ${device_id}`,
      );

      const effectiveSessionId = browserSessionId || sessionId;
      const result = await takeControl(host, device_id, effectiveSessionId, tree_id);

      if (result.success) {
        setIsControlActive(true);
        needsCleanupRef.current = true;
        // Store control parameters for cleanup
        controlParamsRef.current = {
          host,
          device_id,
          sessionId: effectiveSessionId,
        };
        console.log(
          `[useDeviceControl] Successfully took control of: ${host.host_name}, device: ${device_id}`,
        );
        return { success: true };
      } else {
        // Handle specific error types with user-friendly messages
        let errorMessage = result.error || 'Failed to take control';

        if (result.errorType === 'device_locked') {
          errorMessage = `Device is currently in use by another user`;
        } else if (result.errorType === 'device_not_found') {
          errorMessage = `Device is offline or not available`;
        } else if (result.errorType === 'stream_service_error') {
          errorMessage = `AV streaming service error: ${result.error}`;
        } else if (result.errorType === 'adb_connection_error') {
          errorMessage = `Remote connection error: ${result.error}`;
        } else if (result.errorType === 'network_error') {
          errorMessage = `Network error: Unable to reach device`;
        }

        setControlError(errorMessage);
        console.error(`[useDeviceControl] Failed to take control:`, result);
        return {
          success: false,
          errorType: result.errorType,
          error: errorMessage,
          details: result.details,
        };
      }
    } catch (error: any) {
      const errorMessage = `Connection failed: ${error.message || 'Unknown error'}`;
      setControlError(errorMessage);
      console.error(`[useDeviceControl] Exception taking control:`, error);
      return { success: false, error: errorMessage, details: error };
    } finally {
      setIsControlLoading(false);
    }
  }, [host, device_id, browserSessionId, sessionId, tree_id, takeControl]);

  const handleReleaseControl = useCallback(async (): Promise<boolean> => {
    if (!host) {
      console.warn(`[useDeviceControl] No host to release control from`);
      return true; // Consider it success if no host
    }

    setIsControlLoading(true);
    setControlError(null);

    try {
      console.log(
        `[useDeviceControl] Releasing control of device: ${host.host_name}, device_id: ${device_id}`,
      );

      const effectiveSessionId = browserSessionId || sessionId;
      const result = await releaseControl(host, device_id, effectiveSessionId);

      if (result.success) {
        setIsControlActive(false);
        needsCleanupRef.current = false;
        // Clear control parameters
        controlParamsRef.current = {
          host: null,
          device_id: undefined,
          sessionId: undefined,
        };
        console.log(
          `[useDeviceControl] Successfully released control of: ${host.host_name}, device: ${device_id}`,
        );
        return true;
      } else {
        const errorMessage = result.error || 'Failed to release control';
        setControlError(errorMessage);
        console.error(`[useDeviceControl] Failed to release control:`, result);
        return false;
      }
    } catch (error: any) {
      const errorMessage = `Failed to release control: ${error.message || 'Unknown error'}`;
      setControlError(errorMessage);
      console.error(`[useDeviceControl] Exception releasing control:`, error);
      return false;
    } finally {
      setIsControlLoading(false);
    }
  }, [host, device_id, browserSessionId, sessionId, releaseControl]);

  const handleToggleControl = useCallback(async (): Promise<void> => {
    if (isControlActive) {
      await handleReleaseControl();
    } else {
      await handleTakeControl();
    }
  }, [isControlActive, handleTakeControl, handleReleaseControl]);

  const clearError = useCallback(() => {
    setControlError(null);
  }, []);

  // ========================================
  // EFFECTS
  // ========================================

  // Sync control state with HostManager lock status
  useEffect(() => {
    if (host) {
      const effectiveDeviceId = device_id || 'device1';
      const hasLock = hasActiveLock(`${host.host_name}:${effectiveDeviceId}`);
      if (hasLock !== isControlActive) {
        console.log(
          `[useDeviceControl] Syncing control state for ${host.host_name}:${effectiveDeviceId}: ${hasLock}`,
        );
        setIsControlActive(hasLock);
        needsCleanupRef.current = hasLock;
      }
    }
  }, [host, device_id, hasActiveLock, isControlActive]);

  // Auto-cleanup on unmount - NO dependencies so it only runs on actual unmount
  useEffect(() => {
    return () => {
      if (autoCleanup && needsCleanupRef.current) {
        // Use captured control parameters at time of taking control
        const { host: cleanupHost, device_id: cleanupDeviceId, sessionId: cleanupSessionId } = controlParamsRef.current;
        
        if (cleanupHost) {
          console.log(
            `[useDeviceControl] Auto-cleanup: releasing control of ${cleanupHost.host_name}, device: ${cleanupDeviceId}`,
          );
          // Don't await - this is cleanup
          releaseControl(cleanupHost, cleanupDeviceId, cleanupSessionId).catch((error) => {
            console.error(`[useDeviceControl] Cleanup error:`, error);
          });
        }
      }
    };
     
  }, []); // Empty dependency array - only run on mount/unmount

  // ========================================
  // RETURN
  // ========================================

  return {
    // Control state
    isControlActive,
    isControlLoading,
    controlError,

    // Control actions
    handleToggleControl,
    handleTakeControl,
    handleReleaseControl,

    // Utility functions
    clearError,
  };
};
