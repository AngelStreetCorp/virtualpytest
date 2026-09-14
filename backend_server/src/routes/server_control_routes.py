"""
Server Control Routes

This module contains server-side control endpoints that:
- Handle device locking and unlocking on server side
- Coordinate with hosts for device control operations
- Forward requests to appropriate hosts
- Manage device registry and host discovery
- Provide controller type information
"""

from flask import Blueprint, request, jsonify, session
import os
import uuid
import json
import time
import threading
from datetime import datetime
from typing import Dict, Any, Optional

from shared.src.lib.utils.build_url_utils import call_host
from backend_server.src.lib.utils.server_utils import get_host_manager
from backend_server.src.lib.utils.lock_utils import (
    abort_and_force_unlock,
    abort_running_execution,
    acquire_device_lock,
    cleanup_expired_locks,
    get_all_locked_devices,
    get_client_ip,
    get_device_lock_info,
    release_device_lock,
    takeover_device_lock,
)
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.routes.server_system_socket_routes import emit_system_update

# Create blueprint
server_control_bp = Blueprint('server_control', __name__, url_prefix='/server/control')
MANUAL_LOCK_TIMEOUT_SECONDS = 180

# Absolute age after which a script/deployment lock is considered a zombie and
# auto-reaped. These locks normally release on the host's completion callback;
# if that callback never fires (host crash, dropped network, scheduler post-
# processing dying — see project_deployment_queue_bug) the in-memory lock leaks
# forever. Script locks never heartbeat, so this is a pure max-runtime ceiling:
# set it comfortably above the longest real run so a live script is never killed.
SCRIPT_LOCK_TIMEOUT_SECONDS = int(os.environ.get('SCRIPT_LOCK_MAX_AGE_SECONDS', 7200))
SCRIPT_LOCK_OWNER_TYPES = ('script_execution', 'deployment_execution')

# =====================================================
# SERVER-SIDE DEVICE CONTROL ENDPOINTS
# =====================================================


def _get_or_create_session_id(explicit_session_id: Optional[str] = None) -> str:
    if explicit_session_id:
        session['session_id'] = explicit_session_id
        return explicit_session_id
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    return session['session_id']


def _build_lock_conflict_payload(host_name: str, device_id: str, lock_info: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'success': False,
        'error': f'Device {host_name}:{device_id} is locked',
        'errorType': 'device_locked',
        'owner_type': lock_info.get('owner_type'),
        'owner_user_id': lock_info.get('owner_user_id'),
        'owner_user_name': lock_info.get('owner_user_name'),
        'owner_session_id': lock_info.get('owner_session_id'),
        'owner_job_id': lock_info.get('owner_job_id'),
        'can_wait': True,
        'can_force_takeover': bool(lock_info.get('can_force_takeover', False)),
        'message': lock_info.get('lock_reason') or 'Device is currently in use by another execution',
        'lock_info': lock_info,
    }


def _emit_lock_released(released_locks) -> None:
    """Notify clients so stale lock badges clear immediately, not on next refresh."""
    for lock_info in released_locks or []:
        try:
            emit_system_update('lock_changed', {
                'host_name': lock_info.get('host_name'),
                'device_id': lock_info.get('device_id'),
                'is_locked': False,
                'lock_info': lock_info,
            })
        except Exception as exc:
            print(f"⚠️ [CONTROL] Failed to emit lock_changed for reaped lock: {exc}")


def _cleanup_stale_manual_locks() -> None:
    """Auto-reap stale locks (opportunistic, runs on every lock/unlock/list call).

    Two independent sweeps:
    - manual_control: expired when frontend heartbeats stop (MANUAL_LOCK_TIMEOUT).
    - script/deployment: reaped past an absolute max-runtime ceiling, healing
      zombie locks whose completion callback never fired.
    """
    try:
        released = cleanup_expired_locks(timeout_seconds=MANUAL_LOCK_TIMEOUT_SECONDS)
        if released:
            print(f"🧹 [CONTROL] Auto-unlocked {len(released)} stale manual lock(s)")
            _emit_lock_released(released)
    except Exception as exc:
        print(f"⚠️ [CONTROL] Failed to cleanup stale manual locks: {exc}")

    try:
        released = cleanup_expired_locks(
            timeout_seconds=SCRIPT_LOCK_TIMEOUT_SECONDS,
            owner_types=SCRIPT_LOCK_OWNER_TYPES,
        )
        if released:
            print(f"🧹 [CONTROL] Auto-reaped {len(released)} zombie script lock(s)")
            _emit_lock_released(released)
    except Exception as exc:
        print(f"⚠️ [CONTROL] Failed to reap zombie script locks: {exc}")


def _try_populate_navigation_cache(
    data: Dict[str, Any],
    host_name: str,
    team_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    tree_id = data.get('tree_id')
    userinterface_id = data.get('userinterface_id')
    userinterface_name = data.get('userinterface_name')
    if team_id is None:
        team_id = request.args.get('team_id')

    if userinterface_name and team_id and not userinterface_id:
        print(f"🔍 [CONTROL] Resolving userinterface_id from userinterface_name: {userinterface_name}")
        from shared.src.lib.database.userinterface_db import get_userinterface_by_name

        ui_result = get_userinterface_by_name(userinterface_name, team_id)
        if ui_result and ui_result.get('id'):
            userinterface_id = ui_result['id']
            print(f"✅ [CONTROL] Resolved userinterface_id: {userinterface_id}")
        else:
            print(f"⚠️ [CONTROL] No user interface found for name: {userinterface_name}")

    if userinterface_id and team_id and not tree_id:
        print(f"🔍 [CONTROL] Resolving tree_id from userinterface_id: {userinterface_id}")
        from shared.src.lib.database.navigation_trees_db import get_root_tree_for_interface

        tree = get_root_tree_for_interface(userinterface_id, team_id)
        if tree:
            tree_id = tree['id']
            print(f"✅ [CONTROL] Resolved tree_id: {tree_id}")
        else:
            print(f"⚠️ [CONTROL] No tree found for userinterface_id: {userinterface_id}")

    if tree_id and team_id:
        print(f"🗺️ [CONTROL] Populating navigation cache for tree: {tree_id}")
        cache_success = populate_navigation_cache_for_control(tree_id, team_id, host_name)
        if not cache_success:
            return {
                'success': False,
                'error': f'Failed to populate navigation cache for tree {tree_id}. Check server logs for details.',
                'errorType': 'cache_error',
            }

    return None


def _forward_take_control_to_host(host_data: Dict[str, Any], device_id: str) -> Dict[str, Any]:
    request_payload = {'device_id': device_id}
    response_data, status_code = call_host(
        host_data,
        '/host/takeControl',
        method='POST',
        data=request_payload,
        timeout=30,
    )
    return {
        'response_data': response_data,
        'status_code': status_code,
    }


def _release_manual_lock(host_name: str, device_id: str, session_id: str) -> None:
    release_device_lock(
        host_name=host_name,
        device_id=device_id,
        owner_session_id=session_id,
        owner_type='manual_control',
        force=True,
    )


def _abort_running_execution(
    host_data: Dict[str, Any],
    device_id: str,
    owner_type: Optional[str],
) -> Dict[str, Any]:
    """Thin wrapper around shared abort_running_execution utility."""
    return abort_running_execution(host_data, device_id, owner_type)


def _run_take_control_setup(
    host_data: Dict[str, Any],
    host_name: str,
    device_id: str,
    session_id: str,
    request_data: Dict[str, Any],
    team_id: Optional[str],
) -> None:
    """Background worker: host /takeControl + nav cache populate, in parallel.

    On host-call failure releases the manual lock and emits ``control_failed``.
    On success emits ``control_ready`` with controllers + cache state.
    """
    host_holder: Dict[str, Any] = {}
    cache_holder: Dict[str, Any] = {'success': True, 'skipped': True}

    def run_host():
        try:
            host_holder.update(_forward_take_control_to_host(host_data, device_id))
        except Exception as exc:
            print(f"❌ [CONTROL:BG] Host take-control raised: {exc}")
            host_holder['response_data'] = {'success': False, 'error': str(exc)}
            host_holder['status_code'] = 500

    def run_cache():
        try:
            err = _try_populate_navigation_cache(request_data, host_name, team_id=team_id)
            if err:
                cache_holder.clear()
                cache_holder.update({'success': False, **err})
        except Exception as exc:
            print(f"❌ [CONTROL:BG] Cache populate raised: {exc}")
            cache_holder.clear()
            cache_holder.update({'success': False, 'error': str(exc)})

    host_thread = threading.Thread(target=run_host, daemon=True)
    cache_thread = threading.Thread(target=run_cache, daemon=True)
    host_thread.start()
    cache_thread.start()
    host_thread.join(timeout=35)
    cache_thread.join(timeout=35)

    response_data = host_holder.get('response_data') or {}
    status_code = host_holder.get('status_code', 0)
    host_ok = status_code == 200 and response_data.get('success')

    if not host_ok:
        error_message = response_data.get('error', 'Host failed to take control')
        error_type = response_data.get('errorType', 'host_error')
        if status_code == 504:
            error_message, error_type = f"Host communication timeout: {error_message}", 'network_error'
        elif status_code == 503:
            error_message, error_type = f"Could not connect to host: {error_message}", 'network_error'
        print(f"❌ [CONTROL:BG] Host call failed (status: {status_code}): {error_message}")
        _release_manual_lock(host_name, device_id, session_id)
        emit_system_update('lock_changed', {
            'host_name': host_name,
            'device_id': device_id,
            'is_locked': False,
        })
        emit_system_update('control_failed', {
            'host_name': host_name,
            'device_id': device_id,
            'session_id': session_id,
            'error': error_message,
            'errorType': error_type,
            'host_result': response_data,
        })
        return

    cache_ok = cache_holder.get('success', True)
    print(f"✅ [CONTROL:BG] Setup complete for {host_name}:{device_id} (controllers_ready=True, cache_ready={cache_ok})")
    emit_system_update('control_ready', {
        'host_name': host_name,
        'device_id': device_id,
        'session_id': session_id,
        'controllers_ready': True,
        'cache_ready': cache_ok,
        'available_controllers': response_data.get('available_controllers', []),
        'warning': response_data.get('warning'),
        'cache_error': None if cache_ok else cache_holder.get('error'),
    })


@server_control_bp.route('/takeControl', methods=['POST'])
@handle_route_exceptions('server_control:take_control')
def take_control():
    """Take control of a device.

    Returns immediately after acquiring the DB lock. The host /takeControl call
    and navigation-cache populate run in a background thread; their completion
    is broadcast via ``control_ready`` / ``control_failed`` on /system.
    """
    _cleanup_stale_manual_locks()
    data = request.get_json() or {}
    host_name = data.get('host_name')
    device_id = (data.get('device_id') or '').strip()
    team_id = request.args.get('team_id')

    if not host_name or not device_id:
        return jsonify({'error': 'host_name and device_id are required'}), 400

    session_id = _get_or_create_session_id(data.get('session_id'))
    user_id = data.get('user_id') or request.headers.get('X-User-ID')
    user_name = data.get('user_name')
    client_ip = get_client_ip()

    print(f"🎮 [CONTROL] Taking control of host: {host_name}, device: {device_id} (session: {session_id}, user: {user_name or user_id}, IP: {client_ip})")

    host_manager = get_host_manager()
    host_data = host_manager.get_host(host_name)
    if not host_data:
        return jsonify({
            'success': False,
            'error': f'Host {host_name} not found',
            'errorType': 'device_not_found',
        }), 404

    lock_result = acquire_device_lock(
        host_name=host_name,
        device_id=device_id,
        owner_type='manual_control',
        owner_session_id=session_id,
        owner_user_id=user_id,
        owner_user_name=user_name,
        lock_reason='manual_take_control',
        can_force_takeover=True,
        client_ip=client_ip,
    )
    if not lock_result.get('success'):
        conflict = lock_result.get('conflict') or get_device_lock_info(host_name, device_id)
        if conflict:
            return jsonify(_build_lock_conflict_payload(host_name, device_id, conflict)), 423
        return jsonify({
            'success': False,
            'error': f'Failed to lock host {host_name}, device {device_id}',
            'errorType': 'generic_error',
        }), 500

    lock_info = lock_result.get('lock_info') or get_device_lock_info(host_name, device_id)
    emit_system_update('lock_changed', {
        'host_name': host_name,
        'device_id': device_id,
        'is_locked': True,
        'lock_info': lock_info,
    })

    threading.Thread(
        target=_run_take_control_setup,
        args=(host_data, host_name, device_id, session_id, data, team_id),
        daemon=True,
    ).start()

    return jsonify({
        'success': True,
        'message': f'Lock acquired; finishing controller + cache setup in background',
        'session_id': session_id,
        'host_name': host_name,
        'device_id': device_id,
        'lock_info': lock_info,
        'controllers_ready': False,
        'cache_ready': False,
    })


@server_control_bp.route('/releaseControl', methods=['POST'])
@handle_route_exceptions('server_control:release_control')
def release_control():
    """Release control of a device (instant response, host notification in background)"""
    _cleanup_stale_manual_locks()
    data = request.get_json() or {}
    host_name = data.get('host_name')
    device_id = (data.get('device_id') or '').strip()

    if not host_name or not device_id:
        return jsonify({'error': 'host_name and device_id are required'}), 400

    session_id = data.get('session_id') or session.get('session_id')
    if not session_id:
        return jsonify({'error': 'session_id is required to release control'}), 400

    print(f"🔓 [CONTROL] Releasing control of host: {host_name}, device: {device_id} (session: {session_id})")

    unlock_result = release_device_lock(
        host_name=host_name,
        device_id=device_id,
        owner_session_id=session_id,
        owner_type='manual_control',
        force=False,
    )
    if not unlock_result.get('success'):
        # `not_lock_owner` / `owner_type_mismatch` mean the caller doesn't actually
        # own a manual lock here (e.g. a script_execution lock is currently held,
        # or the manual lock was already taken over). The manual-UI release call
        # has nothing to do here — return success-with-warning instead of 409 so
        # the frontend doesn't show an error toast for a state desync.
        err = unlock_result.get('error')
        if err in ('not_lock_owner', 'owner_type_mismatch'):
            existing = unlock_result.get('lock_info') or {}
            print(
                f"🟡 [CONTROL] Release skipped: {err} "
                f"(existing owner_type={existing.get('owner_type')!r}, "
                f"owner_session_id={existing.get('owner_session_id')!r})"
            )
            return jsonify({
                'success': True,
                'released': False,
                'skipped_reason': err,
                'message': (
                    f'No manual lock owned by this session on {host_name}:{device_id}; '
                    f'nothing to release'
                ),
                'lock_info': unlock_result.get('lock_info'),
            })
        return jsonify({
            'success': False,
            'error': err or 'Failed to release control',
            'errorType': 'device_locked',
            'lock_info': unlock_result.get('lock_info'),
        }), 409

    host_manager = get_host_manager()
    host_data = host_manager.get_host(host_name)
    if host_data:
        def notify_host_async():
            try:
                print(f"📡 [CONTROL:ASYNC] Notifying host of release: {host_name}")
                response_data, status_code = call_host(
                    host_data,
                    '/host/releaseControl',
                    method='POST',
                    data={'device_id': device_id},
                    timeout=10,
                )
                if status_code == 200:
                    print(f"✅ [CONTROL:ASYNC] Host confirmed release of device: {device_id}")
                else:
                    print(f"⚠️ [CONTROL:ASYNC] Host responded with status {status_code}")
            except Exception as e:
                print(f"⚠️ [CONTROL:ASYNC] Host notification error: {e}")

        threading.Thread(target=notify_host_async, daemon=True).start()
        print(f"🔓 [CONTROL] Server lock released, host notification in progress")
    else:
        print(f"⚠️ [CONTROL] Host {host_name} not found, but server lock released")

    emit_system_update('lock_changed', {'host_name': host_name, 'device_id': device_id, 'is_locked': False})
    return jsonify({
        'success': True,
        'message': f'Control released for host: {host_name}, device: {device_id}',
        'host_notification': 'in_progress' if host_data else 'host_not_found',
    })


@server_control_bp.route('/checkLock', methods=['POST'])
@handle_route_exceptions('server_control:check_lock')
def check_device_lock():
    """Check if a specific device is locked"""
    _cleanup_stale_manual_locks()
    data = request.get_json() or {}
    host_name = data.get('host_name')
    device_id = (data.get('device_id') or '').strip()
    if not host_name or not device_id:
        return jsonify({'error': 'host_name and device_id are required'}), 400

    lock_info = get_device_lock_info(host_name, device_id)
    if lock_info:
        return jsonify({
            'success': True,
            'is_locked': True,
            'lock_info': lock_info,
        })

    return jsonify({
        'success': True,
        'is_locked': False,
        'lock_info': None,
    })


@server_control_bp.route('/lockedDevices', methods=['GET'])
@handle_route_exceptions('server_control:locked_devices')
def get_locked_devices():
    """Get information about all currently locked devices"""
    _cleanup_stale_manual_locks()
    locked_devices = get_all_locked_devices()

    return jsonify({
        'success': True,
        'locked_devices': locked_devices,
    })


@server_control_bp.route('/heartbeat', methods=['POST'])
@handle_route_exceptions('server_control:heartbeat')
def heartbeat():
    """Lightweight heartbeat to refresh lock last_heartbeat_at for manual control locks."""
    data = request.get_json() or {}
    devices = data.get('devices', [])
    session_id = _get_or_create_session_id(data.get('session_id'))
    user_id = data.get('user_id') or request.headers.get('X-User-ID')

    if not devices:
        return jsonify({'error': 'devices array is required'}), 400

    results = []
    for device_entry in devices:
        host_name = device_entry.get('host_name')
        device_id = (device_entry.get('device_id') or '').strip()
        if not host_name or not device_id:
            continue

        result = acquire_device_lock(
            host_name=host_name,
            device_id=device_id,
            owner_type='manual_control',
            owner_session_id=session_id,
            owner_user_id=user_id,
            lock_reason='heartbeat',
            can_force_takeover=True,
        )
        results.append({
            'host_name': host_name,
            'device_id': device_id,
            'success': bool(result.get('success')),
        })

    return jsonify({'success': True, 'results': results}), 200


@server_control_bp.route('/forceUnlock', methods=['POST'])
@handle_route_exceptions('server_control:force_unlock')
def force_unlock():
    """Force-unlock a specific device lock."""
    data = request.get_json() or {}
    host_name = data.get('host_name')
    device_id = (data.get('device_id') or '').strip()
    if not host_name or not device_id:
        return jsonify({'error': 'host_name and device_id are required'}), 400

    print(f"🔓 [CONTROL] Force unlocking device: {host_name}:{device_id}")

    # strict=False: a human is reclaiming the device, so the lock is cleared even if the
    # abort could not be delivered — leaving them wedged behind an unreachable host is
    # worse. The `aborted` flag distinguishes "killed a live run" from "nothing running".
    unlock_result = abort_and_force_unlock(host_name, device_id, strict=False)
    if unlock_result.get('success'):
        emit_system_update('lock_changed', {'host_name': host_name, 'device_id': device_id, 'is_locked': False})
        return jsonify({
            'success': True,
            'message': f'Successfully force unlocked device: {host_name}:{device_id}',
            'released': bool(unlock_result.get('released')),
            'aborted': bool(unlock_result.get('aborted')),
            'lock_info': unlock_result.get('lock_info'),
        })
    return jsonify({
        'success': False,
        'error': f'Failed to force unlock device: {host_name}:{device_id}',
    }), 500


@server_control_bp.route('/takeover', methods=['POST'])
@handle_route_exceptions('server_control:takeover')
def takeover_control():
    """Take over a locked device and transfer ownership to manual control."""
    _cleanup_stale_manual_locks()
    data = request.get_json() or {}
    host_name = data.get('host_name')
    device_id = (data.get('device_id') or '').strip()
    requested_by_session = _get_or_create_session_id(data.get('requested_by_session'))
    requested_by_user = data.get('requested_by_user') or data.get('user_id') or request.headers.get('X-User-ID')
    stop_running_execution = bool(data.get('stop_running_execution', False))
    reason = data.get('reason') or 'manual_takeover'

    if not host_name or not device_id:
        return jsonify({'error': 'host_name and device_id are required'}), 400

    host_manager = get_host_manager()
    host_data = host_manager.get_host(host_name)
    if not host_data:
        return jsonify({
            'success': False,
            'error': f'Host {host_name} not found',
            'errorType': 'device_not_found',
        }), 404

    existing_lock = get_device_lock_info(host_name, device_id)
    if existing_lock and existing_lock.get('owner_type') == 'manual_control':
        if existing_lock.get('owner_session_id') == requested_by_session:
            return jsonify({
                'success': True,
                'message': 'Device already controlled by this session',
                'lock_info': existing_lock,
                'previous_owner': existing_lock,
            }), 200
        # Force Takeover preempts another session's manual lock too. The user has
        # already confirmed the warning dialog, and manual locks (including zombies
        # left by a closed tab or the no-heartbeat idle window) carry
        # can_force_takeover=True. Any testcase running under the old umbrella is
        # stopped best-effort in the else-branch below; ownership then transfers.
        print(
            f"🔁 [CONTROL] Takeover of {host_name}:{device_id} preempting manual lock "
            f"(prev_session={existing_lock.get('owner_session_id')}, "
            f"prev_user={existing_lock.get('owner_user_id')})"
        )

    if existing_lock and existing_lock.get('owner_type') in ('script_execution', 'deployment_execution'):
        if not stop_running_execution:
            return jsonify({
                'success': False,
                'error': 'Device is running execution; set stop_running_execution=true to preempt',
                'errorType': 'device_locked',
                'lock_info': existing_lock,
                'can_force_takeover': bool(existing_lock.get('can_force_takeover', False)),
            }), 423

        abort_result = _abort_running_execution(host_data, device_id, existing_lock.get('owner_type'))
        # aborted=False here means the host had nothing registered for this device: either a
        # zombie lock (fine) or the execution registered under a different key (bad — the
        # script survives the takeover). Logged so the latter is diagnosable, not silent.
        if not abort_result.get('aborted'):
            print(
                f"⚠️ [CONTROL] Takeover of {host_name}:{device_id} aborted nothing "
                f"(owner={existing_lock.get('owner_type')}); lock may have been stale, "
                f"or the running execution was not found on the host"
            )
        if not abort_result.get('success'):
            return jsonify({
                'success': False,
                'error': abort_result.get('error') or 'Failed to stop running execution before takeover',
                'errorType': 'preemption_failed',
                'details': abort_result.get('details'),
            }), 409
    else:
        # No execution lock — but testcases drive the device without taking one, so an
        # unlocked device is not necessarily an idle one. Best-effort stop; never blocks
        # the takeover, since the common case is genuinely nothing running.
        try:
            testcase_abort = _abort_running_execution(host_data, device_id, None)
            if testcase_abort.get('aborted'):
                print(f"🛑 [CONTROL] Takeover of {host_name}:{device_id} stopped a running testcase")
        except Exception as abort_err:
            print(f"⚠️ [CONTROL] Testcase abort on takeover failed for {host_name}:{device_id}: {abort_err}")

    takeover_result = takeover_device_lock(
        host_name=host_name,
        device_id=device_id,
        new_owner_session_id=requested_by_session,
        new_owner_user_id=requested_by_user,
        reason=reason,
        expected_owner_types=(existing_lock.get('owner_type'),) if existing_lock else None,
    )
    if not takeover_result.get('success'):
        conflict = takeover_result.get('conflict') or get_device_lock_info(host_name, device_id)
        if conflict:
            return jsonify(_build_lock_conflict_payload(host_name, device_id, conflict)), 423
        return jsonify({
            'success': False,
            'error': takeover_result.get('error') or 'Takeover failed',
            'errorType': 'generic_error',
        }), 500

    host_call = _forward_take_control_to_host(host_data, device_id)
    if host_call['status_code'] != 200 or not host_call['response_data'].get('success'):
        _release_manual_lock(host_name, device_id, requested_by_session)
        return jsonify({
            'success': False,
            'error': host_call['response_data'].get('error') or 'Failed to take device control on host',
            'errorType': 'host_error',
            'host_result': host_call['response_data'],
        }), host_call['status_code']

    cache_error = _try_populate_navigation_cache(data, host_name)
    if cache_error:
        _release_manual_lock(host_name, device_id, requested_by_session)
        return jsonify(cache_error), 500

    emit_system_update('lock_changed', {
        'host_name': host_name,
        'device_id': device_id,
        'is_locked': True,
        'lock_info': takeover_result.get('lock_info'),
    })
    return jsonify({
        'success': True,
        'message': f'Takeover complete for {host_name}:{device_id}',
        'host_name': host_name,
        'device_id': device_id,
        'lock_info': takeover_result.get('lock_info'),
        'previous_owner': takeover_result.get('previous_owner'),
        'host_result': host_call['response_data'],
    }), 200


@server_control_bp.route('/acquireExecutionLock', methods=['POST'])
@handle_route_exceptions('server_control:acquire_execution_lock')
def acquire_execution_lock():
    """Acquire a device lock for non-manual execution owners."""
    data = request.get_json() or {}
    host_name = data.get('host_name')
    device_id = (data.get('device_id') or '').strip()
    owner_type = data.get('owner_type')
    owner_session_id = data.get('owner_session_id')
    owner_user_id = data.get('owner_user_id')
    owner_job_id = data.get('owner_job_id')
    lock_reason = data.get('lock_reason')
    can_force_takeover = bool(data.get('can_force_takeover', True))

    if not host_name or not device_id or not owner_type or not owner_session_id:
        return jsonify({
            'success': False,
            'error': 'host_name, device_id, owner_type, and owner_session_id are required',
        }), 400

    lock_result = acquire_device_lock(
        host_name=host_name,
        device_id=device_id,
        owner_type=owner_type,
        owner_session_id=owner_session_id,
        owner_user_id=owner_user_id,
        owner_job_id=owner_job_id,
        lock_reason=lock_reason,
        can_force_takeover=can_force_takeover,
        client_ip=get_client_ip(),
    )
    if not lock_result.get('success'):
        conflict = lock_result.get('conflict') or get_device_lock_info(host_name, device_id)
        if conflict:
            return jsonify(_build_lock_conflict_payload(host_name, device_id, conflict)), 423
        return jsonify({
            'success': False,
            'error': lock_result.get('error') or 'Failed to acquire execution lock',
        }), 500

    emit_system_update('lock_changed', {
        'host_name': host_name,
        'device_id': device_id,
        'is_locked': True,
        'lock_info': lock_result.get('lock_info'),
    })
    return jsonify({
        'success': True,
        'lock_info': lock_result.get('lock_info'),
    }), 200


@server_control_bp.route('/releaseExecutionLock', methods=['POST'])
@handle_route_exceptions('server_control:release_execution_lock')
def release_execution_lock():
    """Release a device lock for non-manual execution owners."""
    data = request.get_json() or {}
    host_name = data.get('host_name')
    device_id = (data.get('device_id') or '').strip()
    owner_session_id = data.get('owner_session_id')
    owner_type = data.get('owner_type')
    owner_job_id = data.get('owner_job_id')
    force = bool(data.get('force', False))

    if not host_name or not device_id:
        return jsonify({'success': False, 'error': 'host_name and device_id are required'}), 400

    release_result = release_device_lock(
        host_name=host_name,
        device_id=device_id,
        owner_session_id=owner_session_id,
        owner_type=owner_type,
        owner_job_id=owner_job_id,
        force=force,
    )
    if not release_result.get('success'):
        return jsonify({
            'success': False,
            'error': release_result.get('error') or 'Failed to release execution lock',
            'lock_info': release_result.get('lock_info'),
        }), 409

    emit_system_update('lock_changed', {
        'host_name': host_name,
        'device_id': device_id,
        'is_locked': False,
        'lock_info': release_result.get('lock_info'),
    })
    return jsonify({
        'success': True,
        'released': bool(release_result.get('released')),
        'lock_info': release_result.get('lock_info'),
    }), 200


@server_control_bp.route('/navigation/execute', methods=['POST'])
@handle_route_exceptions('server_control:execute_navigation')
def execute_navigation():
    """Execute navigation on a host device."""
    data = request.get_json()
    host_name = data.get('host_name')
    navigation_data = data.get('navigation_data')
        
    if not host_name:
        return jsonify({'error': 'host_name is required'}), 400
        
    if not navigation_data:
        return jsonify({'error': 'Navigation data is required'}), 400
        
        
    print(f"🧭 [NAVIGATION] Executing navigation on host: {host_name}")
    print(f"   Navigation data keys: {list(navigation_data.keys())}")
        
    # Check if host is registered
    host_manager = get_host_manager()
    host_data = host_manager.get_host(host_name)
    if not host_data:
        return jsonify({'error': f'Host {host_name} not found'}), 404
        
    # Forward request to host with async support
    print(f"📡 [NAVIGATION] Forwarding navigation to: {host_name}")

    # Use centralized call_host() which automatically adds API key
    response_data, status_code = call_host(
        host_data,
        '/host/navigation/execute',
        method='POST',
        data={'navigation_data': navigation_data},
        timeout=90
    )
        
    if status_code == 200:
        print(f"✅ [NAVIGATION] Navigation completed successfully")
        return jsonify(response_data)
    else:
        error_msg = response_data.get('error', f"Navigation failed with status {status_code}")
        print(f"❌ [NAVIGATION] {error_msg}")
        return jsonify({'error': error_msg}), status_code
        
@server_control_bp.route('/navigationBatchExecute', methods=['POST'])
@handle_route_exceptions('server_control:batch_execute_navigation')
def batch_execute_navigation():
    """Execute batch navigation on a host device."""
    data = request.get_json()
    host_name = data.get('host_name')
    batch_data = data.get('batch_data')
        
    if not host_name:
        return jsonify({'error': 'host_name is required'}), 400
        
    if not batch_data or not isinstance(batch_data, list):
        return jsonify({'error': 'Batch data must be a list of navigation items'}), 400
        
        
    print(f"🧭 [BATCH-NAVIGATION] Executing batch navigation on host: {host_name}")
    print(f"   Batch size: {len(batch_data)} items")
        
    # Check if host is registered
    host_manager = get_host_manager()
    host_data = host_manager.get_host(host_name)
    if not host_data:
        return jsonify({'error': f'Host {host_name} not found'}), 404
        
    # Forward request to host
    print(f"📡 [BATCH-NAVIGATION] Forwarding batch navigation to: {host_name}")

    # Use centralized call_host() which automatically adds API key
    response_data, status_code = call_host(
        host_data,
        '/host/navigation/batchExecute',
        method='POST',
        data={'batch_data': batch_data},
        timeout=180  # Longer timeout for batch operations
    )
        
    if status_code == 200:
        print(f"✅ [BATCH-NAVIGATION] Batch navigation completed successfully")
        return jsonify(response_data)
    else:
        error_msg = response_data.get('error', f"Batch navigation failed with status {status_code}")
        print(f"❌ [BATCH-NAVIGATION] {error_msg}")
        return jsonify({'error': error_msg}), status_code
        
# =====================================================
# CONTROLLER INFORMATION ENDPOINTS
# =====================================================

@server_control_bp.route('/getAllControllers', methods=['GET'])
@handle_route_exceptions('server_control:get_all_controllers')
def get_all_controllers():
    """Get all available controller implementations from Python code"""
    print("[@route:getAllControllers] Fetching all available controller implementations")
        
    # Get controller configurations for different device models to understand available implementations
    controller_types = {
        'remote': [
            {
                'id': 'android_tv',
                'name': 'Android TV (ADB)',
                'description': 'Android TV control with ADB',
                'implementation': 'android_tv',
                'status': 'available',
                'parameters': ['device_ip', 'device_port', 'connection_timeout']
            },
            {
                'id': 'android_mobile',
                'name': 'Android Mobile (ADB)',
                'description': 'Android Mobile control with ADB',
                'implementation': 'android_mobile',
                'status': 'available',
                'parameters': ['device_ip', 'device_port', 'connection_timeout']
            },
            {
                'id': 'ir_remote',
                'name': 'IR Remote',
                'description': 'Infrared remote control with classic TV/STB buttons',
                'implementation': 'ir_remote',
                'status': 'available',
                'parameters': ['device_path', 'protocol', 'frequency']
            },
            {
                'id': 'bluetooth_remote',
                'name': 'Bluetooth Remote',
                'description': 'Bluetooth HID remote control',
                'implementation': 'bluetooth_remote',
                'status': 'available',
                'parameters': ['device_address', 'pairing_pin', 'connection_timeout']
            }
        ],
        'av': [
            {
                'id': 'hdmi_stream',
                'name': 'HDMI Stream (Video Capture)',
                'description': 'HDMI video capture via Flask host with video device',
                'implementation': 'hdmi_stream',
                'status': 'available',
                'parameters': ['video_device', 'resolution', 'fps', 'stream_path', 'service_name']
            }
        ],
        'verification': [
            {
                'id': 'adb',
                'name': 'ADB Verification',
                'description': 'Android device verification via ADB',
                'implementation': 'adb',
                'status': 'available',
                'parameters': ['device_ip', 'device_port', 'connection_timeout']
            },
            {
                'id': 'ocr',
                'name': 'OCR Verification',
                'description': 'Optical Character Recognition verification',
                'implementation': 'ocr',
                'status': 'available',
                'parameters': []
            }
        ],
        'power': [
            {
                'id': 'tapo',
                'name': 'Tapo power Control',
                'description': 'Tapo power control via uhubctl',
                'implementation': 'tapo',
                'status': 'available',
                'parameters': ['hub_location', 'port_number']
            }
        ]
    }
        
    print(f"[@route:getAllControllers] Successfully retrieved {len(controller_types)} controller types")
        
    return jsonify({
        'success': True,
        'controller_types': controller_types
    }), 200
        
# =====================================================
# NAVIGATION CACHE POPULATION HELPER
# =====================================================

# In-memory cache to track which trees have been populated on which hosts
# Format: {(tree_id, team_id, host_name): timestamp}
_navigation_cache_tracker = {}
_cache_tracker_ttl = 3600  # 1 hour TTL for cache tracker

def populate_navigation_cache_for_control(tree_id: str, team_id: str, host_name: str,
                                            force: bool = False,
                                            device_id: Optional[str] = None,
                                            variant: Optional[str] = None) -> bool:
    """
    Ensure navigation cache exists on the host. Relies on edit-time invalidation
    (tree/node/edge save calls invalidate the host file cache) so we only rebuild
    when actually stale. Pass force=True to override.

    Pass `variant` explicitly when the caller already knows which variant the
    upcoming read will use (e.g. /execute receives variant in the request body,
    /preview receives the canvas-selected variant in the query string). The
    server-side `device.navigation_context['variant']` on the host can lag
    behind the incoming request — it is set inside `/host/navigation/execute`,
    which has not run yet when we populate, and for /preview it is never set
    by the request at all — so relying on device-context resolution alone
    races and the populate writes the wrong variant key, causing the
    post-populate verify to fail.

    When only `device_id` is provided (and `variant` is None), the host
    resolves variant from `device.navigation_context` as a fallback.
    """
    import time
    cache_key = (tree_id, team_id, host_name)

    # Get host info first
    host_manager = get_host_manager()
    host_info = host_manager.get_host(host_name)
    if not host_info:
        print(f"[@control:cache] Host {host_name} not found")
        return False

    # STEP 1: Load tree data from database
    print(f"[@control:cache] Loading tree data from database for tree {tree_id}")
    from shared.src.lib.database.navigation_trees_db import get_complete_tree_hierarchy, get_full_tree

    # Try to load complete hierarchy first (for nested trees)
    hierarchy_result = get_complete_tree_hierarchy(tree_id, team_id)

    if hierarchy_result.get('success'):
        all_trees_data = hierarchy_result.get('all_trees_data', [])
        print(f"[@control:cache] Loaded tree hierarchy: {len(all_trees_data)} trees")
    else:
        # Fallback: Load single tree
        tree_result = get_full_tree(tree_id, team_id)
        if not tree_result.get('success'):
            print(f"[@control:cache] Failed to load tree {tree_id}: {tree_result.get('error', 'Unknown error')}")
            return False

        all_trees_data = [tree_result.get('tree')]
        print(f"[@control:cache] Loaded single tree")

    # STEP 2: Populate cache on HOST. Edit-time invalidation handles staleness;
    # only force a rebuild when explicitly requested.
    print(f"[@control:cache] Ensuring cache on HOST for tree {tree_id} (force={force}, device_id={device_id}, variant={variant})")
    query_params = {'team_id': team_id}
    if device_id:
        query_params['device_id'] = device_id
    if variant:
        # Explicit variant wins over device-context resolution on the host.
        query_params['variant'] = variant
    populate_result, status_code = call_host(
        host_info,
        f'/host/navigation/cache/populate/{tree_id}',
        method='POST',
        query_params=query_params,
        data={
            'all_trees_data': all_trees_data,
            'force_repopulate': force,
        }
    )
        
    if populate_result and populate_result.get('success'):
        print(f"[@control:cache] ✅ Cache built successfully on HOST for tree {tree_id}")
        # Track in memory
        _navigation_cache_tracker[cache_key] = time.time()
        return True
    else:
        print(f"[@control:cache] ❌ Cache build failed: {populate_result}")
        return False
        
