"""
System Information Utilities

Utility functions for system monitoring, process management, and environment validation.
"""

import os
import psutil
from backend_host.src.lib.utils.monitor_profile import get_monitor_profile_params, get_monitor_profiles, get_monitoring_off, get_overlay_on, get_profile_services
import hashlib
import platform
import time
import subprocess
import json
import re
import socket
from typing import Dict
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from shared.src.lib.utils.supabase_utils import get_supabase_client
from shared.src.lib.utils.storage_path_utils import get_capture_storage_path, get_capture_base_directories
from shared.src.lib.utils.system_monitoring_utils import _get_load_average, get_cpu_temperature

# Global cache for process start times
_process_start_cache = {}

# Speedtest functionality moved to shared network_utils


def _service_is_running_status(raw_status: str) -> str:
    """Normalize platform-specific service status strings."""
    status = (raw_status or '').strip().lower()
    if status in ('active', 'running'):
        return 'active'
    if status in ('inactive', 'stopped', 'stop_pending', 'paused', 'ready'):
        return 'stopped'
    if status in ('failed', 'error'):
        return 'error'
    return 'unknown'


def _units_not_needed() -> set:
    """The service units no device on this host needs (the applied profiles say so).

    A service in this list is stopped ON PURPOSE by the profile apply, so a stopped
    one of them must not read as a failed critical service. Unknown state -> an empty
    set: the status then keeps treating them as needed, which is the safe direction.
    """
    try:
        from backend_host.src.lib.utils.monitor_profile import units_not_needed
        return set(units_not_needed())
    except Exception:
        return set()


def _browser_run_status() -> Dict[str, Any]:
    """How many browser test runs this host carries right now, and the cap (TASK-146).

    Browser-isolated scripts each run a Chrome of their own, so the host - not the
    device - is what runs out; the dashboard shows this as "N browsers running".

    `leaked` is browsers on this host that belong to no live run: a run gives its slot
    back whether or not its Chrome died, so without this the host reads as idle while it
    carries the corpses (BUG-0760). It is reported, never reaped - killing a browser is
    deliberate work, not something a status read may do.
    """
    try:
        from shared.src.lib.utils.browser_run_slots import browser_run_status
        status = browser_run_status()
        return {
            'running': int(status.get('running') or 0),
            'waiting': int(status.get('waiting') or 0),
            'leaked': int(status.get('leaked') or 0),
            'cap': int(status.get('cap') or 0),
        }
    except Exception:
        return {'running': 0, 'waiting': 0, 'leaked': 0, 'cap': 0}


def _check_linux_service(service_names: List[str]) -> Dict[str, Any]:
    """Check Linux systemd service status trying multiple unit names."""
    missing_units = 0
    for service_name in service_names:
        try:
            load_result = subprocess.run(
                ['systemctl', 'show', '--property=LoadState', '--value', service_name],
                capture_output=True, text=True, timeout=3,
            )
            if load_result.returncode != 0:
                return {'status': 'unknown', 'runtime': 'service', 'resolved_name': service_name}
            load_state = (load_result.stdout or '').strip().lower()
            if load_state == 'not-found':
                missing_units += 1
                continue
            # A masked unit was deliberately taken out of service (e.g. a headless host
            # that must not run vpt-stream, or vpt-vnc on a box with no display). systemd
            # reports LoadState=masked and then is-active -> "inactive", which the mapping
            # below would turn into 'stopped' and the dashboard into a red "down" error for
            # a service nobody asked for. Report it the same way as a missing unit so the
            # UI files it under "Not installed" instead of raising an incident.
            if load_state == 'masked':
                missing_units += 1
                continue
            if not load_state:
                return {'status': 'unknown', 'runtime': 'service', 'resolved_name': service_name}

            result = subprocess.run(
                ['systemctl', 'is-active', service_name],
                capture_output=True, text=True, timeout=3,
            )
            stdout_value = (result.stdout or '').strip().lower()
            if result.returncode == 0:
                return {'status': 'active', 'runtime': 'service', 'resolved_name': service_name}
            if stdout_value == 'inactive':
                return {'status': 'stopped', 'runtime': 'service', 'resolved_name': service_name}
            if stdout_value == 'failed':
                return {'status': 'error', 'runtime': 'service', 'resolved_name': service_name}
            # Mid-(re)start or stop: a known transient state, not "can't tell".
            if stdout_value in ('activating', 'deactivating', 'reloading'):
                return {'status': 'restarting', 'runtime': 'service', 'resolved_name': service_name}
            return {'status': 'unknown', 'runtime': 'service', 'resolved_name': service_name}
        except Exception:
            return {'status': 'unknown', 'runtime': 'service', 'resolved_name': service_name}
    if missing_units == len(service_names):
        return {'status': 'not_installed', 'runtime': 'service'}
    return {'status': 'unknown', 'runtime': 'service'}


def _linux_service_is_masked(service_name: str) -> bool:
    """True when `service_name` is a masked systemd unit (LoadState=masked).
    Used by check_ffmpeg_status / check_monitor_status to short-circuit a
    'no process running' report: a masked stream / monitor unit was deliberately
    taken out of service on this host, so reporting 'stopped' would raise a
    red 'down' incident for a service nobody asked for. The same LoadState=masked
    handling already lives in _check_linux_service above (BUG-0745 follow-up); the
    process-presence checks below need the same escape hatch. Returns False on
    non-Linux, any subprocess error, or any LoadState other than 'masked'."""
    if platform.system() != 'Linux':
        return False
    try:
        result = subprocess.run(
            ['systemctl', 'show', '--property=LoadState', '--value', service_name],
            capture_output=True, text=True, timeout=3,
        )
        return result.returncode == 0 and (result.stdout or '').strip().lower() == 'masked'
    except Exception:
        return False


# Supervisord-specific status strings → our canonical status. Order matters:
# we test in sequence and pick the first match.
_SUPERVISOR_STATUS_MAP = (
    ('RUNNING', 'active'),
    ('STARTING', 'active'),
    ('STOPPED', 'stopped'),
    ('STOPPING', 'stopped'),
    ('FATAL', 'error'),
    ('EXITED', 'error'),
    ('BACKOFF', 'error'),
    ('UNKNOWN', 'unknown'),
    ('NOT_FOUND', 'unknown'),
)


def _supervisor_socket_path() -> Optional[str]:
    """Return the supervisord unix socket filesystem path that exists on this
    host, or None if we cannot find one. Honours ``$SUPERVISOR_SOCKET`` for
    overrides, then probes the two common locations:
    ``/var/run/supervisor.sock`` (Debian/Ubuntu default) and
    ``/tmp/supervisor.sock`` (Alpine and the gcloudstandalone setup, where
    the supervisord conf.d override redirects the socket). The first
    existing path wins.
    """
    env = os.environ.get('SUPERVISOR_SOCKET')
    if env:
        return env
    for candidate in ('/var/run/supervisor.sock', '/tmp/supervisor.sock'):
        if os.path.exists(candidate):
            return candidate
    return None


def _check_supervisor_service(service_names: List[str]) -> Dict[str, Any]:
    """Check service status via `supervisorctl` (used in the containerized
    backend_host where systemd does not manage vpt-* services). Falls back to
    'unknown' / 'not_installed' if supervisorctl is unavailable or none of the
    names resolve. The mapped status is reported with `runtime: 'supervisor'`
    so the dashboard can show which runtime owns the service.
    """
    # Cheap probe: the supervisorctl CLI writes to the supervisor socket.
    # If no socket exists at any known location we are not in a
    # supervisor-managed host. See _supervisor_socket_path for the lookup
    # order. The supervisorctl binary in the gcloudstandalone image (pip's
    # wheel, not the distro package) does NOT honour $SUPERVISOR_SERVER_URL
    # — it falls back to its compiled-in default /var/run/supervisor.sock —
    # so we pass the detected socket explicitly via -s.
    sock = _supervisor_socket_path()
    if not sock:
        return {'status': 'unknown', 'runtime': 'supervisor'}

    server_url = f'unix://{sock}'
    for service_name in service_names:
        try:
            result = subprocess.run(
                ['supervisorctl', '-s', server_url, 'status', service_name],
                capture_output=True, text=True, timeout=3,
            )
        except (FileNotFoundError, OSError):
            return {'status': 'unknown', 'runtime': 'supervisor'}
        except Exception:
            continue
        if result.returncode != 0:
            # supervisorctl exit code 4 == "no such process" → try next alias
            continue
        stdout = (result.stdout or '').strip()
        # supervisorctl format: "<name>    <STATUS>    ..." (whitespace-separated).
        # We do not parse the third column (pid/uptime) — only the status word.
        if not stdout:
            continue
        # First token is the program name (echoed by supervisorctl). The
        # second token is the status word.
        parts = stdout.split()
        if len(parts) < 2:
            continue
        sup_status = parts[1].upper()
        for needle, mapped in _SUPERVISOR_STATUS_MAP:
            if sup_status.startswith(needle):
                return {
                    'status': mapped,
                    'runtime': 'supervisor',
                    'resolved_name': service_name,
                }
        # Status word we did not recognise — record but do not mark active.
        return {
            'status': 'unknown',
            'runtime': 'supervisor',
            'resolved_name': service_name,
        }
    return {'status': 'not_installed', 'runtime': 'supervisor'}


# Windows: services where the canonical vpt-* name may not be the one
# actually running. e.g. on hosts with TightVNC pre-installed, the NSSM
# ``vpt-vnc`` service is registered-but-disabled (port 5900 conflict) and
# ``tvnserver`` is the live service. We try each candidate in order,
# skipping disabled ones, when reading status AND when performing
# start/stop/restart — so the dashboard always reports and acts on
# whichever service is actually usable. Single source of truth.
WINDOWS_SERVICE_ALIASES: Dict[str, List[str]] = {
    'vpt-vnc': ['vpt-vnc', 'tvnserver'],
    # TASK-90: renamed units; a Windows host that has not rerun install_host_windows.ps1 still has the old NSSM service
    'vpt-monitor-img': ['vpt-monitor-img', 'vpt-monitor'],
    'vpt-monitor-audio': ['vpt-monitor-audio', 'vpt-transcript'],
    'vpt-monitor-subtitle': ['vpt-monitor-subtitle', 'vpt-subtitle'],
}


def _windows_service_candidates(canonical_name: str) -> List[str]:
    """Ordered Windows service names to try for a canonical vpt-* unit name.
    Falls back to a single-element list of the canonical name itself."""
    return WINDOWS_SERVICE_ALIASES.get(canonical_name, [canonical_name])


def _check_windows_service(service_names: List[str]) -> Dict[str, Any]:
    """Check Windows service status trying multiple service names.

    A service whose start_type is 'disabled' is treated as **not installed**
    rather than 'stopped'. Rationale: on Windows hosts where a native VNC
    server (e.g. TightVNC's ``tvnserver``) is already present, the NSSM
    ``vpt-vnc`` service is registered but intentionally set to Disabled to
    avoid a port 5900 conflict. We don't want that to surface as a critical
    'stopped' service in the health dashboard — and by skipping to the next
    candidate in ``service_names`` we naturally pick up whichever VNC
    server is actually running.

    When no candidate service exists at all, return ``not_installed``
    rather than ``unknown``: a critical service the host never had
    (e.g. vpt-emulator on a non-Android box) is not the same as a
    service that exists but whose status we cannot read. The dashboard
    uses the former as a non-critical gray badge instead of a red
    "down" badge (BUG-0572 follow-up).
    """
    fallback: Dict[str, Any] = {'status': 'not_installed', 'runtime': 'service'}
    saw_disabled_candidate = False
    for service_name in service_names:
        try:
            service = psutil.win_service_get(service_name)
            service_info = service.as_dict()
            start_type = (service_info.get('start_type') or '').strip().lower()
            if start_type == 'disabled':
                # Remember this in case no later candidate is installed, so
                # the dashboard renders "not installed" (non-critical) rather
                # than "unknown" (degraded).
                saw_disabled_candidate = True
                continue
            mapped_status = _service_is_running_status(service_info.get('status', 'unknown'))
            return {'status': mapped_status, 'runtime': 'service', 'resolved_name': service_name}
        except Exception:
            continue
    if saw_disabled_candidate:
        # At least one candidate existed but was disabled — return
        # ``not_installed`` with the disabled service name as resolved_name,
        # matching the prior behavior so the dashboard surfaces the disabled
        # alias rather than a generic "no candidates" entry.
        return {'status': 'not_installed', 'runtime': 'service',
                'resolved_name': service_names[0], 'start_type': 'disabled'}
    return fallback


def resolve_windows_service_target(canonical_name: str) -> Optional[str]:
    """Find the actual Windows service to act on for a canonical vpt-* unit.

    Walks the candidate list from ``WINDOWS_SERVICE_ALIASES`` and returns
    the first existing service whose ``start_type`` is NOT 'disabled'.
    Used by the start/stop/restart control path so that, on hosts where
    ``vpt-vnc`` is registered-but-disabled in favour of TightVNC's
    ``tvnserver``, dashboard buttons act on the running ``tvnserver``.

    Returns ``None`` if every candidate is either missing or disabled —
    callers should surface a clear "no usable service" error rather than
    invoking ``Restart-Service`` on a name that would just fail.
    """
    for candidate in _windows_service_candidates(canonical_name):
        try:
            info = psutil.win_service_get(candidate).as_dict()
        except Exception:
            continue
        start_type = (info.get('start_type') or '').strip().lower()
        if start_type == 'disabled':
            continue
        return candidate
    return None


def _check_windows_scheduled_task(task_name: str) -> Dict[str, Any]:
    """Check Windows scheduled task state (used by vpt-stream, vpt-host).

    Primary path: PowerShell ``Get-ScheduledTask -TaskName <name> | .State``
    returns the state as a localized PROPERTY NAME but with an English enum
    value (``Unknown`` / ``Disabled`` / ``Queued`` / ``Ready`` / ``Running``)
    regardless of the host's UI locale. The earlier ``schtasks /Query /FO
    LIST /V`` fallback compared the value as a localized string
    (``Statut: En cours`` on a French box, ``Status: Running`` on English),
    so on any non-English Windows the check always fell through to
    ``unknown`` and Host API showed as red on the dashboard despite being
    alive (BUG-0572 / VirtualPyTest Windows host false-negative service
    health on French locale).

    Schtasks fallback kept as defense-in-depth: when PowerShell is not on
    PATH or returns no row, parse schtasks with a per-locale value list
    so the existing English/French/German/Spanish/Japanese hosts all map
    to the right state. Unknown locales still return ``unknown`` rather
    than guessing.
    """
    # 1. PowerShell (locale-independent enum string)
    try:
        ps = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
             f"(Get-ScheduledTask -TaskName '{task_name}' -ErrorAction SilentlyContinue).State"],
            capture_output=True, text=True, timeout=10
        )
        if ps.returncode == 0:
            state = (ps.stdout or '').strip().lower()
            if state == 'running':
                return {'status': 'active', 'runtime': 'task', 'resolved_name': task_name}
            if state in ('ready', 'queued'):
                return {'status': 'stopped', 'runtime': 'task', 'resolved_name': task_name}
            if state == 'disabled':
                return {'status': 'stopped', 'runtime': 'task', 'resolved_name': task_name}
            if state == 'unknown' and ps.stdout.strip():
                return {'status': 'unknown', 'runtime': 'task', 'resolved_name': task_name}
    except Exception:
        pass  # fall through to schtasks

    # 2. Schtasks fallback with multi-locale value matching.
    # The schtasks /V output is fully localized: the field name
    # ("Status:" / "Statut:" / "ステータス:" / "Estado:") and the value
    # ("Running" / "En cours" / "実行中" / "En ejecución"). Match a
    # curated set of state values per locale. Unknown locales still
    # return ``unknown``.
    ACTIVE_VALUES = {
        'running', 'en cours', 'wird ausgeführt', 'ejecutándose',
        'ejecutandose', '実行中', 'in esecuzione',
    }
    STOPPED_VALUES = {
        'ready', 'queued', 'prêt', 'bereit', 'in der warteschlange',
        'en cola', 'en attente', 'リスト', 'in coda', 'deshabilitado',
        'désactivé', 'disabled', 'deaktiviert',
    }
    try:
        sc = subprocess.run(
            ['schtasks', '/Query', '/TN', task_name, '/FO', 'LIST', '/V'],
            capture_output=True, text=True, timeout=5
        )
        if sc.returncode != 0:
            return {'status': 'unknown', 'runtime': 'task', 'error': sc.stderr.strip()[:160]}

        for raw_line in (sc.stdout or '').splitlines():
            if ':' not in raw_line:
                continue
            _, _, value = raw_line.partition(':')
            value_norm = value.strip().lower()
            if not value_norm:
                continue
            # Skip known non-state fields that contain colons in their value
            # (e.g. "Heure de la dernière exécution: 16/10/2026 14:06:49").
            if value_norm in ACTIVE_VALUES:
                return {'status': 'active', 'runtime': 'task', 'resolved_name': task_name}
            if value_norm in STOPPED_VALUES:
                return {'status': 'stopped', 'runtime': 'task', 'resolved_name': task_name}
        return {'status': 'unknown', 'runtime': 'task', 'resolved_name': task_name}
    except Exception as e:
        return {'status': 'unknown', 'runtime': 'task', 'error': str(e)[:160]}


def _host_has_audio_capable_devices(devices: Optional[List[Any]]) -> bool:
    """
    Transcript should not be critical for host_vnc-only hosts.
    Returns True if at least one non-host_vnc device exists.
    """
    if not devices:
        return True

    has_non_vnc_device = False
    for device in devices:
        if isinstance(device, dict):
            model = (device.get('device_model') or '').lower()
        else:
            model = (getattr(device, 'device_model', '') or '').lower()

        if model and model != 'host_vnc':
            has_non_vnc_device = True
            break

    return has_non_vnc_device


def _host_has_vnc_device(devices: Optional[List[Any]]) -> bool:
    """
    vpt-vnc / vpt-websockify only matter when the host exposes a host_vnc
    (remote-desktop) device. With no host_vnc device a stopped VNC stack is
    expected, not an error/warning. Returns True iff a host_vnc device exists.
    """
    if not devices:
        return False

    for device in devices:
        if isinstance(device, dict):
            model = (device.get('device_model') or '').lower()
        else:
            model = (getattr(device, 'device_model', '') or '').lower()

        if model == 'host_vnc':
            return True

    return False


# Services the dashboard exposes start/stop/restart controls for, and the
# same set the autofix flow may restart. vpt-host is intentionally excluded:
# it serves the very request that would control it (use the dedicated
# restart-vpt-host / reboot path instead). This is the single source of
# truth — host_system_routes._AUTOFIX_ALLOWED_UNITS is derived from it.
CONTROLLABLE_SERVICE_NAMES = {
    'vpt-stream',
    'vpt-monitor-img',
    'vpt-archiver',
    'vpt-kpi',
    'vpt-vnc',
    'vpt-websockify',
    'vpt-monitor-audio',
    'vpt-monitor-subtitle',
    'vpt-emulator',
    'vpt-emulator-fifo',
}


def build_service_health_summary(
    ffmpeg_status: Dict[str, Any],
    monitor_status: Dict[str, Any],
    devices: Optional[List[Any]] = None
) -> Dict[str, Any]:
    """
    Build unified service health summary for dashboard display.
    - subtitle is always optional
    - transcript is optional on host_vnc-only hosts
    - runner hosts (HOST_TYPE=runner_*) only run vpt-host; all other services are non-critical
    - lite hosts (HOST_PROFILE=lite) do not run KPI / transcript / VNC / websockify
    """
    platform_name = platform.system()
    has_audio_devices = _host_has_audio_capable_devices(devices)
    has_vnc_device = _host_has_vnc_device(devices)
    host_type = os.getenv('HOST_TYPE', 'host_vnc')
    is_runner = host_type.startswith('runner_')
    is_android = 'android' in host_type
    # HOST_PROFILE=lite (TASK-83): one device on a 1 GB board, no KPI / transcript / VNC services.
    is_lite = os.getenv('HOST_PROFILE', '').strip().lower() == 'lite'
    skip_extras = is_runner or is_lite

    # Start with stream functional check (better than service-only check).
    # For runner hosts, this service is not installed so it is non-critical.
    services = [
        {
            'name': 'vpt-stream',
            'label': 'Stream',
            'status': ffmpeg_status.get('status', 'unknown'),
            'critical': not is_runner,
            'optional': is_runner,
            'controllable': 'vpt-stream' in CONTROLLABLE_SERVICE_NAMES,
            'description': 'Captures & streams device A/V (HLS)',
            'runtime': 'service' if platform_name != 'Windows' else 'task'
        },
    ]

    # Service definitions with Linux/Windows naming differences.
    # On Windows: vpt-host and vpt-stream use Task Scheduler, everything else uses NSSM services.
    # For runner hosts, only vpt-host is critical; all other services are optional/non-critical.
    service_definitions = [
        {'name': 'vpt-host', 'label': 'Host API', 'description': 'Host API: manages devices & incoming requests', 'critical': True, 'optional': False, 'linux_names': ['vpt-host', 'host', 'flask'], 'windows_names': ['vpt-host']},
        {'name': 'vpt-monitor-img', 'label': 'Monitor (image)', 'description': 'Device health & incident monitoring', 'critical': not is_runner, 'optional': is_runner, 'linux_names': ['vpt-monitor-img', 'vpt-monitor', 'monitor', 'capture_monitor'], 'windows_names': ['vpt-monitor-img', 'vpt-monitor']},
        {'name': 'vpt-archiver', 'label': 'Archiver', 'description': 'Buffers video & archives screenshots', 'critical': not is_runner, 'optional': is_runner, 'linux_names': ['vpt-archiver', 'archiver', 'hot_cold_archiver'], 'windows_names': ['vpt-archiver']},
        {'name': 'vpt-kpi', 'label': 'KPI', 'description': 'Measures navigation & action KPIs', 'critical': not skip_extras, 'optional': skip_extras, 'linux_names': ['vpt-kpi', 'kpi', 'kpi_executor'], 'windows_names': ['vpt-kpi']},
        {'name': 'vpt-vnc', 'label': 'VNC', 'description': 'Remote desktop (VNC) for the device', 'critical': has_vnc_device and not skip_extras, 'optional': not has_vnc_device or skip_extras, 'linux_names': ['vpt-vnc', 'vnc', 'x11vnc'], 'windows_names': _windows_service_candidates('vpt-vnc')},
        {'name': 'vpt-websockify', 'label': 'Websockify', 'description': 'Bridges VNC to the browser (noVNC)', 'critical': has_vnc_device and not skip_extras, 'optional': not has_vnc_device or skip_extras, 'linux_names': ['vpt-websockify', 'websockify', 'novnc'], 'windows_names': ['vpt-websockify']},
        {'name': 'vpt-monitor-audio', 'label': 'Monitor (audio)', 'description': 'Audio check & transcription', 'critical': has_audio_devices and not skip_extras, 'optional': not has_audio_devices or skip_extras, 'linux_names': ['vpt-monitor-audio', 'vpt-transcript', 'transcript', 'transcript_accumulator'], 'windows_names': ['vpt-monitor-audio', 'vpt-transcript']},
        {'name': 'vpt-monitor-subtitle', 'label': 'Monitor (subtitle)', 'description': 'Subtitle extraction & overlay', 'critical': False, 'optional': True, 'linux_names': ['vpt-monitor-subtitle', 'vpt-subtitle', 'subtitle'], 'windows_names': []},
        {'name': 'vpt-emulator', 'label': 'Emulator', 'description': 'Android emulator runtime', 'critical': is_android and not is_runner, 'optional': not is_android or is_runner, 'linux_names': ['vpt-emulator'], 'windows_names': []},
        {'name': 'vpt-emulator-fifo', 'label': 'Screencap', 'description': 'Emulator frame capture pipe', 'critical': is_android and not is_runner, 'optional': not is_android or is_runner, 'linux_names': ['vpt-emulator-fifo'], 'windows_names': []},
    ]

    # A service the monitoring profiles deliberately turned off is not needed on this
    # host (TASK-144 stops what no device asks for). It is stopped ON PURPOSE, so it
    # must not make the host look broken: a stopped one of them is not a failure.
    not_needed_units = _units_not_needed()

    for definition in service_definitions:
        if platform_name == 'Linux':
            status_info = _check_linux_service(definition['linux_names'])
            # systemd does not know about vpt-* services on a supervisord-managed
            # host (the containerized backend_host path). Fall back to supervisorctl
            # so the dashboard reflects the real status of flask / capture_monitor /
            # hot_cold_archiver / kpi_executor / x11vnc / novnc / transcript_accumulator.
            # Trust supervisorctl when systemd returns 'unknown', 'not_installed', or
            # even 'stopped' (systemd may have a stale 'inactive' unit from a previous
            # install path while supervisord is actually running the program).
            if status_info.get('status') in ('unknown', 'not_installed', 'stopped'):
                sup_info = _check_supervisor_service(definition['linux_names'])
                if sup_info.get('status') not in ('unknown', 'not_installed'):
                    status_info = sup_info
        elif platform_name == 'Windows':
            if definition['name'] in ('vpt-stream', 'vpt-host'):
                status_info = _check_windows_scheduled_task(definition['name'])
            elif not definition['windows_names']:
                status_info = {'status': 'not_installed', 'runtime': 'service'}
            else:
                status_info = _check_windows_service(definition['windows_names'])
        else:
            status_info = {'status': 'unknown', 'runtime': 'service'}

        services.append({
            'name': definition['name'],
            'label': definition['label'],
            'status': status_info.get('status', 'unknown'),
            'critical': definition['critical'],
            'optional': definition['optional'],
            'controllable': definition['name'] in CONTROLLABLE_SERVICE_NAMES,
            'description': definition['description'],
            'runtime': status_info.get('runtime', 'service'),
            'resolved_name': status_info.get('resolved_name')
        })

    # A stopped service that no device needs (the profiles turned it off) is not a
    # failure: it does not make the host critical-and-broken.
    for service in services:
        if service.get('status') != 'stopped':
            continue
        unit = service.get('resolved_name') or service.get('name')
        if unit in not_needed_units:
            service['critical'] = False
            service['not_needed'] = True

    critical_services = [s for s in services if s.get('critical', False)]
    critical_statuses = {s.get('status', 'unknown') for s in critical_services}

    if 'error' in critical_statuses or 'stopped' in critical_statuses:
        overall_status = 'error'
    elif {'stuck', 'unknown', 'not_installed', 'restarting'} & critical_statuses:
        overall_status = 'degraded'
    else:
        overall_status = 'online'

    return {
        'overall_status': overall_status,
        'services': services
    }


def count_recent_files(
    directory: str,
    pattern: str,
    max_age_seconds: int = 60,
    exclude_pattern: Optional[str] = None
) -> int:
    r"""
    Count files matching pattern modified within max_age_seconds.
    Fast O(n) scan with early filtering - no sorting or subprocess overhead.
    
    Args:
        directory: Directory path to scan
        pattern: Regex pattern to match filenames (e.g., r'^capture_.*\.jpg$')
        max_age_seconds: Only count files modified within this timeframe
        exclude_pattern: Optional regex pattern to exclude files (e.g., r'_thumbnail\.jpg$')
    
    Returns:
        Count of matching recent files
    """
    if not os.path.exists(directory):
        return 0
    
    try:
        compiled_pattern = re.compile(pattern)
        compiled_exclude = re.compile(exclude_pattern) if exclude_pattern else None
        count = 0
        now = time.time()
        
        for entry in os.scandir(directory):
            try:
                if not entry.is_file(follow_symlinks=False):
                    continue
                    
                if not compiled_pattern.match(entry.name):
                    continue
                    
                if compiled_exclude and compiled_exclude.search(entry.name):
                    continue
                
                if now - entry.stat().st_mtime < max_age_seconds:
                    count += 1
                    
            except (FileNotFoundError, OSError):
                # File deleted during scan - skip it
                continue
        
        return count
        
    except Exception:
        return 0


def get_last_file_mtime(
    directory: str,
    pattern: str,
    max_age_seconds: int = 60,
    exclude_pattern: Optional[str] = None
) -> Optional[float]:
    r"""
    Get the most recent modification time of files matching pattern.
    Fast O(n) scan with early filtering - no sorting or subprocess overhead.
    
    Args:
        directory: Directory path to scan
        pattern: Regex pattern to match filenames (e.g., r'^capture_.*\.jpg$')
        max_age_seconds: Only consider files modified within this timeframe
        exclude_pattern: Optional regex pattern to exclude files (e.g., r'_thumbnail\.jpg$')
    
    Returns:
        Most recent mtime (timestamp), or None if no matching files found
    """
    if not os.path.exists(directory):
        return None
    
    try:
        compiled_pattern = re.compile(pattern)
        compiled_exclude = re.compile(exclude_pattern) if exclude_pattern else None
        mtimes = []
        now = time.time()
        
        for entry in os.scandir(directory):
            try:
                if not entry.is_file(follow_symlinks=False):
                    continue
                    
                if not compiled_pattern.match(entry.name):
                    continue
                    
                if compiled_exclude and compiled_exclude.search(entry.name):
                    continue
                
                mtime = entry.stat().st_mtime
                if now - mtime < max_age_seconds:
                    mtimes.append(mtime)
                    
            except (FileNotFoundError, OSError):
                # File deleted during scan - skip it
                continue
        
        return max(mtimes) if mtimes else None

    except Exception:
        return None


def _resolve_capture_base(device_folder_or_path: str) -> str:
    """Accept a bare folder name (``capture1``) or a full base path and return
    the capture base directory. Mirrors the input convention of
    ``get_capture_storage_path`` so health-check helpers can be called from
    either call style without surprising the caller."""
    if os.sep in device_folder_or_path or '/' in device_folder_or_path or ':' in device_folder_or_path:
        from shared.src.lib.utils.build_url_utils import normalize_capture_base_dir
        return normalize_capture_base_dir(device_folder_or_path)
    return os.path.join('/var/www/html/stream', device_folder_or_path)


def _count_recent_files_any_mode(
    device_folder_or_path: str,
    subdir: str,
    pattern: str,
    max_age_seconds: int,
    exclude_pattern: Optional[str] = None,
) -> int:
    """
    Hot/cold-agnostic recent-file count for a capture device.

    FFmpeg writes frames to either <base>/hot/<subdir>/ (tmpfs mode) or
    <base>/<subdir>/ (SD fallback) depending on whether a tmpfs is mounted
    at /hot. run_ffmpeg.sh::setup_capture_directories() is the authoritative
    source of that decision. Health checks must not pre-commit to one path
    via is_ram_mode()/get_capture_storage_path() — a stale empty /hot
    directory on a device running in SD mode causes a false "stuck" alert.
    Check both candidate locations and return the max.
    """
    base = _resolve_capture_base(device_folder_or_path)
    total = 0
    for candidate in (
        os.path.join(base, 'hot', subdir),
        os.path.join(base, subdir),
    ):
        if os.path.isdir(candidate):
            total = max(total, count_recent_files(
                candidate, pattern, max_age_seconds, exclude_pattern
            ))
    return total


def _get_last_file_mtime_any_mode(
    device_folder_or_path: str,
    subdir: str,
    pattern: str,
    max_age_seconds: int,
    exclude_pattern: Optional[str] = None,
) -> Optional[float]:
    """Hot/cold-agnostic most-recent-mtime lookup. See _count_recent_files_any_mode."""
    base = _resolve_capture_base(device_folder_or_path)
    latest: Optional[float] = None
    for candidate in (
        os.path.join(base, 'hot', subdir),
        os.path.join(base, subdir),
    ):
        if os.path.isdir(candidate):
            mtime = get_last_file_mtime(
                candidate, pattern, max_age_seconds, exclude_pattern
            )
            if mtime is not None and (latest is None or mtime > latest):
                latest = mtime
    return latest


def get_files_by_pattern(
    directory: str,
    pattern: str,
    exclude_pattern: Optional[str] = None,
    full_path: bool = True,
    min_mtime: Optional[float] = None,
    max_mtime: Optional[float] = None
) -> List[str]:
    r"""
    Get all files matching pattern using fast os.scandir (no subprocess overhead).
    Replacement for subprocess find commands - 2-5x faster, no timeout risk.
    
    Args:
        directory: Directory path to scan
        pattern: Regex pattern to match filenames (e.g., r'^segment_.*\.ts$')
        exclude_pattern: Optional regex pattern to exclude files
        full_path: If True, return full paths; if False, return just filenames
        min_mtime: Optional minimum modification time (Unix timestamp) - only files newer than this
        max_mtime: Optional maximum modification time (Unix timestamp) - only files older than this
    
    Returns:
        List of matching file paths (or names if full_path=False)
    
    Example:
        # Replace: subprocess.run(['find', dir, '-name', 'segment_*.ts', '-type', 'f'])
        # With: get_files_by_pattern(dir, r'^segment_.*\.ts$')
        
        # Get only files from last 24 hours:
        cutoff = time.time() - (24 * 3600)
        files = get_files_by_pattern(dir, r'^segment_.*\.ts$', min_mtime=cutoff)
    """
    if not os.path.exists(directory):
        return []
    
    try:
        compiled_pattern = re.compile(pattern)
        compiled_exclude = re.compile(exclude_pattern) if exclude_pattern else None
        files = []
        
        for entry in os.scandir(directory):
            try:
                if not entry.is_file(follow_symlinks=False):
                    continue
                    
                if not compiled_pattern.match(entry.name):
                    continue
                    
                if compiled_exclude and compiled_exclude.search(entry.name):
                    continue
                
                # Filter by modification time if specified
                if min_mtime is not None or max_mtime is not None:
                    mtime = entry.stat().st_mtime
                    if min_mtime is not None and mtime < min_mtime:
                        continue
                    if max_mtime is not None and mtime > max_mtime:
                        continue
                
                if full_path:
                    files.append(entry.path)
                else:
                    files.append(entry.name)
                    
            except (FileNotFoundError, OSError):
                # File deleted during scan - skip it
                continue
        
        return files
        
    except Exception:
        return []


# Speedtest functions moved to shared/src/lib/utils/network_utils.py
from shared.src.lib.utils.network_utils import get_network_speed_cached

# All speedtest functions moved to shared/src/lib/utils/network_utils.py


def _read_text_file(path: str, limit: int = 8192) -> Optional[str]:
    """Read the first `limit` bytes of a small text file, or None if unreadable."""
    try:
        with open(path, encoding='utf-8', errors='ignore') as f:
            return f.read(limit)
    except OSError:
        return None


def _detect_wsl() -> bool:
    """
    True when the Linux kernel we are running on is the WSL2 kernel.

    Docker Desktop on Windows runs its Linux VM on the WSL2 kernel, so a
    container there reports `Linux` from `platform.system()` even though the
    machine the operator cares about is a Windows PC. `uname -r` on that kernel
    carries a `microsoft-standard-WSL2` / `-WSL2-` marker, which is the only
    in-band signal available from inside the container.
    """
    release = platform.release().lower()
    if 'microsoft' in release or 'wsl' in release:
        return True
    for marker_path in ('/proc/sys/kernel/osrelease', '/proc/version'):
        content = (_read_text_file(marker_path) or '').lower()
        if 'microsoft' in content or 'wsl' in content:
            return True
    return False


def detect_container_runtime() -> Optional[str]:
    """
    Detect the container runtime this process runs inside, or None on bare metal.

    Returns 'docker' / 'podman' / 'lxc' / 'containerd' when a well-known marker
    is present, else None. Detection is deliberately marker-based and cheap (a
    few small file reads, no subprocesses) because it runs on every stats
    collection — the metrics collector fires every 60s per host.
    """
    if os.path.exists('/.dockerenv'):
        return 'docker'
    if os.path.exists('/run/.containerenv'):
        return 'podman'

    cgroup = (_read_text_file('/proc/1/cgroup') or '').lower()
    for marker, runtime in (
        ('kubepods', 'kubernetes'),
        ('docker', 'docker'),
        ('containerd', 'containerd'),
        ('lxc', 'lxc'),
    ):
        if marker in cgroup:
            return runtime
    return None


def get_physical_platform() -> Dict[str, Any]:
    """
    Describe the machine underneath, which is not always the machine we run on.

    A host named `vpt-windows` whose vpt-host runs as a Linux Docker container
    reports `platform.system() == 'Linux'`, so the dashboard would show the
    physical PC as a Linux box. This resolves the two facts the operator needs
    separately:

    - `in_container` / `container_runtime`: vpt-host is containerised, so the
      Linux it reports describes the container, not the hardware.
    - `physical_platform`: the OS of the machine itself. Under WSL2 (the kernel
      Docker Desktop uses on Windows) that is Windows, so we report it instead
      of the container's Linux. On bare-metal Linux hosts the WSL probe is false
      and this stays identical to `platform.system()`, so nothing changes there.

    Returns a dict; every key is always present so callers can render without
    None-guards.
    """
    system = platform.system()
    runtime = detect_container_runtime()
    is_wsl = _detect_wsl() if system == 'Linux' else False

    # Only claim a physical Windows box when we have positive evidence for it:
    # the WSL2 kernel. Never infer Windows from a hostname — HOST_NAME is an
    # operator-set label and is deliberately unconstrained.
    if is_wsl:
        physical = 'Windows'
    else:
        physical = system

    return {
        'in_container': runtime is not None,
        'container_runtime': runtime,
        'is_wsl': is_wsl,
        'physical_platform': physical,
        # True when the two differ, i.e. the container's own OS misrepresents
        # the hardware. The UI flags this instead of silently showing Linux.
        'os_mismatch': physical != system,
    }


def get_platform_distribution() -> Optional[str]:
    """
    Detect OS distribution beyond platform.system() for Linux hosts.
    Returns human-readable string like "Raspberry Pi OS 12", "Debian 12", "Debian 13", "Ubuntu 22.04".
    Returns None for non-Linux or when detection fails.
    """
    if platform.system() != 'Linux':
        return None
    try:
        os_release: Dict[str, str] = {}
        os_release_path = '/etc/os-release'
        if os.path.exists(os_release_path):
            with open(os_release_path, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if '=' in line and not line.startswith('#'):
                        key, _, val = line.partition('=')
                        os_release[key] = val.strip('"').strip("'")
        id_val = (os_release.get('ID') or '').lower()
        version_id = os_release.get('VERSION_ID', '')
        pretty_name = os_release.get('PRETTY_NAME', '')
        is_raspberry_pi = False
        if os.path.exists('/proc/device-tree/model'):
            try:
                with open('/proc/device-tree/model', 'rb') as f:
                    model = f.read().decode('utf-8', errors='ignore').rstrip('\x00').strip()
                    is_raspberry_pi = 'Raspberry Pi' in model
            except Exception:
                pass
        if not is_raspberry_pi and (pretty_name or '').lower().startswith('raspberry'):
            is_raspberry_pi = True
        if is_raspberry_pi:
            if version_id:
                return f"Raspberry Pi OS {version_id}"
            return "Raspberry Pi OS"
        if id_val and version_id:
            distro_name = id_val.capitalize()
            return f"{distro_name} {version_id}"
        if pretty_name:
            return pretty_name
        if id_val:
            return id_val.capitalize()
        return None
    except Exception:
        return None


def get_capture_folder_size(capture_folder: str) -> str:
    """Get disk usage for a single capture folder"""
    try:
        from shared.src.lib.utils.storage_path_utils import get_device_base_path
        capture_path = get_device_base_path(capture_folder)
        if not os.path.exists(capture_path):
            return 'N/A'
        result = subprocess.run(['du', '-sh', capture_path], capture_output=True, text=True, timeout=5)
        return result.stdout.split()[0] if result.returncode == 0 else 'unknown'
    except Exception:
        return 'unknown'

def get_process_start_time(capture_folder: str, process_type: str) -> float:
    """Get process start time via psutil — cross-platform (Linux, macOS, Windows)."""
    try:
        if process_type == 'ffmpeg':
            needle = f'ffmpeg.*{capture_folder}'
            name_match = ('ffmpeg', 'ffmpeg.exe')
            use_regex = True
        elif process_type == 'monitor':
            needle = 'capture_monitor.py'
            name_match = None
            use_regex = False
        else:
            return None

        pattern = re.compile(needle) if use_regex else None
        oldest_start = None

        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
            try:
                cmdline = proc.info.get('cmdline') or []
                cmdline_str = ' '.join(cmdline)
                name = (proc.info.get('name') or '').lower()

                matched = False
                if process_type == 'ffmpeg':
                    if name in name_match and pattern.search(cmdline_str):
                        matched = True
                else:  # monitor
                    if needle in cmdline_str:
                        matched = True

                if matched:
                    create_time = proc.info.get('create_time')
                    if create_time and (oldest_start is None or create_time < oldest_start):
                        oldest_start = create_time
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return oldest_start

    except Exception as e:
        print(f"⚠️ Error getting {process_type} start time for {capture_folder}: {e}")
        return None

def get_cached_process_start_time(capture_folder: str, process_type: str) -> float:
    """Get cached process start time, query only if not cached"""
    cache_key = f"{process_type}_{capture_folder}"
    
    # Return cached value if exists
    if cache_key in _process_start_cache:
        return _process_start_cache[cache_key]
    
    # Query and cache new start time
    start_time = get_process_start_time(capture_folder, process_type)
    if start_time:
        _process_start_cache[cache_key] = start_time
    
    return start_time

def clear_process_cache_if_stuck(capture_folder: str, process_type: str, status: str):
    """Clear cache when process is stuck/stopped (ready for restart detection)"""
    if status in ['stuck', 'stopped']:
        cache_key = f"{process_type}_{capture_folder}"
        _process_start_cache.pop(cache_key, None)  # Clear cache for restart

def calculate_process_working_uptime(capture_folder: str, process_type: str) -> int:
    """
    Calculate working uptime: process_start_time -> last_file_activity_time
    
    Args:
        capture_folder: Capture folder name (capture1, capture2, etc.)
        process_type: 'ffmpeg' or 'monitor'
        
    Returns:
        Working uptime in seconds (how long process worked before getting stuck)
    """
    try:
        # Get cached process start time (only queries if not cached)
        process_start_time = get_cached_process_start_time(capture_folder, process_type)
        
        if not process_start_time:
            return 0
            
        # Get last file activity time
        last_activity_time = None
        
        if process_type == 'ffmpeg':
            last_activity_time = _get_last_file_mtime_any_mode(
                capture_folder, 'captures',
                r'^capture_.*\.jpg$',
                max_age_seconds=20,  # need to cover stream restart
                exclude_pattern=r'_thumbnail\.jpg$',
            )

        elif process_type == 'monitor':
            last_activity_time = _get_last_file_mtime_any_mode(
                capture_folder, 'metadata',
                r'^capture_.*\.json$',
                max_age_seconds=20,  # need to cover stream restart
            )
        
        # Calculate working uptime: start -> last activity
        if last_activity_time and process_start_time:
            working_uptime = last_activity_time - process_start_time
            return int(max(0, working_uptime))
            
        return 0
        
    except Exception as e:
        print(f"⚠️ Error calculating {process_type} working uptime for {capture_folder}: {e}")
        return 0





def has_vaapi_h264_encode():
    """Whether this host can hardware-encode H.264 via VAAPI (enables the HD+ stream tier).

    Reuses run_ffmpeg.sh's detection rather than re-probing: detect_vaapi() writes the
    render node path to /tmp/vpt_vaapi_render_node when a usable H.264 encode entrypoint
    exists, else leaves it empty. Non-empty file -> capable. Missing/empty (software-only
    host like a Pi 5, or the stream service hasn't probed yet) -> False, so the frontend
    HD+ button simply doesn't appear there (and the server-side gate falls hd_plus->hd
    anyway). Cheap file read; safe to call every stats cycle.
    """
    try:
        with open('/tmp/vpt_vaapi_render_node', 'r') as f:
            return bool(f.read().strip())
    except Exception:
        return False


# ============================================================================
# WEBRTC — is there a WHEP endpoint on this host at all?
# ============================================================================

#: MediaMTX is installed here by `vpt-mediamtx.service`; the config is NOT in the repo,
#: so a fresh host install has no file and therefore no public WebRTC (docs/agent/devices/WEBRTC.md §1).
MEDIAMTX_CONFIG_PATH = '/opt/mediamtx/mediamtx.yml'
DEFAULT_WHEP_PORT = 8889
_FALSEY = ('false', '0', 'no', 'off')


def _whep_port() -> int:
    """The port MediaMTX serves WHEP on, read from its own config (`webrtcAddress: :NNNN`).

    Falls back to MediaMTX's default. Only the address line is read, never the whole
    file, so a config this function does not understand still yields a usable answer.
    """
    try:
        with open(MEDIAMTX_CONFIG_PATH, 'r', errors='ignore') as f:
            for line in f:
                match = re.match(r'\s*webrtcAddress:\s*:(\d+)', line)
                if match:
                    return int(match.group(1))
    except Exception:
        pass
    return DEFAULT_WHEP_PORT


def has_webrtc_endpoint() -> bool:
    """Whether this host can actually serve a WebRTC (WHEP) session.

    The one question the browser will ask first, answered locally: is something
    listening on MediaMTX's WHEP port? Without it every WEB click is a guaranteed
    6 s timeout followed by a fallback to HLS (BUG-0833) — the host either never
    got `vpt-mediamtx` installed (its config is not in the repo) or the service is
    down.

    Deliberately not `systemctl is-active`: that forks on every stats cycle (~1/s)
    and can hang the collector on a loaded host. A config read plus one localhost
    TCP connect is microseconds, and a closed port answers ECONNREFUSED at once.

    False is the safe direction — it only ever removes a button that could not work.
    """
    if os.getenv('WEBRTC_ENABLED', 'true').strip().lower() in _FALSEY:
        return False
    if not os.path.exists(MEDIAMTX_CONFIG_PATH):
        return False
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.settimeout(0.25)
        return probe.connect_ex(('127.0.0.1', _whep_port())) == 0
    except OSError:
        return False
    finally:
        probe.close()



# ============================================================================
# DISK — which filesystems to watch
# ============================================================================
# `psutil.disk_usage('/')` used to be the whole story, and on a host where the
# stream tree has its own mount it is the one filesystem that cannot fill: a
# customer host reported Disk=9.8% (a 56 GB `/` at 10%) while the 960 GB /data
# holding every capture, reference and report was at 100%, so nothing — not the
# dashboard tile with its red threshold, not the Status page's >90% Resources
# row — saw it coming (BUG-0198). `disk_percent` is now the FULLEST monitored
# mount, with the per-mount breakdown alongside it.

def _monitored_disk_paths() -> list:
    """Root, the stream tree (captures/references/reports), and each hot tmpfs."""
    # abspath(os.sep) is the drive root on Windows, '/' on POSIX — no literals.
    paths = [os.path.abspath(os.sep)]
    try:
        from shared.src.lib.utils.storage_path_utils import (
            get_capture_base_directories,
            get_stream_base_path,
        )
        stream_base = get_stream_base_path()
        if stream_base:
            paths.append(stream_base)
        for capture_dir in get_capture_base_directories():
            paths.append(capture_dir)
            hot_dir = os.path.join(capture_dir, 'hot')
            if os.path.isdir(hot_dir):
                paths.append(hot_dir)
    except Exception as e:
        # A dev box without active_captures.conf still reports its root.
        print(f"[@system_info:disk] Could not enumerate stream mounts, watching root only: {e}")
    return paths


def get_disk_stats() -> dict:
    """{disk_percent, disk_used_gb, disk_total_gb, disk_worst_mount, disk_mounts}.

    disk_percent is the fullest monitored mount, so a single number keeps working
    for the tiles, the >90% Resources row and the metrics table while finally
    tracking a filesystem that can actually fill.
    """
    from shared.src.lib.utils.disk_space_utils import worst_usage
    worst, mounts = worst_usage(_monitored_disk_paths())
    if not worst:
        return {'disk_percent': 0, 'disk_used_gb': 0, 'disk_total_gb': 0,
                'disk_worst_mount': None, 'disk_mounts': []}
    return {
        'disk_percent': worst['percent'],
        'disk_used_gb': worst['used_gb'],
        'disk_total_gb': worst['total_gb'],
        'disk_worst_mount': worst['mount'],
        'disk_mounts': mounts,
    }


def get_image_telemetry(devices: Optional[List[Any]] = None) -> Dict[str, Any]:
    """{device_id: telemetry_status.json} written by the img monitor (TASK-157, IMG_TELEMETRY=true).

    A file older than three windows is dropped: stale numbers must not read as live. {} when telemetry is off, so the
    overlay shows nothing rather than zeros."""
    out: Dict[str, Any] = {}
    try:
        from shared.src.lib.utils.storage_path_utils import get_capture_folder, get_metadata_path
        for device in devices or []:
            path = getattr(device, 'video_capture_path', '')
            folder = get_capture_folder(path) if path else None
            if not folder:
                continue
            status_file = os.path.join(get_metadata_path(folder), 'telemetry_status.json')
            try:
                with open(status_file, 'r') as f:
                    data = json.load(f)
            except (OSError, ValueError):
                continue
            window = float(data.get('bucket_seconds') or 60)
            if time.time() - float(data.get('written_at') or 0) > 3 * window:
                continue
            out[device.device_id] = data
    except Exception as e:  # noqa: BLE001 - never break host registration for a telemetry file
        print(f'[@system_info:image_telemetry] read failed: {e}')
    return out


def get_configured_capture_fps() -> Dict[str, int]:
    """{device_id: fps} parsed from the cmdline of every running ffmpeg process.

    ffmpeg is launched by `run_ffmpeg.sh` with `-framerate N` as the input rate
    (see the x11grab / v4l2 / image2pipe blocks; e.g. `-framerate 5 -i ...`).
    That is the rate ffmpeg was *told* to capture at, distinct from the rate the
    monitor actually observes (which depends on host load). The stream-stats
    overlay used to display the measured value as "FPS: in", which was
    misleading — the user expects "in" to be the configured rate (BUG-0575).

    The capture directory appears in the cmdline as part of the output path
    (x11grab / v4l2) or as the parent of the HLS / capture_*.jpg output
    (image2pipe). We match the cmdline against every configured capture base
    directory and use its basename (== device id in the standard layout) as
    the key.
    """
    out: Dict[str, int] = {}
    try:
        from shared.src.lib.utils.storage_path_utils import get_capture_base_directories
        capture_bases = get_capture_base_directories() or []
    except Exception:
        capture_bases = []
    if not capture_bases:
        return out
    # Sort longest first so e.g. /data/captures/host/device1 wins over
    # /data/captures/device1 (same string, but the longer path is a more
    # specific match against the cmdline).
    capture_bases = sorted(capture_bases, key=len, reverse=True)

    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            name = (proc.info.get('name') or '').lower()
            if name not in ('ffmpeg', 'ffmpeg.exe'):
                continue
            cmdline = proc.info.get('cmdline') or []
            full = ' '.join(cmdline)
            # First -framerate N in the cmdline is the input rate. We do
            # not look for output `-r` because the same N is reused for
            # the HLS segment writer; for a per-device "what was it
            # configured to capture at" the input rate is the right number.
            m = re.search(r'(?:^|\s)-framerate\s+(\d+(?:\.\d+)?)', full)
            if not m:
                continue
            fps = int(round(float(m.group(1))))
            if fps <= 0:
                continue
            # Match the cmdline against any configured capture base. Use
            # the first (longest) match; if multiple ffmpeg processes
            # belong to the same device, the second is ignored (they all
            # run with the same -framerate anyway).
            for base in capture_bases:
                if base and base in full:
                    device_id = os.path.basename(base.rstrip(os.sep)) or base
                    out[device_id] = fps
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return out


def get_host_system_stats(skip_speedtest=False, devices: Optional[List[Any]] = None):
    """
    Get basic system statistics for host registration
    
    Args:
        skip_speedtest: If True, skip speedtest if no cache exists (for startup optimization)
    """
    try:
        # Get service uptime from status checks
        ffmpeg_status = check_ffmpeg_status()
        monitor_status = check_monitor_status()
        ffmpeg_service_uptime = ffmpeg_status.get('service_uptime_seconds', 0)
        monitor_service_uptime = monitor_status.get('service_uptime_seconds', 0)
        
        service_health = build_service_health_summary(ffmpeg_status, monitor_status, devices=devices)

        stats = {
            'cpu_percent': psutil.cpu_percent(interval=1),
            'memory_percent': psutil.virtual_memory().percent,
            **get_disk_stats(),
            'uptime_seconds': int(time.time() - psutil.boot_time()),
            'platform': platform.system(),
            'platform_distribution': get_platform_distribution(),
            'architecture': platform.machine(),
            **get_physical_platform(),
            'python_version': platform.python_version(),
            'ffmpeg_service_uptime_seconds': ffmpeg_service_uptime,
            'monitor_service_uptime_seconds': monitor_service_uptime,
            'service_health': service_health,
            # How many browser test runs this host carries at the same time, and the cap
            # (TASK-146). Browser-isolated scripts each run a Chrome of their own, so the
            # host - not the device - is the scarce resource; the dashboard shows it.
            'browser_runs': _browser_run_status(),
            'monitor_profiles': get_monitor_profiles(devices),  # {device_id: profile} (TASK-90)
            'monitoring_off': get_monitoring_off(get_monitor_profiles(devices)),  # tv_lite devices (TASK-95)
            'monitor_overlay_on': get_overlay_on(get_monitor_profiles(devices)),  # counting devices: the modal opens with the overlay on
            'monitor_profile_services': get_profile_services(get_monitor_profiles(devices)),  # {profile: {service: bool}}
            'monitor_profile_params': get_monitor_profile_params(get_monitor_profiles(devices)),  # {device_id: {captions, delay_s, ...}} (TASK-103)
            'operational_status': service_health.get('overall_status', 'unknown'),
            'hardware_encode': has_vaapi_h264_encode(),  # gates the HD+ stream tier in the UI
            # Whether MediaMTX actually answers on its WHEP port: gates the WEB (WebRTC)
            # transport for every device on this host (BUG-0833). False also when
            # WEBRTC_ENABLED=false — the same kill switch run_ffmpeg.sh reads when it
            # decides whether to emit the RTSP slave at all.
            'webrtc': has_webrtc_endpoint(),
            # ARCHIVE_VIDEO=false: no 24h review buffer on this host; the UI disables Last 24h.
            'archive_video': os.getenv('ARCHIVE_VIDEO', 'true').strip().lower() not in ('false', '0', 'no', 'off'),
            # BUG-0575: ffmpeg-configured input rate per device, parsed from the live
            # ffmpeg process cmdline (`-framerate N`). The stream-stats overlay used
            # to display the *measured* value here, which was misleading: the operator
            # expects "FPS: in" to be the rate ffmpeg was told to capture at.
            'stream_capture_fps': get_configured_capture_fps(),
            'image_telemetry': get_image_telemetry(devices),  # TASK-157: {device_id: {frames_arrived, arrived_fps, image_bytes, frame_age_p95_ms, process, ...}}
        }
        
        # Add disk I/O read+write speed tracking (TASK-20).
        # The overlay shows R/W MB/s alongside disk_percent so the host's I/O
        # pressure is visible; tracking read here too is free (same psutil call,
        # same ~1-second cadence as cpu_percent above). The denominator is
        # 1 MiB per the original convention (see disk_write_mb_per_sec history).
        try:
            disk_io = psutil.disk_io_counters()
            if disk_io:
                if hasattr(get_host_system_stats, '_last_disk_io'):
                    last_io = get_host_system_stats._last_disk_io
                    stats['disk_read_mb_per_sec'] = round(
                        max(0, disk_io.read_bytes - last_io.read_bytes) / 1024 / 1024, 2
                    )
                    stats['disk_write_mb_per_sec'] = round(
                        max(0, disk_io.write_bytes - last_io.write_bytes) / 1024 / 1024, 2
                    )
                else:
                    # First run baseline — both rates are 0 until the next sample.
                    stats['disk_read_mb_per_sec'] = 0
                    stats['disk_write_mb_per_sec'] = 0

                # Store for next call
                get_host_system_stats._last_disk_io = disk_io
        except Exception:
            stats['disk_read_mb_per_sec'] = 0
            stats['disk_write_mb_per_sec'] = 0
        
        # Add load average (1, 5, 15 minute) - uses /proc/loadavg fallback on Linux
        load_avg = _get_load_average()
        stats['load_average_1m'] = round(load_avg[0], 2)
        stats['load_average_5m'] = round(load_avg[1], 2)
        stats['load_average_15m'] = round(load_avg[2], 2)

        # Add CPU temperature if available
        cpu_temp = get_cpu_temperature()
        if cpu_temp is not None:
            stats['cpu_temperature_celsius'] = round(cpu_temp, 1)

        # Add network speed (cached) - skip speedtest during startup if requested
        network_speed = get_network_speed_cached(skip_if_no_cache=skip_speedtest)
        stats.update(network_speed)

        return stats
    except Exception as e:
        print(f"⚠️ Error getting system stats: {e}")
        return {
            'cpu_percent': 0,
            'memory_percent': 0,
            'disk_percent': 0,
            'uptime_seconds': 0,
            'platform': 'unknown',
            'platform_distribution': None,
            'architecture': 'unknown',
            'python_version': 'unknown',
            'ffmpeg_service_uptime_seconds': 0,
            'monitor_service_uptime_seconds': 0,
            'service_health': {'overall_status': 'unknown', 'services': []},
            'operational_status': 'unknown',
            'load_average_1m': 0,
            'load_average_5m': 0,
            'load_average_15m': 0
        }


def is_host_stuck():
    """
    Check if host has any stuck processes (FFmpeg or Monitor).
    Reuses existing status checking functions to avoid code duplication.
    
    Returns:
        bool: True if any process is stuck, False otherwise
    """
    try:
        # Get status using existing functions
        ffmpeg_status = check_ffmpeg_status()
        monitor_status = check_monitor_status()
        
        # Check if either process is stuck
        ffmpeg_stuck = ffmpeg_status.get('status') == 'stuck'
        monitor_stuck = monitor_status.get('status') == 'stuck'
        
        return ffmpeg_stuck or monitor_stuck
        
    except Exception as e:
        print(f"⚠️ Error checking if host is stuck: {e}")
        return False

def get_enhanced_system_stats(skip_speedtest=False, devices: Optional[List[Any]] = None):
    """
    Get enhanced system statistics including uptime and process status
    
    Args:
        skip_speedtest: If True, skip speedtest if no cache exists (for startup optimization)
    """
    try:
        # Basic system stats
        memory = psutil.virtual_memory()
        
        # System uptime
        boot_time = psutil.boot_time()
        uptime_seconds = int(time.time() - boot_time)
        
        # FFmpeg status check (includes service uptime)
        ffmpeg_status = check_ffmpeg_status()
        
        # Monitor status check (includes service uptime)
        monitor_status = check_monitor_status()
        
        # Extract service uptime from status checks
        ffmpeg_service_uptime = ffmpeg_status.get('service_uptime_seconds', 0)
        monitor_service_uptime = monitor_status.get('service_uptime_seconds', 0)
        
        service_health = build_service_health_summary(ffmpeg_status, monitor_status, devices=devices)

        stats = {
            'cpu_percent': round(psutil.cpu_percent(interval=1), 2),
            'memory_percent': round(memory.percent, 2),
            'memory_used_gb': round(memory.used / (1024**3), 2),
            'memory_total_gb': round(memory.total / (1024**3), 2),
            **get_disk_stats(),
            'uptime_seconds': uptime_seconds,
            'platform': platform.system(),
            'platform_distribution': get_platform_distribution(),
            'architecture': platform.machine(),
            **get_physical_platform(),
            'ffmpeg_status': ffmpeg_status,
            'monitor_status': monitor_status,
            'ffmpeg_service_uptime_seconds': ffmpeg_service_uptime,
            'monitor_service_uptime_seconds': monitor_service_uptime,
            'service_health': service_health,
            # How many browser test runs this host carries at the same time, and the cap
            # (TASK-146). Browser-isolated scripts each run a Chrome of their own, so the
            # host - not the device - is the scarce resource; the dashboard shows it.
            'browser_runs': _browser_run_status(),
            'monitor_profiles': get_monitor_profiles(devices),  # {device_id: profile} (TASK-90)
            'monitoring_off': get_monitoring_off(get_monitor_profiles(devices)),  # tv_lite devices (TASK-95)
            'monitor_overlay_on': get_overlay_on(get_monitor_profiles(devices)),  # counting devices: the modal opens with the overlay on
            'monitor_profile_services': get_profile_services(get_monitor_profiles(devices)),  # {profile: {service: bool}}
            'monitor_profile_params': get_monitor_profile_params(get_monitor_profiles(devices)),  # {device_id: {captions, delay_s, ...}} (TASK-103)
            'operational_status': service_health.get('overall_status', 'unknown'),
            'hardware_encode': has_vaapi_h264_encode(),  # gates the HD+ stream tier in the UI
            # Whether MediaMTX actually answers on its WHEP port: gates the WEB (WebRTC)
            # transport for every device on this host (BUG-0833). False also when
            # WEBRTC_ENABLED=false — the same kill switch run_ffmpeg.sh reads when it
            # decides whether to emit the RTSP slave at all.
            'webrtc': has_webrtc_endpoint(),
            # ARCHIVE_VIDEO=false: no 24h review buffer on this host; the UI disables Last 24h.
            'archive_video': os.getenv('ARCHIVE_VIDEO', 'true').strip().lower() not in ('false', '0', 'no', 'off'),
        }
        
        # Add disk I/O read+write speed tracking (TASK-20).
        # See get_host_system_stats for the rationale; same _last_disk_io
        # counter + same convention, kept on the enhanced path so any caller
        # that bypasses the lightweight registration payload still gets R/W.
        try:
            disk_io = psutil.disk_io_counters()
            if disk_io:
                if hasattr(get_enhanced_system_stats, '_last_disk_io'):
                    last_io = get_enhanced_system_stats._last_disk_io
                    stats['disk_read_mb_per_sec'] = round(
                        max(0, disk_io.read_bytes - last_io.read_bytes) / 1024 / 1024, 2
                    )
                    stats['disk_write_mb_per_sec'] = round(
                        max(0, disk_io.write_bytes - last_io.write_bytes) / 1024 / 1024, 2
                    )
                else:
                    stats['disk_read_mb_per_sec'] = 0
                    stats['disk_write_mb_per_sec'] = 0

                # Store for next call
                get_enhanced_system_stats._last_disk_io = disk_io
        except Exception:
            stats['disk_read_mb_per_sec'] = 0
            stats['disk_write_mb_per_sec'] = 0
        
        # Add load average (1, 5, 15 minute) - uses /proc/loadavg fallback on Linux
        load_avg = _get_load_average()
        stats['load_average_1m'] = round(load_avg[0], 2)
        stats['load_average_5m'] = round(load_avg[1], 2)
        stats['load_average_15m'] = round(load_avg[2], 2)

        # Add CPU temperature if available
        cpu_temp = get_cpu_temperature()
        if cpu_temp is not None:
            stats['cpu_temperature_celsius'] = round(cpu_temp, 1)

        # Add network speed (cached) - skip speedtest during startup if requested
        network_speed = get_network_speed_cached(skip_if_no_cache=skip_speedtest)
        stats.update(network_speed)

        return stats
    except Exception as e:
        print(f"⚠️ Error getting enhanced system stats: {e}")
        return {
            'cpu_percent': 0,
            'memory_percent': 0,
            'memory_used_gb': 0,
            'memory_total_gb': 0,
            'disk_percent': 0,
            'disk_used_gb': 0,
            'disk_total_gb': 0,
            'uptime_seconds': 0,
            'platform': 'unknown',
            'platform_distribution': None,
            'architecture': 'unknown',
            'ffmpeg_status': {'status': 'unknown', 'error': str(e)},
            'monitor_status': {'status': 'unknown', 'error': str(e)},
            'ffmpeg_service_uptime_seconds': 0,
            'monitor_service_uptime_seconds': 0,
            'service_health': {'overall_status': 'unknown', 'services': []},
            'operational_status': 'unknown',
            'load_average_1m': 0,
            'load_average_5m': 0,
            'load_average_15m': 0
        }


def get_per_device_metrics(devices) -> List[Dict[str, Any]]:
    """
    Get per-device operational metrics WITHOUT recalculating device configurations.
    Only checks FFmpeg/Monitor status for incident detection.
    
    Args:
        devices: List of device objects (not configs)
        
    Returns:
        List of device operational metrics only
    """
    try:
        # Get FFmpeg and Monitor status once
        ffmpeg_status = check_ffmpeg_status()
        monitor_status = check_monitor_status()
        
        device_metrics = []
        
        for device in devices:
            # Use existing device properties (no recalculation)
            device_id = device.device_id
            device_name = device.device_name
            device_model = device.device_model
            device_port = getattr(device, 'device_port', 'unknown')
            
            # Extract capture folder from existing video_capture_path
            video_capture_path = getattr(device, 'video_capture_path', '')
            capture_folder = 'unknown'
            if video_capture_path:
                from shared.src.lib.utils.storage_path_utils import get_capture_folder
                capture_folder = get_capture_folder(video_capture_path) or 'unknown'
            
            # Extract video device path
            video_device = getattr(device, 'video', 'unknown')
            
            # Extract per-device FFmpeg status by checking files directly in device path
            ffmpeg_device_status = 'unknown'
            ffmpeg_last_activity = None
            ffmpeg_uptime_seconds = 0
            
            # Check if FFmpeg processes are running (from overall status)
            ffmpeg_processes_running = ffmpeg_status.get('processes_running', 0) > 0
            
            # Use existing FFmpeg status data (no duplicate file checking)
            if ffmpeg_status.get('recent_files', {}).get(capture_folder):
                device_files = ffmpeg_status['recent_files'][capture_folder]
                if device_files.get('images', 0) > 0:
                    ffmpeg_device_status = 'active'
                    ffmpeg_last_activity = datetime.now(tz=timezone.utc).isoformat()
                    ffmpeg_uptime_seconds = calculate_process_working_uptime(capture_folder, 'ffmpeg')
                else:
                    # No recent files - check if process is running
                    if ffmpeg_processes_running:
                        ffmpeg_device_status = 'stuck'  # Process running but no files
                    else:
                        ffmpeg_device_status = 'stopped'  # No process running
            else:
                # No data for this capture folder
                if ffmpeg_processes_running:
                    ffmpeg_device_status = 'stuck'  # Process running but no data for device
                else:
                    ffmpeg_device_status = 'stopped'  # No process running
            
            # Clear cache if FFmpeg is stuck/stopped (ready for restart detection)
            clear_process_cache_if_stuck(capture_folder, 'ffmpeg', ffmpeg_device_status)
            
            # Extract per-device Monitor status by checking JSON files directly in device path
            monitor_device_status = 'unknown'
            monitor_last_activity = None
            monitor_uptime_seconds = 0
            
            # Check if Monitor process is running (from overall status)
            monitor_process_running = monitor_status.get('process_running', False)
            # tv_lite (TASK-95): no monitor runs for this device on purpose; 'off' is neither 'stopped' nor 'stuck'
            from shared.src.lib.utils.monitor_profile import monitoring_off as _monitoring_off
            monitor_off = _monitoring_off(capture_folder)
            
            # Use existing Monitor status data (no duplicate file checking)
            if monitor_off:
                monitor_device_status = 'off'
            elif monitor_status.get('recent_json_files', {}).get(capture_folder):
                device_json = monitor_status['recent_json_files'][capture_folder]
                if device_json.get('count', 0) > 0:
                    monitor_device_status = 'active'
                    monitor_last_activity = datetime.now(tz=timezone.utc).isoformat()
                    monitor_uptime_seconds = calculate_process_working_uptime(capture_folder, 'monitor')
                else:
                    # No recent JSON files - check if process is running
                    if monitor_process_running:
                        monitor_device_status = 'stuck'  # Process running but no JSON files
                    else:
                        monitor_device_status = 'stopped'  # No process running
            else:
                # No data for this capture folder
                if monitor_process_running:
                    monitor_device_status = 'stuck'  # Process running but no data for device
                else:
                    monitor_device_status = 'stopped'  # No process running
            
            # Clear cache if Monitor is stuck/stopped (ready for restart detection)
            clear_process_cache_if_stuck(capture_folder, 'monitor', monitor_device_status)
            
            # Create lightweight device metrics (operational only)
            device_metric = {
                'device_id': device_id,
                'device_name': device_name,
                'device_port': device_port,
                'device_model': device_model,
                'capture_folder': capture_folder,  # Add capture folder for tracking
                'video_device': video_device,  # Add video device path for hardware tracking
                'disk_usage': get_capture_folder_size(capture_folder),  # Disk usage for capture folder
                'ffmpeg_status': ffmpeg_device_status,
                'ffmpeg_last_activity': ffmpeg_last_activity,
                'ffmpeg_working_uptime_seconds': ffmpeg_uptime_seconds,  # Per-device working time before stuck
                'monitor_status': monitor_device_status,
                'monitor_last_activity': monitor_last_activity,
                'monitor_working_uptime_seconds': monitor_uptime_seconds  # Per-device working time before stuck
            }
            
            device_metrics.append(device_metric)
            
        return device_metrics
        
    except Exception as e:
        print(f"⚠️ Error getting lightweight device metrics: {e}")
        return []


def check_ffmpeg_status():
    """Check FFmpeg process and recent file creation status"""
    try:
        status = {
            'processes_running': 0,
            'recent_files': {},
            'status': 'unknown',
            'service_start_time': None,
            'service_uptime_seconds': 0
        }
        
        # Check running FFmpeg processes
        ffmpeg_processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                name = (proc.info.get('name') or '').lower()
                if name in ('ffmpeg', 'ffmpeg.exe'):
                    ffmpeg_processes.append({
                        'pid': proc.info['pid'],
                        'cmdline': ' '.join(proc.info['cmdline'][:3])  # First 3 args only
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        status['processes_running'] = len(ffmpeg_processes)
        status['processes'] = ffmpeg_processes
        
        # Get service start time (platform-specific)
        try:
            sysname = platform.system()
            if sysname == 'Darwin':  # macOS
                result = subprocess.run(['launchctl', 'list', 'com.virtualpytest.stream'],
                                      capture_output=True, text=True)
                if result.returncode == 0:
                    status['service_start_time'] = time.time()  # approximation
                    status['service_uptime_seconds'] = 0
            elif sysname == 'Linux':
                result = subprocess.run(['systemctl', 'show', 'vpt-stream', '--property=ActiveEnterTimestamp'],
                                      capture_output=True, text=True)
                if result.returncode == 0:
                    timestamp_line = result.stdout.strip()
                    if timestamp_line.startswith('ActiveEnterTimestamp='):
                        timestamp_str = timestamp_line.split('=', 1)[1]
                        if timestamp_str and timestamp_str != '0':
                            from datetime import datetime
                            service_start_time = datetime.strptime(timestamp_str, '%a %Y-%m-%d %H:%M:%S %Z').timestamp()
                            status['service_start_time'] = service_start_time
                            status['service_uptime_seconds'] = int(time.time() - service_start_time)
            else:
                # Windows/other: approximate using oldest ffmpeg process start time
                if ffmpeg_processes:
                    try:
                        starts = [psutil.Process(p['pid']).create_time() for p in ffmpeg_processes]
                        service_start_time = min(starts)
                        status['service_start_time'] = service_start_time
                        status['service_uptime_seconds'] = int(time.time() - service_start_time)
                    except Exception:
                        pass
        except Exception as e:
            print(f"⚠️ Could not get stream service start time: {e}")
            pass
        
        capture_dirs = get_capture_base_directories()
        
        for capture_dir in capture_dirs:
            if os.path.exists(capture_dir):
                device_name = os.path.basename(capture_dir)
                # Check both /hot/captures and /captures — ffmpeg writes to
                # whichever setup_capture_directories() landed on. See
                # _count_recent_files_any_mode for rationale.
                recent_jpg_count = _count_recent_files_any_mode(
                    capture_dir, 'captures',
                    r'^capture_.*\.jpg$',
                    max_age_seconds=2,
                    exclude_pattern=r'_thumbnail\.jpg$',
                )
                
                # Single line per folder with debug info including process status
                print(f"🔍 [FFMPEG] {device_name}: {recent_jpg_count} JPG files (last 10s) | Processes: {status['processes_running']}")
                
                status['recent_files'][device_name] = {
                    'images': recent_jpg_count,
                    'last_activity': time.time() if recent_jpg_count > 0 else 0
                }
        
        # Determine per-device status and overall status
        device_statuses = {}
        active_devices = 0
        
        for device_name, files_info in status['recent_files'].items():
            recent_files_count = files_info['images']  # Only check JPG files now
            
            if recent_files_count > 0:
                device_statuses[device_name] = 'active'
                active_devices += 1
            else:
                device_statuses[device_name] = 'stopped'  # No recent files for this device
        
        status['device_statuses'] = device_statuses
        
        # Overall status logic
        if status['processes_running'] > 0:
            if active_devices > 0:
                status['status'] = 'active'  # At least one device is active
            else:
                status['status'] = 'stuck'  # Processes running but no devices producing files
        else:
            # No ffmpeg process is running. Two reasons this can be true:
            # the stream is idle (most common), or the systemd unit is masked —
            # a deliberately-disabled host (no display / no streams). Distinguish
            # the two so the dashboard files a masked stream under "Not installed"
            # (BUG-0745 follow-up) instead of a red 'down' incident.
            status['status'] = 'not_installed' if _linux_service_is_masked('vpt-stream') else 'stopped'

        return status

    except Exception as e:
        return {
            'status': 'error',
            'error': str(e),
            'processes_running': 0,
            'recent_files': {},
            'service_start_time': None,
            'service_uptime_seconds': 0
        }


def check_monitor_status():
    """Check capture monitor process and JSON file creation"""
    try:
        status = {
            'process_running': False,
            'recent_json_files': {},
            'status': 'unknown',
            'service_start_time': None,
            'service_uptime_seconds': 0
        }
        
        # Check if capture_monitor.py process is running
        monitor_processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = proc.info.get('cmdline')
                if cmdline and 'capture_monitor' in ' '.join(cmdline):
                    monitor_processes.append({
                        'pid': proc.info['pid'],
                        'name': proc.info['name']
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        status['process_running'] = len(monitor_processes) > 0
        status['processes'] = monitor_processes

        # Windows fallback: NSSM-managed services run as LocalSystem and their
        # cmdline often isn't readable by the (non-elevated) host process, so the
        # psutil scan above returns empty even when the monitor is healthy. Trust
        # the service-control state in that case.
        if not status['process_running'] and platform.system() == 'Windows':
            svc_state = _check_windows_service(['vpt-monitor-img', 'vpt-monitor'])
            if svc_state.get('status') == 'active':
                status['process_running'] = True
        
        # Get service start time (platform-specific)
        try:
            sysname = platform.system()
            if sysname == 'Darwin':  # macOS
                result = subprocess.run(['launchctl', 'list', 'com.virtualpytest.monitor-img'],
                                      capture_output=True, text=True)
                if result.returncode == 0:
                    status['service_start_time'] = time.time()  # approximation
                    status['service_uptime_seconds'] = 0
            elif sysname == 'Linux':
                result = subprocess.run(['systemctl', 'show', 'vpt-monitor-img', '--property=ActiveEnterTimestamp'],
                                      capture_output=True, text=True)
                if result.returncode == 0:
                    timestamp_line = result.stdout.strip()
                    if timestamp_line.startswith('ActiveEnterTimestamp='):
                        timestamp_str = timestamp_line.split('=', 1)[1]
                        if timestamp_str and timestamp_str != '0':
                            from datetime import datetime
                            service_start_time = datetime.strptime(timestamp_str, '%a %Y-%m-%d %H:%M:%S %Z').timestamp()
                            status['service_start_time'] = service_start_time
                            status['service_uptime_seconds'] = int(time.time() - service_start_time)
            else:
                # Windows/other: approximate using oldest capture_monitor process start time
                if monitor_processes:
                    try:
                        starts = [psutil.Process(p['pid']).create_time() for p in monitor_processes]
                        service_start_time = min(starts)
                        status['service_start_time'] = service_start_time
                        status['service_uptime_seconds'] = int(time.time() - service_start_time)
                    except Exception:
                        pass
        except Exception as e:
            print(f"⚠️ Could not get monitor service start time: {e}")
            pass
        
        capture_base_dirs = get_capture_base_directories()
        
        for capture_dir in capture_base_dirs:
            if os.path.exists(capture_dir):
                device_name = os.path.basename(capture_dir)
                recent_json_count = _count_recent_files_any_mode(
                    capture_dir, 'metadata',
                    r'^capture_.*\.json$',
                    max_age_seconds=2,
                )
                
                # Single line per folder with debug info including process status
                print(f"🔍 [MONITOR] {device_name}: {recent_json_count} JSON files (last 10s) | Process: {'running' if status['process_running'] else 'stopped'}")
                
                status['recent_json_files'][device_name] = {
                    'count': recent_json_count,
                    'last_activity': time.time() if recent_json_count > 0 else 0
                }
        
        # Determine per-device status and overall status
        device_statuses = {}
        active_devices = 0
        
        for device_name, json_info in status['recent_json_files'].items():
            if json_info['count'] > 0:
                device_statuses[device_name] = 'active'
                active_devices += 1
            else:
                device_statuses[device_name] = 'stopped'  # No recent JSON files for this device
        
        status['device_statuses'] = device_statuses
        
        # Overall status logic
        if status['process_running']:
            if active_devices > 0:
                status['status'] = 'active'  # At least one device is active
            else:
                status['status'] = 'stuck'  # Process running but no devices producing JSON files
        else:
            # No capture_monitor process running. Either the monitor is idle (no
            # image triggers to handle) or its systemd unit is masked — a headless
            # host that does not run vpt-monitor-img at all. Distinguish so the
            # dashboard files a masked monitor under "Not installed" instead of a
            # red 'down' incident (BUG-0745 follow-up, parallel to the stream check).
            status['status'] = 'not_installed' if _linux_service_is_masked('vpt-monitor-img') else 'stopped'

        return status
        
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e),
            'process_running': False,
            'recent_json_files': {},
            'service_start_time': None,
            'service_uptime_seconds': 0
        } 
