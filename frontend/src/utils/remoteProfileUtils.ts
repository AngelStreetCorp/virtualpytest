/**
 * Remote profiles (TASK-76, TASK-80) — mirror of shared/src/lib/config/remote_profiles.py.
 * A profile is a remote controller plus its key map; for multi-profile group
 * control (TASK-80) every member picks its own profile, and the visible skin is
 * the operator-chosen one with keys greyed outside the intersection.
 */
import type { Device } from '../types/common/Host_Types';

const IR_PREFIX = 'ir:';
const BLE_PREFIX = 'ble:';
const FIXED_REMOTE_TYPES: Record<string, string> = { adb_tv: 'android_tv', adb_mobile: 'android_mobile' };
const FIXED_LABELS: Record<string, string> = { adb_tv: 'ADB', adb_mobile: 'ADB', vega: 'Vega', appium: 'Appium' };

// Mirror of shared/src/lib/config/remote_profiles.py:canonical sets — see the
// Python module for the rationale. The frontend never reads IR / BLE JSON
// files; the backend publishes `device.key_capabilities` on every device, and
// the canonical sets live here so the group tile can compute the intersection
// without a round-trip.
const CANONICAL_FIRE_TV_KEYS: ReadonlyArray<string> = [
  'POWER', 'HOME', 'BACK', 'MENU',
  'UP', 'DOWN', 'LEFT', 'RIGHT', 'OK',
  'VOLUME_UP', 'VOLUME_DOWN', 'MUTE',
  'CHANNEL_UP', 'CHANNEL_DOWN',
  'PLAY', 'PAUSE', 'PLAY_PAUSE', 'STOP', 'REWIND', 'FORWARD', 'RECORD',
  'KEY_0', 'KEY_1', 'KEY_2', 'KEY_3', 'KEY_4', 'KEY_5', 'KEY_6', 'KEY_7', 'KEY_8', 'KEY_9',
  'TVGUIDE', 'INFO', 'VOICE',
];
const CANONICAL_PROFILES: Record<string, ReadonlyArray<string>> = {
  adb_tv: CANONICAL_FIRE_TV_KEYS,
  adb_mobile: [
    'POWER', 'HOME', 'BACK', 'MENU', 'VOLUME_UP', 'VOLUME_DOWN', 'MUTE', 'OK', 'ENTER',
    'DPAD_UP', 'DPAD_DOWN', 'DPAD_LEFT', 'DPAD_RIGHT', 'DPAD_CENTER',
  ],
  vega: CANONICAL_FIRE_TV_KEYS,
  appium: ['POWER', 'HOME', 'BACK', 'VOLUME_UP', 'VOLUME_DOWN', 'MUTE', 'OK'],
  tello: [],
  fx: [],
};

export const deviceRemoteProfiles = (device: Device): string[] => device.remote_profiles ?? [];

/** The `remote_type` the host resolves for a profile (and the RemotePanel case it renders). */
export const profileRemoteType = (profile: string): string => {
  if (profile.startsWith(IR_PREFIX)) return 'ir_remote';
  if (profile.startsWith(BLE_PREFIX)) return 'bluetooth_remote';
  return FIXED_REMOTE_TYPES[profile] ?? profile;
};

/** Short label for chips and pickers: "IR stb", "BLE arris", "ADB", "Vega". */
export const formatRemoteProfile = (profile: string): string => {
  if (profile.startsWith(IR_PREFIX)) return `IR ${profile.slice(IR_PREFIX.length)}`;
  if (profile.startsWith(BLE_PREFIX)) return `BLE ${profile.slice(BLE_PREFIX.length)}`;
  return FIXED_LABELS[profile] ?? profile;
};

/** Default profile for a first pick: a direct link (ADB, Vega) before IR before BLE. */
export const preferredRemoteProfile = (profiles: string[]): string | null => {
  const rank = (p: string) => (p.startsWith(BLE_PREFIX) ? 2 : p.startsWith(IR_PREFIX) ? 1 : 0);
  return [...profiles].sort((a, b) => rank(a) - rank(b))[0] ?? null;
};

/**
 * Read the key set for `profile` on the given device. Prefers the backend's
 * `device.key_capabilities[profile]`; falls back to the canonical table for
 * fixed-key profiles (adb_tv, vega, …) when the device hasn't published the
 * map yet (older host) or when the profile is fixed.
 *
 * Returns `null` for IR / BLE profiles the device does not own — the caller
 * can then drop the device from the group.
 */
export const deviceProfileKeys = (device: Device, profile: string): string[] | null => {
  if (profile in CANONICAL_PROFILES) {
    return [...CANONICAL_PROFILES[profile]];
  }
  const caps = (device as Device & { key_capabilities?: Record<string, string[]> }).key_capabilities;
  if (caps && profile in caps) {
    return caps[profile];
  }
  // IR / BLE without a backend-published capability map: the frontend cannot
  // read the JSON files itself; signal "unknown" with null so the caller can
  // either refuse the group or treat the profile as universal (safe default).
  return null;
};

/**
 * The keys present on every member's transport for the given profile set.
 * Mirrors `shared_key_intersection` in the Python lib. Unknown member key
 * sets are dropped from the intersection (safe default), not treated as
 * empty (which would erase every key).
 */
export const sharedKeyIntersection = (device: Device, profiles: string[]): string[] => {
  if (profiles.length === 0) return [];
  const sets: string[][] = [];
  for (const profile of profiles) {
    const keys = deviceProfileKeys(device, profile);
    if (keys && keys.length > 0) {
      sets.push(keys);
    }
  }
  if (sets.length === 0) return [];
  let acc = new Set(sets[0]);
  for (let i = 1; i < sets.length; i += 1) {
    acc = new Set([...acc].filter((k) => sets[i].includes(k)));
  }
  return [...acc].sort();
};

/**
 * Pick the per-member transport profile for a multi-profile group.
 *
 * Priority:
 *   1. The profile the caller already pinned (e.g. the operator dragged a
 *      "use IR" toggle for this device). `pinned` is optional.
 *   2. A profile the device owns that the operator-chosen `displayedProfile`
 *      set requires the keys for — i.e. the device's own profile whose key
 *      set is a superset of the intersection. If multiple match, prefer the
 *      direct one (BLE / IR match) over the canonical.
 *   3. The device's preferred profile (the first pick, ranked direct > IR > BLE).
 *   4. `null` when nothing fits — the caller drops this device from the group.
 */
export const chooseDeviceProfile = (
  device: Device,
  displayedProfile: string,
  sharedKeys: ReadonlyArray<string>,
  pinned?: string | null,
): string | null => {
  const owned = new Set(deviceRemoteProfiles(device));
  if (pinned && owned.has(pinned)) return pinned;

  // Displayed profile that the device also owns: keep the skin as the
  // transport (operator's first pick wins; the simpler case in the screenshot).
  if (owned.has(displayedProfile)) return displayedProfile;

  // The device has the chosen skin AND an alternative transport. We must pick
  // the one that drives the chosen skin's intersection. If both fit, prefer
  // the direct (BLE / IR) profile that *is* the displayedProfile's family.
  for (const profile of owned) {
    const keys = deviceProfileKeys(device, profile);
    if (!keys) continue;
    if (sharedKeys.every((k) => keys.includes(k))) return profile;
  }
  return preferredRemoteProfile([...owned]);
};
