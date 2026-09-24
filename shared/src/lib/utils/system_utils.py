"""
System Utilities

Centralized system command utilities for VirtualPyTest.
Handles systemctl, reboot, and other system-level operations.
"""

import os
import re
import signal
import subprocess
from typing import Dict, Any, Optional, List


def kill_existing_script_instances(script_name: str) -> List[int]:
    """
    Kill any existing instances of a Python script before starting.
    Ensures only ONE instance runs at a time.
    
    Args:
        script_name: Name of the script file (e.g., 'hot_cold_archiver.py')
        
    Returns:
        List of PIDs that were killed
    """
    current_pid = os.getpid()
    killed_pids = []
    
    try:
        import platform
        if platform.system() == 'Windows':
            # Windows: pgrep isn't available; skip to avoid noisy warnings
            return []

        # Find all processes running this script
        output = subprocess.check_output(['pgrep', '-f', script_name], text=True).strip()
        pids = [int(pid) for pid in output.split('\n') if pid]
        
        # Kill all except current process
        for pid in pids:
            if pid != current_pid:
                try:
                    os.kill(pid, signal.SIGKILL)
                    killed_pids.append(pid)
                except ProcessLookupError:
                    pass  # Already dead
        
        return killed_pids
        
    except subprocess.CalledProcessError:
        # No other processes found - this is good
        return []
    except Exception as e:
        print(f"Warning: Error checking for existing {script_name} processes: {e}")
        return []


def restart_systemd_service(service_name: str, timeout: int = 30) -> Dict[str, Any]:
    """
    Restart a systemd service using sudo systemctl restart.
    
    Args:
        service_name: Name of the systemd service (e.g., 'vpt-host', 'vpt-server')
        timeout: Command timeout in seconds
        
    Returns:
        Dict with success status, message, and error details
    """
    try:
        print(f"[SYSTEM_UTILS] Restarting systemd service: {service_name}")
        
        result = subprocess.run(
            ['sudo', 'systemctl', 'restart', service_name],
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        if result.returncode == 0:
            print(f"[SYSTEM_UTILS] Successfully restarted service: {service_name}")
            return {
                'success': True,
                'message': f'Service {service_name} restarted successfully',
                'service': service_name
            }
        else:
            error_msg = result.stderr.strip() or result.stdout.strip() or 'Unknown error'
            print(f"[SYSTEM_UTILS] Failed to restart service {service_name}: {error_msg}")
            return {
                'success': False,
                'error': f'Failed to restart service {service_name}: {error_msg}',
                'service': service_name
            }
            
    except subprocess.TimeoutExpired:
        error_msg = f'Service restart timed out after {timeout}s'
        print(f"[SYSTEM_UTILS] {error_msg}")
        return {
            'success': False,
            'error': error_msg,
            'service': service_name
        }
    except Exception as e:
        error_msg = f'System error restarting service {service_name}: {str(e)}'
        print(f"[SYSTEM_UTILS] {error_msg}")
        return {
            'success': False,
            'error': error_msg,
            'service': service_name
        }


def reboot_system(timeout: int = 10) -> Dict[str, Any]:
    """
    Reboot the system. Uses `shutdown /r` on Windows, `sudo reboot` on Linux.

    Args:
        timeout: Command timeout in seconds (should be short since system will reboot)

    Returns:
        Dict with success status and message
    """
    import platform

    if platform.system() == 'Windows':
        # Windows: `shutdown /r /t N` schedules a reboot N seconds out and returns
        # immediately, so the HTTP response can be sent before the box goes down.
        reboot_cmd = ['shutdown', '/r', '/t', '5', '/c', 'Reboot']
    else:
        reboot_cmd = ['sudo', 'reboot']

    try:
        print("[SYSTEM_UTILS] Initiating system reboot")

        # Use reboot command with short timeout since system will restart
        result = subprocess.run(
            reboot_cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        # If we reach here, reboot command was issued
        print("[SYSTEM_UTILS] Reboot command issued successfully")
        return {
            'success': True,
            'message': 'System reboot initiated',
            'action': 'reboot'
        }
        
    except subprocess.TimeoutExpired:
        # This is actually expected for reboot - system is restarting
        print("[SYSTEM_UTILS] Reboot command timed out (expected - system restarting)")
        return {
            'success': True,
            'message': 'System reboot initiated (timeout expected)',
            'action': 'reboot'
        }
    except Exception as e:
        error_msg = f'System error during reboot: {str(e)}'
        print(f"[SYSTEM_UTILS] {error_msg}")
        return {
            'success': False,
            'error': error_msg,
            'action': 'reboot'
        }


def get_systemd_service_status(service_name: str) -> Dict[str, Any]:
    """
    Get status of a systemd service.
    
    Args:
        service_name: Name of the systemd service
        
    Returns:
        Dict with service status information
    """
    try:
        result = subprocess.run(
            ['systemctl', 'is-active', service_name],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        status = result.stdout.strip()
        is_active = result.returncode == 0
        
        return {
            'success': True,
            'service': service_name,
            'status': status,
            'is_active': is_active
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'service': service_name,
            'status': 'unknown',
            'is_active': False
        }


# journalctl accepts systemd.time(7) spans, NOT bare tokens like "1h".
# Map the unit so "1h" -> "-1h", "15m" -> "-15min", "7d" -> "-7d".
_JOURNAL_SINCE_UNIT = {
    's': 's', 'sec': 's', 'secs': 's', 'second': 's', 'seconds': 's',
    'm': 'min', 'min': 'min', 'mins': 'min', 'minute': 'min', 'minutes': 'min',
    'h': 'h', 'hr': 'h', 'hrs': 'h', 'hour': 'h', 'hours': 'h',
    'd': 'd', 'day': 'd', 'days': 'd',
    'w': 'week', 'week': 'week', 'weeks': 'week',
}

# journalctl -p accepts a syslog priority name, a single digit 0-7, or a
# 'from..to' range over the same vocabulary. Anything else is rejected by
# journalctl itself; we reject it here too so we never pass it to the cmd.
_JOURNAL_PRIORITIES = frozenset({
    'emerg', 'alert', 'crit', 'err', 'warning', 'notice', 'info', 'debug',
})
_PRI_NAMES = '|'.join(sorted(_JOURNAL_PRIORITIES))
_JOURNAL_PRIORITY_RE = re.compile(
    rf'^(?:[0-7]|{_PRI_NAMES})(?:\.\.(?:[0-7]|{_PRI_NAMES}))?$'
)

# Service names reaching subprocess.run must look like a systemd unit name:
# must start with a letter/digit/dot/underscore/@ (systemd template instance),
# then letters/digits/dot/underscore/hyphen/@. No leading hyphen.
_SERVICE_NAME_RE = re.compile(r'^[A-Za-z0-9_.@][A-Za-z0-9_.@-]*$')

# systemctl verbs the codebase uses as subprocess actions. Anything else is
# a command-injection vector: 'enable', 'disable', 'mask', 'start', 'stop',
# 'restart', 'reload', 'reload-or-restart', 'try-reload-or-restart',
# 'kill', 'is-active', 'status', plus 'reset-failed'. We validate against
# this set so an attacker cannot smuggle in arbitrary verbs.
_SYSTEMCTL_ACTIONS = frozenset({
    'start', 'stop', 'restart', 'reload', 'reload-or-restart',
    'try-reload-or-restart', 'kill', 'is-active', 'status',
    'enable', 'disable', 'mask', 'unmask', 'reset-failed',
})


def validate_systemd_unit_name(unit: str) -> str:
    """Return the unit name if it matches systemd's documented unit
    charset, else raise ValueError.

    Defense-in-depth: callers may already whitelist the unit (the route
    layer does), but the helper that runs `systemctl ... <unit>` is a
    shared utility and must not trust its callers.  This narrows the taint
    path that CodeQL flags as 'Uncontrolled command line'.
    """
    if not _SERVICE_NAME_RE.fullmatch(unit):
        raise ValueError(
            f'invalid systemd unit name: {unit!r} '
            f'(must match [A-Za-z0-9_.@-]+)'
        )
    return unit


def validate_systemctl_action(action: str) -> str:
    """Return the action if it is one of the well-known systemctl verbs,
    else raise ValueError. Use this as a gate before any
    `subprocess.run([..., action, unit])` call so the action argv slot
    cannot be set to an arbitrary token (e.g. `--help`, `edit`, `condreload`).
    """
    if action not in _SYSTEMCTL_ACTIONS:
        raise ValueError(
            f'invalid systemctl action: {action!r} '
            f'(expected one of {sorted(_SYSTEMCTL_ACTIONS)})'
        )
    return action


def validate_journalctl_level(level: str) -> str:
    """Return the level if it matches journalctl's documented priority syntax,
    else raise ValueError. Defense-in-depth: callers already validate the
    HTTP layer, but read_journal_logs is a shared utility and must not trust
    its callers.
    """
    if not _JOURNAL_PRIORITY_RE.fullmatch(level):
        raise ValueError(
            f'invalid journalctl priority: {level!r} '
            f'(expected 0-7, one of {sorted(_JOURNAL_PRIORITIES)}, '
            f'or a range like "info..debug")'
        )
    return level


def _validate_service_name(service: str) -> str:
    """Backwards-compatible alias. Prefer validate_systemd_unit_name."""
    return validate_systemd_unit_name(service)


def _validate_journal_level(level: str) -> str:
    """Backwards-compatible alias. Prefer validate_journalctl_level."""
    return validate_journalctl_level(level)


def normalize_journal_since(since: Optional[str]) -> Optional[str]:
    """Convert UI relative tokens (e.g. '1h', '15m', '7d') into valid journalctl
    --since syntax ('-1h', '-15min', '-7d').

    Accepts only the documented systemd.time(7) syntax we use in the UI:
      - relative spans: '1h', '30m', '7d', '2 weeks', '-1h', '+30min'
      - absolute timestamps: 'YYYY-MM-DD', 'YYYY-MM-DD HH:MM[:SS]'
      - keywords: 'today', 'yesterday', 'now', 'tomorrow'
    Anything else returns None so the caller treats it as 'no --since',
    rather than passing a free-form string to subprocess.
    """
    if not since:
        return None
    s = since.strip()
    if not s:
        return None
    # Already-signed relative ('-1h', '+30min').
    if s[:1] in ('-', '+'):
        rest = s[1:]
        if re.fullmatch(r'\d+\s*[a-zA-Z]+', rest):
            return s
        # Anything else after the sign is rejected (no pass-through).
        return None
    if s.lower() in ('today', 'yesterday', 'now', 'tomorrow'):
        return s
    # Absolute date 'YYYY-MM-DD'.
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', s):
        return s
    # Absolute timestamp 'YYYY-MM-DD HH:MM[:SS]'.
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?', s):
        return s
    # Relative span without sign: '1h', '30min', '7d', '2 weeks'.
    m = re.fullmatch(r'(\d+)\s*([a-zA-Z]+)', s)
    if m:
        value, unit = m.group(1), m.group(2).lower()
        mapped = _JOURNAL_SINCE_UNIT.get(unit)
        if mapped:
            return f'-{value}{mapped}'
        return None
    return None


def _read_windows_service_logs(
    service: str,
    lines: int = 100,
    grep: Optional[str] = None,
) -> Dict[str, Any]:
    """Windows has no journald. Host services are NSSM- or Scheduled-Task-
    wrapped and redirect stdout/stderr to flat files under
    %VIRTUALPYTEST_LOGS%. Tail those so the dashboard log viewer shows the
    real failure (e.g. an import traceback) instead of 'journalctl not found'.

    Unit -> files (installer convention; see install_host_windows.ps1,
    host_wrapper.ps1, stream_wrapper.ps1): strip the 'vpt-' prefix, then look
    for <name>_error.log (stderr), <name>.log (stdout) and <name>_wrapper.log
    (the Scheduled-Task wrappers used by vpt-host / vpt-stream). The error log
    is shown first so a crash reason is at the top of the viewer.

    `since`/`level` are journald-only and don't apply to flat files; tailing
    by `lines` is the meaningful control here.
    """
    log_dir = os.environ.get('VIRTUALPYTEST_LOGS') or r'C:\virtualpytest\logs'
    short = service[4:] if service.startswith('vpt-') else service
    candidates = [f'{short}_error.log', f'{short}.log', f'{short}_wrapper.log']

    sections = []
    found_any = False
    for fname in candidates:
        path = os.path.join(log_dir, fname)
        if not os.path.isfile(path):
            continue
        found_any = True
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as fh:
                file_lines = fh.readlines()
        except OSError as exc:
            sections.append(f'==> {fname} <==\n[could not read: {exc}]')
            continue
        tail = file_lines[-int(lines):] if lines else file_lines
        body = ''.join(tail).rstrip('\n')
        if grep and body:
            needle = grep.lower()
            body = '\n'.join(l for l in body.split('\n') if needle in l.lower())
        sections.append(f'==> {fname} <==\n{body}' if body else f'==> {fname} <==\n(empty)')

    if not found_any:
        return {
            'success': False,
            'error': (f"No log files for '{service}' in {log_dir} "
                      f"(looked for: {', '.join(candidates)})"),
        }

    logs = '\n\n'.join(sections)
    return {
        'success': True,
        'service': service,
        'logs': logs,
        'lines_count': len(logs.split('\n')) if logs else 0,
    }


def read_journal_logs(
    service: str,
    lines: int = 100,
    since: Optional[str] = None,
    grep: Optional[str] = None,
    level: Optional[str] = None,
    timeout: int = 10,
) -> Dict[str, Any]:
    """Run `journalctl -u <service>.service` and return a normalized result.

    On Windows there is no journald, so this delegates to
    `_read_windows_service_logs`, which tails the NSSM/wrapper log files.

    Unlike a raw subprocess call, this surfaces non-zero exit codes and stderr
    instead of silently returning empty logs. Two common silent failures it
    now reports explicitly:
      - invalid --since (e.g. "1h"): journalctl exits 1 with empty stdout
      - caller not in 'systemd-journal'/'adm' group: exit 0, empty stdout,
        a hint on stderr
    """
    import platform
    if platform.system() == 'Windows':
        return _read_windows_service_logs(service, lines=lines, grep=grep)

    # Defense-in-depth: validate every caller-controlled arg reaching
    # subprocess.run, even though the routes already whitelist `service`.
    # The route whitelists are the primary defense; this catches any future
    # caller (tests, scripts, internal calls) and turns the taint into a
    # explicit error instead of passing arbitrary strings to journalctl.
    _validate_service_name(service)
    if level is not None:
        try:
            level = _validate_journal_level(str(level))
        except ValueError as exc:
            return {'success': False, 'error': str(exc), 'service': service}

    cmd = ['journalctl', '-u', f'{service}.service', '--no-pager']
    if lines:
        cmd.extend(['-n', str(int(lines))])
    norm_since = normalize_journal_since(since)
    if norm_since:
        cmd.extend(['--since', norm_since])
    if level:
        cmd.extend(['-p', str(level)])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {'success': False, 'error': 'journalctl command timed out'}
    except FileNotFoundError:
        return {'success': False, 'error': 'journalctl not found'}

    stderr = (result.stderr or '').strip()

    if result.returncode != 0:
        return {
            'success': False,
            'error': stderr or f'journalctl exited with code {result.returncode}',
            'returncode': result.returncode,
        }

    logs = result.stdout
    if not logs.strip() and 'systemd-journal' in stderr:
        return {
            'success': False,
            'error': ("No journal access: the service account is not in the "
                      "'systemd-journal' or 'adm' group. " + stderr),
        }

    if grep and logs:
        needle = grep.lower()
        logs = '\n'.join(l for l in logs.split('\n') if needle in l.lower())

    return {
        'success': True,
        'service': service,
        'logs': logs,
        'lines_count': len(logs.split('\n')) if logs else 0,
    }
