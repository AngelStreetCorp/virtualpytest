"""
Report Snapshot Routes (TASK-49) - create / list / revoke a shared snapshot of one test report.

GET    /server/report-snapshots/config
POST   /server/report-snapshots                 {script_result_id, team_id, expires_in, password?, include_video}
GET    /server/report-snapshots?script_result_id=&team_id=
GET    /server/report-snapshots/team?team_id=&status=active|expired|revoked|all
DELETE /server/report-snapshots/<id>?team_id=

The public side (the link itself) lives in server_share_public_routes.py. Design and the leak
list: docs/tasks/TASK-49-report-share-snapshot.md.

Off unless REPORT_SHARING_ENABLED is true. The URL key and the delete key are returned once and
only their SHA-256 is stored.
"""

import hashlib
import os
import secrets
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request
from werkzeug.security import generate_password_hash

from backend_server.src.lib.auth_middleware import principal_holds_permission, require_permission
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from shared.src.lib.database import report_snapshots_db
from shared.src.lib.database.script_results_db import get_script_by_id
from shared.src.lib.utils import report_snapshot_builder

server_report_snapshots_bp = Blueprint(
    'server_report_snapshots', __name__, url_prefix='/server/report-snapshots'
)

EXPIRY_CHOICES = [3600, 86400, 604800, 2592000]
DEFAULT_EXPIRES_IN = 604800
TEAM_QUOTA_BYTES = 5 * 1024 * 1024 * 1024
MAX_PASSWORD_CHARS = 200
MIN_PASSWORD_CHARS = 8
SWEEP_INTERVAL_SECONDS = 15 * 60
SWEEP_BATCH_SIZE = 100
SWEEP_MAX_BATCHES = 10

BUILD_ERROR_STATUS = {'report_gone': 410, 'too_large': 413, 'quota': 413, 'storage_error': 502}
_SECRET_FIELDS = ('key_hash', 'delete_key_hash', 'password_hash')


def _user_uuid():
    """The caller's profile id, or None for a principal that is not a person (the auto-sign
    token's user_id is 'auto_signed', the server public key has none): created_by is a UUID."""
    user_id = getattr(request, 'user_id', None)
    try:
        return str(uuid.UUID(str(user_id))) if user_id else None
    except ValueError:
        return None


def sharing_enabled() -> bool:
    return (os.getenv('REPORT_SHARING_ENABLED') or '').strip().lower() in ('1', 'true', 'yes')


def this_server_name() -> str:
    return (os.getenv('SERVER_NAME') or '').strip()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _team_id_from_request():
    """Same precedence as enforce_team_scope (query string first, then JSON body), so the team
    the middleware checked is the team this route acts on. A GET never reads a body: the list
    route trusts the query string only."""
    team_id = (request.args.get('team_id') or '').strip()
    if team_id or request.method == 'GET':
        return team_id
    data = request.get_json(silent=True) or {}
    value = data.get('team_id')
    return str(value).strip() if value else ''


def _public_row(row: dict) -> dict:
    clean = {k: v for k, v in row.items() if k not in _SECRET_FIELDS}
    clean['has_password'] = bool(row.get('has_password') or row.get('password_hash'))
    return clean


def _disabled_response():
    return jsonify({'error': 'Report sharing is disabled on this server'}), 403


@server_report_snapshots_bp.route('/config', methods=['GET'])
@handle_route_exceptions('report_snapshots:config')
def get_config():
    enabled = sharing_enabled()
    return jsonify({
        'enabled': enabled,
        'can_share': bool(enabled and principal_holds_permission('reports.tests:share')),
        'expiry_choices': EXPIRY_CHOICES,
        'default_expires_in': DEFAULT_EXPIRES_IN,
    })


@server_report_snapshots_bp.route('', methods=['POST'])
@handle_route_exceptions('report_snapshots:create')
def create_snapshot_route():
    if not sharing_enabled():
        return _disabled_response()
    if not principal_holds_permission('reports.tests:share'):
        return jsonify({'error': 'Forbidden', 'message': 'This action requires permission: reports.tests:share'}), 403

    data = request.get_json(silent=True) or {}
    team_id = _team_id_from_request()
    script_result_id = str(data.get('script_result_id') or '').strip()
    if not team_id or not script_result_id:
        return jsonify({'error': 'team_id and script_result_id are required'}), 400

    expires_in = data.get('expires_in')
    if isinstance(expires_in, bool) or expires_in not in EXPIRY_CHOICES:
        return jsonify({'error': f'expires_in must be one of {EXPIRY_CHOICES}'}), 400

    password = data.get('password')
    if password is not None and not isinstance(password, str):
        return jsonify({'error': 'password must be a string'}), 400
    if password and len(password) > MAX_PASSWORD_CHARS:
        return jsonify({'error': f'password is limited to {MAX_PASSWORD_CHARS} characters'}), 400
    if password and len(password) < MIN_PASSWORD_CHARS:
        return jsonify({'error': f'password must be at least {MIN_PASSWORD_CHARS} characters'}), 400
    include_video = bool(data.get('include_video', True))

    server_name = this_server_name()
    if not server_name:
        return jsonify({'error': 'This server has no SERVER_NAME, so it cannot own a snapshot'}), 503

    record = get_script_by_id(script_result_id)
    if not record or str(record.get('team_id') or '') != team_id:
        return jsonify({'error': 'Script result not found'}), 404
    report_path = record.get('html_report_r2_path') or record.get('html_report_r2_url')
    if not report_path:
        return jsonify({'error': 'This run has no stored report to share'}), 410

    snapshot_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=expires_in)
    started = str(record.get('started_at') or record.get('created_at') or '')[:10] or now.date().isoformat()
    banner = (
        f"Snapshot of {record.get('script_name') or 'test report'} ({started}) — "
        f"shared link, expires {expires_at.strftime('%Y-%m-%d %H:%M')} UTC"
    )

    built = report_snapshot_builder.build_snapshot(
        report_path, snapshot_id, include_video, banner, platform_hosts=[request.host],
        quota_left_bytes=TEAM_QUOTA_BYTES - report_snapshots_db.team_live_bytes(team_id),
    )
    if not built.get('success'):
        code = built.get('error_code') or 'storage_error'
        return jsonify({'error': built.get('error') or 'Snapshot failed', 'error_code': code}), \
            BUILD_ERROR_STATUS.get(code, 502)

    size_bytes = int(built.get('size_bytes') or 0)

    key = secrets.token_urlsafe(16)
    delete_key = secrets.token_urlsafe(16)
    password_hash = generate_password_hash(password) if password else None
    row = report_snapshots_db.create_snapshot(
        snapshot_id=snapshot_id,
        team_id=team_id,
        script_result_id=script_result_id,
        server_name=server_name,
        created_by=_user_uuid(),
        key_hash=_sha256(key),
        delete_key_hash=_sha256(delete_key),
        password_hash=password_hash,
        storage_prefix=built['storage_prefix'],
        include_video=include_video,
        size_bytes=size_bytes,
        expires_at=expires_at,
    )
    if not row:
        report_snapshot_builder.purge_snapshot(built['storage_prefix'])
        return jsonify({'error': 'Could not record the snapshot'}), 500

    print(f"[@route:report_snapshots:create] {snapshot_id} team={team_id} result={script_result_id} "
          f"bytes={size_bytes} expires_in={expires_in}")
    return jsonify({
        'id': snapshot_id,
        'path': f'/server/share/{key}/',
        'delete_path': f'/server/share/delete/{delete_key}',
        'expires_at': expires_at.isoformat(),
        'size_bytes': size_bytes,
    }), 201


@server_report_snapshots_bp.route('', methods=['GET'])
@require_permission('reports.tests:view')
@handle_route_exceptions('report_snapshots:list')
def list_snapshots_route():
    team_id = _team_id_from_request()
    script_result_id = (request.args.get('script_result_id') or '').strip()
    if not team_id or not script_result_id:
        return jsonify({'error': 'team_id and script_result_id are required'}), 400
    rows = report_snapshots_db.list_snapshots(team_id, script_result_id, active_only=True) or []
    return jsonify({'snapshots': [_public_row(r) for r in rows]})


def _can_revoke(row: dict) -> bool:
    """Same rule as DELETE: the creator, or manager / admin / service; and not already revoked."""
    if row.get('revoked_at'):
        return False
    user_id = getattr(request, 'user_id', None)
    is_creator = bool(user_id) and str(row.get('created_by') or '') == str(user_id)
    return is_creator or getattr(request, 'user_role', None) in ('manager', 'admin', 'service')


@server_report_snapshots_bp.route('/team', methods=['GET'])
@require_permission('reports.tests:view')
@handle_route_exceptions('report_snapshots:team_list')
def list_team_snapshots_route():
    team_id = _team_id_from_request()
    if not team_id:
        return jsonify({'error': 'team_id is required'}), 400
    status = (request.args.get('status') or 'active').strip().lower()
    if status not in report_snapshots_db.LIST_STATUSES:
        return jsonify({'error': f'status must be one of {list(report_snapshots_db.LIST_STATUSES)}'}), 400
    rows = report_snapshots_db.list_team_snapshots(team_id, status) or []
    scripts = report_snapshots_db.get_script_summaries(team_id, [r.get('script_result_id') for r in rows])
    names = report_snapshots_db.get_profile_names([r.get('created_by') for r in rows])
    out = []
    for r in rows:
        item = _public_row(r)
        script = scripts.get(str(r.get('script_result_id'))) or {}
        item['script_name'] = script.get('script_name')
        item['device_name'] = script.get('device_name')
        item['host_name'] = script.get('host_name')
        item['script_started_at'] = script.get('started_at')
        item['report_url'] = script.get('report_url')
        item['created_by_name'] = (names.get(str(r['created_by'])) or None) if r.get('created_by') else None
        item['can_revoke'] = _can_revoke(r)
        out.append(item)
    return jsonify({'snapshots': out, 'quota': {
        'used_bytes': report_snapshots_db.team_live_bytes(team_id),
        'limit_bytes': TEAM_QUOTA_BYTES,
    }})


def purge_now(row: dict) -> None:
    """Delete the storage objects of a just-revoked row right away, only when this server built
    it (another server's sweeper owns its rows). Failures are logged: the sweeper retries."""
    try:
        if (row.get('server_name') or '') != this_server_name() or not row.get('storage_prefix'):
            return
        if report_snapshot_builder.purge_snapshot(row['storage_prefix']):
            report_snapshots_db.mark_purged(row['id'])
    except Exception as e:
        print(f"[@route:report_snapshots:purge_now] {row.get('id')} failed, sweeper will retry: {e}")


@server_report_snapshots_bp.route('/<snapshot_id>', methods=['DELETE'])
@handle_route_exceptions('report_snapshots:revoke')
def revoke_snapshot_route(snapshot_id):
    team_id = _team_id_from_request()
    if not team_id:
        return jsonify({'error': 'team_id is required'}), 400
    row = report_snapshots_db.get_snapshot(team_id, snapshot_id)
    if not row:
        return jsonify({'error': 'Snapshot not found'}), 404
    user_id = getattr(request, 'user_id', None)
    if not _can_revoke({**row, 'revoked_at': None}):
        return jsonify({'error': 'Forbidden',
                        'message': 'Only the creator, a manager or an admin can revoke this link'}), 403
    if not report_snapshots_db.revoke_snapshot(team_id, snapshot_id):
        return jsonify({'error': 'Snapshot not found'}), 404
    purge_now(row)
    print(f"[@route:report_snapshots:revoke] {snapshot_id} team={team_id} by={user_id}")
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Sweeper: expired or revoked snapshots lose their objects within ~15 minutes.
# ---------------------------------------------------------------------------

_sweeper_lock = threading.Lock()
_sweeper_started = False


def sweep_once() -> int:
    """Purge every expired/revoked snapshot of this server, oldest first. Returns how many were
    purged. Works through the backlog in batches until one comes back short (at most
    SWEEP_MAX_BATCHES per run, so a row that keeps failing cannot spin the thread)."""
    purged = 0
    for _ in range(SWEEP_MAX_BATCHES):
        batch = report_snapshots_db.list_purgeable(this_server_name(), limit=SWEEP_BATCH_SIZE) or []
        for row in batch:
            if not isinstance(row, dict) or not row.get('id') or not row.get('storage_prefix'):
                print(f"[@route:report_snapshots:sweep] skipping malformed row: {str(row)[:200]}")
                continue
            try:
                if report_snapshot_builder.purge_snapshot(row.get('storage_prefix')):
                    if report_snapshots_db.mark_purged(row['id']):
                        purged += 1
            except Exception as e:
                print(f"[@route:report_snapshots:sweep] {row.get('id')} failed: {e}")
        if len(batch) < SWEEP_BATCH_SIZE:
            break
    return purged


def _sweeper_loop():
    while True:
        try:
            count = sweep_once()
            if count:
                print(f"[@route:report_snapshots:sweep] purged {count} snapshot(s)")
        except Exception as e:
            print(f"[@route:report_snapshots:sweep] sweep failed: {e}")
        time.sleep(SWEEP_INTERVAL_SECONDS)


def start_snapshot_sweeper() -> bool:
    """Start the sweeper thread once per process, only when sharing is enabled and the server
    has a SERVER_NAME (it purges only the snapshots it built)."""
    global _sweeper_started
    if not sharing_enabled() or not this_server_name():
        return False
    with _sweeper_lock:
        if _sweeper_started:
            return False
        _sweeper_started = True
    threading.Thread(target=_sweeper_loop, name='report-snapshot-sweeper', daemon=True).start()
    print("[@route:report_snapshots:sweep] sweeper started (every 15 min)")
    return True
