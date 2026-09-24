"""
Analytics Database Operations

Reads the six aggregate objects created by setup/db/schema/048_analytics_views.sql
and shapes them into the payload each Monitoring > Analytics tab needs.

Every GROUP BY already happened in Postgres — the Supabase client cannot express one,
and doing it here would mean pulling ~926k rows over the wire (BUG-0074). So each
function below is a `.table(...).select('*')` plus a little reshaping of tens of rows.

Only `script_results` is tenant-scoped, so only the KPI section takes a team_id; the
monitoring tables are global, exactly as the Grafana dashboards read them.
"""

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from shared.src.lib.utils.supabase_utils import get_supabase_client


def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()


def _log(message: str) -> None:
    ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
    print(f"[{ts}] [@db:analytics] {message}")


def _rows(view: str, limit: int = 20000) -> List[Dict[str, Any]]:
    """Read a whole analytics view. These are aggregates — tens to hundreds of rows."""
    result = get_supabase().table(view).select('*').limit(limit).execute()
    return result.data or []


def _tally(rows, key, value_key='count', default=0):
    """Sum `value_key` grouped by `key(row)`, returned as a plain dict."""
    out = defaultdict(lambda: default)
    for r in rows:
        out[key(r)] += r.get(value_key) or 0
    return dict(out)


def _count_by(rows, column: str, unknown: str = 'unknown') -> Dict[str, int]:
    """Count rows per distinct value of `column`."""
    out = defaultdict(int)
    for r in rows:
        out[r.get(column) or unknown] += 1
    return dict(out)


def _top_n(pairs: Dict[str, int], n: int = 10) -> List[Dict[str, Any]]:
    """Largest n as [{name, value}], everything else summed into one 'others' row.

    Ten bars plus a tail is readable at any fleet size; 200 bars is not. The cut is
    made here rather than in the view so the totals elsewhere in the payload still
    account for every row.
    """
    ordered = sorted(pairs.items(), key=lambda kv: kv[1], reverse=True)
    head, tail = ordered[:n], ordered[n:]
    out = [{'name': k, 'value': v} for k, v in head]
    if tail:
        out.append({'name': f'others ({len(tail)})', 'value': sum(v for _, v in tail),
                    'is_others': True})
    return out


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------

def get_device_status() -> Dict[str, Any]:
    """Live up/issue/down per device, plus the counts the Overview tiles show."""
    rows = _rows('analytics_device_status')
    counts = {'up': 0, 'issue': 0, 'down': 0}
    for r in rows:
        counts[r.get('status', 'down')] = counts.get(r.get('status', 'down'), 0) + 1

    return {
        'devices': rows,
        'counts': counts,
        'total': len(rows),
        'by_model': _top_n(_count_by(rows, 'device_model')),
        'by_host': _top_n(_count_by(rows, 'host_name')),
    }


def get_devices_section() -> Dict[str, Any]:
    """The Devices tab: live status plus the availability rollup."""
    status = get_device_status()
    avail = _rows('analytics_device_availability_daily')

    # Worst availability today, worst first — the bars people actually look at.
    days = sorted({r['day'] for r in avail}) if avail else []
    latest_day = days[-1] if days else None
    today = [r for r in avail if r['day'] == latest_day]
    worst = sorted(today, key=lambda r: r.get('availability_percent') or 0)[:10]

    # Fleet availability per day, for the trend.
    per_day = defaultdict(lambda: {'healthy': 0, 'total': 0})
    for r in avail:
        per_day[r['day']]['healthy'] += r.get('healthy_minutes') or 0
        per_day[r['day']]['total'] += r.get('total_minutes') or 0
    timeline = [
        {'day': d,
         'availability_percent': round(100.0 * v['healthy'] / v['total'], 1) if v['total'] else None}
        for d, v in sorted(per_day.items())
    ]

    return {
        **status,
        'availability_worst': [
            {'name': f"{r.get('device_name') or r.get('device_id')}",
             'host': r.get('host_name'),
             'value': float(r.get('availability_percent') or 0)}
            for r in worst
        ],
        'availability_timeline': timeline,
        'availability_day': latest_day,
    }


# ---------------------------------------------------------------------------
# System (hosts / robots)
# ---------------------------------------------------------------------------

def get_system_section() -> Dict[str, Any]:
    """The System tab: per-host resources, plus devices-per-robot folded in.

    Hosts is not its own tab — with one backend server a robots-per-server donut has
    a single slice — so the two host charts that earn their place live here.
    """
    hosts = _rows('analytics_host_status')
    devices = _rows('analytics_device_status')

    reach = {'reporting': 0, 'stale': 0, 'silent': 0}
    for h in hosts:
        key = h.get('reachability', 'silent')
        reach[key] = reach.get(key, 0) + 1

    def metric(col):
        return sorted(
            [{'name': h['host_name'], 'value': float(h.get(col) or 0)} for h in hosts],
            key=lambda d: d['value'], reverse=True,
        )

    return {
        'hosts': hosts,
        'total': len(hosts),
        'reachability': reach,
        'disk': metric('disk_percent'),
        'memory': metric('memory_percent'),
        'cpu': metric('cpu_percent'),
        'uptime_days': metric('uptime_days'),
        'temperature': [
            {'name': h['host_name'], 'value': float(h['cpu_temperature_celsius'])}
            for h in hosts if h.get('cpu_temperature_celsius') is not None
        ],
        'devices_per_host': _top_n(_count_by(devices, 'host_name')),
        'by_server': _count_by(hosts, 'server_name', unknown='unassigned'),
    }


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------

def get_incidents_section(days: int = 30) -> Dict[str, Any]:
    rows = _rows('analytics_incidents_daily')
    recent = sorted({r['day'] for r in rows})[-days:]
    window = [r for r in rows if r['day'] in recent]

    per_day = defaultdict(lambda: defaultdict(int))
    for r in window:
        per_day[r['day']][r.get('severity') or 'unknown'] += r.get('incidents') or 0

    severities = sorted({r.get('severity') or 'unknown' for r in window})
    open_rows = [r for r in rows if r.get('status') in ('open', 'in_progress')]

    durations = [(r.get('avg_duration_minutes'), r.get('resolved') or 0)
                 for r in window if r.get('avg_duration_minutes') is not None]
    weighted = sum((d or 0) * n for d, n in durations)
    resolved_n = sum(n for _, n in durations)

    return {
        'timeline': [
            {'day': d, **{s: per_day[d].get(s, 0) for s in severities}}
            for d in recent
        ],
        'severities': severities,
        'by_severity': _tally(window, lambda r: r.get('severity') or 'unknown', 'incidents'),
        'by_component': _tally(window, lambda r: r.get('component') or 'unknown', 'incidents'),
        'by_device': _top_n(_tally(window, lambda r: r.get('device_name') or 'unknown', 'incidents')),
        'total': sum(r.get('incidents') or 0 for r in window),
        'open': sum(r.get('incidents') or 0 for r in open_rows),
        'mttr_minutes': round(weighted / resolved_n) if resolved_n else None,
    }


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

def get_alerts_section(days: int = 30) -> Dict[str, Any]:
    rows = _rows('analytics_alerts_daily')
    recent = sorted({r['day'] for r in rows})[-days:]
    window = [r for r in rows if r['day'] in recent]

    per_day = defaultdict(lambda: defaultdict(int))
    for r in window:
        per_day[r['day']][r.get('incident_type') or 'unknown'] += r.get('alerts') or 0
    types = sorted({r.get('incident_type') or 'unknown' for r in window})

    return {
        'timeline': [
            {'day': d, **{t: per_day[d].get(t, 0) for t in types}}
            for d in recent
        ],
        'types': types,
        'by_type': _tally(rows, lambda r: r.get('incident_type') or 'unknown', 'alerts'),
        'by_device': _top_n(_tally(rows, lambda r: r.get('device_name') or 'unknown', 'alerts')),
        'total': sum(r.get('alerts') or 0 for r in rows),
        'active': sum(r.get('alerts') or 0 for r in rows if r.get('status') == 'active'),
        'review': {
            'checked': sum(r.get('checked') or 0 for r in rows),
            'discarded': sum(r.get('discarded') or 0 for r in rows),
            'unreviewed': sum((r.get('alerts') or 0) - (r.get('checked') or 0) - (r.get('discarded') or 0)
                              for r in rows),
        },
    }


# ---------------------------------------------------------------------------
# KPI (test execution) — the one tenant-scoped section
# ---------------------------------------------------------------------------

def get_kpi_section(team_id: Optional[str] = None, days: int = 30) -> Dict[str, Any]:
    query = get_supabase().table('analytics_script_runs_daily').select('*')
    if team_id:
        query = query.eq('team_id', team_id)
    rows = query.limit(20000).execute().data or []

    recent = sorted({r['day'] for r in rows})[-days:]
    window = [r for r in rows if r['day'] in recent]

    per_day = defaultdict(lambda: {'passed': 0, 'failed': 0})
    for r in window:
        per_day[r['day']]['passed'] += r.get('passed') or 0
        per_day[r['day']]['failed'] += r.get('failed') or 0

    passed = sum(r.get('passed') or 0 for r in window)
    failed = sum(r.get('failed') or 0 for r in window)
    total = passed + failed

    return {
        'timeline': [{'day': d, **v} for d, v in sorted(per_day.items())],
        'total_runs': total,
        'passed': passed,
        'failed': failed,
        'pass_rate': round(100.0 * passed / total, 1) if total else None,
        'by_script': _top_n(_tally(window, lambda r: r.get('script_name') or 'unknown', 'runs')),
        'by_environment': _tally(window, lambda r: r.get('environment') or 'unknown', 'runs'),
    }


# ---------------------------------------------------------------------------
# Overview — deliberately the cheap one
# ---------------------------------------------------------------------------

def get_overview_section(team_id: Optional[str] = None) -> Dict[str, Any]:
    """Headline tiles plus the three charts on the landing tab.

    MUST NOT read analytics_device_availability_daily. That is the expensive rollup
    and it belongs to the Devices tab alone — the whole point of the tabbed design is
    that opening the page does not pay for it.
    """
    devices = get_device_status()
    hosts = _rows('analytics_host_status')
    incidents = get_incidents_section(days=14)
    alerts = get_alerts_section(days=14)
    kpi = get_kpi_section(team_id=team_id, days=30)

    return {
        'tiles': {
            'hosts_total': len(hosts),
            'hosts_reporting': sum(1 for h in hosts if h.get('reachability') == 'reporting'),
            'devices_total': devices['total'],
            'devices_up': devices['counts'].get('up', 0),
            'devices_issue': devices['counts'].get('issue', 0),
            'devices_down': devices['counts'].get('down', 0),
            'incidents_open': incidents['open'],
            'alerts_active': alerts['active'],
            'pass_rate': kpi['pass_rate'],
        },
        'device_counts': devices['counts'],
        'incidents_timeline': incidents['timeline'],
        'incident_severities': incidents['severities'],
        'kpi_timeline': kpi['timeline'],
        'pass_rate': kpi['pass_rate'],
        'total_runs': kpi['total_runs'],
    }
