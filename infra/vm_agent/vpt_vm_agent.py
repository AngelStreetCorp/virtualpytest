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
"""

import fnmatch
import http.client
import json
import os
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

AGENT_VERSION = '2'
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


# ── HTTP ─────────────────────────────────────────────────────────────────────

ALLOWED_CLIENTS = set(_csv_env('VM_AGENT_ALLOW'))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if ALLOWED_CLIENTS and self.client_address[0] not in ALLOWED_CLIENTS:
            self._reply(403, {'error': 'forbidden'})
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
