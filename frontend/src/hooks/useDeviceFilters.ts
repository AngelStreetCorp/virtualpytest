import { STORAGE_KEYS } from '../config/constants';
import { Host, Device } from '../types/common/Host_Types';

import { usePersistedState } from './usePersistedState';

/**
 * Target label of one device, shared by the Dashboard and Device Control
 * filter bars so a selected target means the same thing on both pages.
 * Host-only entries (VNC desktop or *_Host) collapse to the host name to match
 * RecHostPreview's display rule; other devices read "device_name - host_name".
 */
export const getDeviceTargetLabel = (host: Host, device: Device) => {
  const rawName = device.device_name || device.device_id;
  if (device.device_model === 'host_vnc' || /_Host$/.test(rawName)) {
    return rawName.replace(/_Host$/, '') || host.host_name;
  }
  return `${rawName} - ${host.host_name}`;
};

/**
 * Target / model / tag filter selection, persisted to localStorage under ONE
 * set of keys so the Dashboard and Device Control pages share it: picking a
 * filter on one page shows the same selection on the other.
 */
export function useDeviceFilters() {
  const [targetFilter, setTargetFilter] = usePersistedState<string[]>(
    `${STORAGE_KEYS.DEVICE_FILTERS}_target`,
    [],
  );
  const [deviceModelFilter, setDeviceModelFilter] = usePersistedState<string[]>(
    `${STORAGE_KEYS.DEVICE_FILTERS}_model`,
    [],
  );
  const [flagFilter, setFlagFilter] = usePersistedState<string[]>(
    `${STORAGE_KEYS.DEVICE_FILTERS}_flag`,
    [],
  );
  // 'AND' = device must carry every selected tag; 'OR' = any one. Default AND.
  const [flagMatchMode, setFlagMatchMode] = usePersistedState<'AND' | 'OR'>(
    `${STORAGE_KEYS.DEVICE_FILTERS}_flagMode`,
    'AND',
  );
  return {
    targetFilter,
    setTargetFilter,
    deviceModelFilter,
    setDeviceModelFilter,
    flagFilter,
    setFlagFilter,
    flagMatchMode,
    setFlagMatchMode,
  };
}
