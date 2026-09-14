import { useState, useEffect, useCallback, useMemo } from 'react';
import { buildServerUrl } from '../utils/buildUrlUtils';
import { api } from '../utils/apiClient';

export interface DeviceFlag {
  id: string;
  host_name: string;
  device_id: string;
  device_name: string;
  flags: string[];
  created_at: string;
  updated_at: string;
}

interface UseDeviceFlagsReturn {
  deviceFlags: DeviceFlag[];
  uniqueFlags: string[];
  isLoading: boolean;
  error: string | null;
  updateDeviceFlags: (hostName: string, deviceId: string, flags: string[]) => Promise<boolean>;
  batchUpdateDeviceFlags: (updates: Array<{ hostName: string; deviceId: string; flags: string[] }>) => Promise<boolean>;
  refreshFlags: () => Promise<void>;
}

const mergeFlagRecord = (
  currentFlags: DeviceFlag[],
  hostName: string,
  deviceId: string,
  flags: string[]
): DeviceFlag[] => {
  const now = new Date().toISOString();
  const index = currentFlags.findIndex(df => df.host_name === hostName && df.device_id === deviceId);

  if (index >= 0) {
    const updated = [...currentFlags];
    updated[index] = { ...updated[index], flags, updated_at: now };
    return updated;
  }

  return [
    ...currentFlags,
    {
      id: `${hostName}:${deviceId}`,
      host_name: hostName,
      device_id: deviceId,
      device_name: deviceId,
      flags,
      created_at: now,
      updated_at: now,
    },
  ];
};

export const useDeviceFlags = (): UseDeviceFlagsReturn => {
  const [deviceFlags, setDeviceFlags] = useState<DeviceFlag[]>([]);
  const [uniqueFlags, setUniqueFlags] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchBatchFlags = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);

      // Use the new batch endpoint to get both device flags and unique flags in one request
      const result = await api.get<{ success: boolean; data?: { device_flags?: DeviceFlag[]; unique_flags?: string[] }; error?: string }>(buildServerUrl('/server/device-flags/batch'));
      if (result.success && result.data) {
        setDeviceFlags(result.data.device_flags || []);
        setUniqueFlags(result.data.unique_flags || []);
      } else {
        throw new Error(result.error || 'Failed to fetch device flags');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
      console.error('Error fetching device flags:', err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const updateDeviceFlags = useCallback(async (hostName: string, deviceId: string, flags: string[]): Promise<boolean> => {
    try {
      const result = await api.put<{ success: boolean; error?: string }>(buildServerUrl(`/server/device-flags/${hostName}/${deviceId}`), { flags });
      if (result.success) {
        // Update local state
        setDeviceFlags(prev => {
          const updated = mergeFlagRecord(prev, hostName, deviceId, flags);
          
          // Recalculate unique flags from the updated device flags
          const allFlags = new Set<string>();
          updated.forEach(df => {
            df.flags.forEach(flag => allFlags.add(flag));
          });
          setUniqueFlags(Array.from(allFlags).sort());
          
          return updated;
        });
        
        return true;
      } else {
        throw new Error(result.error || 'Failed to update device flags');
      }
    } catch (err) {
      console.error('Error updating device flags:', err);
      setError(err instanceof Error ? err.message : 'Unknown error');
      return false;
    }
  }, []); // Remove deviceFlags dependency

  const batchUpdateDeviceFlags = useCallback(async (updates: Array<{ hostName: string; deviceId: string; flags: string[] }>): Promise<boolean> => {
    try {
      const results = await Promise.all(
        updates.map(({ hostName, deviceId, flags }) =>
          api.put<{ success: boolean }>(buildServerUrl(`/server/device-flags/${hostName}/${deviceId}`), { flags })
        )
      );
      const allResultsSuccessful = results.every(result => result.success);
        
      if (allResultsSuccessful) {
        // Update local state for all changes
        setDeviceFlags(prev => {
          let updated = [...prev];
          updates.forEach(({ hostName, deviceId, flags }) => {
            updated = mergeFlagRecord(updated, hostName, deviceId, flags);
          });
          const allFlags = new Set<string>();
          updated.forEach(df => {
            df.flags.forEach(flag => allFlags.add(flag));
          });
          setUniqueFlags(Array.from(allFlags).sort());
          return updated;
        });
        return true;
      } else {
        throw new Error('Some flag updates failed');
      }
    } catch (err) {
      console.error('Error batch updating device flags:', err);
      setError(err instanceof Error ? err.message : 'Unknown error');
      return false;
    }
  }, []); // Remove deviceFlags dependency

  const refreshFlags = useCallback(async () => {
    await fetchBatchFlags();
  }, [fetchBatchFlags]);

  useEffect(() => {
    fetchBatchFlags();
  }, [fetchBatchFlags]);

  // Memoize return value to prevent unnecessary re-renders in consuming components
  return useMemo(() => ({
    deviceFlags,
    uniqueFlags,
    isLoading,
    error,
    updateDeviceFlags,
    batchUpdateDeviceFlags,
    refreshFlags,
  }), [
    deviceFlags,
    uniqueFlags,
    isLoading,
    error,
    updateDeviceFlags,
    batchUpdateDeviceFlags,
    refreshFlags,
  ]);
};
