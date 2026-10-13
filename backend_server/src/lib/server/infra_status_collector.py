"""
Infra Status Collector

The /status page probes the platform live from the browser and keeps nothing, so
Grafana had no history of it. This worker thread runs the same checks once a
minute (setup/db/schema/057_infra_status.sql, read by the "System Service Status"
dashboard). To keep the database small it stores:
  - service_status_current: one live row per component, overwritten every minute
    (the dashboard's "now" view and its STALE check)
  - service_status: a change log — a row only when a component's status changes,
    plus a "down / no report" row when reports stopped for a while
  - vm_metrics: VM resources every VM_METRICS_EVERY_MINUTES minutes

Per run it records:
  - the server's own services (same list as /status: _build_server_service_health)
  - Supabase as seen from the server (the write itself is the proof — if the
    server cannot reach the database no row lands and the dashboard shows the
    component as stale/DOWN), Redis, and the DB backup age
  - every infra VM listed in INFRA_VM_AGENTS: the VM agent's resources and
    services (infra/vm_agent/vpt_vm_agent.py). An agent that does not answer is
    recorded as component "agent" = down, i.e. the VM is off or unreachable.

INFRA_VM_AGENTS is a comma-separated list of name=host:port, e.g.
    INFRA_VM_AGENTS=database=192.168.x.102:9110,storage=192.168.x.101:9110
Set it on ONE server per database: every server that has it pulls the agents,
so two would double the vm_metrics rows.
"""

import json
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from shared.src.lib.database.infra_status_db import (
    get_current_service_status,
    insert_service_status_changes,
    store_vm_metrics,
    upsert_current_service_status,
)

AGENT_TIMEOUT_SECONDS = 5
VM_METRICS_EVERY_MINUTES = 5
# Same threshold the dashboard uses for STALE: a gap longer than this between two
# reports is recorded in the change log as down ("no report").
STALE_AFTER = timedelta(minutes=3)
_last_error = {'message': None}


def _log_error_once(message: str):
    """Print a failure once, not every minute, until it changes or recovers."""
    if _last_error['message'] != message:
        print(f"[@backend_server:infra_status] ❌ {message}")
        _last_error['message'] = message


def _row(checked_at, server_name, vm, component, status, detail=''):
    return {
        'checked_at': checked_at,
        'server_name': server_name,
        'vm': vm,
        'component': component,
        'status': status,
        'detail': (detail or '')[:500],
    }


def _server_rows(checked_at, server_name, record_database_facts):
    # Imported here: the route module pulls in Flask blueprints at import time.
    from backend_server.src.routes.server_system_routes import (
        _build_server_service_health,
        get_db_backup_status,
    )

    rows = [_row(checked_at, server_name, 'database', 'supabase', 'ok', f'reachable from {server_name}')]

    for svc in _build_server_service_health()['services']:
        state = svc['status']
        if svc['optional'] and state == 'not_installed':
            continue  # not part of this install (e.g. discard workers in Docker)
        # stopped = not running (switched off); down = failing (crashed, stuck, missing).
        if state == 'active':
            status = 'ok'
        elif state in ('stopped', 'inactive'):
            status = 'stopped'
        elif state in ('error', 'stuck', 'not_installed'):
            status = 'down'
        elif state == 'unknown':
            status = 'unknown'
        else:  # restarting (systemd activating / deactivating / reloading)
            status = 'degraded'
        detail = svc.get('detail') or state
        rows.append(_row(checked_at, server_name, 'server', svc['label'], status, detail))

    try:
        from shared.src.lib.utils.redis_queue import RedisQueueProcessor
        redis_ok = RedisQueueProcessor().health_check()
        rows.append(_row(checked_at, server_name, 'storage', 'redis', 'ok' if redis_ok else 'down',
                         'connected' if redis_ok else 'disconnected'))
    except Exception as e:
        rows.append(_row(checked_at, server_name, 'storage', 'redis', 'unknown', f'check failed: {e}'))

    # The DB backup is a fact about the shared database, reported only to the primary
    # server's backup cron (the /status page asks the primary too). Recording it from
    # every server would show DOWN from each secondary, so only the server that holds
    # INFRA_VM_AGENTS — the one infra collector per database — records it.
    if not record_database_facts:
        return rows
    backup = get_db_backup_status()
    extra = f" ({backup['age_hours']}h ago)" if backup.get('age_hours') is not None else ''
    rows.append(_row(checked_at, server_name, 'storage', 'db-backup',
                     'ok' if backup['status'] == 'ok' else 'down', f"{backup['detail']}{extra}"))
    return rows


def _parse_agents(value: str):
    agents = []
    for item in value.split(','):
        item = item.strip()
        if '=' not in item:
            continue
        name, address = item.split('=', 1)
        agents.append((name.strip(), address.strip()))
    return agents


def _pull_agent(name, address):
    url = f'http://{address}/status'
    try:
        with urllib.request.urlopen(url, timeout=AGENT_TIMEOUT_SECONDS) as response:
            return name, json.loads(response.read()), None
    except Exception as e:
        return name, None, str(e)


def _vm_rows(checked_at, server_name, agents):
    status_rows, metric_rows = [], []
    if not agents:
        return status_rows, metric_rows

    with ThreadPoolExecutor(max_workers=len(agents)) as pool:
        results = list(pool.map(lambda a: _pull_agent(*a), agents))

    for name, payload, error in results:
        if error:
            status_rows.append(_row(checked_at, server_name, name, 'agent', 'down', f'no answer: {error}'))
            continue
        status_rows.append(_row(checked_at, server_name, name, 'agent', 'ok',
                                f"{payload.get('hostname', '?')} · agent v{payload.get('agent_version', '?')}"))
        for svc in payload.get('services', []):
            status_rows.append(_row(checked_at, server_name, name, svc.get('name', '?'),
                                    svc.get('status', 'unknown'), svc.get('detail', '')))
        m = payload.get('metrics', {})
        metric_rows.append({
            'timestamp': checked_at,
            'server_name': server_name,
            'vm': name,
            'hostname': payload.get('hostname'),
            'cpu_percent': m.get('cpu_percent'),
            'memory_percent': m.get('memory_percent'),
            'memory_used_gb': m.get('memory_used_gb'),
            'memory_total_gb': m.get('memory_total_gb'),
            'disk_percent': m.get('disk_percent'),
            'disk_used_gb': m.get('disk_used_gb'),
            'disk_total_gb': m.get('disk_total_gb'),
            'load_average_1m': m.get('load_average_1m'),
            'cpu_count': m.get('cpu_count'),
            'uptime_seconds': m.get('uptime_seconds'),
        })
    return status_rows, metric_rows


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def _changes_and_current(now: datetime, server_name: str, rows):
    """Compare this run with the live rows: change-log rows + the new live rows."""
    previous = {(r['vm'], r['component']): r for r in get_current_service_status(server_name)}
    changes, current = [], []
    for row in rows:
        before = previous.get((row['vm'], row['component']))
        since = row['checked_at']
        if before is None:
            changes.append(row)
        else:
            last_report = _parse_ts(before['checked_at'])
            gap = now - last_report > STALE_AFTER
            if gap:
                changes.append(_row((last_report + timedelta(minutes=1)).isoformat(), server_name,
                                    row['vm'], row['component'], 'down', 'no report'))
            if gap or before['status'] != row['status']:
                changes.append(row)
            else:
                since = before['since']
        current.append({**row, 'since': since})
    return changes, current


def collect_infra_status_once():
    now = datetime.now(timezone.utc)
    checked_at = now.isoformat()
    server_name = os.getenv('SERVER_NAME') or 'server'
    agents = _parse_agents(os.getenv('INFRA_VM_AGENTS', ''))

    status_rows = _server_rows(checked_at, server_name, record_database_facts=bool(agents))
    vm_status_rows, metric_rows = _vm_rows(checked_at, server_name, agents)
    status_rows.extend(vm_status_rows)

    changes, current = _changes_and_current(now, server_name, status_rows)
    if not insert_service_status_changes(changes):
        raise RuntimeError('service_status insert stored nothing')
    if not upsert_current_service_status(current):
        raise RuntimeError('service_status_current upsert stored nothing')
    if now.minute % VM_METRICS_EVERY_MINUTES != 0:
        metric_rows = []
    if not store_vm_metrics(metric_rows):
        raise RuntimeError('vm_metrics insert stored nothing')
    return len(changes), len(metric_rows)


def collect_infra_status_forever():
    """Worker thread: one run per minute, offset from the system_metrics thread."""
    time.sleep(30)
    print(f"[@backend_server:infra_status] 📡 Collector started (VM agents: {os.getenv('INFRA_VM_AGENTS') or 'none'})")
    while True:
        try:
            statuses, metrics = collect_infra_status_once()
            if _last_error['message'] is not None:
                print(f"[@backend_server:infra_status] ✅ recovered ({statuses} status changes, {metrics} VM rows)")
                _last_error['message'] = None
        except Exception as e:
            _log_error_once(f'collection failed: {e}')
        now = time.time()
        time.sleep(((int(now / 60) + 1) * 60 + 30) - now)
