"""Server routes for the match_runs dashboard (TASK-115 / BUG-0569).

Read-only endpoints, all of them.  The match_runs rows are written by
the host (verify path) and the host's button route (localize path); the
server is the read surface for the operator dashboard.

Endpoints
---------
  POST /server/match-runs/recent          — last N match_runs (filterable)
  POST /server/match-runs/transitions     — top transitions (the matrix)
  POST /server/match-runs/uncertain       — the 'matcher said yes but barely' backlog
  POST /server/match-runs/summary         — KPI strip (BUG-0569)
  POST /server/match-runs/per-device      — heatmap axis (BUG-0569)
  POST /server/match-runs/distribution    — verdict stacked-bar timeseries (BUG-0569)
  POST /server/match-runs/sequence        — single device+UI replay (BUG-0569)

The four BUG-0569 endpoints take an optional ``since`` (ISO timestamp,
default now-24h, max now-7d) and the same ``userinterface_name`` /
``device_name`` / ``device_id`` filters as the rest.
"""
from datetime import datetime, timedelta, timezone
from flask import Blueprint, jsonify, request
from typing import Any, Dict, Optional

from backend_server.src.lib.utils.match_runs_rate_limit import get_limiter
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from shared.src.lib.database.match_runs_db import (
    list_recent, transitions, uncertain_hits,
    summary, per_device, verdict_distribution, sequence,
)

server_match_runs_bp = Blueprint('server_match_runs', __name__, url_prefix='/server/match-runs')

# Allowed time windows for the dashboard endpoints.  ``max`` keeps Grafana
# and a heavy poll from accidentally requesting "everything since 2020";
# the operator page picks one of these via the time-window chips.
WINDOW_HOURS = {'1h': 1, '6h': 6, '24h': 24, '7d': 24 * 7}


def _param(payload: Dict[str, Any], key: str) -> Optional[str]:
    return payload.get(key) or request.args.get(key)


def _enforce_rate_limit(team_id: str, endpoint: str) -> Optional[Any]:
    """Per-team rate limit on the dashboard endpoints.

    Returns a 429 response if the team is over budget for the current
    minute, otherwise ``None``.  The counters are exposed by
    ``GET /server/metrics/match-runs`` so the operator can see what
    the dashboard is costing the server.
    """
    if not team_id:
        return None
    allowed, info = get_limiter().check(team_id, endpoint)
    if allowed:
        return None
    retry = max(1, int(info['window_started_at'] + 60 - datetime.now().timestamp()))
    resp = jsonify({
        'success': False,
        'error': f'rate_limited: {info["used"]}/{info["budget"]} per minute on {endpoint}',
        'retry_after_s': retry,
        'endpoint': endpoint,
    })
    resp.status_code = 429
    resp.headers['Retry-After'] = str(retry)
    return resp


def _resolve_since(payload: Dict[str, Any]) -> str:
    """The window-start timestamp for a dashboard request.

    Accepts either a named window from ``WINDOW_HOURS`` or an explicit
    ISO timestamp in ``since``.  Defaults to 24h.  Returns an ISO-8601
    string with timezone so the supabase client does not need a TZ hint.
    """
    explicit = _param(payload, 'since')
    if explicit:
        try:
            ts = datetime.fromisoformat(explicit.replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            if ts < now - timedelta(days=7):
                ts = now - timedelta(days=7)
            return ts.isoformat()
        except Exception:
            pass
    window = (_param(payload, 'window') or '24h').lower()
    hours = WINDOW_HOURS.get(window, 24)
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


@server_match_runs_bp.route('/recent', methods=['POST'])
@handle_route_exceptions('server_match_runs:recent')
def get_recent_match_runs():
    """Last N match_runs for a team, optionally filtered by device / UI."""
    payload = request.get_json(silent=True) or {}
    team_id = _param(payload, 'team_id')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    device_id = _param(payload, 'device_id')
    userinterface_name = _param(payload, 'userinterface_name')
    limit = min(int(_param(payload, 'limit') or 50), 200)
    rows = list_recent(team_id, device_id=device_id,
                       userinterface_name=userinterface_name, limit=limit,
                       host_name=_param(payload, 'host_name'),
                       device_name=_param(payload, 'device_name'),
                       host_only=bool(payload.get('host_only')),
                       include_fingerprint=bool(payload.get('include_fingerprint')))
    return jsonify({'success': True, 'rows': rows, 'count': len(rows)})


@server_match_runs_bp.route('/transitions', methods=['POST'])
@handle_route_exceptions('server_match_runs:transitions')
def get_node_transitions():
    """P(to_node | from_node, userinterface): the prediction matrix."""
    payload = request.get_json(silent=True) or {}
    team_id = _param(payload, 'team_id')
    userinterface_name = _param(payload, 'userinterface_name')
    from_node_id = _param(payload, 'from_node_id')
    if not team_id or not userinterface_name:
        return jsonify({'success': False,
                        'error': 'team_id and userinterface_name are required'}), 400
    rows = transitions(team_id, userinterface_name, from_node_id=from_node_id)
    return jsonify({'success': True, 'rows': rows, 'count': len(rows)})


@server_match_runs_bp.route('/uncertain', methods=['POST'])
@handle_route_exceptions('server_match_runs:uncertain')
def get_uncertain_hits():
    """The 'matcher said yes but barely' backlog — the operator's TODO list."""
    payload = request.get_json(silent=True) or {}
    team_id = _param(payload, 'team_id')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    userinterface_name = _param(payload, 'userinterface_name')
    rows = uncertain_hits(team_id, userinterface_name=userinterface_name)
    return jsonify({'success': True, 'rows': rows, 'count': len(rows)})


# ─── BUG-0569: dashboard panels ──────────────────────────────────────────────


@server_match_runs_bp.route('/summary', methods=['POST'])
@handle_route_exceptions('server_match_runs:summary')
def get_match_runs_summary():
    """KPI strip: total/matched/uncertain/unknown + distinct counters."""
    payload = request.get_json(silent=True) or {}
    team_id = _param(payload, 'team_id')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    blocked = _enforce_rate_limit(team_id, 'summary')
    if blocked is not None:
        return blocked
    since_iso = _resolve_since(payload)
    ui = _param(payload, 'userinterface_name')
    dev = _param(payload, 'device_name')
    row = summary(team_id, since_iso=since_iso, userinterface_name=ui, device_name=dev)
    # Trend baseline: the window of equal length right before this one.
    since_dt = datetime.fromisoformat(since_iso)
    prev_since = since_dt - (datetime.now(timezone.utc) - since_dt)
    previous = summary(team_id, since_iso=prev_since.isoformat(), until_iso=since_iso,
                       userinterface_name=ui, device_name=dev)
    return jsonify({'success': True, 'row': row, 'previous': previous, 'window_started_at': since_iso})


@server_match_runs_bp.route('/per-device', methods=['POST'])
@handle_route_exceptions('server_match_runs:per_device')
def get_match_runs_per_device():
    """Heatmap axis: one row per (host, device) with counts and last_at."""
    payload = request.get_json(silent=True) or {}
    team_id = _param(payload, 'team_id')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    blocked = _enforce_rate_limit(team_id, 'per_device')
    if blocked is not None:
        return blocked
    since_iso = _resolve_since(payload)
    ui = _param(payload, 'userinterface_name')
    rows = per_device(team_id, since_iso=since_iso, userinterface_name=ui)
    return jsonify({'success': True, 'rows': rows, 'count': len(rows),
                    'window_started_at': since_iso})


@server_match_runs_bp.route('/distribution', methods=['POST'])
@handle_route_exceptions('server_match_runs:distribution')
def get_match_runs_distribution():
    """Hourly verdict counts for the stacked-bar panel."""
    payload = request.get_json(silent=True) or {}
    team_id = _param(payload, 'team_id')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    blocked = _enforce_rate_limit(team_id, 'distribution')
    if blocked is not None:
        return blocked
    since_iso = _resolve_since(payload)
    ui = _param(payload, 'userinterface_name')
    rows = verdict_distribution(team_id, since_iso=since_iso, userinterface_name=ui)
    return jsonify({'success': True, 'rows': rows, 'count': len(rows),
                    'window_started_at': since_iso})


@server_match_runs_bp.route('/sequence', methods=['POST'])
@handle_route_exceptions('server_match_runs:sequence')
def get_match_runs_sequence():
    """Last N match_runs for a single (device, UI) — the replay panel."""
    payload = request.get_json(silent=True) or {}
    team_id = _param(payload, 'team_id')
    device_id = _param(payload, 'device_id')
    ui = _param(payload, 'userinterface_name')
    if not team_id or not device_id or not ui:
        return jsonify({'success': False,
                        'error': 'team_id, device_id and userinterface_name are required'}), 400
    blocked = _enforce_rate_limit(team_id, 'sequence')
    if blocked is not None:
        return blocked
    session_id = _param(payload, 'session_id')
    limit = int(_param(payload, 'limit') or 20)
    rows = sequence(team_id, device_id=device_id, userinterface_name=ui,
                    session_id=session_id, limit=limit)
    return jsonify({'success': True, 'rows': rows, 'count': len(rows)})


# ─── BUG-0571: dashboard ops endpoints ───────────────────────────────────────


@server_match_runs_bp.route('/metrics', methods=['GET'])
@handle_route_exceptions('server_match_runs:metrics')
def get_match_runs_metrics():
    """Per-team and fleet-wide request counters for the dashboard.

    Reads the in-process rate limiter snapshot so the operator can see
    "is the dashboard hot" without standing up prometheus_client.  The
    shape is the same dict-of-endpoints; a future Grafana datasource
    can consume it as-is.
    """
    team_id = request.args.get('team_id')
    return jsonify({'success': True, 'metrics': get_limiter().snapshot(team_id=team_id)})
