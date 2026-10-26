import { useMemo } from 'react';

import { deviceMaintenanceKey, useMaintenanceWindow, type MaintenanceWindow } from './useMaintenanceWindow';

/** The device window that covers `key` and ends last (several may overlap), or undefined. */
const pickLatest = (windows: MaintenanceWindow[], key: string): MaintenanceWindow | undefined =>
  windows
    .filter((w) => w.scope === 'devices' && w.device_ids.includes(key))
    .sort((a, b) => Date.parse(b.window_end) - Date.parse(a.window_end))[0];

/** Lookup of the device-scoped windows, from the single shared fetch. No request per caller. */
export const useDeviceMaintenanceLookup = () => {
  const { windows } = useMaintenanceWindow();
  return useMemo(
    () => (hostName: string | undefined | null, deviceId: string | undefined | null) =>
      pickLatest(windows, deviceMaintenanceKey(hostName, deviceId)),
    [windows],
  );
};

/** The window covering this device (host + device id), if one is in force. */
export const useDeviceMaintenance = (
  hostName: string | undefined | null,
  deviceId: string | undefined | null,
): MaintenanceWindow | undefined => {
  const lookup = useDeviceMaintenanceLookup();
  return useMemo(() => lookup(hostName, deviceId), [lookup, hostName, deviceId]);
};
