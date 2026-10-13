"""
Masterchief HTTP surface (TASK-71 Part 7.3).

Four routes under `/server/masterchief/*`. Auth model:

- Browser with user JWT: required for every route. The global guard in app.py
  has set `request.user_role` and `request.user_id` before we get here.
- The service API key (X-API-Key → `role='service'`) is **rejected outright**
  on every masterchief route. This is the structural fix for the
  MCPAPIClient service-key bypass documented in TASK-71-masterchief-design.md
  Part 1.
- Per-op: the op's `required_permission` is checked, and on prod a
  mutating op additionally requires `require_platform_admin`. The dev
  override is `MASTERCHIEF_REQUIRE_PLATFORM_ADMIN=0` (see
  `backend_server.src.lib.masterchief.ops.platform_admin_required`).

Every successful execute writes three audit states (proposed → executing
→ terminal), and every refusal writes a single `refused` row. The audit
table is the only thing masterchief may write.
"""
from __future__ import annotations

import logging
import time
from functools import wraps
from typing import Optional

from flask import Blueprint, jsonify, request

from backend_server.src.lib.auth_middleware import (
    _caller_is_platform_admin,
    require_permission,
    require_platform_admin,
    require_user_auth,
)
from backend_server.src.lib.masterchief import (
    MASTERCHIEF_OPS,
    audit_db,
    list_ops,
    get_op,
    execute_op,
    platform_admin_required,
    OpContext,
)

logger = logging.getLogger(__name__)

server_masterchief_bp = Blueprint('server_masterchief', __name__, url_prefix='/server/masterchief')


# ---------------------------------------------------------------------------
# Gate helpers
# ---------------------------------------------------------------------------

def _bad(message: str, status: int = 400):
    return jsonify({'success': False, 'error': message}), status


def _refuse_service_key(f):
    """Reject `role='service'` outright — masterchief never accepts the
    server API key. The service-key path is the MCPAPIClient path; the
    Atlas-side propose tool is in-process and does not call these routes.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if getattr(request, 'user_role', None) == 'service':
            return _bad(
                'masterchief routes never accept the service API key '
                '(the Atlas-side propose tool is in-process, not an HTTP call)',
                403,
            )
        return f(*args, **kwargs)
    return decorated


def _team_id() -> Optional[str]:
    """Masterchief audit rows are team-scoped. The global guard has already
    verified that `team_id` from the query/body matches the caller's team
    via `enforce_team_scope()`; we trust it here.
    """
    body = request.get_json(silent=True) or {}
    return request.args.get('team_id') or body.get('team_id') or None


def _user_id() -> str:
    return getattr(request, 'user_id', '') or ''


def _user_email() -> str:
    return getattr(request, 'user_email', '') or ''


def _user_role() -> str:
    return getattr(request, 'user_role', '') or 'unknown'


def _session_id() -> Optional[str]:
    return request.headers.get('X-Masterchief-Session') or None


def _audit_state_from_state(state: str) -> str:
    return state


# ---------------------------------------------------------------------------
# Rate limiter (in-memory, per-user, per-op, TTL-based)
# ---------------------------------------------------------------------------
# Restart is the only op with a meaningful rate limit today; reads are
# bounded by the route guards and the underlying service caps. The limiter
# is intentionally cheap (dict of counters) and resets on process restart,
# which is fine for Part 7.

import threading
from collections import deque
from time import monotonic

_RATE_LOCK = threading.Lock()
# (user_id, op) -> deque[timestamp_seconds]
_RATE: dict = {}


def _rate_check_and_record(user_id: str, op: str, *, limit: int, window_s: int) -> bool:
    """Returns True if the call is allowed, False if it tripped the limit."""
    now = monotonic()
    cutoff = now - window_s
    with _RATE_LOCK:
        dq = _RATE.get((user_id, op))
        if dq is None:
            dq = deque()
            _RATE[(user_id, op)] = dq
        # Drop entries older than the window.
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= limit:
            return False
        dq.append(now)
        return True


# Per-op limits (Part 4 design).
_LIMITS = {
    'service.restart': (5, 3600),     # 5 per hour per user
    'logs.view': (30, 60),            # 30 per minute
    'service.status': (60, 60),
    'logs.services': (60, 60),
    'infra.summary': (60, 60),
    'rollout.explain': (60, 60),
    'deploy.status': (60, 60),
}


def _rate_check(op: str) -> bool:
    limit, window = _LIMITS.get(op, (60, 60))
    return _rate_check_and_record(_user_id(), op, limit=limit, window_s=window)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@server_masterchief_bp.route('/ops', methods=['GET'])
@require_user_auth
@_refuse_service_key
@require_permission('settings.logs:view')
def list_masterchief_ops():
    """Catalog of allowed ops. Drives the confirm card on the front end."""
    return jsonify({
        'success': True,
        'ops': [o.to_descriptor() for o in list_ops()],
    }), 200


@server_masterchief_bp.route('/execute', methods=['POST'])
@require_user_auth
@_refuse_service_key
def execute_masterchief_op():
    """Browser-driven execution of a previously proposed op.

    Three audit states written here:
      - existing row was `proposed` (from the in-process propose tool)
      - this route flips it to `executing` before running, then to
        `executed` / `failed` / `refused` after.
    """
    body = request.get_json(silent=True) or {}
    audit_id = (body.get('audit_id') or '').strip()
    if not audit_id:
        return _bad('audit_id is required')
    team_id = _team_id()
    if not team_id:
        return _bad('team_id is required')

    # Re-read the proposal.
    proposal = audit_db.get_audit_row(audit_id, team_id=team_id)
    if not proposal:
        return _bad('proposal not found for this team', 404)
    if proposal.get('state') not in ('proposed',):
        return _bad(
            f'proposal is in state {proposal.get("state")!r}; only proposed rows are executable',
            400,
        )

    op_name = proposal['op']
    op = get_op(op_name)
    if op is None:
        audit_db.update_audit_state(
            audit_id, team_id=team_id, state='refused',
            result_summary=f'unknown op: {op_name!r}',
        )
        return _bad(f'op not in registry: {op_name!r}', 400)

    # Permission gate. require_permission must run *after* require_user_auth
    # (which the global guard has done) — both decorators are stacked below.
    # We do the check here explicitly because the @require_permission below
    # would not see the op's per-op permission.
    from backend_server.src.lib.auth_middleware import principal_holds_permission
    if not principal_holds_permission(op.required_permission):
        audit_db.update_audit_state(
            audit_id, team_id=team_id, state='refused',
            result_summary=f'missing permission: {op.required_permission}',
        )
        return _bad(f'missing permission: {op.required_permission}', 403)

    # Prod-only admin gate.
    if op.platform_admin_only and platform_admin_required():
        if not _caller_is_platform_admin():
            audit_db.update_audit_state(
                audit_id, team_id=team_id, state='refused',
                result_summary='platform-admin required on prod for mutating ops',
            )
            return _bad('platform-admin required for this op on prod', 403)

    # Rate limit.
    if not _rate_check(op_name):
        audit_db.update_audit_state(
            audit_id, team_id=team_id, state='refused',
            result_summary='rate limit exceeded',
        )
        return _bad('rate limit exceeded', 429)

    # Same-user rule: only the proposer may execute (prevents share-link races).
    if proposal.get('requester_user_id') and proposal['requester_user_id'] != _user_id():
        audit_db.update_audit_state(
            audit_id, team_id=team_id, state='refused',
            result_summary='executed by a different user than the proposer',
        )
        return _bad('this proposal was made by a different user', 403)

    # Mark executing and run.
    audit_db.update_audit_state(audit_id, team_id=team_id, state='executing')
    params = proposal.get('params_redacted') or {}
    ctx = OpContext(
        team_id=team_id,
        requester_user_id=_user_id(),
        requester_email=_user_email(),
        requester_role=_user_role(),
        audit_id=audit_id,
        session_id=_session_id(),
        host_name=params.get('host') if isinstance(params, dict) else None,
    )
    t0 = time.monotonic()
    try:
        result = execute_op(op_name, params, ctx)
    except Exception as e:  # noqa: BLE001 — audit row is the error sink
        logger.exception("masterchief executor %s raised in route", op_name)
        result_summary = f'executor raised {type(e).__name__}'
        audit_db.update_audit_state(
            audit_id, team_id=team_id, state='failed',
            result_summary=result_summary,
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
        return _bad(result_summary, 500)
    duration_ms = int((time.monotonic() - t0) * 1000)

    # Decide terminal state. Executors never raise by contract; a non-success
    # summary here means the op itself reported failure.
    summary = (result.summary or '').strip() or 'no summary'
    terminal = 'executed' if not summary.lower().startswith(('failed', 'executor raised')) else 'failed'
    audit_db.update_audit_state(
        audit_id, team_id=team_id, state=terminal,
        result_summary=summary, duration_ms=duration_ms,
    )

    return jsonify({
        'success': True,
        'audit_id': audit_id,
        'op': op_name,
        'state': terminal,
        'result_summary': summary,
        'duration_ms': duration_ms,
        'detail': result.detail,
    }), 200


@server_masterchief_bp.route('/status/<audit_id>', methods=['GET'])
@require_user_auth
@_refuse_service_key
@require_permission('settings.logs:view')
def get_masterchief_status(audit_id: str):
    """Poll the status of an op. Read-only, no rate limit."""
    team_id = _team_id()
    if not team_id:
        return _bad('team_id is required')
    row = audit_db.get_audit_row(audit_id, team_id=team_id)
    if not row:
        return _bad('audit row not found for this team', 404)
    return jsonify({
        'success': True,
        'audit_id': row['id'],
        'op': row['op'],
        'state': row['state'],
        'result_summary': row.get('result_summary'),
        'duration_ms': row.get('duration_ms'),
        'updated_at': row.get('at'),
    }), 200


@server_masterchief_bp.route('/audit', methods=['GET'])
@require_user_auth
@_refuse_service_key
@require_platform_admin
def list_masterchief_audit():
    """Admin read of the audit table. scope=platform is the documented
    exception to the team_id filter (CONTRACTS #29)."""
    team_id = _team_id()
    if not team_id:
        return _bad('team_id is required')
    scope = request.args.get('scope', 'team')
    if scope not in ('team', 'platform'):
        return _bad("scope must be 'team' or 'platform'")
    if scope == 'platform' and not _caller_is_platform_admin():
        return _bad('scope=platform requires platform admin', 403)
    result = audit_db.list_audit_rows(
        team_id=team_id,
        scope=scope,
        state=request.args.get('state'),
        op=request.args.get('op'),
        days=int(request.args.get('days', 30)),
        limit=int(request.args.get('limit', 50)),
        offset=int(request.args.get('offset', 0)),
    )
    return jsonify({'success': True, **result}), 200
