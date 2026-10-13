"""
Device ceilings (TASK-31 phase C) — which devices a user works with.

The chain is team › role › user › workspace, each level a list of `host_name:device_id` keys (the
workspace `device_filter` format) or None for "no limit". A user's effective devices are the
intersection of every level that has a limit; the team level is the union across the user's
teams, a default team counting only when they are in no other team (users_db.team_cap).

This is a UI filter, not authorization: device lists hide what is outside the effective set,
and the device-control, execute and stream routes still accept any device.
"""

from typing import Iterable, List, Optional, Tuple


def clean_devices(raw) -> Tuple[Optional[List[str]], Optional[str]]:
    """(device list or None, None) or (None, error). None / missing means "no limit"."""
    if raw is None:
        return None, None
    if not isinstance(raw, list):
        return None, "'allowed_devices' must be a list of 'host_name:device_id' keys, or null for no limit"
    keys = []
    for item in raw:
        key = str(item or '').strip()
        host, sep, device = key.partition(':')
        if not sep or not host or not device:
            return None, f"'{key}' is not a 'host_name:device_id' key"
        keys.append(key)
    return sorted(set(keys)), None


def intersect(*levels: Optional[Iterable[str]]) -> Optional[List[str]]:
    """Intersection of the levels that have a limit; None when none of them does."""
    result = None
    for level in levels:
        if level is None:
            continue
        result = set(level) if result is None else result & set(level)
    return None if result is None else sorted(result)


def outside(devices: Optional[Iterable[str]], limit: Optional[Iterable[str]]) -> List[str]:
    """Devices of `devices` that `limit` does not allow. A child with no limit of its own
    (None) under a parent that has one is allowed: it simply inherits the parent's limit."""
    if devices is None or limit is None:
        return []
    return sorted(set(devices) - set(limit))


def user_scope(user: dict, role_devices: Optional[List[str]]) -> dict:
    """Every level of a user's device chain and the effective result (users_db user dict)."""
    team = user.get('team_device_ceiling')
    own = user.get('allowed_devices')
    return {
        'team_devices': team,
        'role_devices': role_devices,
        'user_devices': own,
        'effective_devices': intersect(team, role_devices, own),
    }
