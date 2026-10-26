/**
 * Pure logic of the Settings "Monitoring profile" picker (TASK-90 follow-up): which profile a device runs, and what a
 * change restarts. Mirrors backend_host/src/lib/utils/monitor_profile.py (services_to_restart), so the confirmation
 * dialog states the impact before anything is saved.
 */
export type MonitorService = 'img' | 'audio' | 'subtitle';
export const MONITOR_SERVICES: MonitorService[] = ['img', 'audio', 'subtitle'];
export const DEFAULT_MONITOR_PROFILE = 'tv_app';

export interface MonitorProfileInfo {
  name: string;
  title: string;
  /** the three monitors, plus archiver / kpi / avq on a host that reports them (tv_lite turns those off too) */
  services: Record<string, boolean>;
  /** 'lean' = fewer ffmpeg outputs (tv_lite); changing it restarts vpt-stream */
  stream?: 'full' | 'lean';
  models: Array<{ env: string; path: string; present: boolean }>;
  usable: boolean;
  reason: string | null;
  description: string;
  cost: string;
}

export interface MonitorUnitState {
  unit: string;
  active: boolean;
}
export type MonitorUnits = Record<MonitorService, MonitorUnitState>;

export interface MonitorApplyResult {
  state: 'applying' | 'done';
  started_at?: number;
  finished_at?: number;
  restarted?: string[];
  failed?: string[];
  not_running?: string[];
  first_run?: boolean;
  error?: string;
  profiles?: Record<string, string>;
  fallbacks?: Array<{ device: string; requested: string; effective: string; kind: string; reason: string }>;
}

export interface MonitorProfileStatus {
  saved: Record<string, string>;
  applied: Record<string, string> | null;
  mismatch: string[];
  result: MonitorApplyResult | null;
  units: MonitorUnits;
}

/** What the form holds: the host default and one value per device key ("DEVICE1"). '' = follow the default. */
export interface ProfileSelection {
  host: string;
  devices: Record<string, string>;
}

export const effectiveProfile = (deviceValue: string | undefined, hostValue: string | undefined): string =>
  (deviceValue || '').trim() || (hostValue || '').trim() || DEFAULT_MONITOR_PROFILE;

/** "DEVICE1" -> "device1", the id the host's status uses. */
export const deviceId = (deviceKey: string): string => deviceKey.toLowerCase();

const servicesOf = (name: string, profiles: MonitorProfileInfo[]): Record<string, boolean> =>
  profiles.find((p) => p.name === name)?.services ?? { img: true, audio: true, subtitle: true };

/** Host services that follow a profile's `services` (they care only whether a device is served, not which profile it runs). */
export const HOST_SERVICES = ['archiver', 'kpi', 'avq'] as const;
const isLean = (name: string, profiles: MonitorProfileInfo[]): boolean => profiles.find((p) => p.name === name)?.stream === 'lean';

const effectiveMap = (sel: ProfileSelection, keys: string[]): Record<string, string> =>
  Object.fromEntries(keys.map((k) => [k, effectiveProfile(sel.devices[k], sel.host)]));

export interface ProfileChangePlan {
  changed: boolean;
  devices: Array<{ key: string; from: string; to: string }>;
  hostDefault: { from: string; to: string } | null;
  /** services whose unit is running and will be restarted */
  restarts: MonitorService[];
  /** services that would restart but whose unit is not running on this host (a lite host): nothing happens to them */
  notRunning: MonitorService[];
  /** archiver / kpi / avq units whose set of served devices changes (the host restarts them) */
  restartsHost: string[];
  /** the devices on lean streams change, so vpt-stream restarts (the ffmpeg graph is fixed at start) */
  restartsStream: boolean;
  /** profiles that are new for at least one device, with what they add */
  adds: MonitorProfileInfo[];
}

/** Compare two selections over the same device keys; the services to restart follow services_to_restart() on the host. */
export function planProfileChange(
  before: ProfileSelection, after: ProfileSelection, profiles: MonitorProfileInfo[], units: MonitorUnits | null,
): ProfileChangePlan {
  const keys = Array.from(new Set([...Object.keys(before.devices), ...Object.keys(after.devices)])).sort();
  const was = effectiveMap(before, keys);
  const now = effectiveMap(after, keys);
  const devices = keys.filter((k) => was[k] !== now[k]).map((k) => ({ key: k, from: was[k], to: now[k] }));
  const hostDefault = (before.host || '') !== (after.host || '') ? { from: before.host || '', to: after.host || '' } : null;
  const restartable: MonitorService[] = [];
  for (const s of MONITOR_SERVICES) {
    const needed = (m: Record<string, string>) => keys.filter((k) => servicesOf(m[k], profiles)[s]);
    const a = needed(was);
    const b = needed(now);
    const setChanged = a.join() !== b.join();
    const profileChanged = b.some((k) => was[k] !== now[k]);
    if (setChanged || profileChanged) restartable.push(s);
  }
  const restartsHost = HOST_SERVICES.filter((s) => {
    const served = (m: Record<string, string>) => keys.filter((k) => servicesOf(m[k], profiles)[s] !== false).join();
    return served(was) !== served(now);
  }).map((s) => `vpt-${s}`);
  const leanSet = (m: Record<string, string>) => keys.filter((k) => isLean(m[k], profiles)).join();
  const restartsStream = leanSet(was) !== leanSet(now);
  const running = (s: MonitorService) => !units || units[s]?.active !== false;
  const added = new Set(devices.map((d) => d.to).filter((n) => n !== DEFAULT_MONITOR_PROFILE));
  return {
    changed: devices.length > 0 || hostDefault !== null,
    devices,
    hostDefault,
    restarts: restartable.filter(running),
    notRunning: restartable.filter((s) => !running(s)),
    restartsHost,
    restartsStream,
    adds: profiles.filter((p) => added.has(p.name)),
  };
}

export const profileTitle = (name: string, profiles: MonitorProfileInfo[]): string =>
  profiles.find((p) => p.name === name)?.title ?? name;
