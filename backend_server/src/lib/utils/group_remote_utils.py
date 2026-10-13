"""
Group remote control (TASK-76, TASK-80): one remote command sent to N devices that
share a device model and a remote profile. TASK-80 lifts the profile to per-target:
each device picks its own `remote_profile` (BLE on one, IR on the other), the
backend validates it owns that profile, then fans out one `press_key` per device
on its own transport.

Pure helpers: the route passes in the host lookup, the lock lookup and the sender,
so tests run without Flask, hosts or a lock manager.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from shared.src.lib.config.remote_profiles import (
    device_remote_profiles,
    group_mismatches,
    profile_remote_type,
)

Target = Dict[str, str]
HostInfo = Dict[str, Any]
# Each fan-out job carries the per-target profile so the host gets the right
# remote_type for that device. Legacy callers (single-profile) wrap every job
# with the same profile.
Job = Tuple[HostInfo, Dict[str, Any], str]


def resolve_targets(
    targets: Iterable[Target],
    get_host: Callable[[str], Optional[HostInfo]],
) -> Tuple[List[Tuple[HostInfo, Dict[str, Any]]], List[Dict[str, str]]]:
    """(host_info, device) per target from the host registry, plus the targets not found."""
    resolved, missing = [], []
    for t in targets:
        host_name, device_id = t.get('host_name'), t.get('device_id')
        host = get_host(host_name) if host_name else None
        device = next((d for d in (host or {}).get('devices', []) if d.get('device_id') == device_id), None)
        if not device:
            missing.append({'host_name': host_name or '', 'device_id': device_id or '', 'reason': 'device not found'})
            continue
        resolved.append((host, {**device, 'host_name': host_name}))
    return resolved, missing


def resolve_per_target_profiles(
    resolved: List[Tuple[HostInfo, Dict[str, Any]]],
    targets: Iterable[Target],
    default_profile: Optional[str] = None,
) -> List[Optional[str]]:
    """For each resolved device, return the profile to drive it on. Order matches
    `resolved`. Each target may carry its own `remote_profile` (TASK-80); when it
    doesn't, the top-level `default_profile` is used. Returns None when neither
    is set, so the caller can flag the target as misconfigured."""
    target_list = list(targets)
    if len(target_list) != len(resolved):
        # Defensive: the route always passes matching lists, but never trust a zip.
        return [None] * len(resolved)
    profiles: List[Optional[str]] = []
    for (_, _device), t in zip(resolved, target_list):
        per = t.get('remote_profile')
        profiles.append(per or default_profile)
    return profiles


def per_target_mismatches(
    resolved: List[Tuple[HostInfo, Dict[str, Any]]],
    profiles: List[Optional[str]],
    device_model: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Each device must (a) share `device_model` (or any model when None is allowed)
    and (b) own the profile the caller picked for it. Returns one reason per offender.
    When `device_model` is None, model equality is skipped (the route is responsible
    for any model-family check)."""
    bad: List[Dict[str, str]] = []
    for (_, device), chosen in zip(resolved, profiles):
        host_name = device.get('host_name', '')
        device_id = device.get('device_id', '')
        if not chosen:
            bad.append({'host_name': host_name, 'device_id': device_id, 'reason': 'no remote_profile set for this target'})
            continue
        if device_model is not None and device.get('device_model') != device_model:
            bad.append({
                'host_name': host_name, 'device_id': device_id,
                'reason': f"model {device.get('device_model')} is not {device_model}",
            })
            continue
        if chosen not in device_remote_profiles(device):
            have = ', '.join(device_remote_profiles(device)) or 'none'
            bad.append({
                'host_name': host_name, 'device_id': device_id,
                'reason': f'no {chosen} remote (has: {have})',
            })
    return bad


def validate_group(
    resolved: List[Tuple[HostInfo, Dict[str, Any]]],
    remote_profile: str,
    device_model: Optional[str] = None,
) -> Tuple[Optional[str], List[Dict[str, str]]]:
    """(device_model, mismatches): every device must share the model and have the profile.
    Legacy single-profile entry point kept for backward compatibility with TASK-76 callers."""
    if not resolved:
        return device_model, []
    model = device_model or resolved[0][1].get('device_model')
    return model, group_mismatches([d for _, d in resolved], model, remote_profile)


def lock_blocker(lock_info: Optional[Dict[str, Any]], session_ids: Iterable[str], user_id: Optional[str]) -> Optional[str]:
    """Why a device cannot be driven: held by another session and another user. None = free or ours."""
    if not lock_info:
        return None
    if lock_info.get('owner_session_id') in set(s for s in session_ids if s):
        return None
    if user_id and lock_info.get('owner_user_id') == user_id:
        return None
    owner = lock_info.get('owner_user_name') or lock_info.get('owner_user_id') or lock_info.get('owner_type') or 'another user'
    return f'locked by {owner}'


def fan_out(
    jobs: List[Job],
    command: str,
    params: Dict[str, Any],
    send: Callable[[HostInfo, Dict[str, Any]], Tuple[Dict[str, Any], int]],
) -> List[Dict[str, Any]]:
    """Sends the command to every job in parallel; one result per job, in order.

    Each job is (host, device, remote_profile). The per-target `remote_profile` is
    converted to its `remote_type` and stamped on the host's request body so the
    host routes to the right controller (IR transmitter, BLE dongle, adb_tv, vega…).

    Backwards compatibility: a legacy caller passing jobs as (host, device) tuples
    gets the old behavior — every job sent with no remote_type stamp. The route
    always passes the new shape today.
    """
    def one(job: Any) -> Dict[str, Any]:
        if len(job) == 3:
            host, device, profile = job
        else:
            host, device = job
            profile = ''
        started = time.monotonic()
        body: Optional[Dict[str, Any]] = None
        ok = False
        error: Optional[str] = None
        try:
            payload: Dict[str, Any] = {
                'device_id': device['device_id'],
                'command': command,
                'params': params,
            }
            if profile:
                payload['remote_type'] = profile_remote_type(profile)
            body, status = send(host, payload)
            ok = status < 400 and bool((body or {}).get('success', status < 400))
            error = None if ok else (body or {}).get('error') or f'HTTP {status}'
        except Exception as exc:  # one dead host must not fail the group
            body, ok, error = None, False, str(exc)
        return {
            'host_name': device['host_name'],
            'device_id': device['device_id'],
            'remote_profile': profile or None,
            'success': ok,
            'error': error,
            'ms': round((time.monotonic() - started) * 1000),
            'response': body,
        }

    if not jobs:
        return []
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        return list(pool.map(one, jobs))


def skew_ms(results: List[Dict[str, Any]]) -> int:
    """Spread between the fastest and slowest sent device (ms); 0 below two."""
    sent = [r['ms'] for r in results if not r.get('skipped')]
    return max(sent) - min(sent) if len(sent) > 1 else 0
