"""Run share snapshots and exports (TASK-42 §4.3 Sharing).

Authenticated (team members, ``share:write``):

    POST   /server/run-share-snapshots              {team_id, run_kind, run_id, ttl_days?}
           -> 201 {snapshot, token}  (the token is returned ONCE; only its hash is stored)
    GET    /server/run-share-snapshots?team_id=&run_kind=&run_id=   snapshots of one run
    DELETE /server/run-share-snapshots/<snapshot_id>?team_id=        revoke
    GET    /server/run-share-snapshots/<snapshot_id>/export?team_id=  CSV of the stored payload
    GET    /server/run-share-snapshots/preview/<kind>/<id>?team_id=[&format=csv]
           the sanitized payload a snapshot of this run would contain (also the
           authenticated CSV export of a run summary)

Token-only (no session; must be exempted from the global /server guard):

    GET /server/share/run/<snapshot_id>[?format=csv]
        token only in the ``X-Share-Token`` header.
        Reads only that stored snapshot: id AND token hash must match, not
        expired, not revoked. Rate limited per peer address (see
        ``services/sharing/rate_limit.py``). Never a query param,
        so the token cannot land in access logs or referrers.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from flask import Blueprint, Response, jsonify, request

from backend_server.src.lib.auth_middleware import require_permission, require_user_auth
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.services.analytics.scope import (
    ScopeError,
    actor_id,
    bounded_int,
    error_json,
    handle_scope_errors,
    is_uuid,
    json_body,
    require_uuid,
    resolve_scope,
    resolve_team_id,
)
from backend_server.src.services.sharing import rate_limit, snapshot
from backend_server.src.services.sharing.csv_export import build_csv
from shared.src.lib.database import run_share_db

server_run_share_bp = Blueprint('server_run_share', __name__)

RUN_KINDS = ('script', 'campaign', 'group')
DEFAULT_TTL_DAYS = 7
MAX_TTL_DAYS = 90

_PUBLIC_HEADERS = {
    'Cache-Control': 'no-store, private',
    'Pragma': 'no-cache',
    'Referrer-Policy': 'no-referrer',
    'X-Robots-Tag': 'noindex, nofollow',
    'X-Content-Type-Options': 'nosniff',
}


def _kind(raw) -> str:
    kind = (raw or '').strip() if isinstance(raw, str) else ''
    if kind not in RUN_KINDS:
        raise ScopeError(f'run_kind must be one of {", ".join(RUN_KINDS)}', 400)
    return kind


def _build_payload(kind: str, run_id: str):
    scope = resolve_scope()
    payload = snapshot.BUILDERS[kind](scope, require_uuid(run_id, 'run_id'))
    if payload is None:
        raise ScopeError('run not found', 404)
    return payload


def _snapshot_in_scope(team_id: str, snapshot_id: str):
    """A team snapshot whose run the caller can still see (registered hosts +
    workspace filter), exactly like listing it; anything else is a 404."""
    row = run_share_db.get_snapshot(team_id, require_uuid(snapshot_id, 'snapshot_id'))
    if not row or row.get('run_kind') not in RUN_KINDS:
        raise ScopeError('snapshot not found', 404)
    try:
        _build_payload(row['run_kind'], str(row.get('run_id')))
    except ScopeError as e:
        if e.status == 404:
            raise ScopeError('snapshot not found', 404)
        raise
    return row


def _csv_response(payload, filename: str, extra_headers=None) -> Response:
    headers = {'Content-Disposition': f'attachment; filename="{filename}"', 'Cache-Control': 'no-store'}
    headers.update(extra_headers or {})
    return Response(build_csv(snapshot.CSV_HEADERS, snapshot.payload_csv_rows(payload)),
                    mimetype='text/csv; charset=utf-8', headers=headers)


@server_run_share_bp.route('/server/run-share-snapshots', methods=['POST'])
@handle_route_exceptions('run_share:create')
@require_user_auth
@require_permission('reports.share:create')
@handle_scope_errors
def create_snapshot():
    body = json_body()
    team_id = resolve_team_id()
    kind = _kind(body.get('run_kind'))
    run_id = require_uuid(body.get('run_id'), 'run_id')
    ttl_days = bounded_int(body.get('ttl_days'), default=DEFAULT_TTL_DAYS, minimum=1,
                           maximum=MAX_TTL_DAYS, name='ttl_days')
    payload = _build_payload(kind, run_id)
    token = secrets.token_urlsafe(32)
    created_at = datetime.now(timezone.utc)
    row = run_share_db.insert_snapshot(
        team_id=team_id, creator_id=actor_id(), run_kind=kind, run_id=run_id, payload=payload,
        token_hash=run_share_db.hash_share_token(token), created_at=created_at,
        expires_at=created_at + timedelta(days=ttl_days),
    )
    response = jsonify({
        'snapshot': {
            'id': row['id'],
            'run_kind': kind,
            'run_id': run_id,
            'created_at': row.get('created_at'),
            'expires_at': row.get('expires_at'),
            'revoked_at': None,
        },
        'token': token,
    })
    response.headers['Cache-Control'] = 'no-store'
    return response, 201


@server_run_share_bp.route('/server/run-share-snapshots', methods=['GET'])
@handle_route_exceptions('run_share:list')
@require_user_auth
@require_permission('reports.share:create')
@handle_scope_errors
def list_snapshots():
    team_id = resolve_team_id()
    kind = _kind(request.args.get('run_kind'))
    run_id = require_uuid(request.args.get('run_id'), 'run_id')
    _build_payload(kind, run_id)  # the run must be visible to the caller
    return jsonify({'items': run_share_db.list_snapshots(team_id, kind, run_id)})


@server_run_share_bp.route('/server/run-share-snapshots/<snapshot_id>', methods=['DELETE'])
@handle_route_exceptions('run_share:revoke')
@require_user_auth
@require_permission('reports.share:create')
@handle_scope_errors
def revoke_snapshot(snapshot_id: str):
    team_id = resolve_team_id()
    row = _snapshot_in_scope(team_id, snapshot_id)
    revoked = run_share_db.revoke_snapshot(team_id, row['id'], actor_id())
    if not revoked:
        return error_json('snapshot not found or already revoked', 404)
    return jsonify({'revoked': True, 'snapshot': revoked})


@server_run_share_bp.route('/server/run-share-snapshots/<snapshot_id>/export', methods=['GET'])
@handle_route_exceptions('run_share:export')
@require_user_auth
@require_permission('reports.share:create')
@handle_scope_errors
def export_snapshot(snapshot_id: str):
    row = _snapshot_in_scope(resolve_team_id(), snapshot_id)
    return _csv_response(row.get('sanitized_payload') or {}, f'run-{row["run_kind"]}-snapshot.csv')


@server_run_share_bp.route('/server/run-share-snapshots/preview/<kind>/<run_id>', methods=['GET'])
@handle_route_exceptions('run_share:preview')
@require_user_auth
@require_permission('reports.share:create')
@handle_scope_errors
def preview_payload(kind: str, run_id: str):
    payload = _build_payload(_kind(kind), run_id)
    if (request.args.get('format') or '').lower() == 'csv':
        return _csv_response(payload, f'run-{kind}.csv')
    return jsonify({'payload': payload})


def _presented_token() -> str:
    return (request.headers.get('X-Share-Token') or '').strip()


def _public(body, status: int = 200) -> Response:
    response = body if isinstance(body, Response) else jsonify(body)
    response.status_code = status
    for key, value in _PUBLIC_HEADERS.items():
        response.headers[key] = value
    return response


@server_run_share_bp.route('/server/share/run/<snapshot_id>', methods=['GET'])
@handle_route_exceptions('run_share:public_read')
def public_read(snapshot_id: str):
    """Token-only snapshot read. Every failure is the same 404 so the response
    does not reveal whether an id exists, expired or was revoked."""
    if not is_uuid(snapshot_id):
        return _public({'error': 'snapshot not found'}, 404)
    if not rate_limit.allow(request.remote_addr or 'unknown', snapshot_id.lower()):
        return _public({'error': 'too many requests'}, 429)
    token = _presented_token()
    if not token or len(token) > 256:
        return _public({'error': 'snapshot not found'}, 404)
    row = run_share_db.read_snapshot_with_token(snapshot_id, token)
    if not row:
        return _public({'error': 'snapshot not found'}, 404)
    payload = row.get('sanitized_payload') or {}
    if (request.args.get('format') or '').lower() == 'csv':
        return _public(_csv_response(payload, f'run-{row.get("run_kind")}.csv'))
    return _public({
        'snapshot': {
            'id': row.get('id'),
            'run_kind': row.get('run_kind'),
            'created_at': row.get('created_at'),
            'expires_at': row.get('expires_at'),
            'payload': payload,
        },
    })
