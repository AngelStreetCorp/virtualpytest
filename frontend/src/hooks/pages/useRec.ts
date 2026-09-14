import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { Host, Device } from '../../types/common/Host_Types';
import { useHostData } from '../useHostManager';
import { calculateVncScaling } from '../../utils/vncUtils';

import { buildServerUrl } from '../../utils/buildUrlUtils';
import { api } from '../../utils/apiClient';

const log = (..._args: unknown[]): void => {};
// Removed global state - no longer needed for simple monitoring patterns

interface UseRecReturn {
  avDevices: Array<{ host: Host; device: Device }>;
  isLoading: boolean;
  error: string | null;
  refreshHosts: () => Promise<void>;
  baseUrlPatterns: Map<string, string>; // host_name-device_id -> base URL pattern (for monitoring)
  restartHostStream: (hostName: string) => Promise<void>; // Restart vpt-stream on one host
  restartAllStreams: () => Promise<void>; // Restart vpt-stream on every host (once each)
  isRestarting: boolean; // Loading state for restart operation
  adaptiveInterval: number; // Adaptive interval based on device count
  calculateVncScaling: (targetSize: { width: number; height: number }) => { // VNC scaling calculation for any target size
    transform: string;
    transformOrigin: string;
    width: string;
    height: string;
  };
  getCaptureUrlFromStream: (streamUrl: string, device?: Device, host?: Host) => Promise<string | null>; // Get capture URL from segment (with hot→cold copy)
}

/**
 * Hook for managing recording/AV device discovery and display
 *
 * Simplified to only handle device discovery:
 * - Stream URL fetching: Use useStream hook
 * - Device control: Use useDeviceControl hook or HostControl context directly
 * 
 * Uses useHostData (static data context) so data updates don't cause re-renders
 * when device control state changes (e.g., button presses). Callbacks use refs
 * to remain stable across data updates.
 */
export const useRec = (): UseRecReturn => {
  const [avDevices, setAvDevices] = useState<Array<{ host: Host; device: Device }>>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isRestarting, setIsRestarting] = useState(false);

  const renderCountRef = useRef(0);
  renderCountRef.current += 1;

  // Adaptive interval based on device count
  const adaptiveInterval = useMemo(() => {
    const count = avDevices.length;
    if (count <= 5) return 1000;   // 5 FPS with batch of 5
    if (count <= 10) return 5000;  // 1 FPS
    if (count <= 20) return 10000; // 0.5 FPS
    return Math.round(5000 / 0.3);  // ~16667ms for 0.3 FPS
  }, [avDevices.length]);

  // Remove modal context hook - no longer needed for thumbnail generation

  // Simple state for monitoring base URL patterns (read-only for now)
  // Use useMemo to ensure stable reference across re-renders
  const baseUrlPatterns = useMemo(() => new Map<string, string>(), []);

  // Use the HostData context (static data only - no control state)
  // This prevents re-renders when device control state changes (e.g., button presses)
  const { getDevicesByCapability, isLoading: isHostDataLoading, availableHosts } = useHostData();
  
  // Use refs to store latest values and prevent callback recreation
  const getDevicesByCapabilityRef = useRef(getDevicesByCapability);
  const isHostDataLoadingRef = useRef(isHostDataLoading);
  
  getDevicesByCapabilityRef.current = getDevicesByCapability;
  isHostDataLoadingRef.current = isHostDataLoading;
  
  // Track host list changes to detect server swaps
  const prevHostCountRef = useRef(availableHosts.length);

  // Get AV-capable devices - only when HostData is ready
  // Stabilized with ref to prevent recreation on every HostData update
  const refreshHosts = useCallback(async (): Promise<void> => {
    // Don't fetch if HostData is still loading
    if (isHostDataLoadingRef.current) {
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const devices = getDevicesByCapabilityRef.current('av')
        .filter(({ host }) => !host.host_type?.startsWith('runner_') && host.device_type !== 'host_device_runner');
      
      // Only update if devices actually changed (prevent unnecessary re-renders)
      setAvDevices(prev => {
        // Check if the device list actually changed
        if (prev.length !== devices.length) {
          return devices;
        }
        
        // Include deployment running state so lock icon can update without page reload
        const prevSignature = prev
          .map(({ host, device }) => `${host.host_name}-${device.device_id}:${Boolean(device.has_running_deployment)}`)
          .sort()
          .join(',');
        const newSignature = devices
          .map(({ host, device }) => `${host.host_name}-${device.device_id}:${Boolean(device.has_running_deployment)}`)
          .sort()
          .join(',');
        
        if (prevSignature !== newSignature) {
          return devices;
        }
        
        // No changes, keep previous reference to prevent re-renders
        return prev;
      });
    } catch (error) {
      console.error('[@hook:useRec] Error refreshing devices:', error);
      setError(error instanceof Error ? error.message : 'Failed to refresh devices');
    } finally {
      setIsLoading(false);
    }
  }, []); // No dependencies - use refs instead to keep callback stable

  // Watch for host list changes (server swap or deployment state changes)
  useEffect(() => {
    const currentHostCount = availableHosts.length;
    
    // Detect host count change (server swap or host availability change)
    if (prevHostCountRef.current !== currentHostCount && !isHostDataLoading) {
      log(`[@hook:useRec] Host count changed (${prevHostCountRef.current} -> ${currentHostCount}) - refreshing devices immediately`);
      refreshHosts();
    }
    
    prevHostCountRef.current = currentHostCount;
  }, [availableHosts.length, isHostDataLoading, refreshHosts]);

  // Also refresh device mappings when deployment lock flags change
  const deploymentSignature = useMemo(
    () =>
      availableHosts
        .flatMap((host) =>
          (host.devices || []).map(
            (device) => `${host.host_name}-${device.device_id}:${Boolean(device.has_running_deployment)}`
          )
        )
        .sort()
        .join(','),
    [availableHosts]
  );

  useEffect(() => {
    if (!isHostDataLoading) {
      refreshHosts();
    }
  }, [deploymentSignature, isHostDataLoading, refreshHosts]);

  // Initial load only.
  // Host/device updates are already driven by HostData context changes and signatures above.
  useEffect(() => {
    refreshHosts();
    return () => {
      // no-op cleanup
    };
  }, [refreshHosts]);

  // Use ref to store the latest avDevices and isRestarting to avoid dependency issues
  const avDevicesRef = useRef(avDevices);
  const isRestartingRef = useRef(isRestarting);
  
  avDevicesRef.current = avDevices;
  isRestartingRef.current = isRestarting;

  // `vpt-stream` is a single host-level systemd service. restart_stream()
  // just rewrites the shared active_captures.conf and the one service
  // re-reads it for every device on that host, so a host is restarted with
  // exactly ONE call. Any AV device on the host identifies it for the API.
  // Stable callback (refs only) to prevent recreation.
  const restartHostStreamRequest = useCallback(async (hostName: string): Promise<void> => {
    try {
      // Real `systemctl restart vpt-stream` (one service per host,
      // device-agnostic). Synchronous on the backend — this awaits the
      // actual restart and returns the honest result.
      const result = await api.post(buildServerUrl('/server/system/restartHostStreamService'), {
        host_name: hostName,
      });
      if (result.success) {
        log(`[@hook:useRec] Restarted vpt-stream on ${hostName}`);
      } else {
        console.error(`[@hook:useRec] Failed to restart vpt-stream on ${hostName}:`, result.error);
      }
    } catch (err) {
      console.error(`[@hook:useRec] Restart request failed for ${hostName}:`, err);
    }
  }, []);

  // Restart vpt-stream on a single host (one call).
  const restartHostStream = useCallback(async (hostName: string): Promise<void> => {
    if (isRestartingRef.current) return; // Prevent concurrent restarts
    setIsRestarting(true);
    setError(null);
    try {
      await restartHostStreamRequest(hostName);
    } catch (error) {
      console.error('[@hook:useRec] Error restarting stream:', error);
      setError(error instanceof Error ? error.message : 'Failed to restart stream');
    } finally {
      setIsRestarting(false);
    }
  }, [restartHostStreamRequest]);

  // Restart vpt-stream on every host, once per host.
  const restartAllStreams = useCallback(async (): Promise<void> => {
    if (isRestartingRef.current) return; // Prevent concurrent restarts
    setIsRestarting(true);
    setError(null);
    try {
      const hostNames = [...new Set(avDevicesRef.current.map(({ host }) => host.host_name))];
      for (const hostName of hostNames) {
        await restartHostStreamRequest(hostName);
      }
    } catch (error) {
      console.error('[@hook:useRec] Error restarting streams:', error);
      setError(error instanceof Error ? error.message : 'Failed to restart streams');
    } finally {
      setIsRestarting(false);
    }
  }, [restartHostStreamRequest]);

  // Get capture URL from stream segment (calls backend to copy hot->cold)
  // Backend handles: segment→capture calculation, hot→cold copy, URL building
  const getCaptureUrlFromStream = useCallback(async (streamUrl: string, device?: Device, host?: Host): Promise<string | null> => {
    if (!streamUrl || !device || !host) {
      console.warn('[@hook:useRec] Missing required parameters:', { streamUrl: !!streamUrl, device: !!device, host: !!host });
      return null;
    }
    
    try {
      // Extract segment number from stream URL (e.g., segment_000078741.ts)
      const segmentMatch = streamUrl.match(/segment_(\d+)\.ts/);
      if (!segmentMatch) {
        console.warn('[@hook:useRec] Could not extract segment number from URL:', streamUrl);
        return null;
      }
      
      const segmentNumber = parseInt(segmentMatch[1], 10);
      const fps = device.video_fps || 5;
      
      log(`[@hook:useRec] Requesting capture: segment=${segmentNumber}, fps=${fps}`);
      
      // Call backend to get capture (handles hot→cold copy)
      const result = await api.post<{ success?: boolean; capture_url?: string; error?: string }>(
        buildServerUrl('/server/av/getSegmentCapture'),
        {
          host_name: host.host_name,
          device_id: device.device_id,
          segment_number: segmentNumber,
          fps: fps,
        }
      );
      if (result.success && result.capture_url) {
        log(`[@hook:useRec] Got capture URL (COLD): ${result.capture_url}`);
        return result.capture_url;
      }
      
      console.error('[@hook:useRec] Backend returned error:', result.error);
      return null;
    } catch (error) {
      console.error('[@hook:useRec] Failed to get capture URL:', error);
      return null;
    }
  }, []);

  // Memoize return value to prevent RecContent re-renders when context changes
  // but our actual values haven't changed
  const returnValue = useMemo(() => {
    return {
      avDevices,
      isLoading,
      error,
      refreshHosts,
      baseUrlPatterns, // Only used for monitoring now
      restartHostStream,
      restartAllStreams,
      isRestarting,
      adaptiveInterval,
      calculateVncScaling, // Now using the imported version
      getCaptureUrlFromStream, // Calculate capture URL from segment
    };
  }, [
    avDevices,
    isLoading,
    error,
    refreshHosts,
    baseUrlPatterns,
    restartHostStream,
    restartAllStreams,
    isRestarting,
    adaptiveInterval,
    getCaptureUrlFromStream,
  ]);
  
  return returnValue;
};
