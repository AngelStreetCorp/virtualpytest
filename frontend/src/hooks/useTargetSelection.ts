import { useState, useMemo, useCallback, useEffect } from 'react';
import { useHostData } from './useHostManager';
import { useWorkspaceContext } from '../contexts/workspace/WorkspaceContext';

export interface TargetSelectionResult {
  selectedDevices: Map<string, string>;
  toggleTarget: (key: string) => void;
  updateDeviceUserinterface: (key: string, ui: string) => void;
  getTargetDisplayName: (key: string) => string;
  reconcileTargets: (reconciler: (prev: Map<string, string>) => Map<string, string>) => void;
  clearTargets: () => void;
  filterCompatible: (requiresDevice: boolean) => void;
  filterTargetKeys: (predicate: (key: string) => boolean) => void;
  firstSelectedDevice: { hostName: string; deviceId: string; deviceModel: string };
  allHosts: any[];
  getDevicesFromHost: (hostName: string) => any[];
}

export const useTargetSelection = (): TargetSelectionResult => {
  const [selectedDevices, setSelectedDevices] = useState<Map<string, string>>(new Map());
  const { getAllHosts, getDevicesFromHost: getRawDevicesFromHost } = useHostData();
  const { isDeviceAllowed } = useWorkspaceContext();

  // Devices not allowed by the active workspace are hidden from every caller
  // of this hook — the rendered target list, the "select all" action, and
  // any consumer reading `allHosts` or `getDevicesFromHost`.
  const getDevicesFromHost = useCallback(
    (hostName: string) =>
      getRawDevicesFromHost(hostName).filter((d: any) => isDeviceAllowed(hostName, d.device_id)),
    [getRawDevicesFromHost, isDeviceAllowed],
  );

  const allHosts = useMemo(() => {
    return getAllHosts()
      .map((h) => ({ ...h, devices: getDevicesFromHost(h.host_name) }))
      .filter((h) => (h.devices?.length ?? 0) > 0);
  }, [getAllHosts, getDevicesFromHost]);

  // If the active workspace changes and the current selection references a
  // device that is no longer allowed, drop it from the selection.
  useEffect(() => {
    setSelectedDevices((prev) => {
      let changed = false;
      const next = new Map<string, string>();
      prev.forEach((ui, key) => {
        const [hostName, deviceId] = key.split(':');
        if (!deviceId || isDeviceAllowed(hostName, deviceId)) {
          next.set(key, ui);
        } else {
          changed = true;
        }
      });
      return changed ? next : prev;
    });
  }, [isDeviceAllowed]);

  const toggleTarget = useCallback((key: string) => {
    setSelectedDevices(prev => {
      const next = new Map(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        // Prevent selecting the same device_id on the same host under a different key
        const [hostName, deviceId] = key.split(':');
        // A device the active workspace doesn't allow can never enter the
        // selection — this also catches the sessionStorage restore on mount,
        // which replays keys saved under a different workspace.
        if (deviceId && !isDeviceAllowed(hostName, deviceId)) {
          return prev;
        }
        const alreadySelected = deviceId && Array.from(next.keys()).some((existingKey) => {
          const [existingHost, existingDeviceId] = existingKey.split(':');
          return existingHost === hostName && existingDeviceId === deviceId && existingKey !== key;
        });
        if (!alreadySelected) {
          next.set(key, '');
        }
      }
      return next;
    });
  }, [isDeviceAllowed]);

  const updateDeviceUserinterface = useCallback((key: string, ui: string) => {
    setSelectedDevices(prev => {
      const next = new Map(prev);
      next.set(key, ui);
      return next;
    });
  }, []);

  const getTargetDisplayName = useCallback((key: string): string => {
    const [hostName, deviceId] = key.split(':');
    if (!deviceId) return hostName;
    const devices = getDevicesFromHost(hostName);
    const device = devices.find((d: any) => d.device_id === deviceId);
    return `${hostName} → ${device?.device_name || deviceId}`;
  }, [getDevicesFromHost]);

  const reconcileTargets = useCallback((reconciler: (prev: Map<string, string>) => Map<string, string>) => {
    setSelectedDevices((prev) => {
      const next = reconciler(prev);

      if (next === prev) {
        return prev;
      }

      if (next.size !== prev.size) {
        return next;
      }

      for (const [key, value] of prev.entries()) {
        if (next.get(key) !== value) {
          return next;
        }
      }

      return prev;
    });
  }, []);

  const clearTargets = useCallback(() => setSelectedDevices(new Map()), []);

  const filterCompatible = useCallback((requiresDevice: boolean) => {
    setSelectedDevices(prev => {
      let changed = false;
      const filtered = new Map<string, string>();
      prev.forEach((ui, key) => {
        const [, deviceId] = key.split(':');
        const hasDevice = Boolean(deviceId);
        const compatible = requiresDevice ? hasDevice : !hasDevice;
        if (compatible) filtered.set(key, ui);
        else changed = true;
      });
      return changed ? filtered : prev;
    });
  }, []);

  const filterTargetKeys = useCallback((predicate: (key: string) => boolean) => {
    setSelectedDevices((prev) => {
      let changed = false;
      const next = new Map<string, string>();
      prev.forEach((ui, key) => {
        if (predicate(key)) {
          next.set(key, ui);
        } else {
          changed = true;
        }
      });
      return changed ? next : prev;
    });
  }, []);

  const firstSelectedDevice = useMemo(() => {
    if (selectedDevices.size === 0) return { hostName: '', deviceId: '', deviceModel: 'unknown' };
    const firstKey = Array.from(selectedDevices.keys())[0];
    const [hostName, deviceId] = firstKey.split(':');
    if (deviceId) {
      const devices = getDevicesFromHost(hostName);
      const device = devices.find((d: any) => d.device_id === deviceId);
      return { hostName, deviceId, deviceModel: device?.device_model || 'unknown' };
    }
    return { hostName, deviceId: '', deviceModel: 'unknown' };
  }, [selectedDevices, getDevicesFromHost]);

  return {
    selectedDevices,
    toggleTarget,
    updateDeviceUserinterface,
    getTargetDisplayName,
    reconcileTargets,
    clearTargets,
    filterCompatible,
    filterTargetKeys,
    firstSelectedDevice,
    allHosts,
    getDevicesFromHost,
  };
};
