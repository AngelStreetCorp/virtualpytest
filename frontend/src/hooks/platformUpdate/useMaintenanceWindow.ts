import { createContext, useContext } from 'react';

/** Window scope: 'platform' = the whole install, 'devices' = the devices listed in `device_ids`. */
export type MaintenanceScope = 'platform' | 'devices';

/**
 * One window in force. Comes from a Platform update run (`source: 'run'`, has `current_step`) or from
 * Settings -> Maintenance (`source: 'settings'`, has `reason`). `device_ids` are device keys, see
 * `deviceMaintenanceKey`.
 */
export interface MaintenanceWindow {
  id: string;
  source: 'run' | 'settings';
  run_id?: string;
  scope: MaintenanceScope;
  device_ids: string[];
  window_start: string;
  window_end: string;
  started_by: string;
  note?: string;
  reason?: string;
  current_step?: { index: number; title: string; state: string };
}

export interface MaintenanceNotice {
  run_id: string;
  scope: MaintenanceScope;
  status: 'ok' | 'failed' | 'rolled_back';
  closed_at: string;
  message: string;
}

export interface MaintenanceState {
  windows: MaintenanceWindow[];
  notice: MaintenanceNotice | null;
  reload: () => Promise<void>;
}

export const MaintenanceContext = createContext<MaintenanceState>({
  windows: [],
  notice: null,
  reload: async () => {},
});

/**
 * Device key used in `device_ids`. `device1` exists on every host, so the key is host + device:
 * "<host_name>:<device_id>".
 */
export const deviceMaintenanceKey = (hostName: string | undefined | null, deviceId: string | undefined | null): string =>
  `${hostName ?? ''}:${deviceId ?? ''}`;

/** The active maintenance windows (fetched once by MaintenanceProvider, shared by every consumer). */
export const useMaintenanceWindow = (): MaintenanceState => useContext(MaintenanceContext);
