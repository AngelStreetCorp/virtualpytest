"""Masterchief op registry.

TASK-71 Part 7.2. The op set is the *single source of truth* for what
masterchief is allowed to do. An op not in `MASTERCHIEF_OPS` is refused at
every entry point (route, propose tool, executor dispatch). Add an op here
and it becomes available; remove it and the audit table still holds the
historical record.

Each entry is a `MasterchiefOp` with:
  - op name (e.g. 'logs.view')
  - summary (shown in the confirm card)
  - mutates (True for ops that change host state)
  - required_permission (settings.logs:view / system.services:restart / ...)
  - platform_admin_only (True for mutating ops on prod)
  - params_schema (JSON Schema draft-07 subset, used to render the form)
  - blast_radius (one-line risk statement shown in the card)
  - executor (callable, returns `OpResult`)

The executors below are functional for the read-only ops and `service.restart`
(via call_host to the existing /host/system/* routes), and explicitly stubbed
for `infra.summary` / `rollout.explain` / `deploy.status` where the underlying
data lives outside the platform (proxmox, GH, etc.). Stubs return a clear
"not yet wired" state that is itself audited.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from shared.src.lib.utils.build_url_utils import call_host

if TYPE_CHECKING:
    # Avoid a runtime import cycle with the routes module.
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass
class OpContext:
    """Everything an executor needs that isn't the params dict.

    The route layer fills this in once the user has been permission-checked.
    Executors must not re-check permissions.
    """
    team_id: str
    requester_user_id: str
    requester_email: str
    requester_role: str
    audit_id: str
    session_id: Optional[str] = None
    trace_id: Optional[str] = None
    host_name: Optional[str] = None  # set by the route when the op targets a host
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OpResult:
    """What an executor returns. Everything is a plain string/dict; the route
    layer wraps this in the JSON response. The route also re-redacts the
    result_summary before writing it to the audit table, so executors do not
    need to re-redact (and shouldn't echo raw command output)."""
    summary: str
    detail: Optional[Dict[str, Any]] = None
    # If set, the route returns 202 with a poll URL and the op keeps running in
    # a background thread. The background thread is responsible for writing
    # the terminal state to masterchief_audit itself (state=executed|failed).
    async_poll: bool = False


class MasterchiefOp:
    """One op. Not a dataclass because we want a clean `op` accessor and
    callable executor dispatch."""

    __slots__ = ('op', 'summary', 'mutates', 'required_permission',
                 'platform_admin_only', 'params_schema', 'blast_radius',
                 'executor')

    def __init__(self, *, op: str, summary: str, mutates: bool,
                 required_permission: str, platform_admin_only: bool,
                 params_schema: Dict[str, Any], blast_radius: str,
                 executor: Callable[[Dict[str, Any], OpContext], OpResult]):
        self.op = op
        self.summary = summary
        self.mutates = mutates
        self.required_permission = required_permission
        self.platform_admin_only = platform_admin_only
        self.params_schema = params_schema
        self.blast_radius = blast_radius
        self.executor = executor

    def to_descriptor(self) -> Dict[str, Any]:
        return {
            'op': self.op,
            'summary': self.summary,
            'mutates': self.mutates,
            'required_permission': self.required_permission,
            'platform_admin_only': self.platform_admin_only,
            'params_schema': self.params_schema,
            'blast_radius': self.blast_radius,
        }


# ---------------------------------------------------------------------------
# Executors
# ---------------------------------------------------------------------------

# Whitelist copied from backend_server/src/routes/logs_routes.py:16-32.
# Kept in sync by review (test 7.6 asserts the two lists match).
ALLOWED_SERVICES = [
    'vpt-server', 'vpt-server-host', 'vpt-host', 'vpt-frontend',
    'vpt-heatmap', 'vpt-discard-scripts', 'vpt-discard-incidents',
    'vpt-stream', 'vpt-monitor', 'vpt-archiver', 'vpt-kpi',
    'vpt-transcript', 'vpt-subtitle', 'vpt-vnc', 'vpt-websockify',
    'vpt-emulator', 'vpt-emulator-fifo',
]

# 500-line cap mirrors logs_routes.
_LOG_LINES_MAX = 500


def _exec_logs_view(params: Dict[str, Any], ctx: OpContext) -> OpResult:
    service = (params.get('service') or '').strip()
    if not service:
        return OpResult(summary='service is required')
    if service not in ALLOWED_SERVICES:
        return OpResult(summary=f'service not in whitelist: {service!r}')
    try:
        lines = max(1, min(_LOG_LINES_MAX, int(params.get('lines', 50))))
    except (TypeError, ValueError):
        lines = 50
    try:
        out = subprocess.run(
            ['journalctl', '-u', service, '-n', str(lines), '--no-pager', '-q'],
            capture_output=True, text=True, timeout=8,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return OpResult(summary=f'journalctl failed: {type(e).__name__}')
    body = (out.stdout or '').strip()
    if not body:
        return OpResult(summary=f'{lines} lines returned (empty journal for {service})')
    return OpResult(
        summary=f'{min(lines, body.count(chr(10)) + 1)} lines returned for {service}',
        detail={'first_line': body.splitlines()[0][:200] if body else ''},
    )


def _exec_logs_services(_params: Dict[str, Any], _ctx: OpContext) -> OpResult:
    return OpResult(
        summary=f'{len(ALLOWED_SERVICES)} whitelisted services',
        detail={'services': ALLOWED_SERVICES},
    )


def _exec_service_status(params: Dict[str, Any], ctx: OpContext) -> OpResult:
    host = (params.get('host') or ctx.host_name or '').strip()
    service = (params.get('service') or '').strip()
    if not host or not service:
        return OpResult(summary='host and service are required')
    if service not in ALLOWED_SERVICES:
        return OpResult(summary=f'service not in whitelist: {service!r}')
    try:
        from backend_server.src.lib.utils.server_utils import get_host_manager
        host_info = get_host_manager().get_host(host)
    except Exception:
        host_info = None
    if not host_info:
        return OpResult(summary=f'host not found: {host}')
    try:
        resp, status = call_host(
            host_info, '/host/system/services/status',
            method='POST', data={'service': service}, timeout=10,
        )
    except Exception as e:
        return OpResult(summary=f'call_host failed: {type(e).__name__}')
    if status != 200 or not resp.get('success'):
        return OpResult(summary=f'status query failed: status={status}')
    return OpResult(
        summary=f'{service} on {host}: {resp.get("active_state", "?")} ({resp.get("sub_state", "?")})',
        detail=resp,
    )


def _exec_service_restart(params: Dict[str, Any], ctx: OpContext) -> OpResult:
    host = (params.get('host') or ctx.host_name or '').strip()
    service = (params.get('service') or '').strip()
    if not host or not service:
        return OpResult(summary='host and service are required')
    if service not in ALLOWED_SERVICES:
        return OpResult(summary=f'service not in whitelist: {service!r}')
    try:
        from backend_server.src.lib.utils.server_utils import get_host_manager
        host_info = get_host_manager().get_host(host)
    except Exception:
        host_info = None
    if not host_info:
        return OpResult(summary=f'host not found: {host}')

    pre_start = time.monotonic()
    try:
        resp, status = call_host(
            host_info, '/host/restartHostService',
            method='POST', data={'service_name': service}, timeout=120,
        )
    except Exception as e:
        return OpResult(summary=f'restart call failed: {type(e).__name__}')
    duration_ms = int((time.monotonic() - pre_start) * 1000)
    if status != 200 or not resp.get('success'):
        return OpResult(
            summary=f'restart failed for {service} on {host} after {duration_ms}ms (status={status})',
            detail=resp,
        )
    return OpResult(
        summary=f'restart OK: {service} on {host} after {duration_ms}ms',
        detail=resp,
    )


def _exec_infra_summary(_params: Dict[str, Any], ctx: OpContext) -> OpResult:
    try:
        from backend_server.src.lib.utils.server_utils import get_host_manager
        hosts = get_host_manager().get_all_hosts()
    except Exception as e:
        return OpResult(summary=f'host list unavailable: {type(e).__name__}')
    if not hosts:
        return OpResult(summary='no registered hosts')
    n = len(hosts)
    sample = ', '.join(sorted(hosts.keys())[:5])
    return OpResult(
        summary=f'{n} registered host(s) ({sample}{"..." if n > 5 else ""}); '
                'per-host disk/RAM requires /host/system/health — not yet wired in masterchief',
        detail={'hosts': list(hosts.keys())},
    )


def _exec_rollout_explain(params: Dict[str, Any], _ctx: OpContext) -> OpResult:
    fb = params.get('from_build')
    tb = params.get('to_build')
    if not fb or not tb:
        return OpResult(summary='from_build and to_build are required')
    return OpResult(
        summary=f'rollout.explain {fb}->{tb} is not yet wired in masterchief '
                '(release-note diff is a separate build; tracked in TASK-41)',
        detail={'from_build': fb, 'to_build': tb},
    )


def _exec_deploy_status(params: Dict[str, Any], _ctx: OpContext) -> OpResult:
    deploy_id = (params.get('deploy_id') or '').strip()
    if not deploy_id:
        return OpResult(summary='deploy_id is required')
    return OpResult(
        summary=f'deploy.status {deploy_id} is not yet wired in masterchief '
                '(requires vpt-lease CLI on proxmox — out of scope for Part 7)',
        detail={'deploy_id': deploy_id},
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

MASTERCHIEF_OPS: List[MasterchiefOp] = [
    MasterchiefOp(
        op='logs.view',
        summary='Read the last N lines of a whitelisted service journal',
        mutates=False,
        required_permission='settings.logs:view',
        platform_admin_only=False,
        params_schema={
            'type': 'object',
            'required': ['service'],
            'properties': {
                'service': {'type': 'string', 'enum': ALLOWED_SERVICES},
                'lines': {'type': 'integer', 'minimum': 1, 'maximum': 500, 'default': 50},
            },
        },
        blast_radius='Read-only. 500-line cap. Service whitelisted.',
        executor=_exec_logs_view,
    ),
    MasterchiefOp(
        op='logs.services',
        summary='List the whitelisted services available for log review',
        mutates=False,
        required_permission='settings.logs:view',
        platform_admin_only=False,
        params_schema={'type': 'object', 'properties': {}},
        blast_radius='Read-only. Returns the static whitelist.',
        executor=_exec_logs_services,
    ),
    MasterchiefOp(
        op='service.status',
        summary='Read the systemd status of one service on one host',
        mutates=False,
        required_permission='settings.logs:view',
        platform_admin_only=False,
        params_schema={
            'type': 'object',
            'required': ['host', 'service'],
            'properties': {
                'host': {'type': 'string', 'minLength': 1},
                'service': {'type': 'string', 'enum': ALLOWED_SERVICES},
            },
        },
        blast_radius='Read-only. One host, one service.',
        executor=_exec_service_status,
    ),
    MasterchiefOp(
        op='service.restart',
        summary='Restart one service on one host (MUTATES; admin-only on prod)',
        mutates=True,
        required_permission='system.services:restart',
        platform_admin_only=True,
        params_schema={
            'type': 'object',
            'required': ['host', 'service'],
            'properties': {
                'host': {'type': 'string', 'minLength': 1},
                'service': {'type': 'string', 'enum': ALLOWED_SERVICES},
                'reason': {'type': 'string', 'maxLength': 200,
                           'description': 'Free-text reason recorded in the audit row.'},
            },
        },
        blast_radius=(
            'MUTATES: a 90s systemctl restart on a single host service. '
            'Triggers a SIGTERM to the existing process. Recorded in masterchief_audit.'
        ),
        executor=_exec_service_restart,
    ),
    MasterchiefOp(
        op='infra.summary',
        summary='List registered hosts and a summary digest',
        mutates=False,
        required_permission='settings.status:view',
        platform_admin_only=False,
        params_schema={'type': 'object', 'properties': {}},
        blast_radius='Read-only. Per-host disk/RAM not yet wired (see audit summary).',
        executor=_exec_infra_summary,
    ),
    MasterchiefOp(
        op='rollout.explain',
        summary='Explain what changed between two build numbers',
        mutates=False,
        required_permission='settings.code_deploy:view',
        platform_admin_only=False,
        params_schema={
            'type': 'object',
            'required': ['from_build', 'to_build'],
            'properties': {
                'from_build': {'type': 'integer', 'minimum': 1},
                'to_build': {'type': 'integer', 'minimum': 1},
            },
        },
        blast_radius='Read-only. Release-note diff not yet wired.',
        executor=_exec_rollout_explain,
    ),
    MasterchiefOp(
        op='deploy.status',
        summary='Show the current state of a deploy by id',
        mutates=False,
        required_permission='settings.code_deploy:view',
        platform_admin_only=False,
        params_schema={
            'type': 'object',
            'required': ['deploy_id'],
            'properties': {
                'deploy_id': {'type': 'string', 'minLength': 1, 'maxLength': 200},
            },
        },
        blast_radius='Read-only. vpt-lease access not yet wired.',
        executor=_exec_deploy_status,
    ),
]


_BY_OP: Dict[str, MasterchiefOp] = {o.op: o for o in MASTERCHIEF_OPS}


def get_op(op_name: str) -> Optional[MasterchiefOp]:
    return _BY_OP.get(op_name)


def list_ops() -> List[MasterchiefOp]:
    return list(MASTERCHIEF_OPS)


def execute_op(op_name: str, params: Dict[str, Any], ctx: OpContext) -> OpResult:
    """Dispatch to the executor for op_name. Refuses unknown ops."""
    op = get_op(op_name)
    if op is None:
        return OpResult(summary=f'unknown op: {op_name!r}')
    try:
        return op.executor(params, ctx)
    except Exception as e:  # noqa: BLE001 — the audit row is the error sink
        logger.exception("masterchief executor %s raised", op_name)
        return OpResult(summary=f'executor raised {type(e).__name__}')


# ---------------------------------------------------------------------------
# Prod-vs-dev gate
# ---------------------------------------------------------------------------

def platform_admin_required() -> bool:
    """True on prod (default), False when the operator has explicitly opted
    out via `MASTERCHIEF_REQUIRE_PLATFORM_ADMIN=0` for a dev site.

    The hard rule is "admin-only on prod (broader auth on dev)". A platform
    install that wants dev behaviour sets the env var to 0. Defaults to True
    so a missing flag is the safe (admin-only) posture.
    """
    raw = os.getenv('MASTERCHIEF_REQUIRE_PLATFORM_ADMIN', '1').strip().lower()
    return raw not in ('0', 'false', 'no', 'off')
