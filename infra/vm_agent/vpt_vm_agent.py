#!/usr/bin/env python3
"""VirtualPyTest VM agent — reports one infra VM's health over HTTP.

The infra VMs (database, storage, frontend, proxy, …) run no VirtualPyTest code,
so nothing records their CPU/RAM/disk or whether their services are up. This agent
answers `GET /status` with both; the backend server's infra-status collector
(backend_server/src/lib/server/infra_status_collector.py) pulls it once a minute
and writes vm_metrics + service_status, which the "System Service Status" Grafana
dashboard reads. Pull, not push: the VM holds no credentials.

Standard library only (Debian 12 python3, no pip). Configuration is environment
variables, normally from /etc/default/vpt-vm-agent (see install.sh):

    VM_AGENT_PORT        listen port (default 9110)
    VM_AGENT_BIND        listen address (default 0.0.0.0)
    VM_AGENT_ALLOW       comma-separated client IPs allowed to read /status
                         (empty = any client)
    VM_AGENT_UNITS       comma-separated systemd units to report, e.g. nginx,minio
    VM_AGENT_CONTAINERS  comma-separated docker container names or globs,
                         e.g. supabase_*  (read through /var/run/docker.sock)
    VM_AGENT_DISK_PATH   filesystem whose usage is reported (default /)

Optional action (OFF unless both of these are set — see infra/vm_agent/README.md):

    VM_AGENT_ACTIONS         comma-separated actions to enable; only `db-backup` exists
    VM_AGENT_ACTION_TOKEN    shared secret the caller sends in the X-VM-Agent-Token header
    VM_AGENT_DB_BACKUP_UNIT  the ONE systemd one-shot unit `db-backup` starts
                             (default vpt-db-backup.service); never taken from a request

    POST /actions/db-backup  `systemctl start --no-block <unit>`: systemd runs it outside this agent's
                             sandbox -> 202 {request_id, started_at}
                             (409 while it runs, 429 within 5 min of a successful one)
    GET  /actions/db-backup  {running, started_at, finished_at, exit_code, log_tail} from
                             `systemctl show` + `journalctl -u <unit>`

`GET /status` stays read-only and needs no token.
"""

import fnmatch
import hmac
import http.client
import json
import os
import re
import socket
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

AGENT_VERSION = '4'
CPU_SAMPLE_SECONDS = 15
DOCKER_SOCKET = '/var/run/docker.sock'


def _csv_env(name):
    return [item.strip() for item in os.getenv(name, '').split(',') if item.strip()]


# ── Resources ────────────────────────────────────────────────────────────────

_cpu_percent = None


def _read_cpu_times():
    with open('/proc/stat') as f:
        fields = [int(v) for v in f.readline().split()[1:]]
    idle = fields[3] + (fields[4] if len(fields) > 4 else 0)  # idle + iowait
    return sum(fields), idle


def _sample_cpu_forever():
    """CPU % over the last CPU_SAMPLE_SECONDS, kept fresh in the background."""
    global _cpu_percent
    previous = _read_cpu_times()
    interval = 1  # first value after 1s, so a fresh agent never reports null CPU
    while True:
        time.sleep(interval)
        interval = CPU_SAMPLE_SECONDS
        current = _read_cpu_times()
        total = current[0] - previous[0]
        idle = current[1] - previous[1]
        if total > 0:
            _cpu_percent = round(100.0 * (total - idle) / total, 1)
        previous = current


def _memory():
    info = {}
    with open('/proc/meminfo') as f:
        for line in f:
            key, value = line.split(':', 1)
            info[key] = int(value.split()[0]) * 1024
    total = info['MemTotal']
    used = total - info.get('MemAvailable', info.get('MemFree', 0))
    return {
        'memory_percent': round(100.0 * used / total, 1),
        'memory_used_gb': round(used / 1024 ** 3, 2),
        'memory_total_gb': round(total / 1024 ** 3, 2),
    }


def _disk(path):
    st = os.statvfs(path)
    total = st.f_blocks * st.f_frsize
    used = total - st.f_bfree * st.f_frsize
    # Same basis as `df`: used / (used + available to non-root).
    usable = used + st.f_bavail * st.f_frsize
    return {
        'disk_percent': round(100.0 * used / usable, 1) if usable else None,
        'disk_used_gb': round(used / 1024 ** 3, 2),
        'disk_total_gb': round(total / 1024 ** 3, 2),
    }


def _metrics():
    with open('/proc/uptime') as f:
        uptime = int(float(f.read().split()[0]))
    metrics = {
        'cpu_percent': _cpu_percent,
        'cpu_count': os.cpu_count(),
        'load_average_1m': round(os.getloadavg()[0], 2),
        'uptime_seconds': uptime,
    }
    metrics.update(_memory())
    metrics.update(_disk(os.getenv('VM_AGENT_DISK_PATH', '/')))
    return metrics


# ── Services ─────────────────────────────────────────────────────────────────

def _unit_status(unit):
    try:
        out = subprocess.run(
            ['systemctl', 'show', unit, '-p', 'LoadState', '-p', 'ActiveState', '-p', 'SubState'],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except Exception as e:
        return {'name': unit, 'kind': 'unit', 'status': 'unknown', 'detail': f'systemctl failed: {e}'}
    props = dict(line.split('=', 1) for line in out.splitlines() if '=' in line)
    load, active, sub = props.get('LoadState'), props.get('ActiveState'), props.get('SubState', '')
    if load == 'not-found':
        status = 'unknown'
    elif active == 'active':
        status = 'ok'
    elif active in ('activating', 'reloading', 'deactivating'):
        status = 'degraded'
    elif active == 'failed':
        status = 'down'      # crashed / failed to start
    else:  # inactive
        status = 'stopped'   # not running, switched off
    return {'name': unit, 'kind': 'unit', 'status': status, 'detail': f'{active}/{sub}' if load != 'not-found' else 'not installed'}


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__('localhost', timeout=5)
        self._path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(5)
        self.sock.connect(self._path)


def _container_statuses(patterns):
    try:
        conn = _UnixHTTPConnection(DOCKER_SOCKET)
        conn.request('GET', '/containers/json?all=1')
        containers = json.loads(conn.getresponse().read())
        conn.close()
    except Exception as e:
        return [{'name': p, 'kind': 'container', 'status': 'unknown', 'detail': f'docker unreachable: {e}'} for p in patterns]

    by_name = {}
    for c in containers:
        for name in c.get('Names', []):
            by_name[name.lstrip('/')] = c

    results = []
    for pattern in patterns:
        matched = sorted(n for n in by_name if fnmatch.fnmatchcase(n, pattern))
        if not matched:
            results.append({'name': pattern, 'kind': 'container', 'status': 'down', 'detail': 'no such container'})
            continue
        for name in matched:
            c = by_name[name]
            state, text = c.get('State', ''), c.get('Status', '')
            if state in ('created', 'paused') or (state == 'exited' and text.startswith('Exited (0)')):
                status = 'stopped'   # not running, stopped cleanly
            elif state != 'running':
                status = 'down'      # crashed (non-zero exit), dead or restart-looping
            elif '(unhealthy)' in text or '(health: starting)' in text:
                status = 'degraded'
            else:
                status = 'ok'
            results.append({'name': name, 'kind': 'container', 'status': status, 'detail': text})
    return results


def _services():
    services = [_unit_status(u) for u in _csv_env('VM_AGENT_UNITS')]
    patterns = _csv_env('VM_AGENT_CONTAINERS')
    if patterns:
        services.extend(_container_statuses(patterns))
    return services


# ── Actions (opt-in) ─────────────────────────────────────────────────────────

ACTION_DB_BACKUP = 'db-backup'
ACTION_TOKEN_HEADER = 'X-VM-Agent-Token'
DEFAULT_DB_BACKUP_UNIT = 'vpt-db-backup.service'
DB_BACKUP_COOLDOWN_SECONDS = 300
LOG_TAIL_LINES = 40
SHOW_PROPERTIES = 'ActiveState,SubState,Result,ExecMainStatus,ExecMainStartTimestamp,ExecMainExitTimestamp'
_UNIT_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9:_.@-]{0,99}\.service$')
_RUNNING_STATES = ('activating', 'active', 'reloading')


def actions_enabled():
    """db-backup answers only when it is listed AND a token is configured; otherwise both routes are 404."""
    return ACTION_DB_BACKUP in _csv_env('VM_AGENT_ACTIONS') and bool(os.getenv('VM_AGENT_ACTION_TOKEN', '').strip())


def token_valid(supplied):
    expected = os.getenv('VM_AGENT_ACTION_TOKEN', '').strip()
    return bool(expected) and bool(supplied) and hmac.compare_digest(supplied.encode(), expected.encode())


def _run(argv, timeout=15):
    """-> (returncode, combined output). argv list, never a shell."""
    p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    return p.returncode, (p.stdout or '') + (p.stderr or '')


def _unix(value):
    """systemctl `--timestamp=unix` prints `@1760522400`; empty or `n/a` means it never happened."""
    value = (value or '').strip()
    if value.startswith('@') and value[1:].isdigit() and int(value[1:]) > 0:
        return float(value[1:])
    return None


class SystemdUnitAction:
    """One fixed systemd one-shot unit, started on request OUTSIDE this agent's sandbox.

    The agent runs under ProtectSystem=strict, and a child inherits that: the backup script could not
    write /data/backups. systemd starts the unit from PID 1 instead, with the unit's own (open) settings.
    """

    def __init__(self, unit, cooldown=DB_BACKUP_COOLDOWN_SECONDS, run=_run, clock=time.time):
        if not _UNIT_NAME.match(unit or ''):
            raise ValueError(f'invalid unit name: {unit!r}')
        self._unit, self._cooldown, self._run, self._clock = unit, cooldown, run, clock
        self._lock = threading.Lock()
        self._request_id = None
        self._requested_at = None

    def _show(self):
        rc, out = self._run(['systemctl', 'show', '--timestamp=unix', self._unit, '-p', SHOW_PROPERTIES])
        props = dict(line.split('=', 1) for line in out.splitlines() if '=' in line)
        if rc != 0 or not props:
            raise RuntimeError(f'systemctl show failed: {out.strip()[:200]}')
        return props

    def start(self):
        """-> (http_code, body). The unit comes from the constructor, never from the request."""
        with self._lock:
            try:
                props = self._show()
                state = props.get('ActiveState', '')
                if state in _RUNNING_STATES:
                    return 409, {'error': 'already running', 'request_id': self._request_id,
                                 'started_at': _unix(props.get('ExecMainStartTimestamp')) or self._requested_at}
                now = self._clock()
                ended = _unix(props.get('ExecMainExitTimestamp'))
                if state == 'inactive' and props.get('ExecMainStatus') == '0' and ended and now - ended < self._cooldown:
                    return 429, {'error': 'cooldown', 'retry_after': int(self._cooldown - (now - ended)) + 1}
                rc, out = self._run(['systemctl', 'start', '--no-block', self._unit])
            except Exception as e:
                return 500, {'error': f'cannot start: {type(e).__name__}: {e}'}
            if rc != 0:
                return 500, {'error': f'cannot start: {out.strip()[:200]}'}
            self._request_id, self._requested_at = uuid.uuid4().hex, now
            return 202, {'request_id': self._request_id, 'started_at': now}

    def snapshot(self):
        with self._lock:
            request_id, requested_at = self._request_id, self._requested_at
        try:
            props = self._show()
        except Exception as e:
            return {'request_id': request_id, 'running': False, 'started_at': requested_at, 'finished_at': None,
                    'exit_code': None, 'log_tail': [f'agent: {type(e).__name__}: {e}']}
        state = props.get('ActiveState', '')
        running = state in _RUNNING_STATES
        started = _unix(props.get('ExecMainStartTimestamp'))
        ended = _unix(props.get('ExecMainExitTimestamp'))
        exit_code = None
        if not running and started:
            try:
                exit_code = int(props.get('ExecMainStatus', ''))
            except ValueError:
                exit_code = None
            if state == 'failed' and not exit_code:
                exit_code = -1   # failed without an exit status (killed, timeout): never report success
        argv = ['journalctl', '-u', self._unit, '-n', str(LOG_TAIL_LINES), '--no-pager', '-o', 'cat']
        if started:
            argv += ['--since', f'@{int(started)}']
        try:
            rc, out = self._run(argv)
            tail = out.splitlines()[-LOG_TAIL_LINES:] if rc == 0 else [f'agent: journalctl failed: {out.strip()[:200]}']
        except Exception as e:
            tail = [f'agent: {type(e).__name__}: {e}']
        return {'request_id': request_id, 'running': running, 'started_at': started or requested_at,
                'finished_at': None if running else ended, 'exit_code': exit_code, 'log_tail': tail}


_db_backup = None
_db_backup_lock = threading.Lock()


def db_backup_action():
    global _db_backup
    with _db_backup_lock:
        if _db_backup is None:
            _db_backup = SystemdUnitAction(os.getenv('VM_AGENT_DB_BACKUP_UNIT', '').strip() or DEFAULT_DB_BACKUP_UNIT)
        return _db_backup


# ── HTTP ─────────────────────────────────────────────────────────────────────

ALLOWED_CLIENTS = set(_csv_env('VM_AGENT_ALLOW'))


class Handler(BaseHTTPRequestHandler):
    def _action_gate(self):
        """True when the request may use /actions/db-backup; otherwise the error reply is already sent."""
        if self.path.split('?')[0] != '/actions/' + ACTION_DB_BACKUP or not actions_enabled():
            self._reply(404, {'error': 'not found'})
            return False
        if not token_valid(self.headers.get(ACTION_TOKEN_HEADER, '')):
            self._reply(401, {'error': 'unauthorized'})
            return False
        return True

    def do_POST(self):
        if ALLOWED_CLIENTS and self.client_address[0] not in ALLOWED_CLIENTS:
            self._reply(403, {'error': 'forbidden'})
            return
        if not self._action_gate():
            return
        code, body = db_backup_action().start()   # the request body is never read
        self._reply(code, body)

    def do_GET(self):
        if ALLOWED_CLIENTS and self.client_address[0] not in ALLOWED_CLIENTS:
            self._reply(403, {'error': 'forbidden'})
            return
        if self.path.startswith('/actions/'):
            if self._action_gate():
                self._reply(200, db_backup_action().snapshot())
            return
        if self.path.split('?')[0] != '/status':
            self._reply(404, {'error': 'not found'})
            return
        try:
            body = {
                'agent_version': AGENT_VERSION,
                'hostname': socket.gethostname(),
                'timestamp': time.time(),
                'metrics': _metrics(),
                'services': _services(),
            }
            self._reply(200, body)
        except Exception as e:
            self._reply(500, {'error': str(e)})

    def _reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass  # one poll a minute — journald does not need every request


def main():
    threading.Thread(target=_sample_cpu_forever, daemon=True).start()
    bind = os.getenv('VM_AGENT_BIND', '0.0.0.0')
    port = int(os.getenv('VM_AGENT_PORT', '9110'))
    print(f'[vpt-vm-agent] listening on {bind}:{port}', flush=True)
    ThreadingHTTPServer((bind, port), Handler).serve_forever()


if __name__ == '__main__':
    main()
