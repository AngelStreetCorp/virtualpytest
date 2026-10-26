import { useEffect } from 'react';

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

/** Profile a device runs when the host reports none (TASK-90 default). It gets no badge. */
export const DEFAULT_MONITOR_PROFILE = 'tv_app';

/**
 * Monitoring profile of one device, read from the host's system stats
 * (`monitor_profiles: {device_id: profile}`); a host with no device list reports under 'host'.
 * Hosts that predate the field fall back to the default profile.
 */
export const getDeviceMonitorProfile = (host: Host, device: Device): string => {
  const profiles = host.system_stats?.monitor_profiles;
  return profiles?.[device.device_id] ?? profiles?.host ?? DEFAULT_MONITOR_PROFILE;
};

/** Preferred short badge name per profile, readable on a small tile. Unlisted profiles fall back to the profile name. */
const PROFILE_SHORT_NAMES: Record<string, string> = {
  tv_app: 'TV',
  tv_lite: 'Lite',
  pc: 'PC',
  caption_playback: 'Captions',
  counting_cars: 'Car count',
  egg_count_yolo_belt_fast: 'Egg count',
  egg_quality: 'Eggs',
  ad_meter: 'Ads',
  drone: 'Drone',
};

export const profileShortName = (profile: string): string =>
  PROFILE_SHORT_NAMES[profile] ?? profile.replace(/_/g, ' ');

/** Name tooltip of a device: "<name> - <host> - <model> - <profile>" (VNC devices show just the host). */
export const deviceTooltipName = (host: Host, device: Device | undefined, displayName: string): string => {
  if (!device || device.device_model === 'host_vnc') return displayName;
  const parts = [displayName, device.device_model, getDeviceMonitorProfile(host, device)].filter(Boolean);
  return parts.join(' - ');
};

/** Sorted distinct profiles of the given devices, and how many devices run each. */
export const countMonitorProfiles = (
  pairs: Array<{ host: Host; device: Device }>,
): { uniqueProfiles: string[]; profileCounts: Record<string, number> } => {
  const profileCounts: Record<string, number> = {};
  pairs.forEach(({ host, device }) => {
    const profile = getDeviceMonitorProfile(host, device);
    profileCounts[profile] = (profileCounts[profile] ?? 0) + 1;
  });
  return { uniqueProfiles: Object.keys(profileCounts).sort(), profileCounts };
};

/** The chip row / filter only earn their space when at least one device leaves the default profile. */
export const hasNonDefaultProfile = (uniqueProfiles: string[]) =>
  uniqueProfiles.some((p) => p !== DEFAULT_MONITOR_PROFILE);

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
  const [profileFilter, setProfileFilter] = usePersistedState<string[]>(
    `${STORAGE_KEYS.DEVICE_FILTERS}_profile`,
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
    profileFilter,
    setProfileFilter,
    flagFilter,
    setFlagFilter,
    flagMatchMode,
    setFlagMatchMode,
  };
}

type ListSetter = React.Dispatch<React.SetStateAction<string[]>>;

/** The four filter axes a device grid ANDs together. */
export interface DeviceFilterAxes {
  targetFilter: string[];
  deviceModelFilter: string[];
  profileFilter: string[];
  flagFilter: string[];
  flagMatchMode?: 'AND' | 'OR';
}

/** Which filter list an option belongs to. */
export type DeviceFilterAxis = 'targets' | 'models' | 'profiles' | 'flags';

/** Every option list the filter bar can show, narrowed to what stays pickable. */
export type ReachableFilterOptions = Record<DeviceFilterAxis, string[]>;

/**
 * The values one device contributes to each axis. The target label and the
 * monitor profile are *derived* from the host/device pair, so both pages must
 * read them through the helpers above rather than trusting a field that may be
 * absent (a VNC device has no `device_model`).
 */
const axisValuesOf = (host: Host, device: Device, tags: string[]): Record<DeviceFilterAxis, string[]> => ({
  targets: [getDeviceTargetLabel(host, device)],
  // A device without a model can never satisfy a model filter, so it
  // contributes none — listing `undefined` would offer a value that matches
  // nothing.
  models: device.device_model ? [device.device_model] : [],
  profiles: [getDeviceMonitorProfile(host, device)],
  flags: tags,
});

/**
 * Values each filter axis may offer, given the devices that survive the
 * current selection. This is what makes "No targets match the selected
 * filters" unreachable by clicking (BUG-0829).
 *
 * The rule: a value stays in the list only while at least one *surviving*
 * device carries it. Because the grid is the AND of all four axes, a value no
 * surviving device has is a dead end — picking it empties the grid, and the
 * user is left staring at an empty page with a filter chip they cannot explain.
 * Hiding it keeps every offered value meaningful: click anything on offer and
 * at least one device is still there.
 *
 * Two consequences worth knowing:
 *  - The list is *recomputed* after each change, so it tracks the user down the
 *    narrowing path. Filter targets to 2 Tellos, open More, and the tags of a
 *    third device are gone from the list because that device no longer survives.
 *  - Selected values are always kept even when unreachable, otherwise a device
 *    going offline would make its own filter value unselectable — the user
 *    could not clear their way out.
 *
 * Removing a filter value can never empty the grid (dropping an AND clause only
 * widens the result), so only additions need to be guarded — which is why this
 * narrows the *offer* and never silently rewrites the selection.
 */
export function reachableFilterOptions(
  pool: Array<{ host: Host; device: Device }>,
  axes: DeviceFilterAxes,
  tagsOf?: (hostName: string, deviceId: string) => string[],
): ReachableFilterOptions {
  const found: ReachableFilterOptions = { targets: [], models: [], profiles: [], flags: [] };
  const selected: Record<DeviceFilterAxis, string[]> = {
    targets: axes.targetFilter,
    models: axes.deviceModelFilter,
    profiles: axes.profileFilter,
    flags: axes.flagFilter,
  };
  // Each axis is offered the values of the devices that pass every OTHER axis,
  // never its own: values inside one axis are a union, so picking one must not
  // hide its siblings (the pool is the unfiltered device list).
  const tagsFor = (host: Host, device: Device) => tagsOf?.(host.host_name, device.device_id) ?? [];
  const passes = (axis: DeviceFilterAxis, host: Host, device: Device): boolean => {
    const sel = selected[axis];
    if (sel.length === 0) return true;
    const values = axisValuesOf(host, device, tagsFor(host, device))[axis];
    if (axis === 'flags' && (axes.flagMatchMode ?? 'AND') === 'AND') return sel.every((v) => values.includes(v));
    return sel.some((v) => values.includes(v));
  };
  (Object.keys(found) as DeviceFilterAxis[]).forEach((axis) => {
    const keep = new Set<string>(selected[axis]);
    pool.forEach(({ host, device }) => {
      if (!(Object.keys(found) as DeviceFilterAxis[]).every((other) => other === axis || passes(other, host, device))) return;
      axisValuesOf(host, device, tagsFor(host, device))[axis].forEach((value) => keep.add(value));
    });
    found[axis] = Array.from(keep);
  });
  return found;
}

/**
 * Narrow one filter list to the values a set of surviving devices actually
 * carries. Values already selected stay in the list (see
 * `reachableFilterOptions`), and the caller's original order is preserved.
 */
export const narrowFilterOptions = (allOptions: string[], reachable: string[], selected: string[] = []): string[] => {
  if (!reachable) return allOptions;
  const keep = new Set([...reachable, ...selected]);
  return allOptions.filter((option) => keep.has(option));
};

/**
 * Drop persisted target/model/tag picks that no longer exist in the options on
 * screen. The selection is shared across pages, servers and workspaces through
 * localStorage, so a target picked on another server (e.g. "Tello-F014A0 - ...")
 * would otherwise linger and hide every host here ("No hosts match").
 * Pass `ready=false` while the device list is still loading so an empty
 * mid-fetch option list doesn't wipe filters restored on refresh; same for
 * `flagsReady` and the tag list.
 */
export function usePruneDeviceFilters(
  setters: {
    setTargetFilter: ListSetter;
    setDeviceModelFilter: ListSetter;
    setFlagFilter: ListSetter;
    setProfileFilter: ListSetter;
  },
  options: { targetOptions: string[]; uniqueDeviceModels: string[]; uniqueFlags: string[]; uniqueProfiles: string[] },
  ready: boolean,
  flagsReady: boolean,
) {
  const { setTargetFilter, setDeviceModelFilter, setFlagFilter, setProfileFilter } = setters;
  const { targetOptions, uniqueDeviceModels, uniqueFlags, uniqueProfiles } = options;
  useEffect(() => {
    if (!ready) return;
    const prune = (setter: ListSetter, valid: string[]) => {
      const validSet = new Set(valid);
      setter((prev) => {
        const next = prev.filter((v) => validSet.has(v));
        return next.length === prev.length ? prev : next;
      });
    };
    prune(setTargetFilter, targetOptions);
    prune(setDeviceModelFilter, uniqueDeviceModels);
    prune(setProfileFilter, uniqueProfiles);
    if (flagsReady) prune(setFlagFilter, uniqueFlags);
  }, [ready, flagsReady, targetOptions, uniqueDeviceModels, uniqueFlags, uniqueProfiles, setTargetFilter, setDeviceModelFilter, setFlagFilter, setProfileFilter]);
}
