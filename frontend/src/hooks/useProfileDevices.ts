import { useContext, useMemo } from 'react';

import { HostDataContext } from '../contexts/HostDataContext';
import { getDeviceMonitorProfile } from './useDeviceFilters';

/** Devices on every known host, grouped by the monitoring profile they run ("name - host"). Empty outside a host provider. */
export const useProfileDevices = (): Record<string, string[]> => {
  const ctx = useContext(HostDataContext);
  const hosts = ctx?.availableHosts;
  return useMemo(() => {
    const out: Record<string, string[]> = {};
    (hosts ?? []).forEach((host) => {
      (host.devices ?? []).forEach((device) => {
        const profile = getDeviceMonitorProfile(host, device);
        (out[profile] ??= []).push(`${device.device_name || device.device_id} - ${host.host_name}`);
      });
    });
    Object.values(out).forEach((l) => l.sort());
    return out;
  }, [hosts]);
};
