import React, { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { io, Socket } from 'socket.io-client';
import { useLocation } from 'react-router-dom';

import { useUserSession } from '../hooks/useUserSession';
import { useServerManager } from '../hooks/useServerManager';
import { Host, Device } from '../types/common/Host_Types';
import { buildServerUrl, getServerBaseUrl } from '../utils/buildUrlUtils';
import { clearUserInterfaceCaches } from '../hooks/pages/useUserInterface';
import { hasCompatibleDevice } from '../utils/userinterface/deviceCompatibilityUtils';
import { useToast } from '../hooks/useToast';

import { IdleLockDialog } from '../components/common/IdleLockDialog';
import { useIdleLockMonitor } from '../hooks/useIdleLockMonitor';

import { HostDataContext } from './HostDataContext';
import { HostControlContext } from './HostControlContext';
import { useAuthContext } from './auth';

const log = (..._args: unknown[]): void => {};

const buildDeviceRefreshSignature = (host: Host): string => {
  return (host.devices || [])
    .map((device) =>
      JSON.stringify({
        device_id: device.device_id,
        device_name: device.device_name,
        device_model: device.device_model,
        ir_type: device.ir_type ?? null,
        remote_capability: device.device_capabilities?.remote ?? null,
        av_capability: device.device_capabilities?.av ?? null,
        video_stream_path: device.video_stream_path ?? null,
        video_capture_path: device.video_capture_path ?? null,
        has_running_deployment: Boolean(device.has_running_deployment),
      }),
    )
    .join('|');
};

interface HostManagerProviderProps {
  children: React.ReactNode;
  userInterface?: {
    models?: string[];
  };
}

/**
 * Provider component for host management
 * This component provides access to host data and device control functionality
 */
export const HostManagerProvider: React.FC<HostManagerProviderProps> = ({
  children,
  userInterface,
}) => {
  // ========================================
  // STATE
  // ========================================

  // Get server selection and server data from ServerManager (now centralized)
  const { selectedServer, availableServers, setSelectedServer, serverHostsData, isLoading: serverLoading, error: serverError, refreshServerData } = useServerManager();
  
  // Toast notifications
  const { showWarning, showError } = useToast();

  // Extract hosts from server data, filtering by selected server only
  // This ensures we only show hosts from the currently selected server
  const [selectedServerError, setSelectedServerError] = useState<string | null>(null);
  const cacheRefreshAttemptedRef = useRef<string | null>(null);
  
  const allHostsFromServers = useMemo(() => {
    if (!selectedServer) return [];
    
    const selectedServerData = serverHostsData.find(
      serverData => serverData.server_info.server_url === selectedServer
    );
    
    if (!selectedServerData) {
      if (!serverLoading) {
        setSelectedServerError('Selected server is not responding. Please select another server.');
      }
      return [];
    } else {
      setSelectedServerError(null);
    }
    
    return selectedServerData.hosts;
  }, [serverHostsData, selectedServer, serverLoading]);
  
  // Invalidate cache if hostCount is 0 (side effect in useEffect, not useMemo)
  useEffect(() => {
    // Only attempt refresh once per selected server (don't include length in cache key)
    const cacheKey = `${selectedServer}`;
    
    if (
      allHostsFromServers.length === 0 && 
      !serverLoading && 
      selectedServer &&
      serverHostsData.length > 0 && // Only refresh if we have server data but no hosts for this server
      cacheRefreshAttemptedRef.current !== cacheKey
    ) {
      console.warn('[@HostManagerProvider] hostCount is 0 - invalidating cache and forcing refresh (once)');
      cacheRefreshAttemptedRef.current = cacheKey;
      refreshServerData();
    }
  }, [allHostsFromServers.length, serverLoading, selectedServer, serverHostsData.length, refreshServerData]);

  // Use hosts from ServerManager instead of fetching separately
  const [availableHosts, setAvailableHosts] = useState<Host[]>([]);
  const isLoading = serverLoading;
  const error = serverError;

  // Panel and UI state
  const [selectedHost, setSelectedHost] = useState<Host | null>(null);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null);
  const [isControlActive, setIsControlActive] = useState(false);
  const [isRemotePanelOpen, setIsRemotePanelOpen] = useState(false);
  const [showRemotePanel, setShowRemotePanel] = useState(false);
  const [showAVPanel, setShowAVPanel] = useState(false);
  const [isVerificationActive, _setIsVerificationActive] = useState(false);

  // Filtered hosts based on interface models
  const [filteredAvailableHosts, setFilteredAvailableHosts] = useState<Host[]>([]);

  // Track active locks owned by this browser session (deviceKey -> user ID)
  const [activeLocks, setActiveLocks] = useState<Map<string, string>>(new Map());
  // Track server authoritative lock map (deviceKey -> lock metadata)
  const [remoteLocks, setRemoteLocks] = useState<Map<string, any>>(new Map());
  const reclaimInProgressRef = useRef(false);
  const initializedRef = useRef(false);
  const activeLocksRef = useRef<Map<string, string>>(new Map());
  const availableHostsRef = useRef<Host[]>([]);
  const releaseControlRef = useRef<(
    (
      host: Host,
      device_id?: string,
      sessionId?: string,
    ) => Promise<{
      success: boolean;
      error?: string;
      errorType?: 'network_error' | 'generic_error';
      details?: any;
    }>
  ) | null>(null);
  const lockSocketRef = useRef<Socket | null>(null);
  const lockRefreshInFlightRef = useRef<Promise<Map<string, any>> | null>(null);
  // Tracks in-flight per-device schema loads (host:device keys) so the
  // rehydration effect doesn't fire duplicate getDeviceActions fetches while
  // the first one is still resolving.
  const schemaLoadInFlightRef = useRef<Set<string>>(new Set());

  // Use shared user session for consistent identification
  const { userId, sessionId: browserSessionId, isOurLock } = useUserSession();

  // Display name attached to manual locks so other viewers see WHO holds
  // control instead of the generic "take-control" label.
  const { profile } = useAuthContext();
  const userName = profile?.full_name || null;

  // Get current location to determine when lock sync is needed
  const location = useLocation();
  const pathname = location.pathname;
  const isIncidentsPage = pathname.includes('/monitoring/incidents');
  const isAIQueuePage = pathname.includes('/monitoring/ai-queue');
  const isNavigationEditorPage = pathname.includes('/navigation-editor');
  const isDeviceControlPage = pathname.includes('/device-control');
  const isRunLockAwarePage =
    pathname.startsWith('/run/tests') ||
    pathname.startsWith('/run/build') ||
    pathname.startsWith('/test-execution/run-tests') ||
    pathname.startsWith('/test-execution/build-campaign');
  const hasOpenControlOrPreview =
    isControlActive || isRemotePanelOpen || showRemotePanel || showAVPanel;
  const hasOwnedLocks = activeLocks.size > 0;
  const shouldSyncLocks =
    !isIncidentsPage &&
    !isAIQueuePage &&
    (isDeviceControlPage || isNavigationEditorPage || isRunLockAwarePage || hasOpenControlOrPreview || hasOwnedLocks);

  // Memoize userInterface to prevent unnecessary re-renders
  const stableUserInterface = useMemo(() => userInterface, [userInterface]);

  // Update availableHosts when server data changes (from ServerManager)
  // Only update if the hosts actually changed to prevent unnecessary re-renders
  useEffect(() => {
    setAvailableHosts(prev => {
      // Quick length check first
      if (prev.length !== allHostsFromServers.length) {
        log('[@context:HostManagerProvider] Hosts count changed:', prev.length, '->', allHostsFromServers.length);
        return allHostsFromServers;
      }
      
      // Deep comparison: check if any host data actually changed
      const hostsChanged = allHostsFromServers.some((newHost, index) => {
        const oldHost = prev[index];
        if (!oldHost) return true;
        
        // Compare key properties
        if (oldHost.host_name !== newHost.host_name) return true;
        if (oldHost.status !== newHost.status) return true;
        if ((oldHost.devices?.length || 0) !== (newHost.devices?.length || 0)) return true;
        // Device metadata like ir_type must trigger updates so remote config changes propagate.
        const oldDeviceSignature = buildDeviceRefreshSignature(oldHost);
        const newDeviceSignature = buildDeviceRefreshSignature(newHost);
        if (oldDeviceSignature !== newDeviceSignature) return true;
        // Liveness must propagate too: a rebooting host keeps the same
        // host_name/status (the registry serves stale heartbeat data until
        // it goes offline), so without these the Dashboard reboot-recovery
        // effect — which depends on availableHosts and reads last_seen —
        // never re-runs and its spinner hangs forever.
        if (oldHost.last_seen !== newHost.last_seen) return true;
        if (oldHost.system_stats?.operational_status !== newHost.system_stats?.operational_status) return true;

        return false;
      });
      
      if (hostsChanged) {
        log('[@context:HostManagerProvider] Host data changed, updating');
        return allHostsFromServers;
      }
      
      // No changes, keep previous reference to prevent re-renders
      return prev;
    });
  }, [allHostsFromServers]);

  // ========================================
  // DIRECT DATA ACCESS FUNCTIONS
  // ========================================

  // Get all hosts without filtering (raw data from server)
  const getAllHosts = useCallback((): Host[] => {
    return availableHosts;
  }, [availableHosts]);

  // Get host by name
  const getHostByName = useCallback(
    (hostName: string): Host | null => {
      return availableHosts.find((h) => h.host_name === hostName) || null;
    },
    [availableHosts],
  );

  // Get hosts filtered by device models or capabilities
  const getHostsByModel = useCallback(
    (models: string[]): Host[] => {
      const filtered = availableHosts
        .map((host) => ({
          ...host,
          devices: (host.devices || []).filter((device) => {
            // Check exact model match first
            if (models.includes(device.device_model)) {
              return true;
            }
            // Check capability match - if model is 'web' or 'desktop', 
            // match devices that have those capabilities
            return models.some(model => 
              device.device_capabilities && (device.device_capabilities as any)[model]
            );
          }),
        }))
        .filter((host) => host.devices.length > 0);

      return filtered;
    },
    [availableHosts],
  );

  // Get all devices from all available hosts
  const getAllDevices = useCallback((): Device[] => {
    const allDevices = availableHosts.flatMap((host) =>
      (host.devices || []).map((device) => ({ ...device, hostName: host.host_name })),
    );
    return allDevices;
  }, [availableHosts]);

  // Get all devices from specific host
  const getDevicesFromHost = useCallback(
    (hostName: string): Device[] => {
      const host = availableHosts.find((h) => h.host_name === hostName);
      const devices = host?.devices || [];
      return devices;
    },
    [availableHosts],
  );

  // Get devices with specific capability, returning {host, device} pairs
  const getDevicesByCapability = useCallback(
    (capability: string): { host: Host; device: Device }[] => {
      const matchingDevices: { host: Host; device: Device }[] = [];

      availableHosts.forEach((host) => {
        if (host.devices) {
          host.devices.forEach((device) => {
            // Check if device has the specified capability in device.device_capabilities object
            if (device.device_capabilities && (device.device_capabilities as any)[capability]) {
              matchingDevices.push({ host, device });
            }
          });
        }
      });

      return matchingDevices;
    },
    [availableHosts],
  );

  // ========================================
  // DEVICE CONTROL HANDLERS
  // ========================================

  const refreshServerLocks = useCallback(async (): Promise<Map<string, any>> => {
    // Coalesce concurrent callers onto the same in-flight request. The reclaim
    // effect on mount and the socket `connect` handler both call this within a
    // few milliseconds of each other; without this, the page fires two identical
    // GET /lockedDevices requests on every load.
    if (lockRefreshInFlightRef.current) {
      return lockRefreshInFlightRef.current;
    }
    const p = (async () => {
      try {
        const response = await fetch(buildServerUrl('/server/control/lockedDevices'), {
          method: 'GET',
          headers: {
            'Content-Type': 'application/json',
          },
        });

        if (!response.ok) {
          return new Map<string, any>();
        }

        const result = await response.json();
        const nextLocks = new Map<string, any>(
          Object.entries(result?.locked_devices || {}) as Array<[string, any]>,
        );
        setRemoteLocks(nextLocks);
        return nextLocks;
      } catch (error) {
        console.error('[@context:HostManagerProvider] Failed to refresh server locks:', error);
        return new Map<string, any>();
      } finally {
        lockRefreshInFlightRef.current = null;
      }
    })();
    lockRefreshInFlightRef.current = p;
    return p;
  }, []);

  // Automatically reclaim locks for devices that belong to this user
  const reclaimUserLocks = useCallback(async () => {
    // Prevent multiple simultaneous reclaim operations
    if (reclaimInProgressRef.current) {
      log('[@context:HostManagerProvider] Reclaim already in progress, skipping');
      return;
    }

    reclaimInProgressRef.current = true;

    try {
      log(
        `[@context:HostManagerProvider] Checking for locks to reclaim for user: ${userId}`,
      );

      const latestLocks = await refreshServerLocks();
      // Only reclaim manual_control locks — script_execution / deployment_execution
      // are owned by the runner, not by this browser session. Treating them as
      // "ours" would let the rehydration effect auto-select the device and then
      // a later release call would hit `owner_type_mismatch` on the server.
      const userLockedDevices = Array.from(latestLocks.entries()).filter(
        ([, lockInfo]) =>
          isOurLock(lockInfo) && lockInfo?.owner_type === 'manual_control',
      );

      if (userLockedDevices.length > 0) {
        log(
          `[@context:HostManagerProvider] Found ${userLockedDevices.length} manual_control devices locked by current user, reclaiming...`,
        );

        for (const [deviceKey] of userLockedDevices) {
          if (!deviceKey.includes(':')) {
            continue;
          }
          const [, deviceId] = deviceKey.split(':');
          if (!deviceId) {
            continue;
          }
          setActiveLocks((prev) => new Map(prev).set(deviceKey, userId));
        }
      }
    } catch (error) {
      console.error(`[@context:HostManagerProvider] Error reclaiming user locks:`, error);
    } finally {
      reclaimInProgressRef.current = false;
    }
  }, [userId, isOurLock, refreshServerLocks]);

  // Load a device's action/verification schemas into the host objects.
  // The schemas (device_action_types / device_verification_types) are NOT part
  // of the lightweight host registry payload — they're fetched on demand so the
  // editing UI (action/verification dropdowns) can resolve commands. This runs
  // both when taking control AND when rehydrating control on a page refresh,
  // otherwise the rehydrated session shows actions as "unsupported" (⚠️) and
  // empty verification rows until the user releases and re-takes control.
  const loadDeviceSchemas = useCallback(
    async (host: Host, device_id?: string): Promise<void> => {
      const effectiveDeviceId = device_id || 'device1';
      const deviceKey = `${host.host_name}:${effectiveDeviceId}`;

      // Skip if schemas are already present on the host object (perf).
      const deviceWithSchemas = host.devices?.find(
        (d: any) =>
          d.device_id === effectiveDeviceId &&
          d.device_action_types &&
          Object.keys(d.device_action_types).length > 0,
      );
      if (deviceWithSchemas) {
        log(
          `[@context:HostManagerProvider] Action schemas already loaded for ${deviceKey}, skipping reload`,
        );
        return;
      }

      // Coalesce concurrent loads for the same device (the rehydration effect
      // can re-run on every lock refresh before the first fetch resolves).
      if (schemaLoadInFlightRef.current.has(deviceKey)) {
        return;
      }
      schemaLoadInFlightRef.current.add(deviceKey);

      try {
        log(`[@context:HostManagerProvider] Loading action schemas for ${deviceKey}...`);
        const schemaResponse = await fetch(
          buildServerUrl(
            `/server/system/getDeviceActions?host_name=${encodeURIComponent(host.host_name)}&device_id=${encodeURIComponent(effectiveDeviceId)}`,
          ),
        );
        if (schemaResponse.ok) {
          const schemaData = await schemaResponse.json();
          if (schemaData.success) {
            // Update just this device's action/verification schemas
            setAvailableHosts((prev) => {
              const updated = prev.map((h) => {
                if (h.host_name === host.host_name) {
                  return {
                    ...h,
                    devices: h.devices?.map((d: any) => {
                      if (d.device_id === effectiveDeviceId) {
                        return {
                          ...d,
                          device_action_types: schemaData.device_action_types,
                          device_verification_types: schemaData.device_verification_types,
                        };
                      }
                      return d;
                    }),
                  };
                }
                return h;
              });

              // Also update selectedHost if it's the same host
              setSelectedHost((prevSelectedHost) => {
                if (prevSelectedHost && prevSelectedHost.host_name === host.host_name) {
                  const updatedHost = updated.find((h) => h.host_name === host.host_name);
                  if (updatedHost) {
                    log(`[@context:HostManagerProvider] Updating selectedHost with new schemas`);
                    return updatedHost;
                  }
                }
                return prevSelectedHost;
              });

              return updated;
            });
            log(`[@context:HostManagerProvider] Action schemas loaded for ${deviceKey}`);
          }
        }
      } catch (error) {
        console.warn(
          `[@context:HostManagerProvider] Failed to load device action schemas (non-critical):`,
          error,
        );
      } finally {
        schemaLoadInFlightRef.current.delete(deviceKey);
      }
    },
    [],
  );

  // Take control via server control endpoint with comprehensive error handling
  const takeControl = useCallback(
    async (
      host: Host,
      device_id?: string,
      sessionId?: string,
      tree_id_or_userinterface_id?: string,
      id_type?: 'tree_id' | 'userinterface_id'  // NEW: specify which ID type
    ): Promise<{
      success: boolean;
      error?: string;
      errorType?:
        | 'stream_service_error'
        | 'adb_connection_error'
        | 'device_locked'
        | 'device_not_found'
        | 'network_error'
        | 'generic_error';
      details?: any;
    }> => {
      try {
        const effectiveSessionId = sessionId || browserSessionId;
        const effectiveDeviceId = device_id || 'device1';

        log(
          `[@context:HostManagerProvider] Taking control of device: ${host.host_name}, device_id: ${effectiveDeviceId}`,
        );
        log(`[@context:HostManagerProvider] Using user ID for lock: ${userId}`);
        if (tree_id_or_userinterface_id) {
          const idTypeLabel = id_type || 'tree_id';
          log(`[@context:HostManagerProvider] Including ${idTypeLabel} for cache population: ${tree_id_or_userinterface_id}`);
        }

        // Build request body with optional tree_id OR userinterface_id for cache population
        const requestBody: any = {
          host_name: host.host_name,
          device_id: effectiveDeviceId,
          session_id: effectiveSessionId,
          user_id: userId,
          ...(userName ? { user_name: userName } : {}),
        };

        // Add tree_id OR userinterface_id if provided (server resolves tree_id from userinterface_id)
        if (tree_id_or_userinterface_id) {
          if (id_type === 'userinterface_id') {
            requestBody.userinterface_id = tree_id_or_userinterface_id;
          } else {
            // Default to tree_id for backward compatibility
            requestBody.tree_id = tree_id_or_userinterface_id;
          }
          // team_id is automatically added by buildServerUrl
        }

        const response = await fetch(buildServerUrl('/server/control/takeControl'), {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(requestBody),
        });

        const result = await response.json();

        if (response.ok && result.success) {
          // takeControl now returns immediately after the DB lock; the host call
          // and nav-cache populate run in the background. Warnings/failures arrive
          // via 'control_ready' / 'control_failed' on the /system socket below.

          // Clear user interface caches to fetch fresh data on take-control
          // This ensures multi-user scenarios get latest data when taking control
          clearUserInterfaceCaches();
          
          log(
            `[@context:HostManagerProvider] Successfully took control of device: ${host.host_name}:${effectiveDeviceId}`,
          );
          // Store lock using device-oriented key
          setActiveLocks((prev) =>
            new Map(prev).set(`${host.host_name}:${effectiveDeviceId}`, userId),
          );
          setRemoteLocks((prev) =>
            new Map(prev).set(
              `${host.host_name}:${effectiveDeviceId}`,
              result.lock_info || {
                host_name: host.host_name,
                device_id: effectiveDeviceId,
                owner_type: 'manual_control',
                owner_user_id: userId,
                owner_user_name: userName,
                owner_session_id: effectiveSessionId,
              },
            ),
          );
          
          // ✅ Load device action/verification schemas for editing capabilities
          await loadDeviceSchemas(host, effectiveDeviceId);

          return { success: true };
        } else {
          // Handle specific error cases
          console.error(`[@context:HostManagerProvider] Failed to take control:`, result);

          let errorType: any = 'generic_error';
          let errorMessage = result.error || 'Failed to take control of device';

          if (result.errorType === 'stream_service_error' || result.error_type === 'stream_service_error') {
            errorType = 'stream_service_error';
            errorMessage = `AV Stream Error: ${result.error}`;
          } else if (result.errorType === 'adb_connection_error' || result.error_type === 'adb_connection_error') {
            errorType = 'adb_connection_error';
            errorMessage = `Remote Connection Error: ${result.error}`;
          } else if (result.errorType === 'device_locked' || result.status === 'device_locked') {
            errorType = 'device_locked';
            const lockOwner = result.owner_user_name || result.owner_user_id || result.owner_session_id || result.locked_by || 'another user';
            errorMessage = `Device is locked by ${lockOwner}`;
          } else if (result.errorType === 'device_not_found' || result.status === 'device_not_found') {
            errorType = 'device_not_found';
            errorMessage = `Device ${host.host_name}:${effectiveDeviceId} not found or offline`;
          } else if (result.error && result.error.includes('secret key')) {
            errorType = 'server_configuration_error';
            errorMessage = `Server configuration error: Flask secret key not configured. Please restart the server.`;
          } else if (response.status === 409 && result.locked_by_same_user) {
            log(
              `[@context:HostManagerProvider] Device ${host.host_name}:${effectiveDeviceId} locked by same user, reclaiming lock`,
            );
            setActiveLocks((prev) =>
              new Map(prev).set(`${host.host_name}:${effectiveDeviceId}`, userId),
            );
            return { success: true };
          }

          return {
            success: false,
            error: errorMessage,
            errorType,
            details: result,
          };
        }
      } catch (error: any) {
        console.error(
          `[@context:HostManagerProvider] Exception taking control of device ${host.host_name}:${device_id || 'device1'}:`,
          error,
        );
        return {
          success: false,
          error: `Network error: ${error.message || 'Failed to communicate with server'}`,
          errorType: 'network_error',
          details: error,
        };
      }
    },
    [browserSessionId, userId, userName, loadDeviceSchemas],
  );

  // Release control via server control endpoint
  const releaseControl = useCallback(
    async (
      host: Host,
      device_id?: string,
      sessionId?: string,
    ): Promise<{
      success: boolean;
      error?: string;
      errorType?: 'network_error' | 'generic_error';
      details?: any;
    }> => {
      try {
        const effectiveSessionId = sessionId || browserSessionId;
        const effectiveDeviceId = device_id || 'device1';

        log(
          `[@context:HostManagerProvider] Releasing control of device: ${host.host_name}, device_id: ${effectiveDeviceId}`,
        );
        log(`[@context:HostManagerProvider] Using user ID for unlock: ${userId}`);

        const response = await fetch(buildServerUrl('/server/control/releaseControl'), {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            host_name: host.host_name,
            device_id: effectiveDeviceId,
            session_id: effectiveSessionId,
            user_id: userId,
          }),
        });

        const result = await response.json();
        if (!response.ok) {
          return {
            success: false,
            error: result.error || `Failed to release control of device: ${response.statusText}`,
            errorType: 'generic_error',
            details: result,
          };
        }

        if (result.success) {
          log(
            `[@context:HostManagerProvider] Successfully released control of device: ${host.host_name}:${effectiveDeviceId}`,
          );
          // Remove lock using device-oriented key
          setActiveLocks((prev) => {
            const newMap = new Map(prev);
            newMap.delete(`${host.host_name}:${effectiveDeviceId}`);
            return newMap;
          });
          setRemoteLocks((prev) => {
            const next = new Map(prev);
            next.delete(`${host.host_name}:${effectiveDeviceId}`);
            return next;
          });
          return { success: true };
        } else {
          console.error(
            `[@context:HostManagerProvider] Server failed to release control of device: ${result.error}`,
          );
          return {
            success: false,
            error: result.error || 'Failed to release control of device',
            errorType: 'generic_error',
            details: result,
          };
        }
      } catch (error: any) {
        console.error(
          `[@context:HostManagerProvider] Exception releasing control of device ${host.host_name}:${device_id || 'device1'}:`,
          error,
        );
        return {
          success: false,
          error: `Network error: ${error.message || 'Failed to communicate with server'}`,
          errorType: 'network_error',
          details: error,
        };
      }
    },
    [browserSessionId, userId],
  );

  useEffect(() => {
    activeLocksRef.current = activeLocks;
  }, [activeLocks]);

  useEffect(() => {
    availableHostsRef.current = availableHosts;
  }, [availableHosts]);

  useEffect(() => {
    releaseControlRef.current = releaseControl;
  }, [releaseControl]);

  // Check if we have an active lock for a device
  const hasActiveLock = useCallback(
    (deviceKey: string): boolean => {
      // Support both legacy "hostname" and new "hostname:device_id" formats
      if (deviceKey.includes(':')) {
        return activeLocks.has(deviceKey);
      } else {
        // Legacy support: check for any device on this host
        const hostLocks = Array.from(activeLocks.keys()).filter((key) =>
          key.startsWith(`${deviceKey}:`),
        );
        return hostLocks.length > 0 || activeLocks.has(deviceKey);
      }
    },
    [activeLocks],
  );

  // Check if device is locked (server-authoritative by host:device key)
  const isDeviceLocked = useCallback(
    (host: Host | null, deviceId?: string): boolean => {
      if (!host) return false;
      const resolvedDeviceId = deviceId || 'device1';
      const deviceKey = `${host.host_name}:${resolvedDeviceId}`;

      // If we own this lock locally, treat as unlocked for current user.
      if (hasActiveLock(deviceKey)) {
        return false;
      }
      return remoteLocks.has(deviceKey);
    },
    [hasActiveLock, remoteLocks],
  );

  const getDeviceLockInfo = useCallback(
    (host: Host | null, deviceId?: string): any | null => {
      if (!host) return null;
      const resolvedDeviceId = deviceId || 'device1';
      const deviceKey = `${host.host_name}:${resolvedDeviceId}`;
      return remoteLocks.get(deviceKey) || null;
    },
    [remoteLocks],
  );

  // Check if device can be locked (based on host data)
  const canLockDevice = useCallback(
    (host: Host | null, deviceId?: string): boolean => {
      if (!host) return false;

      // Check if specific device exists if deviceId is provided
      if (deviceId && host.devices) {
        const device = host.devices.find((d) => d.device_id === deviceId);
        if (!device) return false;
      }

      return host.status === 'online' && !isDeviceLocked(host, deviceId);
    },
    [isDeviceLocked],
  );

  // ========================================
  // UI HANDLERS
  // ========================================

  // Handle device selection
  const handleDeviceSelect = useCallback((host: Host | null, deviceId: string | null) => {
    if (!host || !deviceId) {
      setSelectedHost(null);
      setSelectedDeviceId(null);
      return;
    }

    // Verify device exists in host
    const device = host.devices?.find((d) => d.device_id === deviceId);
    if (!device) {
      console.error(
        `[@context:HostManagerProvider] Device ${deviceId} not found in host ${host.host_name}`,
      );
      setSelectedHost(null);
      setSelectedDeviceId(null);
      return;
    }

    setSelectedHost(host);
    setSelectedDeviceId(deviceId);
  }, []);

  // Handle control state changes (called from header after successful device control)
  const handleControlStateChange = useCallback((active: boolean) => {
    setIsControlActive(active);

    if (active) {
      // Show panels when control is active
      setShowRemotePanel(true);
      setShowAVPanel(true);
      setIsRemotePanelOpen(true);
    } else {
      // Hide panels when control is inactive
      setShowRemotePanel(false);
      setShowAVPanel(false);
      setIsRemotePanelOpen(false);
    }
    
    // Note: Navigation tree lock is now handled in NavigationEditor
    // to maintain separation of concerns between device control and tree editing
  }, []);

  // Handle remote panel toggle
  const handleToggleRemotePanel = useCallback(() => {
    const newState = !isRemotePanelOpen;
    setIsRemotePanelOpen(newState);
  }, [isRemotePanelOpen]);

  // Handle connection change (for panels)
  const handleConnectionChange = useCallback((_connected: boolean) => {
    // Could update UI state based on connection status
  }, []);

  // Handle disconnect complete (for panels)
  const handleDisconnectComplete = useCallback(() => {
    setIsControlActive(false);
    setShowRemotePanel(false);
    setShowAVPanel(false);
    setIsRemotePanelOpen(false);
  }, []);

  // ========================================
  // EFFECTS
  // ========================================

  // Initialize lock reclaim on mount (skip for incidents and AI queue pages)
  useEffect(() => {
    if (!initializedRef.current && !isIncidentsPage && !isAIQueuePage) {
      initializedRef.current = true;
      reclaimUserLocks();
    }
  }, [reclaimUserLocks, isIncidentsPage, isAIQueuePage]);

  // Rehydrate device-control UI state on refresh for navigation editor.
  // If this browser session still owns a manual lock, restore selected device and panels.
  useEffect(() => {
    if (!isNavigationEditorPage || isIncidentsPage || isAIQueuePage) {
      return;
    }

    const parseDeviceKey = (deviceKey: string): { hostName: string; deviceId: string } | null => {
      if (!deviceKey || !deviceKey.includes(':')) return null;
      const [hostName, deviceId] = deviceKey.split(':');
      if (!hostName || !deviceId) return null;
      return { hostName, deviceId };
    };

    // Prefer authoritative server lock owned by this exact browser session.
    let ownedDeviceKey: string | null = null;
    for (const [deviceKey, lockInfo] of remoteLocks.entries()) {
      const ownerType = lockInfo?.owner_type;
      const ownerSessionId =
        lockInfo?.owner_session_id || lockInfo?.session_id || lockInfo?.ownerSessionId;
      if (ownerType === 'manual_control' && ownerSessionId === browserSessionId) {
        ownedDeviceKey = deviceKey;
        break;
      }
    }

    // Fallback: local active lock map (can be populated before remote lock refresh completes).
    // Skip any entry whose authoritative server lock is NOT manual_control —
    // script_execution / deployment_execution locks must never be promoted into
    // the manual UI, otherwise the next release would hit owner_type_mismatch.
    if (!ownedDeviceKey) {
      for (const localKey of activeLocks.keys()) {
        const remote = remoteLocks.get(localKey);
        if (remote && remote.owner_type && remote.owner_type !== 'manual_control') {
          continue;
        }
        ownedDeviceKey = localKey;
        break;
      }
    }

    if (!ownedDeviceKey) {
      return;
    }

    const parsed = parseDeviceKey(ownedDeviceKey);
    if (!parsed) return;

    const host = availableHosts.find((h) => h.host_name === parsed.hostName);
    const deviceExists = host?.devices?.some((d) => d.device_id === parsed.deviceId);
    if (!host || !deviceExists) {
      return;
    }

    const alreadySelected =
      selectedHost?.host_name === parsed.hostName && selectedDeviceId === parsed.deviceId;
    if (!alreadySelected) {
      setSelectedHost(host);
      setSelectedDeviceId(parsed.deviceId);
    } else if (selectedHost !== host) {
      // Keep selectedHost object fresh when hosts list refreshes.
      setSelectedHost(host);
    }

    if (!isControlActive) {
      setIsControlActive(true);
    }
    if (!showRemotePanel) {
      setShowRemotePanel(true);
    }
    if (!showAVPanel) {
      setShowAVPanel(true);
    }
    if (!isRemotePanelOpen) {
      setIsRemotePanelOpen(true);
    }

    // Rehydrated control restores the lock/panels but the host registry payload
    // doesn't carry action/verification schemas — load them now so the editing
    // UI resolves commands. Without this, after a refresh the edge actions show
    // as "unsupported" (⚠️) and node verifications render empty until the user
    // releases and re-takes control. loadDeviceSchemas is idempotent (skips if
    // schemas are present, coalesces concurrent calls).
    void loadDeviceSchemas(host, parsed.deviceId);
  }, [
    isNavigationEditorPage,
    isIncidentsPage,
    isAIQueuePage,
    remoteLocks,
    activeLocks,
    availableHosts,
    browserSessionId,
    selectedHost,
    selectedDeviceId,
    isControlActive,
    showRemotePanel,
    showAVPanel,
    isRemotePanelOpen,
    loadDeviceSchemas,
  ]);

  useEffect(() => {
    if (!shouldSyncLocks) {
      return;
    }

    const socket = // The server, not the page. These are the same host on the web, but the mobile app serves
    // the bundle from its own https://localhost, where a socket aimed at the page origin is
    // refused forever (net::ERR_CONNECTION_REFUSED) and the app never learns any device state.
    io(`${getServerBaseUrl()}/system`, {
      transports: ['websocket'],
      path: '/socket.io',
      reconnection: true,
      reconnectionAttempts: Infinity,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
    });

    lockSocketRef.current = socket;

    socket.on('connect', () => {
      refreshServerLocks();
    });

    socket.on('system_update', (event: any) => {
      if (event?.type === 'lock_changed') {
        refreshServerLocks();
        return;
      }
      if (event?.type === 'control_ready') {
        if (event?.warning) {
          showWarning(event.warning, { duration: 6000 });
        }
        return;
      }
      if (event?.type === 'control_failed') {
        const hostName = event?.host_name;
        const deviceId = event?.device_id;
        if (hostName && deviceId) {
          const key = `${hostName}:${deviceId}`;
          setActiveLocks((prev) => {
            if (!prev.has(key)) return prev;
            const next = new Map(prev);
            next.delete(key);
            return next;
          });
          setRemoteLocks((prev) => {
            if (!prev.has(key)) return prev;
            const next = new Map(prev);
            next.delete(key);
            return next;
          });
        }
        if (event?.error) {
          showError(event.error, { duration: 6000 });
        }
        refreshServerLocks();
      }
    });

    const refreshOnFocusOrOnline = () => {
      refreshServerLocks();
    };
    window.addEventListener('focus', refreshOnFocusOrOnline);
    window.addEventListener('online', refreshOnFocusOrOnline);

    // Fallback polling prevents stale lock state if a websocket event is missed.
    const refreshInterval = window.setInterval(() => {
      refreshServerLocks();
    }, 15000);

    return () => {
      window.clearInterval(refreshInterval);
      window.removeEventListener('focus', refreshOnFocusOrOnline);
      window.removeEventListener('online', refreshOnFocusOrOnline);
      socket.disconnect();
      lockSocketRef.current = null;
    };
  }, [refreshServerLocks, shouldSyncLocks, showWarning, showError]);

  // Clean up locks only on actual provider unmount
  useEffect(() => {
    return () => {
      const locksAtUnmount = activeLocksRef.current;
      const hostsAtUnmount = availableHostsRef.current;
      const releaseAtUnmount = releaseControlRef.current;
      if (!releaseAtUnmount) {
        return;
      }

      // Clean up any active locks when component unmounts
      locksAtUnmount.forEach(async (_lockUserId, deviceKey) => {
        try {
          const [hostName, deviceId] = deviceKey.split(':');
          if (!hostName || !deviceId) {
            return;
          }
          log(`[@context:HostManagerProvider] Cleaning up lock for ${deviceKey} on unmount`);
          const host = hostsAtUnmount.find((h) => h.host_name === hostName);
          if (host) {
            await releaseAtUnmount(host, deviceId);
          }
        } catch (error) {
          console.error(
            `[@context:HostManagerProvider] Error cleaning up lock for ${deviceKey}:`,
            error,
          );
        }
      });
    };
  }, []);

  // Update filtered hosts when availableHosts changes - using shared compatibility logic
  useEffect(() => {
    if (stableUserInterface?.models && availableHosts.length > 0) {
      // Filter hosts to only include those with devices compatible with the interface
      const compatibleHosts = availableHosts.filter((host) =>
        hasCompatibleDevice(host.devices || [], stableUserInterface as any)
      );

      setFilteredAvailableHosts(compatibleHosts);
    } else {
      setFilteredAvailableHosts(availableHosts);
    }
  }, [availableHosts, stableUserInterface?.models]);

  // ========================================
  // IDLE LOCK MONITOR
  // ========================================

  const { idleDialogOpen, idleCountdown, handleIdleDismiss } = useIdleLockMonitor({
    activeLocks,
    remoteLocks,
    releaseControl,
    availableHosts,
    sessionId: browserSessionId,
    userId,
  });

  // ========================================
  // CONTEXT VALUES - Split into Data and Control
  // ========================================

  // Host Data Context - static data (rarely changes)
  const hostDataValue = useMemo(
    () => ({
      // Server selection state
      selectedServer,
      availableServers,
      setSelectedServer,

      // Host data (filtered by interface models)
      availableHosts: filteredAvailableHosts,
      getHostByName,
      isLoading,
      error: serverError || selectedServerError, // Combine errors

      // Direct data access functions
      getAllHosts,
      getHostsByModel,
      getAllDevices,
      getDevicesFromHost,
      getDevicesByCapability,
    }),
    [
      selectedServer,
      availableServers,
      setSelectedServer,
      filteredAvailableHosts,
      getHostByName,
      isLoading,
      error,
      getAllHosts,
      getHostsByModel,
      getAllDevices,
      getDevicesFromHost,
      getDevicesByCapability,
      serverError,
      selectedServerError,
    ],
  );

  // Host Control Context - dynamic control state (changes frequently)
  const hostControlValue = useMemo(
    () => ({
      // Panel and UI state
      selectedHost,
      selectedDeviceId,
      isControlActive,
      isRemotePanelOpen,
      showRemotePanel,
      showAVPanel,
      isVerificationActive,

      // Device control methods
      takeControl,
      releaseControl,
      isDeviceLocked,
      getDeviceLockInfo,
      canLockDevice,
      hasActiveLock,

      // Panel and UI handlers
      handleDeviceSelect,
      handleControlStateChange,
      handleToggleRemotePanel,
      handleConnectionChange,
      handleDisconnectComplete,

      // Panel and control actions
      setSelectedHost,
      setSelectedDeviceId,
      setIsControlActive,
      setIsRemotePanelOpen,
      setShowRemotePanel,
      setShowAVPanel,
      setIsVerificationActive: (active: boolean) => _setIsVerificationActive(active),

      // Lock management
      reclaimLocks: async () => {
        await reclaimUserLocks();
        return true;
      },
    }),
    [
      selectedHost,
      selectedDeviceId,
      isControlActive,
      isRemotePanelOpen,
      showRemotePanel,
      showAVPanel,
      isVerificationActive,
      takeControl,
      releaseControl,
      isDeviceLocked,
      getDeviceLockInfo,
      canLockDevice,
      hasActiveLock,
      handleDeviceSelect,
      handleControlStateChange,
      handleToggleRemotePanel,
      handleConnectionChange,
      handleDisconnectComplete,
      reclaimUserLocks,
    ],
  );

  return (
    <HostDataContext.Provider value={hostDataValue}>
      <HostControlContext.Provider value={hostControlValue}>
        <IdleLockDialog
          open={idleDialogOpen}
          countdown={idleCountdown}
          onDismiss={handleIdleDismiss}
        />
        {children}
      </HostControlContext.Provider>
    </HostDataContext.Provider>
  );
};

HostManagerProvider.displayName = 'HostManagerProvider';
