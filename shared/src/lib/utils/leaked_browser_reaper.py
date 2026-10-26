"""Reclaim the browsers on this host that belong to no live run (BUG-0760 part 1).

A script run takes a debug port and a profile directory, launches a Chrome there, and
gives the slot back when the run ends whether or not that Chrome died. ``leaked_browser_ports()``
finds the ports where that happened. This module is what the rest of the platform does about
it: it kills those browsers and nothing else.

It reclaims the **drivers** too, which hold no port and were therefore invisible to every
port-based count: a Playwright driver is the Node process ``async_playwright().start()``
spawns, and it waits for ever once the browser it drove is gone (BUG-0842).

**It never signals a process group.** Signalling a Chromium's process *group* on
``host-clone-2`` on 2026-10-22 took the host's SSH down with it: reading ``pgid`` off the
target pid does not prove the group holds nothing but that browser, and the signalled group
took the sshd session too. Everything below signals *individual pids*, all positive, matched
from ``/proc`` and re-checked before every signal.

Four conditions must all hold before a single process is signalled:

1. the port is listening and ``port_owner_pid(port)`` is ``None`` — no live run owns it, so
   this is not somebody's browser in progress;
2. the process on that port was launched with ``--remote-debugging-port=<that port>``;
3. its ``--user-data-dir`` sits under the per-run profile root (``user_data_runs/``), which
   only the run allocator creates — never the host's persistent profile, never a browser a
   human opened, never the display browser;
4. the pid is neither this process nor the host service that started us.

Anything that fails a condition is reported and left running.

The driver half asks the same question of the driver instead of the port: a driver holds
the browser it drives through the CDP connection it opened to that browser's debug port,
so a driver whose connection is gone is holding nothing and belongs to no live run. The
driver of a run in progress still holds its browser, and the port registry names the run
that owns that browser, so it is left alone.
"""

import os
import signal
import time
from typing import Any, Dict, List, Optional, Tuple

_REAPER_ENABLED_ENV = 'VPT_REAP_LEAKED_BROWSERS'
_KEEP_BROWSER_OPEN_ENV = 'VPT_KEEP_BROWSER_OPEN'


def reaping_enabled() -> bool:
    """False when the host sets VPT_REAP_LEAKED_BROWSERS to a falsey value.

    Off switch only: the default is to reclaim, because the alternative is the host filling
    with browsers nobody will ever clean. There is no mode that reaps a browser whose run is
    still alive.

    The switch covers the run-scoped teardown too: a run's own browser belongs to no live
    run the moment the run ends, so an operator who sets this is asking for no browser to
    be killed on that host - and the leak this platform used to suffer comes back by the
    operator's own choice. That is the switch's meaning, not a defect.
    """
    return os.environ.get(_REAPER_ENABLED_ENV, '').strip().lower() not in ('0', 'false', 'no', 'off')


def keep_browser_open() -> bool:
    """True when the host sets VPT_KEEP_BROWSER_OPEN to a true-ish value.

    A documented, host-level operator opt-out: leave the browser open when the run ends
    (for debugging, or a sequence that wants the browser warm). A fix must not silently
    remove an operator's explicit capability, so the run-scoped teardown leaves the
    browser alone when this is set - and says so, with the pid.
    """
    return os.environ.get(_KEEP_BROWSER_OPEN_ENV, '').strip().lower() in ('1', 'true', 'yes')


def default_run_profile_root() -> str:
    """Where the run allocator puts per-run profiles: ``<root>/backend_host/config/user_data_runs``.

    Found by walking up to the directory that actually holds ``backend_host/config``, never by
    counting ``dirname`` levels: this module is four levels deep under ``shared/`` and five under
    the project root depending on the tree, and a wrong count silently produced
    ``shared/backend_host/config/user_data_runs`` on the deployed host — a run root that matches no
    real browser, so the guard refused everything and the reaper would never reap a thing.
    """
    marker = os.path.join('backend_host', 'config')
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        here = os.path.dirname(here)
        if os.path.isdir(os.path.join(here, marker)):
            return os.path.join(here, 'backend_host', 'config', 'user_data_runs')
    # Fallback kept honest rather than guessed: this path is only ever compared against a
    # browser's own --user-data-dir, and a wrong one means "reap nothing".
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       '..', '..', '..', '..', 'backend_host', 'config', 'user_data_runs'))


def _argv(pid: int) -> List[str]:
    """The real argv of a process: the NUL-separated entries, not one whitespace blob."""
    try:
        with open(f'/proc/{pid}/cmdline', 'rb') as fh:
            raw = fh.read()
        return [part.decode('utf-8', errors='replace')
                for part in raw.split(b'\0') if part]
    except (OSError, ValueError):
        return []


def _cmdline(pid: int) -> str:
    return ' '.join(_argv(pid))


def _looks_like_a_browser(argv: List[str]) -> bool:
    if not argv:
        return False
    exe = os.path.basename(argv[0])
    return exe in ('chromium', 'chromium-browser', 'chrome', 'google-chrome', 'google-chrome-stable')


def _ppid(pid: int) -> Optional[int]:
    try:
        with open(f'/proc/{pid}/stat', 'rb') as fh:
            # comm (field 2) can contain spaces and parentheses; fields after it are stable.
            tail = fh.read().decode('utf-8', errors='replace').rsplit(')', 1)[-1].split()
        return int(tail[1])
    except (OSError, ValueError, IndexError):
        return None


def _all_pids() -> List[int]:
    return [int(name) for name in os.listdir('/proc') if name.isdigit()]


def browser_pid_for_port(port: int) -> Optional[int]:
    """The pid launched with ``--remote-debugging-port=<port>``, or None.

    Read out of ``/proc``, so this needs no root and no ``ss``.

    The flag must be an actual **argv entry**, not a substring of a command line, and the process
    must look like a browser. Substring matching found the WRONG process on host-clone-2: an
    ``ssh 'python -c "..."'`` wrapper carries the whole script in one argv entry, so its command
    line *contains* ``--remote-debugging-port=9397`` while it is not the browser holding that port.
    The profile guard refused it, which was the right answer for the wrong reason — and had that
    wrapper carried a run-scoped path, the reaper would have signalled somebody's shell.
    """
    needle = f'--remote-debugging-port={port}'
    for pid in _all_pids():
        argv = _argv(pid)
        # an argv ENTRY, never a substring of a command line
        if needle not in argv:
            continue
        if not _looks_like_a_browser(argv):
            continue
        return pid
    return None


def _user_data_dir(pid: int) -> Optional[str]:
    for token in _argv(pid):
        if token.startswith('--user-data-dir='):
            return token.split('=', 1)[1]
    return None


def _remote_debugging_port(pid: int) -> Optional[int]:
    """The debug port this process was launched with, or None."""
    for token in _argv(pid):
        if token.startswith('--remote-debugging-port='):
            try:
                return int(token.split('=', 1)[1])
            except ValueError:
                return None
    return None


def pid_is_running(pid: int) -> bool:
    """True when the pid is a live process.

    A process that died but was not waited for is a zombie: its /proc entry is still
    there, but it is not running any more and must not be reported as alive.
    """
    try:
        with open(f'/proc/{pid}/stat', 'rb') as fh:
            fields = fh.read().decode('utf-8', errors='replace').rsplit(')', 1)[-1].split()
    except OSError:
        return False
    return bool(fields) and fields[0] != 'Z'


def browser_pid_for_profile(profile_dir: str) -> Optional[int]:
    """The browser launched with exactly this ``--user-data-dir``, or None.

    The profile directory is what tells the browser of ONE run from the browser of
    another: the host's persistent service browser lives on the profile next door,
    outside ``user_data_runs/``, and can never be found here.

    The browser process itself is the one that carries ``--remote-debugging-port``;
    its renderers do not, so the browser is preferred over any other process that
    happens to inherit the flag.
    """
    try:
        target = os.path.abspath(profile_dir)
    except (OSError, ValueError):
        return None
    fallback: Optional[int] = None
    for pid in _all_pids():
        argv = _argv(pid)
        if not _looks_like_a_browser(argv):
            continue
        user_data_dir = _user_data_dir(pid)
        if not user_data_dir:
            continue
        try:
            if os.path.abspath(user_data_dir) != target:
                continue
        except (OSError, ValueError):
            continue
        if _remote_debugging_port(pid) is not None:
            return pid
        if fallback is None:
            fallback = pid
    return fallback


def descendants_of(pid: int) -> List[int]:
    """Every descendant of ``pid``, deepest last, found by walking ppid through /proc."""
    children: Dict[int, List[int]] = {}
    for candidate in _all_pids():
        parent = _ppid(candidate)
        if parent is not None:
            children.setdefault(parent, []).append(candidate)

    found: List[int] = []
    stack = list(children.get(pid, []))
    while stack:
        current = stack.pop()
        found.append(current)
        stack.extend(children.get(current, []))
    return found


def _is_run_scoped(user_data_dir: Optional[str], run_root: str) -> bool:
    """True only for a profile under the allocator's per-run root."""
    if not user_data_dir:
        return False
    try:
        return os.path.abspath(user_data_dir).startswith(os.path.abspath(run_root) + os.sep)
    except (OSError, ValueError):
        return False


# ── the driver half: a Playwright driver holds no port, so the port scan is blind to it ──

# Playwright's driver is the Node process `async_playwright().start()` spawns. It exits on
# `playwright.stop()` or when its parent exits, so a run that is killed leaves it behind for
# ever (BUG-0191). A driver that has just started may not have opened its CDP connection
# yet, so a driver younger than this is never taken for an orphan.
DRIVER_MIN_AGE_SECONDS = 60.0


def _is_playwright_driver(argv: List[str]) -> bool:
    """True for Playwright's own driver process.

    Playwright starts it as ``node <...>/playwright/driver/package/cli.js run-driver``. The
    match is on argv ENTRIES, never a substring of a command line: a wrapper that merely
    mentions the path is somebody else's process and must never be signalled.
    """
    if not argv or 'run-driver' not in argv:
        return False
    return any('playwright' in entry for entry in argv)


def _socket_inodes(pid: int) -> set:
    """The socket inodes this process holds open."""
    inodes = set()
    fd_dir = f'/proc/{pid}/fd'
    try:
        entries = os.listdir(fd_dir)
    except OSError:
        return inodes
    for entry in entries:
        try:
            target = os.readlink(os.path.join(fd_dir, entry))
        except OSError:
            continue
        if target.startswith('socket:[') and target.endswith(']'):
            try:
                inodes.add(int(target[len('socket:['):-1]))
            except ValueError:
                continue
    return inodes


def _tcp_sockets() -> List[tuple]:
    """(inode, local_port, remote_port, state) for every TCP socket of this namespace."""
    rows: List[tuple] = []
    for path in ('/proc/net/tcp', '/proc/net/tcp6'):
        try:
            with open(path, 'r') as fh:
                lines = fh.readlines()[1:]
        except OSError:
            continue
        for line in lines:
            parts = line.split()
            if len(parts) < 10:
                continue
            try:
                local_port = int(parts[1].rsplit(':', 1)[1], 16)
                remote_port = int(parts[2].rsplit(':', 1)[1], 16)
                inode = int(parts[9])
            except (IndexError, ValueError):
                continue
            rows.append((inode, local_port, remote_port, parts[3]))
    return rows


def driver_browser_ports(pid: int) -> List[int]:
    """The debug ports this driver is connected to.

    Playwright talks to the browser over CDP, so the driver opens the connection to the
    browser's debug port: the browser it holds is the port it is connected to. When that
    browser is reclaimed the connection goes with it and the driver is left with nothing.
    """
    inodes = _socket_inodes(pid)
    if not inodes:
        return []
    ports: List[int] = []
    for inode, _local, remote, state in _tcp_sockets():
        if inode in inodes and state == '01' and remote and remote not in ports:
            ports.append(remote)
    return ports


def _process_age_seconds(pid: int) -> float:
    """How long this process has been running."""
    try:
        with open(f'/proc/{pid}/stat', 'rb') as fh:
            # comm (field 2) can contain spaces and parentheses; fields after it are stable.
            tail = fh.read().decode('utf-8', errors='replace').rsplit(')', 1)[-1].split()
        start_ticks = int(tail[19])
        with open('/proc/uptime', 'r') as fh:
            uptime = float(fh.read().split()[0])
        return max(0.0, uptime - start_ticks / os.sysconf('SC_CLK_TCK'))
    except (OSError, ValueError, IndexError):
        return 0.0


def orphaned_driver_pids(min_age_seconds: float = DRIVER_MIN_AGE_SECONDS) -> List[Dict[str, Any]]:
    """The Playwright drivers on this host that belong to no live run.

    A driver belongs to a live run while it still holds the browser it drives: the port
    scan's rule, asked of the driver instead of the port. The run that owns that browser is
    the one the port registry names, so a driver of a run in progress is never listed here.
    """
    from shared.src.lib.utils.browser_port_allocator import port_owner_pid

    me = os.getpid()
    parent = _ppid(me)
    orphans: List[Dict[str, Any]] = []
    for pid in _all_pids():
        if pid in (me, parent):
            continue
        if not _is_playwright_driver(_argv(pid)):
            continue
        if _process_age_seconds(pid) < min_age_seconds:
            continue
        ports = driver_browser_ports(pid)
        if ports and any(port_owner_pid(port) is not None for port in ports):
            continue  # a live run owns the browser it holds: this driver is not an orphan
        orphans.append({
            'pid': pid,
            'ports': ports,
            'reason': 'its browser is gone' if not ports
                      else 'no live run owns the browser it held',
        })
    return orphans


def reap_orphaned_drivers(dry_run: bool = False, grace_seconds: float = 5.0,
                          min_age_seconds: float = DRIVER_MIN_AGE_SECONDS) -> Dict[str, Any]:
    """SIGTERM then SIGKILL the drivers that belong to no live run. Never raises.

    Individual positive pids only, exactly like the browser half: a process group took
    host-clone-2's SSH down on 2026-10-22.

    A driver lands in ``reaped`` only if it was really signalled, or if it was already
    gone. A driver the reaper was not allowed to signal lands in ``skipped`` with the
    reason: a driver nobody could touch is not a reclaimed driver, and saying so is the
    one job this reaper has (BUG-0089's shape again, inside the fix for BUG-0842).
    """
    result: Dict[str, Any] = {'reaped': [], 'skipped': [], 'dry_run': bool(dry_run)}
    for orphan in orphaned_driver_pids(min_age_seconds=min_age_seconds):
        pid = orphan['pid']
        if dry_run:
            result['skipped'].append({**orphan, 'reason': 'dry run'})
            continue
        try:
            outcome = reap_browser_tree(pid, '', grace_seconds)
        except Exception as exc:  # noqa: BLE001 - a reap failure must not stop a run
            result['skipped'].append({**orphan, 'reason': f'{type(exc).__name__}: {exc}'})
            print(f"[leaked_browser_reaper] driver {pid}: NOT reaped - {type(exc).__name__}: {exc}")
            continue

        status, reason = _reap_verdict(pid, outcome)
        entry = {**orphan,
                 'signalled': outcome.get('signalled', []),
                 'killed': outcome.get('killed', []),
                 'failed': outcome.get('failed', [])}
        if status == 'signalled':
            result['reaped'].append(entry)
            print(f"[leaked_browser_reaper] driver {pid}: {orphan['reason']}, took down "
                  f"{len(entry['signalled'])} process(es)")
        elif status == 'gone':
            result['reaped'].append({**entry, 'already_gone': True})
            print(f"[leaked_browser_reaper] driver {pid}: {orphan['reason']}, already gone")
        else:
            result['skipped'].append({**entry, 'reason': reason})
            print(f"[leaked_browser_reaper] driver {pid}: NOT reaped - {reason}")
    return result


def _reap_verdict(pid: int, outcome: Dict[str, Any]) -> Tuple[str, str]:
    """What really happened to the tree of ``pid``: (status, reason).

    'signalled' - we took it down. 'gone' - it was already dead, so the goal is met and
    nothing is wrong. 'failed' - we were not allowed to signal it: a real failure the
    operator must see. 'skipped' - nothing was signalled at all (the early return, or a
    tree that was not there).

    The root pid decides. A tree whose root was refused is not reclaimed, whatever else
    happened to its children.
    """
    signalled = outcome.get('signalled') or []
    killed = outcome.get('killed') or []
    gone = outcome.get('gone') or []
    failed = outcome.get('failed') or []

    root_failed = next((item for item in failed if item.get('pid') == pid), None)
    if root_failed is not None:
        return 'failed', f"could not signal {pid}: {root_failed.get('error')}"
    if pid in signalled or pid in killed:
        return 'signalled', ''
    if pid in gone:
        return 'gone', ''
    if failed:
        detail = ', '.join(f"{item.get('pid')}: {item.get('error')}" for item in failed)
        return 'failed', f'could not signal {detail}'
    return 'skipped', outcome.get('skipped') or 'nothing was signalled'


def reap_browser_tree(pid: int, run_root: str, grace_seconds: float = 5.0) -> Dict[str, Any]:
    """SIGTERM then SIGKILL ``pid`` and its descendants, one positive pid at a time.

    The outcome says what really happened, because a caller that cannot tell a signal
    that was refused from one that was never sent will report a reclaim it never did:
    ``signalled`` and ``killed`` are the pids we reached, ``gone`` the ones that were
    already dead (benign - the goal is met) and ``failed`` the ones we were not allowed
    to signal, each with its cause. A PermissionError used to be swallowed as a plain
    OSError, which is how a driver nobody could signal was reported as reclaimed.
    """
    me = os.getpid()
    parent = os.getpid() and _ppid(me)
    if pid in (me, parent):
        return {'pid': pid, 'signalled': [], 'killed': [], 'gone': [], 'failed': [],
                'skipped': 'this process or its parent'}

    # Renderers first, the browser process last: signalling the parent first can leave the
    # children to notice on their own, and a Chromium that outlives one SIGTERM respawns.
    tree = descendants_of(pid) + [pid]
    signalled: List[int] = []
    killed: List[int] = []
    gone: List[int] = []
    failed: List[Dict[str, Any]] = []

    for target in tree:
        try:
            os.kill(target, signal.SIGTERM)
            signalled.append(target)
        except ProcessLookupError:
            gone.append(target)  # ESRCH: already dead, the goal is met
        except PermissionError as exc:
            failed.append({'pid': target, 'error': f'permission denied: {exc}'})
        except OSError as exc:
            failed.append({'pid': target, 'error': f'{type(exc).__name__}: {exc}'})

    deadline = time.time() + max(grace_seconds, 0.0)
    while time.time() < deadline:
        if not any(os.path.exists(f'/proc/{p}') for p in tree):
            break
        time.sleep(0.2)

    for target in tree:
        if os.path.exists(f'/proc/{target}'):
            try:
                os.kill(target, signal.SIGKILL)
                killed.append(target)
            except ProcessLookupError:
                gone.append(target)
            except PermissionError as exc:
                failed.append({'pid': target, 'error': f'permission denied: {exc}'})
            except OSError as exc:
                failed.append({'pid': target, 'error': f'{type(exc).__name__}: {exc}'})

    return {'pid': pid, 'signalled': signalled, 'killed': killed, 'gone': gone,
            'failed': failed, 'skipped': ''}


def reap_run_browser(run_id: str, run_root: Optional[str] = None,
                     grace_seconds: float = 5.0) -> Dict[str, Any]:
    """Take down the browser of ONE run, by that run's own profile directory.

    A run closes its browser over the Playwright controller loop, and a wedged loop is
    exactly why the run went wrong: the close is scheduled on that loop, never runs, and
    the browser outlives the run (BUG-0760). This path does not use the loop at all - it
    finds the browser by the run's own profile directory (``user_data_runs/<run id>``)
    and signals it by pid.

    What it may touch, in the order it is checked:

    - only a profile under the allocator's per-run root, so the host's persistent
      service browser (next door, outside ``user_data_runs/``) is out of reach;
    - only a port no LIVE run owns: a browser a run in progress is driving is left
      alone;
    - individual positive pids only, never a process group.

    Two host switches decide whether the browser dies with the run, and both are honoured:
    ``VPT_KEEP_BROWSER_OPEN`` (the operator asked for the browser to live: it is left open
    and the run says so) and ``VPT_REAP_LEAKED_BROWSERS=0`` (the operator asked for no
    killing on that host at all).

    The outcome says what really happened: ``taken_down`` (we signalled it),
    ``already_gone`` (there was nothing to take down), ``left_open`` (the operator asked
    for it to live) or ``not_reaped`` (we found it and could not signal it, with the
    reason). It never claims a reclaim that did not happen.
    """
    from shared.src.lib.utils.browser_port_allocator import (
        port_owner_pid, run_profile_dir_under,
    )

    run_root = run_root or default_run_profile_root()
    profile_dir = run_profile_dir_under(run_root, run_id)
    result: Dict[str, Any] = {
        'run_id': run_id, 'profile_dir': profile_dir, 'pid': None, 'port': None,
        'status': 'already_gone', 'reason': '', 'signalled': [], 'killed': [], 'failed': [],
    }

    def _refuse(reason: str) -> Dict[str, Any]:
        result['status'] = 'not_reaped'
        result['reason'] = reason
        print(f"[leaked_browser_reaper] run {run_id}: NOT reaped - {reason}")
        return result

    if not reaping_enabled():
        return _refuse(f'reaping is disabled by {_REAPER_ENABLED_ENV}')

    # The profile rule of the periodic sweep, reused: only the allocator's per-run
    # directories are ever in reach.
    if not _is_run_scoped(profile_dir, run_root):
        return _refuse('the run profile is not under the per-run profile root')

    pid = browser_pid_for_profile(profile_dir)
    if pid is None:
        result['reason'] = 'the run has no browser running'
        print(f"[leaked_browser_reaper] run {run_id}: already gone - {result['reason']}")
        return result

    result['pid'] = pid
    port = _remote_debugging_port(pid)
    result['port'] = port

    if keep_browser_open():
        # The operator asked for the browser to live (a host-level opt-out, e.g. for
        # debugging). It is left alone, and the run is told so - with the pid - rather
        # than the teardown quietly skipping it.
        result['status'] = 'left_open'
        result['reason'] = f'{_KEEP_BROWSER_OPEN_ENV} is set'
        print(f"[leaked_browser_reaper] run {run_id}: browser {pid} left open - "
              f"{_KEEP_BROWSER_OPEN_ENV} is set")
        return result

    if port is not None:
        # Re-check ownership at the moment of the kill: a browser a LIVE run is
        # driving belongs to that run, not to this one.
        owner = port_owner_pid(port)
        if owner is not None:
            return _refuse(f'a live run ({owner}) owns this browser now')

    try:
        outcome = reap_browser_tree(pid, run_root, grace_seconds)
    except Exception as exc:  # noqa: BLE001 - a reap failure must not stop a run
        return _refuse(f'{type(exc).__name__}: {exc}')

    result['signalled'] = outcome.get('signalled', [])
    result['killed'] = outcome.get('killed', [])
    result['failed'] = outcome.get('failed', [])

    status, reason = _reap_verdict(pid, outcome)
    if status == 'signalled':
        result['status'] = 'taken_down'
        print(f"[leaked_browser_reaper] run {run_id}: browser {pid} was still running, took it down "
              f"({len(result['signalled'])} process(es) signalled) on {profile_dir}")
    elif status == 'gone':
        result['status'] = 'already_gone'
        print(f"[leaked_browser_reaper] run {run_id}: browser {pid} is already gone")
    else:
        return _refuse(reason)
    return result


def reap_leaked_browsers(dry_run: bool = False, grace_seconds: float = 5.0,
                         run_root: Optional[str] = None) -> Dict[str, Any]:
    """Kill the browsers on this host that no live run owns. Never raises.

    Returns ``{'reaped': [...], 'skipped': [...], 'enabled': bool, 'dry_run': bool}``.
    Each reaped entry names the port, the pid and how many processes it took down; each
    skipped entry says which condition refused it.
    """
    from shared.src.lib.utils.browser_run_slots import (
        invalidate_leak_cache, leaked_browser_ports,
    )
    from shared.src.lib.utils import browser_port_allocator as allocator

    result: Dict[str, Any] = {'reaped': [], 'skipped': [], 'enabled': reaping_enabled(), 'dry_run': bool(dry_run)}
    if not result['enabled']:
        print('[leaked_browser_reaper] disabled by VPT_REAP_LEAKED_BROWSERS; nothing was touched')
        return result

    run_root = run_root or default_run_profile_root()
    for port in leaked_browser_ports():
        # Re-check ownership at the moment of the kill, not just when the port was listed:
        # a run may have taken the port over in between.
        if allocator.port_owner_pid(port) is not None:
            result['skipped'].append({'port': port, 'reason': 'a live run owns this port now'})
            continue

        pid = browser_pid_for_port(port)
        if pid is None:
            result['skipped'].append({'port': port, 'reason': 'no process holds this debug port'})
            continue

        user_data_dir = _user_data_dir(pid)
        if not _is_run_scoped(user_data_dir, run_root):
            result['skipped'].append({
                'port': port, 'pid': pid, 'reason': 'profile is not a per-run profile',
                'user_data_dir': user_data_dir,
            })
            continue

        if dry_run:
            result['skipped'].append({'port': port, 'pid': pid, 'reason': 'dry run'})
            continue

        try:
            outcome = reap_browser_tree(pid, run_root, grace_seconds)
        except Exception as exc:  # noqa: BLE001 - a reap failure must not stop a run
            result['skipped'].append({'port': port, 'pid': pid, 'reason': f'{type(exc).__name__}: {exc}'})
            print(f"[leaked_browser_reaper] port {port}: NOT reaped - {type(exc).__name__}: {exc}")
            continue

        status, reason = _reap_verdict(pid, outcome)
        if status == 'signalled':
            result['reaped'].append({
                'port': port, 'pid': pid, 'signalled': outcome.get('signalled', []),
                'killed': outcome.get('killed', []), 'user_data_dir': user_data_dir,
            })
            print(f"[leaked_browser_reaper] port {port}: run {pid} is gone, took down "
                  f"{len(outcome.get('signalled', []))} process(es) on {user_data_dir}")
        elif status == 'gone':
            result['reaped'].append({
                'port': port, 'pid': pid, 'signalled': outcome.get('signalled', []),
                'killed': outcome.get('killed', []), 'user_data_dir': user_data_dir,
                'already_gone': True,
            })
            print(f"[leaked_browser_reaper] port {port}: run {pid} is already gone")
        else:
            result['skipped'].append({
                'port': port, 'pid': pid, 'reason': reason, 'user_data_dir': user_data_dir,
                'failed': outcome.get('failed', []),
            })
            print(f"[leaked_browser_reaper] port {port}: NOT reaped - {reason}")

    if result['reaped']:
        # The cached sweep would keep counting browsers that no longer exist.
        invalidate_leak_cache()
        print(f"[leaked_browser_reaper] reclaimed {len(result['reaped'])} browser(s) whose run had ended")

    # The driver half: it holds no port, so the sweep above never sees it. A run that ended
    # without stopping its driver leaves it behind for ever (BUG-0842).
    try:
        drivers = reap_orphaned_drivers(dry_run=dry_run, grace_seconds=grace_seconds)
    except Exception as exc:  # noqa: BLE001 - a reap failure must not stop a run
        drivers = {'reaped': [], 'skipped': [{'reason': f'{type(exc).__name__}: {exc}'}]}
    result['reaped_drivers'] = drivers['reaped']
    result['skipped_drivers'] = drivers['skipped']
    if drivers['reaped']:
        print(f"[leaked_browser_reaper] reclaimed orphaned Playwright driver(s): "
              f"{[d.get('pid') for d in drivers['reaped']]}")
    return result