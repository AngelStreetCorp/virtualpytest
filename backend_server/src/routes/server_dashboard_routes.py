"""
Dashboard routes (TASK-123): two read-only endpoints feeding the dashboard cards.

  GET /server/dashboard/summary?team_id=&range=24h|7d|30d[&host_filter=[...]]   any authenticated role
  GET /server/dashboard/system                                                  admin only (server-enforced)

Each block degrades to null on its own when its source is missing; nothing here invents data.
Handlers are cached 10 s per team+range so a page of cards costs a handful of queries.
"""

import json
import logging
import os
import shutil
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from flask import Blueprint, jsonify, request

from backend_server.src.lib.auth_middleware import require_role, require_user_auth
from backend_server.src.lib.utils.response_cache import get_cached_response, set_cached_response
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from shared.src.lib.database import dashboard_db
from shared.src.lib.utils.app_utils import get_team_id
from shared.src.lib.utils.disk_space_utils import HOST_DISK_TREND_LOOKAHEAD_HOURS, host_disk_severity

server_dashboard_bp = Blueprint('server_dashboard', __name__, url_prefix='/server/dashboard')
logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 10
RANGES = {'24h': timedelta(hours=24), '7d': timedelta(days=7), '30d': timedelta(days=30)}
_ONE_SHOT_CRON = '0 0 1 1 *'  # queued-run placeholder deployments (max_executions=1)


def get_host_manager():
    from backend_server.src.lib.utils.server_utils import get_host_manager as _get
    return _get()


def get_all_locked_devices() -> Dict[str, Dict[str, Any]]:
    from backend_server.src.lib.utils.lock_utils import get_all_locked_devices as _get
    return _get()


def running_script_tasks(team_id: str) -> List[Dict[str, Any]]:
    from backend_server.src.lib.utils.task_manager import task_manager
    return task_manager.running_tasks('script_execute', team_id)


def _safe(label: str, fn: Callable[[], Any]) -> Any:
    """A missing or unreachable source must give null for its block, never a 500."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        logger.warning('dashboard %s unavailable: %s', label, exc)
        return None


def _parse(ts: Any) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def _is_running_row(row: Dict[str, Any]) -> bool:
    # record_script_execution_start writes completed_at == started_at until the outcome lands.
    return bool(row.get('started_at')) and row.get('started_at') == row.get('completed_at')


def _verdict(row: Dict[str, Any]) -> str:
    if row.get('success'):
        return 'passed'
    return 'aborted' if 'abort' in str(row.get('error_msg') or '').lower() else 'failed'


def _host_scope() -> Optional[set]:
    """Registered hosts, intersected with the active workspace host_filter when given."""
    names = set(get_host_manager().get_all_hosts().keys())
    raw = request.args.get('host_filter')
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                names &= {str(h) for h in parsed if h}
        except (ValueError, TypeError):
            pass
    return names


def _running(team_id: str, hosts: set, in_flight: List[Dict[str, Any]]) -> Dict[str, Any]:
    items: Dict[tuple, Dict[str, Any]] = {}
    queued = 0
    for row in dashboard_db.get_active_executions(team_id):
        dep = row.get('deployments') or {}
        if dep.get('host_name') not in hosts:
            continue
        if row.get('status') == 'queued':
            queued += 1
            continue
        key = (dep.get('host_name'), str(dep.get('device_id')))
        items[key] = {'script_name': dep.get('script_name'), 'device_id': dep.get('device_id'),
                      'host_name': dep.get('host_name'), 'started_at': row.get('started_at'),
                      'result_id': row.get('script_result_id')}
    for task in running_script_tasks(team_id):
        params = task.get('params') or {}
        if params.get('host_name') not in hosts or params.get('queued_deployment_id'):
            continue
        key = (params.get('host_name'), str(params.get('device_id') or ''))
        started = task.get('created_at')
        items.setdefault(key, {
            'script_name': params.get('script_name'), 'device_id': params.get('device_id'),
            'host_name': params.get('host_name'),
            'started_at': _iso(datetime.fromtimestamp(started, timezone.utc)) if started else None,
            'result_id': None})
    for item in items.values():
        if not item['result_id']:
            match = next((r for r in in_flight if r.get('host_name') == item['host_name']
                          and r.get('script_name') == item['script_name']), None)
            item['result_id'] = match.get('id') if match else None
    listed = sorted(items.values(), key=lambda i: i.get('started_at') or '', reverse=True)
    return {'count': len(listed), 'queued': queued, 'items': listed}


def _results(rows: List[Dict[str, Any]], range_key: str, now: datetime) -> Dict[str, Any]:
    hourly = range_key == '24h'
    step = timedelta(hours=1) if hourly else timedelta(days=1)
    start = (now - RANGES[range_key]).astimezone(timezone.utc)
    start = start.replace(minute=0, second=0, microsecond=0) if hourly else \
        start.replace(hour=0, minute=0, second=0, microsecond=0)
    buckets: Dict[datetime, List[int]] = {}
    cursor = start
    while cursor <= now:
        buckets[cursor] = [0, 0]
        cursor += step
    counts = {'passed': 0, 'failed': 0, 'aborted': 0}
    for row in rows:
        counts[_verdict(row)] += 1
        done = _parse(row.get('completed_at'))
        if done:
            key = done.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
            if not hourly:
                key = key.replace(hour=0)
            if key in buckets:
                buckets[key][0] += 1
                buckets[key][1] += 1 if row.get('success') else 0
    return {'total': len(rows), **counts,
            'trend': [{'bucket_start': _iso(k), 'total': v[0], 'passed': v[1]} for k, v in sorted(buckets.items())]}


def _failures(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{'result_id': r.get('id'), 'script_name': r.get('script_name'), 'host_name': r.get('host_name'),
             'device_id': r.get('device_name'), 'reason': r.get('error_msg'), 'finished_at': r.get('completed_at')}
            for r in rows if _verdict(r) == 'failed'][:20]


def _flaky(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    per_script: Dict[str, List[bool]] = defaultdict(list)
    for r in rows:  # newest first
        if len(per_script[r.get('script_name')]) < 10 and _verdict(r) != 'aborted':
            per_script[r.get('script_name')].append(bool(r.get('success')))
    out = [{'script_name': name, 'runs': len(v), 'failed': v.count(False)}
           for name, v in per_script.items() if 0 < v.count(False) < len(v)]
    return sorted(out, key=lambda e: (-e['failed'], -e['runs'], e['script_name'] or ''))[:10]


def _failing(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Scripts with at least one failed run in the range, one row per script (not one per failed run)."""
    per_script: Dict[str, Dict[str, Any]] = {}
    for r in rows:  # newest first
        name = r.get('script_name')
        if not name or _verdict(r) == 'aborted':  # an abort says nothing about the script
            continue
        e = per_script.setdefault(name, {'script_name': name, 'runs': 0, 'failed': 0,
                                         'last_verdict': _verdict(r), 'last_at': r.get('completed_at'),
                                         'last_result_id': r.get('id')})
        e['runs'] += 1
        e['failed'] += 1 if _verdict(r) == 'failed' else 0
    out = [e for e in per_script.values() if e['failed'] > 0]
    return sorted(out, key=lambda e: (-e['failed'], e['script_name']))[:20]


def _deployments(team_id: str, now: datetime) -> Dict[str, Any]:
    items = []
    for dep in dashboard_db.get_active_deployments(team_id):
        if dep.get('cron_expression') == _ONE_SHOT_CRON and dep.get('max_executions') == 1:
            continue  # a queued one-shot run, not a schedule
        starts = sorted(d for d in (_parse((s or {}).get('start')) for s in (dep.get('scheduled_today') or [])
                                    if isinstance(s, dict)) if d and d > now)
        items.append({'name': dep.get('name'), 'next_run_at': _iso(starts[0]) if starts else None,
                      'state': dep.get('status')})
    items.sort(key=lambda i: (i['next_run_at'] is None, i['next_run_at'] or ''))
    return {'active': len(items), 'items': items[:50]}


def _devices(hosts: set) -> Dict[str, Any]:
    all_hosts = get_host_manager().get_all_hosts()
    locks = get_all_locked_devices() or {}
    total = down = 0
    keys = set()
    per_host: Dict[str, Dict[str, Any]] = {}
    down_items = []
    for name in sorted(hosts):
        info = all_hosts.get(name) or {}
        host_down = _host_is_down(info)
        row = per_host.setdefault(name, {'host_name': name, 'total': 0, 'down': 0, 'locked': 0})
        for dev in info.get('devices') or []:
            total += 1
            row['total'] += 1
            keys.add((name, str(dev.get('device_id'))))
            if host_down:
                down += 1
                row['down'] += 1
                down_items.append({'host_name': name, 'device_id': dev.get('device_id'),
                                   'device_name': dev.get('device_name') or dev.get('device_id')})
    locked_items = []
    for lock in locks.values():
        key = (lock.get('host_name'), str(lock.get('device_id')))
        if key not in keys or _host_is_down(all_hosts.get(key[0]) or {}):
            continue
        locked_items.append({'host_name': key[0], 'device_id': lock.get('device_id'),
                             'holder': lock.get('owner_user_name') or lock.get('owner_type'),
                             'since': _iso(datetime.fromtimestamp(lock['locked_at'], timezone.utc))
                             if lock.get('locked_at') else None})
    for item in locked_items:
        per_host[item['host_name']]['locked'] += 1
    locked = len(locked_items)
    return {'total': total, 'free': max(total - down - locked, 0), 'locked': locked, 'down': down,
            'locked_items': locked_items, 'down_items': down_items[:50],
            'hosts': [h for h in per_host.values() if h['total'] > 0]}


def build_summary(team_id: str, range_key: str, hosts: set, now: datetime) -> Dict[str, Any]:
    since = _iso(now - RANGES[range_key])
    rows = _safe('results', lambda: dashboard_db.get_results_since(team_id, since)) 
    rows = [r for r in rows if r.get('host_name') in hosts] if rows is not None else None
    in_flight = [r for r in (rows or []) if _is_running_row(r)]
    done = [r for r in (rows or []) if not _is_running_row(r)]
    recent = _safe('flaky', lambda: dashboard_db.get_recent_results(team_id))
    recent = [r for r in recent if r.get('host_name') in hosts and not _is_running_row(r)] if recent is not None else None
    return {
        'success': True, 'generated_at': _iso(now), 'range': range_key,
        'running': _safe('running', lambda: _running(team_id, hosts, in_flight)),
        'results': _safe('results', lambda: _results(done, range_key, now)) if rows is not None else None,
        'failures': _failures(done) if rows is not None else None,
        'failing': _failing(done) if rows is not None else None,
        'flaky': _flaky(recent) if recent is not None else None,
        'deployments': _safe('deployments', lambda: _deployments(team_id, now)),
        'devices': _safe('devices', lambda: _devices(hosts)),
    }


@server_dashboard_bp.route('/summary', methods=['GET'])
@handle_route_exceptions('dashboard:summary')
@require_user_auth
def dashboard_summary():
    """GET /server/dashboard/summary?team_id=&range=24h|7d|30d"""
    range_key = request.args.get('range', '24h')
    if range_key not in RANGES:
        return jsonify({'success': False, 'error': 'range must be one of 24h, 7d, 30d'}), 400
    team_id = request.args.get('team_id') or get_team_id()
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    hosts = _host_scope()
    cache_key = f"dashboard:summary:{team_id}:{range_key}:{','.join(sorted(hosts))}"
    cached = get_cached_response(cache_key, CACHE_TTL_SECONDS)
    if cached is not None:
        return jsonify(cached), 200
    payload = build_summary(team_id, range_key, hosts, datetime.now(timezone.utc))
    set_cached_response(cache_key, payload)
    return jsonify(payload), 200


def _storage() -> Dict[str, Any]:
    usage = shutil.disk_usage('/')
    inode_pct = None
    st = os.statvfs('/')
    if st.f_files:
        inode_pct = round((st.f_files - st.f_ffree) * 100.0 / st.f_files, 1)
    return {'disk_pct': round(usage.used * 100.0 / usage.total, 1) if usage.total else None, 'inode_pct': inode_pct}


def _host_is_down(info: Dict[str, Any]) -> bool:
    """The Hosts list / Status page rule: a registered host that is not online, or whose heartbeat is older than the
    display threshold (a rebooting host is not 'online' for minutes)."""
    from backend_server.src.routes.server_system_routes import _host_heartbeat_is_stale
    return info.get('status') != 'online' or _host_heartbeat_is_stale(info)


def _disk_trend_detail(name: str, current) -> Optional[str]:
    """'disk 62% filling, full in ~9 h' for a host under the warning line that is filling fast (TASK-156)."""
    if current is None:
        return None
    from shared.src.lib.database.system_metrics_db import get_oldest_disk_sample
    from shared.src.lib.utils.disk_space_utils import HOST_DISK_TREND_WINDOW_HOURS, host_disk_hours_to_full
    old = get_oldest_disk_sample(name, HOST_DISK_TREND_WINDOW_HOURS)
    if not old or old.get('disk_percent') is None or not old.get('timestamp'):
        return None
    elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(str(old['timestamp']).replace('Z', '+00:00'))).total_seconds() / 3600
    eta = host_disk_hours_to_full(float(old['disk_percent']), float(current), elapsed)
    if eta is None or eta > HOST_DISK_TREND_LOOKAHEAD_HOURS:
        return None
    return f"disk {round(current)}% filling, full in ~{max(1, round(eta))} h"


def _monitoring() -> Dict[str, Any]:
    """Hosts registered on THIS server, judged like the Hosts list and /status do. analytics_host_status is a
    database-wide 24 h roster (every server's hosts, retired ones included), so it is used only for the disk figure of
    a registered host, never to decide who is listed or silent."""
    registered = get_host_manager().get_all_hosts()
    disk = {r.get('host_name'): r.get('disk_percent') for r in dashboard_db.get_host_status_rows()}
    problems = []
    ok = 0
    for name, info in sorted(registered.items()):
        if _host_is_down(info):
            problems.append({'host_name': name, 'detail': 'offline'})
        elif host_disk_severity(disk.get(name)):
            problems.append({'host_name': name, 'detail': f"disk {round(disk[name])}% full",
                             'severity': host_disk_severity(disk[name])})
        elif (trend := _disk_trend_detail(name, disk.get(name))):
            problems.append({'host_name': name, 'detail': trend, 'severity': 'warning'})
        else:
            ok += 1
    return {'hosts_total': len(registered), 'hosts_ok': ok, 'problems': problems}


def _ai_budget(team_id: str) -> Optional[Dict[str, Any]]:
    """The budget bucket closest to (or past) its monthly limit, as {share, label}; None without a budget (TASK-145)."""
    from shared.src.lib.ai import budgets
    from shared.src.lib.database import ai_routing_db
    since = budgets.month_start()
    worst = None
    for row in ai_routing_db.list_buckets(team_id):
        bucket_type = row.get('bucket_type') or 'team'
        spend = ai_routing_db.get_bucket_spend(row['team_scope'], bucket_type, row.get('bucket_id') or team_id, since)
        status = budgets.status_from(row, spend)
        if status and (worst is None or status['share'] > worst['share']):
            worst = {'share': status['share'], 'label': status.get('label') or bucket_type}
    return worst


def _ai_waste(team_id: str) -> Optional[Dict[str, Any]]:
    """Last 24 h of AI calls that gave nothing usable (failed, unparseable, cut off: AI_USAGE.md "Wasted tokens"),
    from the same hourly rollup as the AI usage page. {tokens, cost, spend, share_pct, top}; None without calls."""
    from shared.src.lib.ai import usage_view
    from shared.src.lib.database import ai_routing_db
    rows = ai_routing_db.get_calls_rollup(team_id, 24, False, 'hour')
    if not rows:
        return None
    view = usage_view.overview(rows, limit_callers=50)
    total = view['totals']
    if total['cost'] is not None:
        share = (total['cost_wasted'] or 0) / total['cost'] if total['cost'] else 0.0
    else:
        share = total['tokens_wasted'] / total['tokens'] if total['tokens'] else 0.0
    top = sorted(({'source': c['key'], 'tokens': c['tokens_wasted'], 'cost': c['cost_wasted']} for c in view['callers']),
                 key=lambda c: -(c['cost'] or 0) - c['tokens'] * 1e-9)
    return {'tokens': total['tokens_wasted'], 'cost': total['cost_wasted'], 'spend': total['cost'],
            'share_pct': round(share * 100, 1), 'top': [c for c in top if c['tokens'] > 0][:3]}


def _ai_usage(team_id: str) -> Optional[Dict[str, Any]]:
    from shared.src.lib.database import ai_routing_db
    budget = _safe('ai_budget', lambda: _ai_budget(team_id))
    waste = _safe('ai_waste', lambda: _ai_waste(team_id))
    rows = ai_routing_db.get_usage_rows(team_id, 24 * 7)
    if not rows:
        return {'cost_7d': None, 'top_model': None, 'budget': budget, 'waste': waste}
    by_model: Dict[str, float] = defaultdict(float)
    for r in rows:
        by_model[r.get('profile') or 'unknown'] += float(r.get('cost') or 0)
    priced = sum(int(r.get('priced_calls') or 0) for r in rows)
    top = max(by_model.items(), key=lambda kv: kv[1])[0] if priced else None
    return {'cost_7d': round(sum(by_model.values()), 4) if priced else None, 'top_model': top, 'budget': budget, 'waste': waste}


VM_STALE_AFTER = timedelta(minutes=15)  # the collector writes every 5 minutes
VM_LABELS = {'server': 'Server', 'frontend': 'Frontend', 'proxy': 'Proxy', 'database': 'Database', 'storage': 'Storage'}
VM_ORDER = ['server', 'frontend', 'proxy', 'database', 'storage']


def _vm_status(cpu, ram, disk, stamp: Optional[datetime], now: datetime) -> str:
    """ok / warning (>= 80 %) / error (>= 90 %) / stale (no recent report): the Status page thresholds."""
    if stamp is not None and now - stamp > VM_STALE_AFTER:
        return 'stale'
    worst = max([v for v in (cpu, ram, disk) if v is not None] or [0])
    return 'error' if worst >= 90 else 'warning' if worst >= 80 else 'ok'


def _vms(now: datetime) -> List[Dict[str, Any]]:
    """One row per machine, from the same sources as the /status VM summary: the server's own psutil
    numbers plus the latest vm_metrics row of every infra VM."""
    import psutil
    from shared.src.lib.database.infra_status_db import get_latest_vm_metrics

    def num(v):
        return round(float(v), 1) if v is not None else None

    rows = [{'id': 'server', 'name': VM_LABELS['server'], 'cpu': num(psutil.cpu_percent(interval=0.2)),
             'load1': num(os.getloadavg()[0]) if hasattr(os, 'getloadavg') else None,
             'ram': num(psutil.virtual_memory().percent), 'disk': num(psutil.disk_usage('/').percent),
             'status': 'ok', 'checked_at': _iso(now)}]
    rows[0]['status'] = _vm_status(rows[0]['cpu'], rows[0]['ram'], rows[0]['disk'], None, now)
    metrics = get_latest_vm_metrics() or {}
    for vm in sorted((v for v in metrics if v != 'server'), key=lambda v: (VM_ORDER.index(v) if v in VM_ORDER else 99, v)):
        m = metrics[vm]
        stamp = _parse(m.get('timestamp'))
        rows.append({'id': vm, 'name': VM_LABELS.get(vm, vm.replace('_', ' ').title()),
                     'cpu': num(m.get('cpu_percent')), 'load1': num(m.get('load_average_1m')),
                     'ram': num(m.get('memory_percent')), 'disk': num(m.get('disk_percent')),
                     'status': _vm_status(m.get('cpu_percent'), m.get('memory_percent'), m.get('disk_percent'), stamp, now),
                     'checked_at': _iso(stamp)})
    return rows


def _services() -> Optional[Dict[str, int]]:
    """Healthy / total components the collector last recorded for this server (the /status 'Services healthy')."""
    from shared.src.lib.database.infra_status_db import get_current_service_status
    rows = [r for r in get_current_service_status(os.getenv('SERVER_NAME') or 'server')
            if r.get('status') != 'not_installed']
    return {'ok': sum(1 for r in rows if r.get('status') == 'ok'), 'total': len(rows)} if rows else None


@server_dashboard_bp.route('/system', methods=['GET'])
@handle_route_exceptions('dashboard:system')
@require_user_auth
@require_role('admin')
def dashboard_system():
    """GET /server/dashboard/system (admin)"""
    team_id = request.args.get('team_id') or get_team_id()
    cache_key = f'dashboard:system:{team_id}'
    cached = get_cached_response(cache_key, CACHE_TTL_SECONDS)
    if cached is not None:
        return jsonify(cached), 200
    now = datetime.now(timezone.utc)
    vms = _safe('vms', lambda: _vms(now))
    payload = {
        'success': True, 'generated_at': _iso(now),
        'storage': _safe('storage', _storage),
        'vms': vms,
        'services': _safe('services', _services),
        'monitoring': _safe('monitoring', _monitoring),
        'ai_usage': _safe('ai_usage', lambda: _ai_usage(team_id)),
    }
    set_cached_response(cache_key, payload)
    return jsonify(payload), 200
