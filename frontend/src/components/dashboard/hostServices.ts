/**
 * Grouping and expected-vs-actual state for the Services section of a Dashboard host card.
 *
 * Which services SHOULD run depends on the device monitoring profiles (TASK-90): a profile-driven service
 * (img/audio/subtitle/archiver/kpi/avq) is expected only when at least one device's profile turns it on.
 * Everything else is expected when the backend marks it critical (core services, VNC on a VNC host, ...).
 * "down" therefore only ever means "expected and not running"; the rest is idle (off on purpose) or not installed.
 */

export interface RawService {
  name: string;
  label: string;
  status: string;
  critical: boolean;
  optional: boolean;
  controllable?: boolean;
  description?: string;
  detail?: string;
  resolved_name?: string;
}

export type ServiceState = 'active' | 'idle' | 'down';
export type ServiceGroup = 'core' | 'monitoring' | 'optional';

export interface ServiceRow {
  key: string;
  label: string;
  description?: string;
  group: ServiceGroup;
  state: ServiceState;
  /** Word shown next to the dot: active, down, stuck, idle … */
  word: string;
  /** Why it is idle / what is wrong; empty when active. */
  reason: string;
  /** Devices whose profile uses this service (profile-driven services only). */
  deviceCount: number | null;
  /** Underlying services this row acts on (Remote view = VNC + Websockify). */
  members: RawService[];
}

export interface HostServicesModel {
  groups: Record<ServiceGroup, ServiceRow[]>;
  notInstalled: string[];
  counts: { running: number; down: number; idle: number };
}

/** Service name -> key in a profile's `services` manifest. */
export const PROFILE_SERVICE_KEY: Record<string, string> = {
  'vpt-monitor-img': 'img',
  'vpt-monitor-audio': 'audio',
  'vpt-monitor-subtitle': 'subtitle',
  'vpt-archiver': 'archiver',
  'vpt-kpi': 'kpi',
  'vpt-avq': 'avq',
};
const MONITORING_KEYS = new Set(['img', 'audio', 'subtitle']);
const CORE_NAMES = new Set(['vpt-stream', 'vpt-host']);
const REMOTE_VIEW = ['vpt-vnc', 'vpt-websockify'];
const DEFAULT_PROFILE = 'tv_app';
const NOT_RUNNING = new Set(['stopped', 'error', 'stuck', 'failed', 'unknown', 'inactive']);

export interface ProfileInput {
  /** {device_id: profile}; absent on hosts that predate the field. */
  monitorProfiles?: Record<string, string>;
  /** {profile: {service: bool}} */
  profileServices?: Record<string, Record<string, boolean>>;
  /** Number of devices on the host, for a host that reports no per-device profiles. */
  deviceCount: number;
}

/** Devices per profile; a host with no profile data runs every device as tv_app. */
export const profileMix = (input: ProfileInput): Record<string, number> => {
  const mix: Record<string, number> = {};
  const profiles = input.monitorProfiles;
  if (profiles && Object.keys(profiles).length) {
    Object.values(profiles).forEach((p) => { mix[p] = (mix[p] ?? 0) + 1; });
  } else if (input.deviceCount > 0) {
    mix[DEFAULT_PROFILE] = input.deviceCount;
  }
  return mix;
};

/** Devices whose profile turns `key` on. null = the host sent no mapping (fall back to the backend's critical flag). */
export const devicesUsing = (key: string, input: ProfileInput): number | null => {
  if (!input.profileServices) return null;
  const mix = profileMix(input);
  let n = 0;
  Object.entries(mix).forEach(([profile, count]) => {
    // A profile the host did not map counts as tv_app (everything on), like the backend does.
    const services = input.profileServices?.[profile];
    if (services === undefined ? true : services[key] === true) n += count;
  });
  return n;
};

/** Short row labels; under the group header the service prefix is redundant. */
const ROW_LABEL: Record<string, string> = {
  'vpt-monitor-img': 'Image',
  'vpt-monitor-audio': 'Audio',
  'vpt-monitor-subtitle': 'Subtitle',
};

const downWord = (status: string): string => (status === 'stuck' ? 'stuck' : status === 'not_installed' ? 'not installed' : 'down');

const classify = (
  members: RawService[],
  group: ServiceGroup,
  input: ProfileInput,
  profileKey: string | undefined,
): Pick<ServiceRow, 'state' | 'word' | 'reason' | 'deviceCount'> | 'hidden' => {
  const deviceCount = profileKey ? devicesUsing(profileKey, input) : null;
  // Expected: needed by a device profile, otherwise the backend's critical flag (core services always are).
  const expected = deviceCount !== null && profileKey ? deviceCount > 0 : members.some((m) => m.critical);
  const statuses = members.map((m) => m.status);
  // Not installed is never a failure of its own: it goes to the collapsed list, whatever the profiles expect.
  if (statuses.every((s) => s === 'not_installed')) return 'hidden';

  const bad = members.filter((m) => m.status === 'not_installed' || NOT_RUNNING.has(m.status));
  if (!bad.length) return { state: 'active', word: 'active', reason: '', deviceCount };
  if (expected) {
    const detail = members.length > 1 ? bad.map((m) => `${m.label} ${downWord(m.status)}`).join(', ') : '';
    return { state: 'down', word: downWord(bad[0].status), reason: detail, deviceCount };
  }
  let reason = 'not needed on this host';
  if (deviceCount === 0) {
    const mix = profileMix(input);
    const allLite = Object.keys(mix).length > 0 && Object.keys(mix).every((p) => p === 'tv_lite');
    reason = allLite ? 'tv_lite: monitoring off' : 'no device needs it';
  }
  // Running members of a partly-up row stay visible in the reason.
  return { state: 'idle', word: 'idle', reason: group === 'core' ? 'not needed on this host' : reason, deviceCount };
};

export const buildHostServices = (services: RawService[], input: ProfileInput): HostServicesModel => {
  const byName = new Map(services.map((s) => [s.name, s]));
  const groups: Record<ServiceGroup, ServiceRow[]> = { core: [], monitoring: [], optional: [] };
  const notInstalled: string[] = [];
  const counts = { running: 0, down: 0, idle: 0 };

  const add = (members: RawService[], label: string, group: ServiceGroup, key: string) => {
    const profileKey = members.length === 1 ? PROFILE_SERVICE_KEY[members[0].name] : undefined;
    const c = classify(members, group, input, profileKey);
    if (c === 'hidden') { notInstalled.push(label); return; }
    // Idle services (installed but no device needs them) collapse to Optional. Their
    // "tv_lite: monitoring off" / "no device needs it" / "not needed on this host"
    // reasons are state explanations, not card subtitles — keeping them in core/monitoring
    // forced the dashboard to truncate long reason text inside cards that have no width
    // for it. Routing them to Optional also keeps the Core/Monitoring columns tight.
    const targetGroup: ServiceGroup = c.state === 'idle' ? 'optional' : group;
    const shortLabel = members.length === 1 ? ROW_LABEL[members[0].name] ?? label : label;
    groups[targetGroup].push({ key, label: shortLabel, description: members[0].description, group: targetGroup, members, ...c });
    if (c.state === 'active') counts.running += 1;
    else if (c.state === 'down') counts.down += 1;
    else counts.idle += 1;
  };

  const remote = REMOTE_VIEW.map((n) => byName.get(n)).filter((s): s is RawService => !!s);
  if (remote.length) add(remote, 'VNC', 'core', 'remote-view');

  services.forEach((s) => {
    if (REMOTE_VIEW.includes(s.name)) return;
    const pk = PROFILE_SERVICE_KEY[s.name];
    const group: ServiceGroup = CORE_NAMES.has(s.name) ? 'core' : pk && MONITORING_KEYS.has(pk) ? 'monitoring' : 'optional';
    add([s], s.label, group, s.name);
  });

  const order = (list: string[]) => (r: ServiceRow) => { const i = list.indexOf(r.members[0].name); return i < 0 ? 99 : i; };
  groups.core.sort((a, b) => (a.key === 'remote-view' ? 2 : order(['vpt-stream', 'vpt-host'])(a)) - (b.key === 'remote-view' ? 2 : order(['vpt-stream', 'vpt-host'])(b)));
  groups.monitoring.sort((a, b) => order(['vpt-monitor-img', 'vpt-monitor-audio', 'vpt-monitor-subtitle'])(a) - order(['vpt-monitor-img', 'vpt-monitor-audio', 'vpt-monitor-subtitle'])(b));
  return { groups, notInstalled, counts };
};
