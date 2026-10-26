"""
`api.call` audit emitter (TASK-154). Registered once as an ``after_request`` hook.

Logs mutating calls and denied/failed calls under /server/. The drop-list (what is NOT logged) is
in docs/tasks/TASK-154-comprehensive-audit-trail.md: health/status polls, successful reads,
OPTIONS preflight, static assets and docs. Never raises into the request.
"""

import time
from typing import Optional

from flask import g, request

from shared.src.lib.database import audit_events_db

MUTATING_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})
# Path fragments of polling endpoints that use POST/GET but carry no audit meaning.
NOISE_FRAGMENTS = ('/health', '/status', '/heartbeat', '/poll', '/metrics', '/docs', '/static/',
                   '/getstatus', '/service_status', '/ping', '/system/register')
# Successful GETs that do have audit meaning.
PROMOTED_READ_FRAGMENTS = ('/export', '/download')


def should_audit(method: str, path: str, status_code: int) -> bool:
    if method == 'OPTIONS' or not path.startswith('/server/'):
        return False
    lowered = path.lower()
    denied = status_code in (401, 403)
    if any(fragment in lowered for fragment in NOISE_FRAGMENTS) and not denied:
        return False
    if method in MUTATING_METHODS:
        return True
    if denied or status_code >= 500:
        return True
    return any(fragment in lowered for fragment in PROMOTED_READ_FRAGMENTS)


def _outcome(status_code: int) -> str:
    if status_code in (401, 403):
        return 'denied'
    return 'error' if status_code >= 400 else 'ok'


def _team_id() -> Optional[str]:
    """Team for the row: the one the caller named, only if the auth layer says they belong to it.

    Never queries the database (request thread): ``_vpt_team_ids`` is the set auth_middleware already
    cached on the request. A named team outside that set is written as NULL and counted. When the set
    is unknown (open mode, service keys) the named team is kept if it is a valid UUID (the writer checks).
    """
    ids = getattr(request, '_vpt_team_ids', None)
    named = (request.args.get('team_id') or '').strip() or (request.headers.get('X-Team-ID') or '').strip()
    if named:
        if ids and named not in ids:
            audit_events_db.note_team_rejected()
            return None
        return named
    if ids and len(ids) == 1:
        return next(iter(ids))
    return None


def _call_meta() -> dict:
    """What a call targeted: host, device and command name from a JSON body (never params, which can hold typed text)."""
    meta = {'endpoint': request.endpoint or request.path}
    body = request.get_json(silent=True) if request.is_json else None
    if isinstance(body, dict):
        for key in ('host_name', 'device_id', 'command'):
            if isinstance(body.get(key), str):
                meta[key] = body[key]
        params = body.get('params')
        if isinstance(params, dict) and isinstance(params.get('key'), str):
            meta['key'] = params['key']  # remote key name (HOME, OK...), not free text
    return meta


def emit_api_call(response):
    try:
        status = response.status_code
        if not should_audit(request.method, request.path or '', status):
            return response
        user_id = getattr(request, 'user_id', None)
        started = getattr(g, '_audit_started', None)
        forwarded = (request.headers.get('X-Forwarded-For') or '').split(',')[0].strip()
        audit_events_db.record(
            category='api',
            action='api.call',
            actor_kind=audit_events_db.actor_for(user_id),
            actor_id=user_id,
            actor_email=getattr(request, 'user_email', None),
            actor_role=getattr(request, 'user_role', None),
            team_id=_team_id(),
            target=request.path,
            outcome=_outcome(status),
            method=request.method,
            status_code=status,
            duration_ms=int((time.monotonic() - started) * 1000) if started else None,
            request_id=request.headers.get('X-Request-Id'),
            network=audit_events_db.network_info(forwarded or request.remote_addr,
                                                 request.headers.get('User-Agent')),
            meta=_call_meta(),
        )
    except Exception as exc:  # auditing must never fail a request
        print(f"⚠️ [AuditEmitter] {exc}")
    return response


def init_audit(app) -> None:
    @app.before_request
    def _audit_start():
        g._audit_started = time.monotonic()

    app.after_request(emit_api_call)
