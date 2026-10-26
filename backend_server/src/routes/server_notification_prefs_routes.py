"""
Notification Preferences Routes (TASK-145, contract #43)

GET    /server/notification-prefs?team_id=   -> {rows, user_id, is_admin}  (shared rows + the caller's own)
PUT    /server/notification-prefs  {team_id, row: {scope_type (user|device|team|workspace|project), scope_id, category, bell, toast, email,
                                                   min_severity, muted_until, locked}}
DELETE /server/notification-prefs  {team_id, scope_type, scope_id, category}  (the row inherits again)

Any signed-in role may write ITS OWN user and device rows (a device row = this user mutes one device), viewer included (the path is in VIEWER_WRITE_EXEMPT_PREFIXES: a
user row changes nothing shared). Team / workspace / project rows and `locked` need the admin role. The user comes
from the verified principal, never from the request. A user cannot write a category an admin locked.
"""
from flask import Blueprint, request, jsonify

from shared.src.lib.database import notification_prefs_db
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions

server_notification_prefs_bp = Blueprint(
    'server_notification_prefs', __name__, url_prefix='/server/notification-prefs'
)

CATEGORIES = ('device', 'host', 'script', 'capture', 'ai_spend', 'storage', 'deploy', 'security', 'support', 'action')
SCOPE_TYPES = ('team', 'workspace', 'project', 'device', 'user')
SEVERITIES = ('info', 'warning', 'error')


def _body() -> dict:
    return request.get_json(silent=True) or {}


def _team_id() -> str:
    return str(_body().get('team_id') or request.args.get('team_id') or '').strip()


def _user_id() -> str:
    return str(getattr(request, 'user_id', '') or '').strip()


def _is_admin() -> bool:
    return getattr(request, 'user_role', None) == 'admin'


def _bad(msg: str, status: int = 400):
    return jsonify({'success': False, 'error': msg}), status


@server_notification_prefs_bp.route('', methods=['GET'], strict_slashes=False)
@handle_route_exceptions('notification_prefs:list')
def list_prefs():
    team_id = _team_id()
    if not team_id:
        return _bad('team_id is required')
    user_id = _user_id()
    if not user_id:
        return _bad('Preferences belong to a signed-in user', 403)
    rows = notification_prefs_db.list_prefs(team_id, user_id)
    return jsonify({'success': True, 'rows': rows, 'user_id': user_id, 'is_admin': _is_admin()})


def _locked_by_admin(rows, category: str) -> bool:
    return any(r.get('category') == category and r.get('locked') and r.get('scope_type') != 'user' for r in rows)


@server_notification_prefs_bp.route('', methods=['PUT'], strict_slashes=False)
@handle_route_exceptions('notification_prefs:upsert')
def upsert_pref():
    team_id = _team_id()
    raw = _body().get('row') or {}
    if not team_id:
        return _bad('team_id is required')
    user_id = _user_id()
    if not user_id:
        return _bad('Preferences belong to a signed-in user', 403)
    scope_type, category = raw.get('scope_type'), raw.get('category')
    if scope_type not in SCOPE_TYPES or category not in CATEGORIES:
        return _bad('scope_type or category is not valid')
    if raw.get('min_severity', 'info') not in SEVERITIES:
        return _bad('min_severity is not valid')
    row = {
        'scope_type': scope_type,
        'category': category,
        'bell': bool(raw.get('bell', True)),
        'toast': bool(raw.get('toast', False)),
        'email': bool(raw.get('email', False)),
        'min_severity': raw.get('min_severity', 'info'),
        'muted_until': raw.get('muted_until') or None,
        'locked': bool(raw.get('locked', False)),
    }
    if scope_type in ('user', 'device'):
        # The caller's own row (a `device` row is "this user + this device"). Nobody locks their own row.
        scope_id = user_id if scope_type == 'user' else str(raw.get('scope_id') or '').strip()
        if not scope_id:
            return _bad('scope_id is required')
        row.update(scope_id=scope_id, user_id=user_id, locked=False)
        if not _is_admin() and _locked_by_admin(notification_prefs_db.list_prefs(team_id, user_id), category):
            return _bad('This category is locked by a team admin', 403)
    else:
        scope_id = str(raw.get('scope_id') or '').strip()
        if not _is_admin():
            return _bad('Only a team admin can change team, workspace or project preferences', 403)
        if not scope_id:
            return _bad('scope_id is required')
        row.update(scope_id=scope_id, user_id='')
    notification_prefs_db.upsert_pref(team_id, row)
    return jsonify({'success': True})


@server_notification_prefs_bp.route('', methods=['DELETE'], strict_slashes=False)
@handle_route_exceptions('notification_prefs:delete')
def delete_pref():
    team_id = _team_id()
    body = _body()
    scope_type, category = body.get('scope_type') or request.args.get('scope_type'), body.get('category') or request.args.get('category')
    scope_id = str(body.get('scope_id') or request.args.get('scope_id') or '').strip()
    if not (team_id and scope_type in SCOPE_TYPES and category in CATEGORIES):
        return _bad('team_id, scope_type and category are required')
    user_id = _user_id()
    if not user_id:
        return _bad('Preferences belong to a signed-in user', 403)
    if scope_type == 'user':
        scope_id, row_user = user_id, user_id
    elif scope_type == 'device':
        if not scope_id:
            return _bad('scope_id is required')
        row_user = user_id
    else:
        if not _is_admin():
            return _bad('Only a team admin can change team, workspace or project preferences', 403)
        if not scope_id:
            return _bad('scope_id is required')
        row_user = ''
    notification_prefs_db.delete_pref(team_id, scope_type, scope_id, row_user, category)
    return jsonify({'success': True})
