#!/usr/bin/env python3
"""Free debug-port allocation for the browsers a host runs.

TASK-146 (and the older BUG-0114): several browser test runs can share one host.
Every run needs its own Chrome debug port and its own Chrome profile, otherwise
the second run either kills the first one's browser ("ANOTHER BROWSER IS ALREADY
RUNNING on CDP port 9222 - killing it") or attaches to it and drives the SAME tab.

The allocator hands out a port nothing else is using and records the owner in a
small per-host registry, so that:

  - two concurrent runs never pick the same port,
  - a run that died leaves an entry that is pruned automatically (the pid is gone),
  - the orphan cleanup can tell "a browser left behind by a dead run" (kill it)
    from "another LIVE run's browser" (never touch it).

Port 9222 stays reserved for the host's own service browser (the agent tree, the
web worker and the KPI executor all attach to it), so a script run takes a port
from the run range instead.
"""

from __future__ import annotations

import errno
import json
import os
import socket
import tempfile
import time
from typing import Any, Dict, List, Optional

# The host service browser (vpt-host's own web controller, the web worker, the KPI
# executor). Everything on the host that attaches to "the" browser uses this port.
RESERVED_DEBUG_PORT = 9222

# Script runs take their port from this range, so they never fight the service
# browser for 9222.
RUN_DEBUG_PORT_BASE = int(os.environ.get('VPT_CHROME_DEBUG_PORT_BASE', '9300'))
RUN_DEBUG_PORT_SCAN = int(os.environ.get('VPT_CHROME_DEBUG_PORT_SCAN', '64'))

REGISTRY_FILENAME = 'vpt-chrome-ports.json'
LOCK_FILENAME = 'vpt-chrome-ports.lock'
REGISTRY_ENV = 'VPT_CHROME_PORT_REGISTRY'
DEBUG_PORT_ENV = 'VPT_CHROME_DEBUG_PORT'


def _registry_paths(registry_path: Optional[str] = None) -> tuple:
    if registry_path:
        path = os.path.abspath(registry_path)
        return path, path + '.lock'
    base = os.environ.get(REGISTRY_ENV) or tempfile.gettempdir()
    return (
        os.path.join(base, REGISTRY_FILENAME),
        os.path.join(base, LOCK_FILENAME),
    )


def _pid_alive(pid: Any) -> bool:
    """True when a pid is still running on this host."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError as exc:
        # EPERM: the process exists, we are simply not allowed to signal it.
        return exc.errno == errno.EPERM
    except Exception:
        return False
    return True


def is_port_listening(port: int, host: str = '127.0.0.1', timeout: float = 0.25) -> bool:
    """True when something accepts TCP connections on the port.

    A connect, not a bind: a bind probe would take the port a browser is about to
    listen on. A refused connection answers at once, so a free port costs ~1 ms.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class _RegistryLock:
    """flock-guarded access to the registry file.

    Two runs starting at the same time must not pick the same port, so the
    read-modify-write of the registry is serialized. Without flock (Windows) the
    registry is still written atomically, only the race window stays open.
    """

    def __init__(self, lock_path: str):
        self.lock_path = lock_path
        self._handle = None

    def __enter__(self) -> '_RegistryLock':
        try:
            import fcntl
        except ImportError:
            return self
        try:
            self._handle = open(self.lock_path, 'a+')
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)
        except Exception:
            self._handle = None
        return self

    def __exit__(self, *exc_info) -> bool:
        if self._handle is not None:
            try:
                import fcntl
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                self._handle.close()
            except Exception:
                pass
            self._handle = None
        return False


def _read_registry(path: str) -> Dict[str, Any]:
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_registry(path: str, data: Dict[str, Any]) -> None:
    tmp_path = f'{path}.tmp'
    try:
        with open(tmp_path, 'w', encoding='utf-8') as handle:
            json.dump(data, handle)
        os.replace(tmp_path, path)
    except OSError as exc:
        # Loud on purpose: without the registry two runs can pick the same port.
        print(f'[browser_port_allocator] ⚠️ Could not write the port registry {path}: {exc}')
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass


def _prune(registry: Dict[str, Any]) -> Dict[str, Any]:
    """Drop the entries whose owner is gone: a crashed run must not hold a port."""
    alive: Dict[str, Any] = {}
    for key, entry in registry.items():
        if isinstance(entry, dict) and _pid_alive(entry.get('pid')):
            alive[key] = entry
    return alive


def port_owner_pid(port: int, registry_path: Optional[str] = None) -> Optional[int]:
    """The pid of the live run that reserved the port, or None.

    Used by the orphan cleanup: a listener on our port that belongs to a LIVE run
    must not be killed, one that belongs to nobody is a leftover we may reap.
    """
    registry_path, _ = _registry_paths(registry_path)
    with _RegistryLock(_registry_paths(registry_path)[1]):
        registry = _prune(_read_registry(registry_path))
    entry = registry.get(str(port))
    if not entry:
        return None
    try:
        return int(entry.get('pid'))
    except (TypeError, ValueError):
        return None


def reserve_debug_port(port: int, owner_pid: Optional[int] = None,
                       registry_path: Optional[str] = None) -> int:
    """Record the port as owned by a process, without checking whether it is free."""
    registry_path, lock_path = _registry_paths(registry_path)
    pid = owner_pid if owner_pid is not None else os.getpid()
    with _RegistryLock(lock_path):
        registry = _prune(_read_registry(registry_path))
        registry[str(int(port))] = {'pid': int(pid), 'started_at': time.time()}
        _write_registry(registry_path, registry)
    return int(port)


def release_debug_port(port: int, owner_pid: Optional[int] = None,
                       registry_path: Optional[str] = None) -> None:
    """Give the port back. Only the owner may release it."""
    registry_path, lock_path = _registry_paths(registry_path)
    pid = owner_pid if owner_pid is not None else os.getpid()
    with _RegistryLock(lock_path):
        registry = _prune(_read_registry(registry_path))
        entry = registry.get(str(int(port)))
        if entry is None:
            return
        try:
            entry_pid = int(entry.get('pid'))
        except (TypeError, ValueError):
            entry_pid = -1
        if entry_pid not in (pid, os.getpid()):
            return
        registry.pop(str(int(port)), None)
        _write_registry(registry_path, registry)


def allocate_debug_port(
    preferred: int = RESERVED_DEBUG_PORT,
    *,
    base: Optional[int] = None,
    max_scan: int = RUN_DEBUG_PORT_SCAN,
    host: str = '127.0.0.1',
    registry_path: Optional[str] = None,
    owner_pid: Optional[int] = None,
    allow_reserved: bool = True,
) -> int:
    """Reserve a debug port that is free and not owned by another live run.

    `base` restricts the search to [base, base + max_scan): script runs use it to
    stay out of the host service browser's 9222. Without `base` the search starts
    at `preferred`.

    An explicit VPT_CHROME_DEBUG_PORT in the environment wins: the operator
    pinned that port, so we take it (and record it as ours).
    """
    registry_path, lock_path = _registry_paths(registry_path)
    pid = owner_pid if owner_pid is not None else os.getpid()

    explicit = (os.environ.get(DEBUG_PORT_ENV) or '').strip()
    if explicit:
        try:
            port = int(explicit)
        except ValueError:
            port = 0
        if port > 0:
            return reserve_debug_port(port, owner_pid=pid, registry_path=registry_path)

    with _RegistryLock(lock_path):
        registry = _prune(_read_registry(registry_path))
        start = base if base is not None else preferred
        for offset in range(max_scan):
            port = start + offset
            if port > 65535:
                break
            if port == RESERVED_DEBUG_PORT and not allow_reserved:
                continue
            entry = registry.get(str(port))
            if entry and _pid_alive(entry.get('pid')):
                continue
            if is_port_listening(port, host=host):
                continue
            registry[str(port)] = {'pid': int(pid), 'started_at': time.time()}
            _write_registry(registry_path, registry)
            return port

    raise RuntimeError(
        f'No free Chrome debug port found in '
        f'{base if base is not None else preferred}..'
        f'{(base if base is not None else preferred) + max_scan - 1}'
    )


def allocate_run_debug_port(
    base: int = RUN_DEBUG_PORT_BASE,
    *,
    max_scan: int = RUN_DEBUG_PORT_SCAN,
    host: str = '127.0.0.1',
    registry_path: Optional[str] = None,
    owner_pid: Optional[int] = None,
) -> int:
    """Reserve a debug port for a script run (never the host service's 9222)."""
    return allocate_debug_port(
        base,
        base=base,
        max_scan=max_scan,
        host=host,
        registry_path=registry_path,
        owner_pid=owner_pid,
        allow_reserved=False,
    )


def safe_run_id(run_id: str) -> str:
    """The run id as it appears in a profile directory name."""
    return ''.join(ch if ch.isalnum() or ch in '-_' else '_' for ch in str(run_id)) or 'run'


def run_profile_dir_under(run_root: str, run_id: str) -> str:
    """The profile directory of ONE run inside a given per-run profile root.

    The same layout `run_profile_dir` builds, but from the run root itself: the end
    of a run knows the run id and the root, not the base profile directory.
    """
    return os.path.join(os.path.abspath(run_root), safe_run_id(run_id))


def run_profile_dir(base_user_data_dir: str, run_id: str) -> str:
    """The profile directory of ONE run: a sibling of the host's persistent profile.

    Two Chromes can never share a user-data-dir (the second one joins the first
    through its SingletonLock), so every run needs its own directory. It lives
    next to the persistent profile, not inside it, so the host's own browser keeps
    its cookies and its lock file.
    """
    base = os.path.abspath(base_user_data_dir)
    parent = os.path.dirname(base)
    name = os.path.basename(base) or 'user_data'
    run_root = os.path.join(parent, f'{name}_runs')
    return run_profile_dir_under(run_root, run_id)
