"""
Host System Control Routes

System control endpoints for host-level operations:
- Restart vpt-host service
- Reboot host machine
- Restart host streaming services
- Update host core code from shared storage (with backup)
- Rollback host core code from backup
"""

from flask import Blueprint, request, jsonify, current_app
from backend_host.src.lib.utils.route_decorators import route_exception_handler
from backend_host.src.lib.utils.system_info_utils import (
    CONTROLLABLE_SERVICE_NAMES,
    resolve_windows_service_target,
)
import time
import os
import subprocess
from pathlib import Path
from datetime import datetime
import json
import shutil

host_system_bp = Blueprint('host_system', __name__, url_prefix='/host/system')
UPDATE_LOCK_FILE = '/tmp/vpt_update_core.lock'
DEPLOY_STATE_FILE = '/var/tmp/virtualpytest_deploy_state.json'
BACKUP_META_FILENAME = '.vpt-backup-meta.json'


def _project_root() -> str:
    """Resolve /opt/virtualpytest style project root from this route file."""
    return str(Path(__file__).resolve().parents[3])


def _backup_root() -> str:
    return '/var/tmp/virtualpytest_backups'


def _utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'


def _read_deployed_version(target_dir: str = '/opt/virtualpytest') -> str:
    for path in [os.path.join(target_dir, 'version'), os.path.join(target_dir, 'VERSION.txt')]:
        if os.path.isfile(path):
            with open(path, 'r', encoding='utf-8') as file:
                return file.readline().strip() or 'unknown'
    return 'unknown'


def _coerce_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {'true', '1', 'yes', 'y', 'on'}:
            return True
        if lowered in {'false', '0', 'no', 'n', 'off'}:
            return False
    return default


def _parse_kv_output(output: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in (output or '').splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            parsed[key.strip()] = value.strip()
    return parsed


def _read_deploy_state_file() -> dict:
    try:
        if os.path.isfile(DEPLOY_STATE_FILE):
            with open(DEPLOY_STATE_FILE, 'r', encoding='utf-8') as file:
                payload = json.load(file)
                if isinstance(payload, dict):
                    return payload
    except Exception:
        pass
    return {}


def _write_deploy_state_file(payload: dict) -> None:
    os.makedirs(os.path.dirname(DEPLOY_STATE_FILE), exist_ok=True)
    with open(DEPLOY_STATE_FILE, 'w', encoding='utf-8') as file:
        json.dump(payload, file, ensure_ascii=True)


def _set_deploy_state(state: str, version: str | None = None, error: str | None = None) -> None:
    current = _read_deploy_state_file()
    current['deploy_state'] = state
    current['last_deploy_at'] = _utc_now_iso()
    current['deployed_version'] = version or _read_deployed_version('/opt/virtualpytest')
    if error:
        current['last_error'] = error[:2000]
    else:
        current.pop('last_error', None)
    _write_deploy_state_file(current)


def _list_backups() -> list[str]:
    root = Path(_backup_root())
    if not root.exists():
        return []
    return sorted(
        [str(p) for p in root.iterdir() if p.is_dir()],
        reverse=True,
    )


def _backup_excludes() -> list[str]:
    return [
        '.env',
        'venv',
        'node_modules',
        'frontend/public/docs',
        'frontend/dist',
        'playwright-report*',
        'playwright-viewport-report*',
        'security_report',
        'frontend/vite.config.local.json',
        'frontend/public/branding.json',
        '.backups',
    ]


def _backup_meta_path(backup_dir: str) -> str:
    return os.path.join(backup_dir, BACKUP_META_FILENAME)


def _write_backup_metadata(backup_dir: str, payload: dict) -> None:
    os.makedirs(backup_dir, exist_ok=True)
    with open(_backup_meta_path(backup_dir), 'w', encoding='utf-8') as file:
        json.dump(payload, file, ensure_ascii=True, indent=2)


def _read_backup_metadata(backup_dir: str) -> dict:
    meta_path = _backup_meta_path(backup_dir)
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, 'r', encoding='utf-8') as file:
                payload = json.load(file)
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    stat = os.stat(backup_dir)
    return {
        'backup_id': os.path.basename(backup_dir),
        'backup_path': backup_dir,
        'created_at': datetime.utcfromtimestamp(stat.st_mtime).replace(microsecond=0).isoformat() + 'Z',
        'version': _read_deployed_version(backup_dir),
        'status': 'stable',
        'reason': 'legacy',
    }


def _run_backup_rsync(source_dir: str, destination_dir: str, timeout: int = 1800) -> subprocess.CompletedProcess:
    command = ['rsync', '-a', '--delete']
    for pattern in _backup_excludes():
        command.append(f'--exclude={pattern}')
    command.extend([f'{source_dir}/', f'{destination_dir}/'])
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _create_backup_snapshot(
    target_dir: str,
    backup_root: str,
    reason: str,
    source_path: str | None = None,
    rolled_forward_to: str | None = None,
) -> tuple[str, dict]:
    created_at = _utc_now_iso()
    backup_id = datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')
    backup_dir = os.path.join(backup_root, backup_id)
    os.makedirs(backup_root, exist_ok=True)
    result = _run_backup_rsync(target_dir, backup_dir)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-400:] or result.stdout[-400:] or 'backup snapshot failed')

    metadata = {
        'backup_id': backup_id,
        'backup_path': backup_dir,
        'created_at': created_at,
        'version': _read_deployed_version(target_dir),
        'status': 'stable',
        'reason': reason,
    }
    if source_path:
        metadata['source_path'] = source_path
    if rolled_forward_to:
        metadata['rolled_forward_to'] = rolled_forward_to
    _write_backup_metadata(backup_dir, metadata)
    return backup_dir, metadata


def _list_backup_entries(backup_root: str, target_dir: str, ensure_baseline: bool = False) -> list[dict]:
    if ensure_baseline and os.path.isdir(target_dir):
        existing_dirs = [str(p) for p in Path(backup_root).iterdir() if p.is_dir()] if os.path.isdir(backup_root) else []
        if not existing_dirs:
            _create_backup_snapshot(target_dir, backup_root, reason='baseline')

    if not os.path.isdir(backup_root):
        return []

    entries = []
    for backup_dir in sorted([str(p) for p in Path(backup_root).iterdir() if p.is_dir()], reverse=True):
        metadata = _read_backup_metadata(backup_dir)
        metadata['backup_path'] = backup_dir
        entries.append(metadata)
    return entries


def _prune_backup_entries(backup_root: str, keep_backups: int) -> None:
    if keep_backups <= 0 or not os.path.isdir(backup_root):
        return
    backup_dirs = sorted([str(p) for p in Path(backup_root).iterdir() if p.is_dir()])
    if len(backup_dirs) <= keep_backups:
        return
    for backup_dir in backup_dirs[:len(backup_dirs) - keep_backups]:
        shutil.rmtree(backup_dir, ignore_errors=True)


def _resolve_backup_dir(
    backup_root: str,
    target_dir: str,
    backup_id: str | None = None,
    backup_path: str | None = None,
    ensure_baseline: bool = False,
) -> str:
    entries = _list_backup_entries(backup_root, target_dir, ensure_baseline=ensure_baseline)
    if backup_id:
        for entry in entries:
            if entry.get('backup_id') == backup_id:
                return os.path.realpath(str(entry['backup_path']))
        raise FileNotFoundError(f'Backup not found: {backup_id}')
    if backup_path:
        return os.path.realpath(str(backup_path))
    if not entries:
        raise FileNotFoundError('No backup found to rollback')
    return os.path.realpath(str(entries[0]['backup_path']))


def _acquire_update_lock() -> bool:
    try:
        fd = os.open(UPDATE_LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode('utf-8'))
        os.close(fd)
        return True
    except FileExistsError:
        return False


def _release_update_lock() -> None:
    try:
        os.remove(UPDATE_LOCK_FILE)
    except FileNotFoundError:
        pass


def _schedule_host_service_restart(delay_seconds: int = 2) -> None:
    import platform

    delay = max(1, delay_seconds)

    if platform.system() == 'Windows':
        # On Windows, vpt-host is a Scheduled Task (not a systemd service):
        # restart = `schtasks /End` then `/Run`. The helper must be fully
        # detached and broken away from the task's job object, otherwise
        # `/End` kills it before it can `/Run`.
        ps_cmd = (
            f'Start-Sleep -Seconds {delay}; '
            'schtasks /End /TN vpt-host; '
            'Start-Sleep -Seconds 2; '
            'schtasks /Run /TN vpt-host'
        )
        argv = [
            'powershell', '-NoProfile', '-NonInteractive',
            '-WindowStyle', 'Hidden', '-Command', ps_cmd,
        ]
        base_flags = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
        try:
            subprocess.Popen(
                argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=base_flags | subprocess.CREATE_BREAKAWAY_FROM_JOB,
            )
        except OSError:
            # Job object doesn't permit breakaway — fall back without it.
            subprocess.Popen(
                argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=base_flags,
            )
        return

    subprocess.Popen(
        ['bash', '-lc', f'sleep {delay} && sudo systemctl restart vpt-host'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


# =====================================================
# HEALTH CHECK ENDPOINT
# =====================================================

@host_system_bp.route('/health', methods=['GET'])
def health():
    """Health check endpoint with system status"""
    try:
        from shared.src.lib.utils.supabase_utils import get_supabase_client, get_db_key_role
        supabase_client = get_supabase_client()
        supabase_status = "connected" if supabase_client else "disconnected"
        db_key_role = get_db_key_role()  # TASK-10 rollout signal: service_role | anon | none
    except Exception:
        supabase_status = "unavailable"
        db_key_role = "unknown"

    return jsonify({
        'status': 'ok',
        'timestamp': time.time(),
        'mode': 'host',
        'host_name': current_app.host_name,
        'supabase': supabase_status,
        'db_key_role': db_key_role
    }), 200


@host_system_bp.route('/device/<device_id>/is_busy', methods=['GET'])
def device_is_busy(device_id: str):
    """Check if a device is actively executing anything (campaign, testcase, or script).

    Used by the server's stale-lock liveness probe during host pings.
    Returns {busy: true/false, active_jobs: [...]} so the server can decide
    whether a lock for this device is still valid.
    """
    active_jobs = []

    # 1. Check running campaigns
    try:
        from backend_host.src.routes.host_campaign_routes import running_campaigns
        for exec_id, info in running_campaigns.items():
            if info.get('status') == 'running':
                active_jobs.append({
                    'type': 'campaign',
                    'execution_id': exec_id,
                    'campaign_id': info.get('campaign_id'),
                    'started_at': info.get('started_at'),
                })
    except Exception as exc:
        print(f"⚠️ [is_busy] Error checking campaigns: {exc}")

    # 2. Check running testcase executions
    try:
        if hasattr(current_app, 'testcase_executor'):
            executor = current_app.testcase_executor
            with executor._lock:
                for exec_id, execution in executor._executions.items():
                    if execution.get('status') == 'running' and execution.get('device_id') == device_id:
                        active_jobs.append({
                            'type': 'testcase',
                            'execution_id': exec_id,
                            'started_at': execution.get('start_time'),
                        })
    except Exception as exc:
        print(f"⚠️ [is_busy] Error checking testcases: {exc}")

    # 3. Check running legacy script processes
    try:
        from shared.src.lib.executors.script_executor import _running_processes_by_device, _running_processes_lock
        with _running_processes_lock:
            proc_info = _running_processes_by_device.get(device_id)
            if proc_info and proc_info.get('process') and proc_info['process'].poll() is None:
                active_jobs.append({
                    'type': 'script',
                    'script_name': proc_info.get('script_name'),
                    'started_at': proc_info.get('started_at'),
                })
    except Exception as exc:
        print(f"⚠️ [is_busy] Error checking scripts: {exc}")

    return jsonify({
        'busy': len(active_jobs) > 0,
        'device_id': device_id,
        'active_jobs': active_jobs,
    }), 200


@host_system_bp.route('/restartHostService', methods=['POST'])
@route_exception_handler()
def restart_host_service():
    _schedule_host_service_restart()
    return jsonify({
        'success': True,
        'service': 'vpt-host',
        'message': 'Service restart scheduled',
        'restart_scheduled': True,
    }), 200


# Units the autofix flow may restart and the dashboard may start/stop/restart.
# Single source of truth is CONTROLLABLE_SERVICE_NAMES (canonical vpt-* unit
# names); the short systemd aliases are added here because _check_linux_service
# resolves to whichever alias matched. vpt-host stays excluded — it serves this
# very request, so it goes through the dedicated restart-vpt-host / reboot path.
_AUTOFIX_ALLOWED_UNITS = CONTROLLABLE_SERVICE_NAMES | {
    'stream', 'monitor', 'archiver', 'kpi',
    'vnc', 'websockify', 'transcript', 'subtitle',
}


def _restart_systemd_unit(unit: str):
    """Restart a single unit. Linux: `sudo systemctl restart`. Windows:
    Scheduled Task (vpt-stream) or Service. Returns (ok: bool, error: str|None)."""
    import platform
    is_windows = platform.system() == 'Windows'
    # On Windows vpt-stream is a Scheduled Task (like vpt-host); every other
    # autofixable unit is a real Windows service. See system_info_utils.py.
    windows_scheduled_tasks = {'vpt-stream'}
    try:
        if is_windows:
            if unit in windows_scheduled_tasks:
                ps_cmd = (
                    f'schtasks /End /TN {unit}; '
                    'Start-Sleep -Seconds 2; '
                    f'schtasks /Run /TN {unit}'
                )
            else:
                # Resolve canonical vpt-* unit to the actual Windows service
                # (e.g. vpt-vnc → tvnserver when vpt-vnc is Disabled). Without
                # this, Restart-Service runs on a disabled name and errors.
                target = resolve_windows_service_target(unit)
                if target is None:
                    return False, f"no usable Windows service for '{unit}' (all candidates missing or disabled)"
                ps_cmd = f"Restart-Service -Name '{target}' -Force -ErrorAction Stop"
            cmd = ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_cmd]
        else:
            cmd = ['sudo', 'systemctl', 'restart', unit]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        if proc.returncode == 0:
            return True, None
        return False, (proc.stderr or proc.stdout or 'restart failed').strip()[:200]
    except subprocess.TimeoutExpired:
        return False, 'restart timed out'
    except Exception as exc:
        return False, str(exc)[:200]


def _unit_is_active(unit: str) -> bool:
    """True if the unit is running. Linux: `systemctl is-active`. Windows:
    best-effort True (the restart command itself raises on failure)."""
    import platform
    if platform.system() == 'Windows':
        return True
    try:
        proc = subprocess.run(
            ['systemctl', 'is-active', unit], capture_output=True, text=True, timeout=10
        )
        return proc.stdout.strip() == 'active'
    except Exception:
        return False


def _control_systemd_unit(unit: str, action: str):
    """Start / stop / restart a single unit. Linux: `sudo systemctl <action>`.
    Windows: Scheduled Task (vpt-stream) or Service. Returns (ok, error)."""
    import platform
    is_windows = platform.system() == 'Windows'
    # On Windows vpt-stream is a Scheduled Task (like vpt-host); every other
    # controllable unit is a real Windows service. See system_info_utils.py.
    windows_scheduled_tasks = {'vpt-stream'}
    try:
        if is_windows:
            if unit in windows_scheduled_tasks:
                if action == 'start':
                    ps_cmd = f'schtasks /Run /TN {unit}'
                elif action == 'stop':
                    ps_cmd = f'schtasks /End /TN {unit}'
                else:  # restart
                    ps_cmd = (
                        f'schtasks /End /TN {unit}; '
                        'Start-Sleep -Seconds 2; '
                        f'schtasks /Run /TN {unit}'
                    )
            else:
                # See _restart_systemd_unit: resolve to whichever VNC service
                # is actually present and not Disabled (vpt-vnc → tvnserver).
                target = resolve_windows_service_target(unit)
                if target is None:
                    return False, f"no usable Windows service for '{unit}' (all candidates missing or disabled)"
                verb = {'start': 'Start', 'stop': 'Stop', 'restart': 'Restart'}[action]
                ps_cmd = f"{verb}-Service -Name '{target}' -Force -ErrorAction Stop"
            cmd = ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_cmd]
        else:
            cmd = ['sudo', 'systemctl', action, unit]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        if proc.returncode == 0:
            return True, None
        return False, (proc.stderr or proc.stdout or f'{action} failed').strip()[:200]
    except subprocess.TimeoutExpired:
        return False, f'{action} timed out'
    except Exception as exc:
        return False, str(exc)[:200]


@host_system_bp.route('/controlService', methods=['POST'])
@route_exception_handler()
def control_service():
    """Start / stop / restart a single controllable host service from the
    dashboard. Synchronous: none of the controllable units serve this
    request, so acting on them in-band is safe. vpt-host is not in the
    allowlist — it uses the dedicated restart-vpt-host / reboot path."""
    data = request.get_json() or {}
    unit = str(data.get('service') or '').strip()
    action = str(data.get('action') or '').strip().lower()
    if action not in ('start', 'stop', 'restart'):
        return jsonify({'success': False, 'error': "action must be start, stop or restart"}), 400
    if not unit:
        return jsonify({'success': False, 'error': 'service is required'}), 400
    if unit not in _AUTOFIX_ALLOWED_UNITS:
        return jsonify({'success': False, 'error': f"'{unit}' is not a controllable service"}), 400

    ok, error = _control_systemd_unit(unit, action)
    return jsonify({
        'success': ok,
        'service': unit,
        'action': action,
        'error': error,
    }), 200


@host_system_bp.route('/restartService', methods=['POST'])
@route_exception_handler()
def restart_service():
    """Restart specific down host services (autofix). Synchronous: none of
    these units serve this request, so restarting them in-band is safe."""
    data = request.get_json() or {}
    requested = data.get('services') or []
    if not isinstance(requested, list) or not requested:
        return jsonify({'success': False, 'error': 'services (non-empty list) is required'}), 400

    results = []
    for raw in requested:
        unit = str(raw or '').strip()
        if unit not in _AUTOFIX_ALLOWED_UNITS:
            results.append({'service': unit, 'restarted': False, 'error': 'not an autofixable service'})
            continue
        ok, error = _restart_systemd_unit(unit)
        results.append({'service': unit, 'restarted': ok, 'error': error})

    return jsonify({
        'success': any(r['restarted'] for r in results),
        'results': results,
    }), 200


# Max bytes kept per output stream. Tail is kept (errors are usually at the
# end) so a runaway command can't blow the JSON payload / proxy memory.
_RUNCMD_MAX_OUTPUT = 64 * 1024


def _truncate_tail(text: str) -> tuple:
    """Return (text, truncated). Keeps the last _RUNCMD_MAX_OUTPUT chars."""
    if text is None:
        return '', False
    if len(text) <= _RUNCMD_MAX_OUTPUT:
        return text, False
    kept = text[-_RUNCMD_MAX_OUTPUT:]
    marker = f"...[truncated, showing last {_RUNCMD_MAX_OUTPUT} of {len(text)} bytes]\n"
    return marker + kept, True


@host_system_bp.route('/runCommand', methods=['POST'])
@route_exception_handler()
def run_command():
    """Run an admin-authored shell script on THIS host and return its
    stdout/stderr/exit code. Gated upstream by admin auth on backend_server
    and by X-API-Key here. The script runs as the vpt-host service user
    (vpt_user); passwordless sudo inside it requires the opt-in
    /etc/sudoers.d/run-command drop-in. Synchronous and bounded by `timeout`."""
    import platform
    import tempfile
    import hashlib

    data = request.get_json() or {}
    command = str(data.get('command') or '')
    if not command.strip():
        return jsonify({'success': False, 'error': 'command is required'}), 400

    try:
        timeout = max(1, min(600, int(data.get('timeout', 120))))
    except (TypeError, ValueError):
        timeout = 120

    if platform.system() == 'Windows':
        return jsonify({
            'success': False,
            'error': 'runCommand is unsupported on Windows hosts',
        }), 200

    host_name = getattr(current_app, 'host_name', '?')
    cmd_sha = hashlib.sha256(command.encode('utf-8', 'replace')).hexdigest()[:12]
    first_line = command.splitlines()[0][:120] if command.splitlines() else ''

    path = None
    try:
        fd, path = tempfile.mkstemp(prefix='vpt_runcmd_', suffix='.sh', dir='/tmp')
        with os.fdopen(fd, 'w') as fh:
            fh.write(command)
        os.chmod(path, 0o700)

        start = time.time()
        timed_out = False
        try:
            proc = subprocess.run(
                ['/bin/bash', path],
                capture_output=True, text=True, timeout=timeout, cwd='/tmp',
            )
            stdout, stderr, exit_code = proc.stdout, proc.stderr, proc.returncode
            error = None
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = exc.stdout or ''
            stderr = exc.stderr or ''
            exit_code = None
            error = f'command timed out after {timeout}s'
        duration_ms = int((time.time() - start) * 1000)

        success = (not timed_out) and exit_code == 0
        out, out_trunc = _truncate_tail(stdout)
        err, err_trunc = _truncate_tail(stderr)

        print(
            f"[@host_system:runCommand] host={host_name} "
            f"exit={'timeout' if timed_out else exit_code} dur={duration_ms}ms "
            f"cmd_sha={cmd_sha} first_line={first_line!r}",
            flush=True,
        )

        return jsonify({
            'success': success,
            'exit_code': exit_code,
            'stdout': out,
            'stderr': err,
            'stdout_truncated': out_trunc,
            'stderr_truncated': err_trunc,
            'duration_ms': duration_ms,
            'timed_out': timed_out,
            'error': error,
        }), 200
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass


@host_system_bp.route('/rebootHost', methods=['POST'])
@route_exception_handler()
def reboot_host():
    from shared.src.lib.utils.system_utils import reboot_system

    result = reboot_system()

    if result['success']:
        return jsonify(result), 200
    else:
        return jsonify(result), 500


@host_system_bp.route('/restartHostStreamService', methods=['POST'])
@route_exception_handler()
def restart_host_stream_service():
    """Real restart of the host-level vpt-stream service.

    vpt-stream is one service per host (handles every device via
    active_captures.conf). This does an actual `systemctl restart` and
    verifies the unit comes back active, so it recovers a failed/dead
    service and returns an honest result. Synchronous — it takes as long
    as the restart actually takes. Device-agnostic (no device_id needed)."""
    ok, error = _restart_systemd_unit('vpt-stream')

    if ok and _unit_is_active('vpt-stream'):
        return jsonify({
            'success': True,
            'restarted': True,
            'service': 'vpt-stream',
            'message': 'vpt-stream restarted',
        }), 200

    return jsonify({
        'success': False,
        'restarted': False,
        'service': 'vpt-stream',
        'error': error or 'vpt-stream did not become active after restart',
    }), 500


@host_system_bp.route('/setStreamQuality', methods=['POST'])
@route_exception_handler()
def set_stream_quality():
    """Soft per-device quality change — NO service restart.

    Rewrites this device's line in active_captures.conf; the already
    running vpt-stream loop detects it and recycles just this device's
    ffmpeg. Requires the service to be alive (use the restart endpoint to
    recover a dead one)."""
    data = request.get_json() or {}
    device_id = data.get('device_id', 'device1')
    quality = data.get('quality', 'sd')

    from backend_host.src.lib.utils.host_utils import get_controller, get_device_by_id

    av_controller = get_controller(device_id, 'av')

    if not av_controller:
        device = get_device_by_id(device_id)
        if not device:
            return jsonify({
                'success': False,
                'error': f'Device {device_id} not found'
            }), 404

        return jsonify({
            'success': False,
            'error': f'No AV controller found for device {device_id}',
            'available_capabilities': device.get_capabilities()
        }), 404

    if av_controller.set_quality(quality=quality):
        return jsonify({
            'success': True,
            'device_id': device_id,
            'quality': quality,
            'message': f'Quality set to {quality.upper()}'
        }), 200

    return jsonify({
        'success': False,
        'error': 'Failed to set stream quality'
    }), 500


@host_system_bp.route('/getStreamQuality', methods=['GET'])
@route_exception_handler()
def get_stream_quality():
    """Return the device's current stream quality (low/sd/hd) as recorded in
    active_captures.conf. Used by the REC modal to initialize the quality
    toggle to the actual stream quality instead of a hardcoded default."""
    device_id = request.args.get('device_id', 'device1')

    from backend_host.src.lib.utils.host_utils import get_controller, get_device_by_id

    av_controller = get_controller(device_id, 'av')

    if not av_controller:
        device = get_device_by_id(device_id)
        if not device:
            return jsonify({
                'success': False,
                'error': f'Device {device_id} not found'
            }), 404

        return jsonify({
            'success': False,
            'error': f'No AV controller found for device {device_id}'
        }), 404

    return jsonify({
        'success': True,
        'device_id': device_id,
        'quality': av_controller.get_quality()
    }), 200


@host_system_bp.route('/updateCore', methods=['POST'])
@route_exception_handler()
def update_core():
    """
    Backup /opt/virtualpytest and sync code from shared NFS source.

    Body:
      - dry_run: bool (default false)
      - restart_host_service: bool (default true)
      - source_path: str (default /mnt/shared/code/virtualpytest)
      - target_kind: str (default host-linux)
    """
    data = request.get_json() or {}
    dry_run = _coerce_bool(data.get('dry_run', False), default=False)
    restart_host_service = _coerce_bool(data.get('restart_host_service', True), default=True)
    source_path = str(data.get('source_path', '/mnt/shared/code/virtualpytest'))
    target_kind = str(data.get('target_kind', 'host-linux')).strip() or 'host-linux'

    if not _acquire_update_lock():
        return jsonify({
            'success': False,
            'error': 'Another update is currently in progress',
        }), 409

    try:
        if not dry_run:
            _set_deploy_state('running')
        project_root = _project_root()
        script_path = os.path.join(project_root, 'scripts', 'code-deploy.sh')
        if not os.path.exists(script_path):
            return jsonify({
                'success': False,
                'error': f'Code deploy script not found: {script_path}',
            }), 500

        env = os.environ.copy()
        env['VPT_SOURCE_DIR'] = source_path
        env['VPT_TARGET_DIR'] = '/opt/virtualpytest'
        env['VPT_BACKUP_ROOT'] = _backup_root()
        env['VPT_KEEP_BACKUPS'] = '5'
        env['VPT_DRY_RUN'] = '1' if dry_run else '0'
        env['VPT_TARGET_KIND'] = target_kind
        env['VPT_RESTART_ENABLED'] = '0' if restart_host_service else '0'

        result = subprocess.run(
            ['bash', script_path],
            capture_output=True,
            text=True,
            check=False,
            env=env,
            timeout=1800,
        )

        if result.returncode != 0:
            if not dry_run:
                _set_deploy_state('failed', error=result.stderr[-2000:] or result.stdout[-2000:])
            return jsonify({
                'success': False,
                'dry_run': dry_run,
                'error': 'Core update failed',
                'stdout': result.stdout[-2000:],
                'stderr': result.stderr[-2000:],
            }), 500

        deploy_data = _parse_kv_output(result.stdout)
        backup_path = deploy_data.get('BACKUP_DIR')
        version_before = deploy_data.get('VERSION_BEFORE', _read_deployed_version())
        version_after = deploy_data.get('VERSION_AFTER', version_before)
        backup_id = None
        if backup_path and not dry_run:
            metadata = {
                'backup_id': os.path.basename(backup_path),
                'backup_path': backup_path,
                'created_at': _utc_now_iso(),
                'version': version_before,
                'status': 'stable',
                'reason': 'pre_deploy',
                'source_path': source_path,
                'rolled_forward_to': version_after,
            }
            _write_backup_metadata(backup_path, metadata)
            _prune_backup_entries(_backup_root(), 5)
            backup_id = metadata['backup_id']
        restart_scheduled = False
        if not dry_run and restart_host_service:
            _schedule_host_service_restart()
            restart_scheduled = True
        if not dry_run:
            _set_deploy_state('success', version=version_after)

        return jsonify({
            'success': True,
            'dry_run': dry_run,
            'target_kind': target_kind,
            'backup_path': backup_path,
            'backup_id': backup_id,
            'version_before': version_before,
            'version_after': version_after,
            'restart_scheduled': restart_scheduled,
            'deploy_state': 'idle' if dry_run else 'success',
            'message': 'Dry-run checks passed' if dry_run else 'Core update completed',
            'stdout': result.stdout[-2000:],
        }), 200
    except Exception as exc:
        if not dry_run:
            _set_deploy_state('failed', error=str(exc))
        raise
    finally:
        _release_update_lock()


@host_system_bp.route('/rollbackCore', methods=['POST'])
@route_exception_handler()
def rollback_core():
    """
    Rollback /opt/virtualpytest from backup.

    Body:
      - backup_id: str (optional, defaults to latest stable backup)
      - backup_path: str (legacy optional, defaults to latest backup)
      - restart_host_service: bool (default true)
      - dry_run: bool (default false)
    """
    data = request.get_json() or {}
    dry_run = _coerce_bool(data.get('dry_run', False), default=False)
    restart_host_service = _coerce_bool(data.get('restart_host_service', True), default=True)
    backup_id = data.get('backup_id')
    backup_path = data.get('backup_path')

    backup_root = os.path.realpath(_backup_root())
    try:
        selected_backup = _resolve_backup_dir(
            _backup_root(),
            '/opt/virtualpytest',
            backup_id=str(backup_id).strip() if backup_id else None,
            backup_path=backup_path,
            ensure_baseline=True,
        )
    except FileNotFoundError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 404
    if not selected_backup.startswith(backup_root + os.sep):
        return jsonify({'success': False, 'error': 'Invalid backup_path'}), 400
    if not os.path.isdir(selected_backup):
        return jsonify({'success': False, 'error': f'Backup path not found: {selected_backup}'}), 404

    if not _acquire_update_lock():
        return jsonify({
            'success': False,
            'error': 'Another update is currently in progress',
        }), 409

    try:
        version_before = _read_deployed_version('/opt/virtualpytest')
        if dry_run:
            return jsonify({
                'success': True,
                'dry_run': True,
                'backup_id': os.path.basename(selected_backup),
                'backup_path': selected_backup,
                'version_before': version_before,
                'version_after': version_before,
                'message': 'Rollback dry-run checks passed',
            }), 200
        _set_deploy_state('running')
        try:
            pre_rollback_backup_path, pre_rollback_metadata = _create_backup_snapshot(
                '/opt/virtualpytest',
                _backup_root(),
                reason='pre_rollback',
            )
        except Exception as exc:
            _set_deploy_state('failed', error=str(exc))
            print(f'[@host_system:rollback_core] pre-rollback snapshot failed: {exc}')
            return jsonify({'success': False, 'error': 'Failed to snapshot current version before rollback (see host log / deploy state)'}), 500

        sync_result = subprocess.run(
            [
                'rsync', '-a', '--delete',
                '--exclude=.env',
                '--exclude=venv',
                '--exclude=node_modules',
                '--exclude=frontend/public/docs',
                '--exclude=frontend/dist',
                '--exclude=playwright-report*',
                '--exclude=playwright-viewport-report*',
                '--exclude=security_report',
                '--exclude=frontend/vite.config.local.json',
                '--exclude=frontend/public/branding.json',
                '--exclude=.backups',
                f'{selected_backup}/', '/opt/virtualpytest/'
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=1800,
        )
        if sync_result.returncode != 0:
            _set_deploy_state('failed', error=sync_result.stderr[-2000:] or sync_result.stdout[-2000:])
            return jsonify({
                'success': False,
                'dry_run': False,
                'backup_path': selected_backup,
                'error': 'Rollback sync failed',
                'stdout': sync_result.stdout[-2000:],
                'stderr': sync_result.stderr[-2000:],
            }), 500

        version_after = _read_deployed_version('/opt/virtualpytest')
        restart_scheduled = False
        if restart_host_service:
            _schedule_host_service_restart()
            restart_scheduled = True
        _set_deploy_state('success', version=version_after)
        _prune_backup_entries(_backup_root(), 5)
        return jsonify({
            'success': True,
            'dry_run': False,
            'backup_id': os.path.basename(selected_backup),
            'backup_path': selected_backup,
            'pre_rollback_backup_id': pre_rollback_metadata.get('backup_id'),
            'pre_rollback_backup_path': pre_rollback_backup_path,
            'version_before': version_before,
            'version_after': version_after,
            'restart_scheduled': restart_scheduled,
            'message': 'Rollback completed',
        }), 200
    finally:
        _release_update_lock()


@host_system_bp.route('/listBackups', methods=['POST'])
@route_exception_handler()
def list_backups():
    """List rollback backup options for this host."""
    entries = _list_backup_entries(_backup_root(), '/opt/virtualpytest', ensure_baseline=True)
    return jsonify({
        'success': True,
        'backups': entries,
        'default_backup_id': entries[0]['backup_id'] if entries else None,
    }), 200


# ── Log file endpoints ────────────────────────────────────────────────────────

_LOG_FILES_WHITELIST = {
    'deployments': 'deployments.log',
}

_JOURNAL_SERVICES_WHITELIST = {
    'vpt-host', 'vpt-stream', 'vpt-monitor', 'vpt-archiver',
    'vpt-kpi', 'vpt-transcript', 'vpt-subtitle', 'vpt-vnc',
    'vpt-websockify', 'vpt-emulator', 'vpt-emulator-fifo',
}


@host_system_bp.route('/logs/journal', methods=['POST'])
@route_exception_handler()
def view_journal_logs():
    """Read systemd journal logs for a whitelisted service on this host.

    Request body: { "service": "vpt-host", "lines": 100, "since": "1h", "grep": "error" }
    """
    data = request.get_json() or {}
    service = data.get('service')
    lines = min(int(data.get('lines', 100)), 2000)
    since = data.get('since')
    grep_pattern = data.get('grep')

    if not service or service not in _JOURNAL_SERVICES_WHITELIST:
        return jsonify({
            'success': False,
            'error': f'Service not allowed: {service}',
            'available': sorted(_JOURNAL_SERVICES_WHITELIST),
        }), 400

    from shared.src.lib.utils.system_utils import read_journal_logs
    result = read_journal_logs(service, lines=lines, since=since, grep=grep_pattern)
    return jsonify(result), 200 if result.get('success') else 500


def _resolve_log_dir() -> str:
    log_dir = os.getenv('VIRTUALPYTEST_LOGS')
    if not log_dir:
        log_dir = '/tmp'
    return log_dir


@host_system_bp.route('/logs/file', methods=['POST'])
@route_exception_handler()
def view_log_file():
    """Read a whitelisted log file from the host.

    Request body: { "name": "deployments", "lines": 200 }
    """
    data = request.get_json() or {}
    name = data.get('name')
    lines = min(int(data.get('lines', 200)), 2000)

    if not name or name not in _LOG_FILES_WHITELIST:
        return jsonify({
            'success': False,
            'error': f'Unknown log file: {name}',
            'available': list(_LOG_FILES_WHITELIST.keys()),
        }), 400

    log_path = os.path.join(_resolve_log_dir(), _LOG_FILES_WHITELIST[name])
    if not os.path.isfile(log_path):
        return jsonify({
            'success': False,
            'error': f'Log file not found: {log_path}',
        }), 404

    # Read last N lines efficiently
    try:
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            all_lines = f.readlines()
        tail = all_lines[-lines:]
        return jsonify({
            'success': True,
            'name': name,
            'logs': ''.join(tail),
            'lines_count': len(tail),
            'total_lines': len(all_lines),
            'log_path': log_path,
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def _is_valid_stream_device_id(device_id: str) -> bool:
    """Strict allowlist for the ffmpeg log filename component (no path
    traversal): the synthetic 'host' device or 'device<1-12>'."""
    if device_id == 'host':
        return True
    if device_id.startswith('device'):
        suffix = device_id[len('device'):]
        return suffix.isdigit() and 1 <= int(suffix) <= 12
    return False


@host_system_bp.route('/logs/stream', methods=['POST'])
@route_exception_handler()
def view_stream_logs():
    """Read a single device's ffmpeg capture log for vpt-stream.

    vpt-stream redirects ffmpeg stdout/stderr to per-device files
    (run_ffmpeg.sh: /tmp/ffmpeg_output_<device_id>.log), NOT journald, so
    `journalctl -u vpt-stream` is near-empty. The UI shows one tab per
    device and fetches each file through this endpoint.

    Request body: { "device_id": "device1", "lines": 200 }
    """
    import tempfile
    data = request.get_json() or {}
    device_id = (data.get('device_id') or '').strip()
    lines = min(int(data.get('lines', 200)), 2000)

    if not _is_valid_stream_device_id(device_id):
        return jsonify({
            'success': False,
            'error': f'Invalid device_id: {device_id}',
        }), 400

    # gettempdir() == /tmp on Linux, %TEMP% on Windows — matches both
    # run_ffmpeg.sh and run_ffmpeg.ps1 log locations.
    log_path = os.path.join(tempfile.gettempdir(), f'ffmpeg_output_{device_id}.log')
    if not os.path.isfile(log_path):
        return jsonify({
            'success': False,
            'error': f'No ffmpeg log for {device_id} (capture not running?): {log_path}',
        }), 404

    try:
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            all_lines = f.readlines()
        tail = all_lines[-lines:]
        return jsonify({
            'success': True,
            'device_id': device_id,
            'logs': ''.join(tail),
            'lines_count': len(tail),
            'total_lines': len(all_lines),
            'log_path': log_path,
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
