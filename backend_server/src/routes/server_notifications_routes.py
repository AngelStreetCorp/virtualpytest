"""
Notification History Routes (TASK-145 follow-up, contract #43)

GET    /server/notifications?team_id=                  -> {rows, user_id}  (the caller's own, newest first, tombstones included)
POST   /server/notifications  {team_id, items: [...]}  upsert by id (an item that comes back is unread again)
PATCH  /server/notifications  {team_id, id?}           mark one (or all) read
DELETE /server/notifications  {team_id, id?}           dismiss one (or all)

The history belongs to the signed-in user: the user id comes from the verified principal, never from the
request, and every query filters team_id + user_id. Any role may write its own history (the path is in
VIEWER_WRITE_EXEMPT_PREFIXES: it changes nothing shared).
"""
from flask import Blueprint, request, jsonify

from shared.src.lib.database import notifications_db
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions

server_notifications_bp = Blueprint('server_notifications', __name__, url_prefix='/server/notifications')

CATEGORIES = ('device', 'host', 'script', 'capture', 'ai_spend', 'storage', 'deploy', 'security', 'support', 'action')
SEVERITIES = ('error', 'warning', 'info', 'success')
MAX_BATCH = 200


def _body() -> dict:
    return request.get_json(silent=True) or {}


def _team_id() -> str:
    return str(_body().get('team_id') or request.args.get('team_id') or '').strip()


def _user_id() -> str:
    return str(getattr(request, 'user_id', '') or '').strip()


def _bad(msg: str, status: int = 400):
    return jsonify({'success': False, 'error': msg}), status


def _context():
    """(team_id, user_id, error response)"""
    team_id, user_id = _team_id(), _user_id()
    if not team_id:
        return None, None, _bad('team_id is required')
    if not user_id:
        return None, None, _bad('Notification history belongs to a signed-in user', 403)
    return team_id, user_id, None


def _clean(raw: dict):
    """One valid row for the table, or None."""
    nid = str(raw.get('id') or '').strip()
    severity = raw.get('severity')
    message = raw.get('message')
    ts = raw.get('ts')
    if not nid or severity not in SEVERITIES or not isinstance(message, str) or not isinstance(ts, (int, float)):
        return None
    category = raw.get('category') if raw.get('category') in CATEGORIES else 'action'
    return {
        'id': nid[:300],
        'category': category,
        'severity': severity,
        'message': message[:2000],
        'vars': raw.get('vars') if isinstance(raw.get('vars'), dict) else None,
        'to_path': (str(raw['to'])[:500] if raw.get('to') else None),
        'scope': raw.get('scope') if isinstance(raw.get('scope'), dict) else None,
        'ts': int(ts),
        'read': bool(raw.get('read', False)),
        'dismissed': False,
        # TASK-100: optional resolve state. Accept int (epoch ms) or None.
        'resolved_at': raw.get('resolved_at') if isinstance(raw.get('resolved_at'), int) else None,
    }


@server_notifications_bp.route('', methods=['GET'], strict_slashes=False)
@handle_route_exceptions('notifications:list')
def list_notifications():
    team_id, user_id, err = _context()
    if err:
        return err
    rows = notifications_db.list_notifications(team_id, user_id)
    items = [{**{k: v for k, v in r.items() if k != 'to_path'}, 'to': r.get('to_path')} for r in rows]
    return jsonify({'success': True, 'rows': items, 'user_id': user_id})


@server_notifications_bp.route('', methods=['POST'], strict_slashes=False)
@handle_route_exceptions('notifications:upsert')
def upsert_notifications():
    team_id, user_id, err = _context()
    if err:
        return err
    items = _body().get('items')
    if not isinstance(items, list) or len(items) > MAX_BATCH:
        return _bad(f'items must be a list of at most {MAX_BATCH}')
    rows = [r for r in (_clean(i) for i in items if isinstance(i, dict)) if r]
    notifications_db.upsert_notifications(team_id, user_id, rows)
    return jsonify({'success': True, 'saved': len(rows)})


@server_notifications_bp.route('', methods=['PATCH'], strict_slashes=False)
@handle_route_exceptions('notifications:read')
def mark_read():
    team_id, user_id, err = _context()
    if err:
        return err
    notifications_db.mark_read(team_id, user_id, str(_body().get('id') or '').strip() or None)
    return jsonify({'success': True})


@server_notifications_bp.route('', methods=['DELETE'], strict_slashes=False)
@handle_route_exceptions('notifications:dismiss')
def dismiss():
    team_id, user_id, err = _context()
    if err:
        return err
    nid = str(_body().get('id') or request.args.get('id') or '').strip() or None
    notifications_db.dismiss(team_id, user_id, nid)
    return jsonify({'success': True})
