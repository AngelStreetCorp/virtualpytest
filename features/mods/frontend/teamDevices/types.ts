/** One device of the team in the widget. */
export interface DeviceRow {
  hostName: string;
  deviceId: string;
  deviceName: string;
  deviceModel?: string;
  online: boolean;
  running: number;
  failed: number;
}

export interface FleetTotals {
  devices: number;
  offline: number;
  running: number;
  failed: number;
}

/** A running run's device, by run id (from run.update). */
export type RunningRuns = Record<string, { hostName: string; deviceId: string }>;

/** A stored script result, the fields the widget reads. */
export interface ScriptResultRow {
  host_name?: string;
  device_name?: string;
  success?: boolean;
  started_at?: string;
}

/** A stored open alert, the fields the widget reads. */
export interface AlertRow {
  host_name?: string;
  device_id?: string;
  team_id?: string | null;
}

export type ErrorSource = 'failed_24h' | 'failed_7d' | 'open_alerts';

/** Error counts by device: failed runs are matched on `host:deviceName`, alerts on `host:deviceId`. */
export interface ErrorCounts {
  byName: Record<string, number>;
  byId: Record<string, number>;
}

export interface FleetState {
  running: RunningRuns;
  /** Error counts per source, filled while a widget using that source is on screen. */
  errors: Partial<Record<ErrorSource, ErrorCounts>>;
}
