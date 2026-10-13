"""
Remote profiles (TASK-76 group control, TASK-80 multi-profile transport).

A remote profile names a remote controller *and* its key map. Two devices can be
driven as one group only when they share the device model and a profile: the same
key name does different things on different controllers (IR `stb.json` POWER is not
BLE `arris.json` POWER, ADB HOME is not IR `fire_tv.json` HOME).

    ir_remote (lirc / IR Toy / IRTrans) → ir:<ir_type>   (transport does not change the codes)
    bluetooth_remote                    → ble:<ble_type>
    android_tv                          → adb_tv
    android_mobile                      → adb_mobile
    anything else                       → its implementation name (vega, appium, tello, fx…)

TASK-80 multi-profile transport: a group can mix controllers when every member
shares the same model family (or model) and the **chosen profile's** key set is
a subset of every member's key set. The visible skin = the chosen profile; the
send is per-member on its own transport. `available_keys(model, profile)` and
`shared_key_intersection(model, profiles)` are the contract.
"""

import json
import os
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Set

# Largest group one command fans out to (the device page and the MCP tool share it).
GROUP_MAX_SIZE = 6

IR_PREFIX = 'ir:'
BLE_PREFIX = 'ble:'

_FIXED_PROFILES = {
    'android_tv': 'adb_tv',
    'android_mobile': 'adb_mobile',
}

# Where the IR / BLE key maps live (mirrors of frontend config).
_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
_IR_CONF_DIR = os.path.join(_REPO_ROOT, 'backend_host', 'src', 'controllers', 'remote', 'ir_conf')
_BLE_CONF_DIR = os.path.join(_REPO_ROOT, 'backend_host', 'src', 'controllers', 'remote', 'bluetooth', 'ble_conf')

# Canonical key sets for fixed-key remotes (Vega, ADB TV). These are the keys the
# device's own controller implementation always accepts — Vega through inputd-cli,
# Android TV through `adb shell input keyevent`. They're the "everything the box
# can do" set, so they're a superset of every layout we've ever drawn.
CANONICAL_FIRE_TV_KEYS = [
    'POWER', 'HOME', 'BACK', 'MENU',
    'UP', 'DOWN', 'LEFT', 'RIGHT', 'OK',
    'VOLUME_UP', 'VOLUME_DOWN', 'MUTE',
    'CHANNEL_UP', 'CHANNEL_DOWN',
    'PLAY', 'PAUSE', 'PLAY_PAUSE', 'STOP', 'REWIND', 'FORWARD', 'RECORD',
    'KEY_0', 'KEY_1', 'KEY_2', 'KEY_3', 'KEY_4', 'KEY_5', 'KEY_6', 'KEY_7', 'KEY_8', 'KEY_9',
    'TVGUIDE', 'INFO', 'VOICE',
]
CANONICAL_ANDROID_TV_KEYS = sorted(set(CANONICAL_FIRE_TV_KEYS))  # same key surface for adb_tv
CANONICAL_VEGA_KEYS = sorted(set(CANONICAL_FIRE_TV_KEYS))         # vega remote = Fire TV remote

# Profiles whose key set is the canonical table above, not a JSON file.
_CANONICAL_PROFILES = {
    'adb_tv': CANONICAL_ANDROID_TV_KEYS,
    'adb_mobile': ['POWER', 'HOME', 'BACK', 'MENU', 'VOLUME_UP', 'VOLUME_DOWN', 'MUTE', 'OK', 'ENTER',
                   'DPAD_UP', 'DPAD_DOWN', 'DPAD_LEFT', 'DPAD_RIGHT', 'DPAD_CENTER'],
    'vega': CANONICAL_VEGA_KEYS,
    'appium': ['POWER', 'HOME', 'BACK', 'VOLUME_UP', 'VOLUME_DOWN', 'MUTE', 'OK'],
    'tello': [],  # drone, no remote key surface
    'fx': [],
}


def remote_profile(implementation: str, conf: Optional[str] = None) -> str:
    """Profile of one remote controller: implementation + key map."""
    if implementation == 'ir_remote':
        return f"{IR_PREFIX}{conf or 'unknown'}"
    if implementation == 'bluetooth_remote':
        return f"{BLE_PREFIX}{conf or 'unknown'}"
    return _FIXED_PROFILES.get(implementation, implementation)


def remote_conf(controller: Any) -> Optional[str]:
    """Key-map name carried by an IR (`ir_type`) or BLE (`ble_type`) controller instance."""
    return getattr(controller, 'ir_type', None) or getattr(controller, 'ble_type', None)


def profile_remote_type(profile: str) -> str:
    """The `remote_type` the host route resolves for a profile (see get_remote_controller_by_type)."""
    if profile.startswith(IR_PREFIX):
        return 'ir_remote'
    if profile.startswith(BLE_PREFIX):
        return 'bluetooth_remote'
    for implementation, fixed in _FIXED_PROFILES.items():
        if profile == fixed:
            return implementation
    return profile


def device_remote_profiles(device: Dict[str, Any]) -> List[str]:
    """Profiles of a serialized device (`Device.to_dict()` / getAllHosts entry)."""
    return list(device.get('remote_profiles') or [])


def group_mismatches(devices: Iterable[Dict[str, Any]], device_model: str, profile: str) -> List[Dict[str, str]]:
    """Devices that cannot join a (device_model, profile) group, each with the reason."""
    bad = []
    for d in devices:
        if d.get('device_model') != device_model:
            reason = f"model {d.get('device_model')} is not {device_model}"
        elif profile not in device_remote_profiles(d):
            have = ', '.join(device_remote_profiles(d)) or 'none'
            reason = f"no {profile} remote (has: {have})"
        else:
            continue
        bad.append({'host_name': d.get('host_name', ''), 'device_id': d.get('device_id', ''), 'reason': reason})
    return bad


def build_groups(devices: Iterable[Dict[str, Any]], min_size: int = 2) -> List[Dict[str, Any]]:
    """Every (device_model, profile) shared by at least `min_size` devices, largest first."""
    buckets: Dict[tuple, List[Dict[str, Any]]] = {}
    for d in devices:
        for profile in device_remote_profiles(d):
            buckets.setdefault((d.get('device_model'), profile), []).append(d)
    groups = [
        {
            'device_model': model,
            'remote_profile': profile,
            'remote_type': profile_remote_type(profile),
            'devices': [
                {'host_name': d.get('host_name'), 'device_id': d.get('device_id'), 'device_name': d.get('device_name')}
                for d in members
            ],
        }
        for (model, profile), members in buckets.items()
        if len(members) >= min_size
    ]
    return sorted(groups, key=lambda g: (-len(g['devices']), g['device_model'] or '', g['remote_profile']))


# --- TASK-80: key capability surface and shared intersection ---------------------

def _ir_conf_path(ir_type: str) -> str:
    return os.path.join(_IR_CONF_DIR, f"{ir_type}.json")


def _ble_conf_path(ble_type: str) -> str:
    return os.path.join(_BLE_CONF_DIR, f"{ble_type}.json")


@lru_cache(maxsize=128)
def _load_ir_keys(ir_type: str) -> frozenset:
    """Cached keys of an IR keymap (JSON file). Strips the `_comment` metadata key."""
    if not ir_type:
        return frozenset()
    path = _ir_conf_path(ir_type)
    if not os.path.exists(path):
        return frozenset()
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return frozenset()
    return frozenset(k for k in data.keys() if not k.startswith('_'))


@lru_cache(maxsize=128)
def _load_ble_keys(ble_type: str) -> frozenset:
    """Cached keys of a BLE keymap (JSON file). Strips the `_comment` metadata key."""
    if not ble_type:
        return frozenset()
    path = _ble_conf_path(ble_type)
    if not os.path.exists(path):
        return frozenset()
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return frozenset()
    return frozenset(k for k in data.keys() if not k.startswith('_'))


def invalidate_key_cache() -> None:
    """Drop the in-memory IR/BLE key caches (e.g. after a BLE re-pair writes a new keymap)."""
    _load_ir_keys.cache_clear()
    _load_ble_keys.cache_clear()


def available_keys(model: str, profile: str) -> List[str]:
    """Keys that `profile` accepts on `model`. The contract for TASK-80 multi-profile
    grouping: every member of a group must own the keys the chosen skin renders.

    For IR / BLE profiles the result comes from the on-disk keymap. For the fixed
    profiles (Vega, ADB TV, appium, …) it is the canonical table the controller
    implementation always accepts. Returns a sorted list for stable comparison.
    """
    del model  # the key set is the same for any model that has this profile
    if profile in _CANONICAL_PROFILES:
        return sorted(_CANONICAL_PROFILES[profile])
    if profile.startswith(IR_PREFIX):
        return sorted(_load_ir_keys(profile[len(IR_PREFIX):]))
    if profile.startswith(BLE_PREFIX):
        return sorted(_load_ble_keys(profile[len(BLE_PREFIX):]))
    return []  # unknown profile: no claims


def device_key_capabilities(device: Dict[str, Any]) -> Dict[str, List[str]]:
    """Map of profile → keys, for one device. Returns an empty map when the device
    has no profiles (still cheaper than recomputing on the frontend)."""
    out: Dict[str, List[str]] = {}
    model = device.get('device_model') or ''
    for profile in device_remote_profiles(device):
        keys = available_keys(model, profile)
        if keys:
            out[profile] = keys
    return out


def shared_key_intersection(model: str, profiles: List[str]) -> List[str]:
    """Sorted intersection of `available_keys` across the given profiles — the keys
    present on every selected device's transport. Empty list when no key is shared
    or when `profiles` is empty (the frontend disables the Start button in that case)."""
    if not profiles:
        return []
    sets: List[Set[str]] = [set(available_keys(model, p)) for p in profiles]
    sets = [s for s in sets if s]
    if not sets:
        return []
    return sorted(set.intersection(*sets))
