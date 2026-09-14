"""
System Information Utilities

Utility functions for system monitoring, process management, and environment validation.
"""

import os
import psutil
import hashlib
import platform
import time
import subprocess
import json
import re
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


def _check_linux_service(service_names: List[str]) -> Dict[str, Any]:
    """Check Linux systemd service status trying multiple unit names."""
    for service_name in service_names:
        cmd = ['systemctl', 'is-active', service_name]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            stdout_value = (result.stdout or '').strip().lower()
            stderr_value = (result.stderr or '').strip().lower()
            if result.returncode == 0:
                return {'status': 'active', 'runtime': 'service', 'resolved_name': service_name}
            if result.returncode == 3:
                # Distinguish true inactive from "unit not found" scenarios.
                if stdout_value == 'inactive' and 'not found' not in stderr_value:
                    return {'status': 'stopped', 'runtime': 'service', 'resolved_name': service_name}
                continue
        except Exception:
            continue
    return {'status': 'unknown', 'runtime': 'service'}


# Windows: services where the canonical vpt-* name may not be the one
# actually running. e.g. on hosts with TightVNC pre-installed, the NSSM
# ``vpt-vnc`` service is registered-but-disabled (port 5900 conflict) and
# ``tvnserver`` is the live service. We try each candidate in order,
# skipping disabled ones, when reading status AND when performing
# start/stop/restart — so the dashboard always reports and acts on
# whichever service is actually usable. Single source of truth.
WINDOWS_SERVICE_ALIASES: Dict[str, List[str]] = {
    'vpt-vnc': ['vpt-vnc', 'tvnserver'],
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
    """
    fallback = {'status': 'unknown', 'runtime': 'service'}
    for service_name in service_names:
        try:
            service = psutil.win_service_get(service_name)
            service_info = service.as_dict()
            start_type = (service_info.get('start_type') or '').strip().lower()
            if start_type == 'disabled':
                # Remember this in case no later candidate is installed, so
                # the dashboard renders "not installed" (non-critical) rather
                # than "unknown" (degraded).
                fallback = {'status': 'not_installed', 'runtime': 'service',
                            'resolved_name': service_name, 'start_type': 'disabled'}
                continue
            mapped_status = _service_is_running_status(service_info.get('status', 'unknown'))
            return {'status': mapped_status, 'runtime': 'service', 'resolved_name': service_name}
        except Exception:
            continue
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
    """Check Windows scheduled task state (used by vpt-stream, vpt-host)."""
    try:
        result = subprocess.run(
            ['schtasks', '/Query', '/TN', task_name, '/FO', 'LIST', '/V'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode != 0:
            return {'status': 'unknown', 'runtime': 'task', 'error': result.stderr.strip()[:160]}

        content = result.stdout.lower()
        if 'status:' in content and 'running' in content:
            return {'status': 'active', 'runtime': 'task', 'resolved_name': task_name}
        if 'status:' in content and ('ready' in content or 'queued' in content):
            return {'status': 'stopped', 'runtime': 'task', 'resolved_name': task_name}
        if 'disabled' in content:
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
    'vpt-monitor',
    'vpt-archiver',
    'vpt-kpi',
    'vpt-vnc',
    'vpt-websockify',
    'vpt-transcript',
    'vpt-subtitle',
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
    """
    platform_name = platform.system()
    has_audio_devices = _host_has_audio_capable_devices(devices)
    has_vnc_device = _host_has_vnc_device(devices)
    host_type = os.getenv('HOST_TYPE', 'host_vnc')
    is_runner = host_type.startswith('runner_')
    is_android = 'android' in host_type

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
        {'name': 'vpt-host', 'label': 'Host API', 'description': 'Host API: manages devices & incoming requests', 'critical': True, 'optional': False, 'linux_names': ['vpt-host', 'host'], 'windows_names': ['vpt-host']},
        {'name': 'vpt-monitor', 'label': 'Monitor', 'description': 'Device health & incident monitoring', 'critical': not is_runner, 'optional': is_runner, 'linux_names': ['vpt-monitor', 'monitor'], 'windows_names': ['vpt-monitor']},
        {'name': 'vpt-archiver', 'label': 'Archiver', 'description': 'Buffers video & archives screenshots', 'critical': not is_runner, 'optional': is_runner, 'linux_names': ['vpt-archiver', 'archiver'], 'windows_names': ['vpt-archiver']},
        {'name': 'vpt-kpi', 'label': 'KPI', 'description': 'Measures navigation & action KPIs', 'critical': not is_runner, 'optional': is_runner, 'linux_names': ['vpt-kpi', 'kpi'], 'windows_names': ['vpt-kpi']},
        {'name': 'vpt-vnc', 'label': 'VNC', 'description': 'Remote desktop (VNC) for the device', 'critical': has_vnc_device and not is_runner, 'optional': not has_vnc_device or is_runner, 'linux_names': ['vpt-vnc', 'vnc'], 'windows_names': _windows_service_candidates('vpt-vnc')},
        {'name': 'vpt-websockify', 'label': 'Websockify', 'description': 'Bridges VNC to the browser (noVNC)', 'critical': has_vnc_device and not is_runner, 'optional': not has_vnc_device or is_runner, 'linux_names': ['vpt-websockify', 'websockify'], 'windows_names': ['vpt-websockify']},
        {'name': 'vpt-transcript', 'label': 'Transcript', 'description': 'Audio → text transcription', 'critical': has_audio_devices and not is_runner, 'optional': not has_audio_devices or is_runner, 'linux_names': ['vpt-transcript', 'transcript'], 'windows_names': ['vpt-transcript']},
        {'name': 'vpt-subtitle', 'label': 'Subtitle', 'description': 'Subtitle extraction & overlay', 'critical': False, 'optional': True, 'linux_names': ['vpt-subtitle', 'subtitle'], 'windows_names': []},
        {'name': 'vpt-emulator', 'label': 'Emulator', 'description': 'Android emulator runtime', 'critical': is_android and not is_runner, 'optional': not is_android or is_runner, 'linux_names': ['vpt-emulator'], 'windows_names': []},
        {'name': 'vpt-emulator-fifo', 'label': 'Screencap', 'description': 'Emulator frame capture pipe', 'critical': is_android and not is_runner, 'optional': not is_android or is_runner, 'linux_names': ['vpt-emulator-fifo'], 'windows_names': []},
    ]

    for definition in service_definitions:
        if platform_name == 'Linux':
            status_info = _check_linux_service(definition['linux_names'])
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

    critical_services = [s for s in services if s.get('critical', False)]
    critical_statuses = {s.get('status', 'unknown') for s in critical_services}

    if 'error' in critical_statuses or 'stopped' in critical_statuses:
        overall_status = 'error'
    elif 'stuck' in critical_statuses or 'unknown' in critical_statuses:
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
            'disk_percent': psutil.disk_usage('/').percent,
            'uptime_seconds': int(time.time() - psutil.boot_time()),
            'platform': platform.system(),
            'platform_distribution': get_platform_distribution(),
            'architecture': platform.machine(),
            'python_version': platform.python_version(),
            'ffmpeg_service_uptime_seconds': ffmpeg_service_uptime,
            'monitor_service_uptime_seconds': monitor_service_uptime,
            'service_health': service_health,
            'operational_status': service_health.get('overall_status', 'unknown'),
            'hardware_encode': has_vaapi_h264_encode(),  # gates the HD+ stream tier in the UI
        }
        
        # Add disk I/O write speed tracking
        try:
            disk_io = psutil.disk_io_counters()
            if disk_io:
                # Store current counters for next calculation
                if hasattr(get_host_system_stats, '_last_disk_io'):
                    last_io = get_host_system_stats._last_disk_io
                    # Calculate MB written per second (uses cpu_percent's 1-sec interval)
                    bytes_written = disk_io.write_bytes - last_io.write_bytes
                    stats['disk_write_mb_per_sec'] = round(bytes_written / 1024 / 1024, 2)
                else:
                    stats['disk_write_mb_per_sec'] = 0  # First run baseline
                
                # Store for next call
                get_host_system_stats._last_disk_io = disk_io
        except Exception:
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
        disk = psutil.disk_usage('/')
        
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
            'disk_percent': round((disk.used / disk.total) * 100, 2),
            'disk_used_gb': round(disk.used / (1024**3), 2),
            'disk_total_gb': round(disk.total / (1024**3), 2),
            'uptime_seconds': uptime_seconds,
            'platform': platform.system(),
            'platform_distribution': get_platform_distribution(),
            'architecture': platform.machine(),
            'ffmpeg_status': ffmpeg_status,
            'monitor_status': monitor_status,
            'ffmpeg_service_uptime_seconds': ffmpeg_service_uptime,
            'monitor_service_uptime_seconds': monitor_service_uptime,
            'service_health': service_health,
            'operational_status': service_health.get('overall_status', 'unknown'),
            'hardware_encode': has_vaapi_h264_encode(),  # gates the HD+ stream tier in the UI
        }
        
        # Add disk I/O write speed tracking
        try:
            disk_io = psutil.disk_io_counters()
            if disk_io:
                # Store current counters for next calculation
                if hasattr(get_enhanced_system_stats, '_last_disk_io'):
                    last_io = get_enhanced_system_stats._last_disk_io
                    # Calculate MB written per second (uses cpu_percent's 1-sec interval)
                    bytes_written = disk_io.write_bytes - last_io.write_bytes
                    stats['disk_write_mb_per_sec'] = round(bytes_written / 1024 / 1024, 2)
                else:
                    stats['disk_write_mb_per_sec'] = 0  # First run baseline
                
                # Store for next call
                get_enhanced_system_stats._last_disk_io = disk_io
        except Exception:
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
            
            # Use existing Monitor status data (no duplicate file checking)
            if monitor_status.get('recent_json_files', {}).get(capture_folder):
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
            status['status'] = 'stopped'  # No processes running
            
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
            svc_state = _check_windows_service(['vpt-monitor'])
            if svc_state.get('status') == 'active':
                status['process_running'] = True
        
        # Get service start time (platform-specific)
        try:
            sysname = platform.system()
            if sysname == 'Darwin':  # macOS
                result = subprocess.run(['launchctl', 'list', 'com.virtualpytest.monitor'],
                                      capture_output=True, text=True)
                if result.returncode == 0:
                    status['service_start_time'] = time.time()  # approximation
                    status['service_uptime_seconds'] = 0
            elif sysname == 'Linux':
                result = subprocess.run(['systemctl', 'show', 'vpt-monitor', '--property=ActiveEnterTimestamp'],
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
            status['status'] = 'stopped'  # No process running
            
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
