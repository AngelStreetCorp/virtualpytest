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
    's': 's', 'sec': 's', 'second': 's',
    'm': 'min', 'min': 'min', 'minute': 'min',
    'h': 'h', 'hr': 'h', 'hour': 'h',
    'd': 'd', 'day': 'd',
    'w': 'week', 'week': 'week',
}


def normalize_journal_since(since: Optional[str]) -> Optional[str]:
    """Convert UI relative tokens (e.g. '1h', '15m', '7d') into valid journalctl
    --since syntax ('-1h', '-15min', '-7d').

    Absolute timestamps ('2026-05-19 08:00'), keywords ('today', 'yesterday'),
    and already-relative values ('-1h') are passed through unchanged so
    journalctl can parse them itself.
    """
    if not since:
        return since
    s = since.strip()
    # Already journalctl-acceptable: signed relative, has time/date separators.
    if s[:1] in ('-', '+') or ' ' in s or ':' in s:
        return s
    if s.lower() in ('today', 'yesterday', 'now'):
        return s
    m = re.fullmatch(r'(\d+)\s*([a-zA-Z]+)', s)
    if not m:
        # e.g. a bare date "2026-05-19" — let journalctl parse it.
        return s
    value, unit = m.group(1), m.group(2).lower()
    mapped = _JOURNAL_SINCE_UNIT.get(unit)
    if not mapped:
        return s
    return f'-{value}{mapped}'


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
