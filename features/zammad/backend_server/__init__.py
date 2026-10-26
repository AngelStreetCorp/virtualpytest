"""Zammad feature - backend_server part (TASK-96).

Registered by shared/src/lib/utils/features.py when the feature is enabled (docs/technical/FEATURES.md).
Support tickets: the browser never talks to the helpdesk or sees its token.

  Plugin page (any signed-in user reads, admin changes)
    GET  /server/zammad/status               {enabled, configured}  - drives the "Open a ticket" entry
    GET  /server/zammad/health               {config, reachable, version?, user?, error?}
    PUT  /server/zammad/config               {base_url, token?, public_url?, name?, enabled?}  (admin)
         tests GET /api/v1/users/me with the new pair BEFORE saving; a failing test saves nothing (502)
    PUT  /server/zammad/enabled              {enabled: bool}  (admin)  the on/off switch alone

  Tickets (409 "support tickets are disabled" while the switch is off or nothing is configured)
    POST /server/zammad/tickets              {ticket_type, family, category, frequency, priority (P0|P1|P2), severity?, target_id?,
                                              target_label?, title, description,
                                              attachments?: [{filename, data_b64, mime_type?}]}
         enums are validated against lib/model.py (severity is required for incident and bug, ignored for
         request and question; category must belong to the family)
         -> 201 {ticket}   opens a ticket in the helpdesk on behalf of the caller's email, then indexes it
    GET  /server/zammad/tickets              ?status=&category=&target_id=&type=&family=&severity=&user=&project=&period=
                                             the team's tickets (+ zammad_url, reporter_status)
    GET  /server/zammad/tickets/stats        ?period=today|7d|30d|all&type=&family=&severity=&user=&project=
                                             {opened, closed, total, users}
         opened = created in the period, closed = closed | duplicate | wont_fix with updated_at in the period,
         total = all in scope
    GET  /server/zammad/tickets/<id>         {ticket, articles}   DB row + helpdesk articles (proxied)
    POST /server/zammad/tickets/<id>/reply   {body, attachments?} -> 201 {article}

team_id comes from the query string (buildServerUrl adds it); every query is filtered by it, and a caller
can only use a team they belong to.
"""

from __future__ import annotations

import base64
import binascii
import re
from datetime import datetime, timedelta, timezone
from typing import List

from flask import Blueprint, jsonify, request

from backend_server.src.lib.auth_middleware import (
    _caller_is_platform_admin, _caller_team_ids, require_role, require_user_auth,
)
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.services.analytics.scope import (
    ScopeError, actor_id, error_json, handle_scope_errors, json_body, require_uuid, resolve_team_id,
)
from features.zammad.lib import config, support_tickets_db
from features.zammad.lib.zammad import ZammadProvider
from features.zammad.lib import (
    Attachment, SupportError, SupportNotConfigured, TicketFields,
)
from features.zammad.lib.model import (
    FAMILIES, FREQUENCIES, PRIORITIES, SEVERITIES, SEVERITY_TYPES, STATUS_NEW, TICKET_TYPES, reporter_status,
)

PROVIDER_ZAMMAD = 'zammad'

feature_zammad_bp = Blueprint('feature_zammad', __name__, url_prefix='/server/zammad')

MAX_TITLE = 200
MAX_BODY = 20000
MAX_ATTACHMENTS = 5
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _team_id() -> str:
    team_id = resolve_team_id()
    if not (getattr(request, 'user_role', None) == 'service' or _caller_is_platform_admin()
            or team_id in _caller_team_ids()):
        raise ScopeError('you are not a member of this team', 403)
    return team_id


def _requester_email() -> str:
    email = str(getattr(request, 'user_email', '') or '').strip()
    if not _EMAIL_RE.match(email):
        raise ScopeError('a real user email is required to open a ticket (auto-sign and service callers have none)', 400)
    return email


def _text(value, name: str, maximum: int) -> str:
    text = value.strip() if isinstance(value, str) else ''
    if not text:
        raise ScopeError(f'{name} is required', 400)
    if len(text) > maximum:
        raise ScopeError(f'{name} is too long (max {maximum} characters)', 400)
    return text


def _choice(value, name: str, allowed) -> str:
    text = str(value or '').strip()
    if text not in allowed:
        raise ScopeError(f'{name} must be one of {", ".join(allowed)}', 400)
    return text


def _optional_text(value, maximum: int = 200):
    text = str(value).strip() if value not in (None, '') else ''
    return text[:maximum] or None


def _fields(body: dict) -> TicketFields:
    """The ticket model's classification, validated: type, family -> category, priority (P0-P2, always required), severity (only incident and
    bug carry one and they need it), frequency (always required), optional target."""
    ticket_type = _choice(body.get('ticket_type'), 'ticket_type', TICKET_TYPES)
    family = _choice(body.get('family'), 'family', tuple(FAMILIES))
    category = _choice(body.get('category'), 'category', FAMILIES[family])
    frequency = _choice(body.get('frequency'), 'frequency', FREQUENCIES)
    priority = _choice(body.get('priority'), 'priority', PRIORITIES)
    severity = None
    if ticket_type in SEVERITY_TYPES:
        severity = _choice(body.get('severity'), 'severity', SEVERITIES)
    return TicketFields(ticket_type=ticket_type, family=family, category=category, frequency=frequency, priority=priority,
                        severity=severity, target_id=_optional_text(body.get('target_id')),
                        target_label=_optional_text(body.get('target_label')))


def _with_reporter_status(row: dict) -> dict:
    """The simplified status the requester sees (Open / In progress / Waiting for you / Delivered / Closed)."""
    row['reporter_status'] = reporter_status(row.get('status'))
    return row


def _classification_filters() -> dict:
    """Optional ?type=&family=&severity= on the list and the stats; unknown values are a 400, not an empty page."""
    out = {}
    for arg, column, allowed in (('type', 'ticket_type', TICKET_TYPES), ('family', 'family', tuple(FAMILIES)),
                                 ('severity', 'severity', SEVERITIES)):
        value = (request.args.get(arg) or '').strip()
        out[column] = _choice(value, arg, allowed) if value else None
    return out


def _attachments(raw) -> List[Attachment]:
    if raw in (None, ''):
        return []
    if not isinstance(raw, list) or len(raw) > MAX_ATTACHMENTS:
        raise ScopeError(f'attachments must be a list of at most {MAX_ATTACHMENTS} files', 400)
    files: List[Attachment] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ScopeError('each attachment must be an object', 400)
        name = str(item.get('filename') or '').replace('\\', '/').split('/')[-1].strip()
        data = item.get('data_b64')
        if not name or not isinstance(data, str) or not data:
            raise ScopeError('each attachment needs filename and data_b64', 400)
        try:
            size = len(base64.b64decode(data, validate=True))
        except (binascii.Error, ValueError):
            raise ScopeError(f'attachment {name} is not valid base64', 400)
        if size > MAX_ATTACHMENT_BYTES:
            raise ScopeError(f'attachment {name} is larger than {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB', 400)
        files.append(Attachment(filename=name, data_b64=data,
                                mime_type=str(item.get('mime_type') or 'application/octet-stream')))
    return files


PERIODS = ('today', '7d', '30d', 'all')


def _since(period: str):
    """ISO start of the period (UTC), None for 'all'."""
    period = (period or 'all').strip() or 'all'
    if period not in PERIODS:
        raise ScopeError(f'period must be one of {", ".join(PERIODS)}', 400)
    if period == 'all':
        return None
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period != 'today':
        start = now - timedelta(days=7 if period == '7d' else 30)
    return start.isoformat()


def _filters() -> dict:
    user = (request.args.get('user') or '').strip() or None
    return {'created_by': user, 'project': _project()}


def _project():
    """``(team ids, user ids)`` of ?project=<workspace id>, resolved by the AI usage helper (a workspace the
    caller may see; admins see all). None without the parameter. The caller's team check (_team_id) still applies."""
    workspace = (request.args.get('project') or '').strip()
    if not workspace:
        return None
    from backend_server.src.routes.server_ai_routing_routes import _UsageArgs
    scope = _UsageArgs._load_project(require_uuid(workspace, 'project'))
    if scope is None:
        raise ScopeError('Unknown project', 404)
    return scope


def _provider():
    return config.provider()


def _require_enabled():
    """ScopeError 409 while the Enabled switch is off or nothing is configured."""
    if not config.is_enabled():
        raise ScopeError('support tickets are disabled', 409)


def _helpdesk_error(e: SupportError):
    status = 503 if isinstance(e, SupportNotConfigured) else 502
    return error_json(str(e), status)


def _ticket_in_team(team_id: str, ticket_id: str) -> dict:
    row = support_tickets_db.get_ticket(team_id, require_uuid(ticket_id, 'ticket_id'))
    if not row:
        raise ScopeError('ticket not found', 404)
    return row


@feature_zammad_bp.route('/tickets', methods=['POST'])
@handle_route_exceptions('zammad:create')
@require_user_auth
@handle_scope_errors
def create_ticket():
    body = json_body()
    _require_enabled()
    team_id = _team_id()
    fields = _fields(body)
    title = _text(body.get('title'), 'title', MAX_TITLE)
    description = _text(body.get('description'), 'description', MAX_BODY)
    email = _requester_email()
    files = _attachments(body.get('attachments'))
    try:
        ref = _provider().create_ticket(title=title, body=description, fields=fields,
                                        requester_email=email, attachments=files)
    except SupportError as e:
        return _helpdesk_error(e)
    row = support_tickets_db.insert_ticket(
        team_id=team_id, ticket_type=fields.ticket_type, family=fields.family, category=fields.category,
        target_id=fields.target_id, target_label=fields.target_label, severity=fields.severity,
        frequency=fields.frequency, priority=fields.priority, title=title, status=ref.status or STATUS_NEW,
        external_provider=PROVIDER_ZAMMAD, external_id=ref.external_id,
        external_number=ref.number, created_by=actor_id(), created_by_email=email)
    return jsonify({'success': True, 'ticket': _with_reporter_status(row)}), 201


@feature_zammad_bp.route('/tickets', methods=['GET'])
@handle_route_exceptions('zammad:list')
@require_user_auth
@handle_scope_errors
def list_tickets():
    team_id = _team_id()
    rows = support_tickets_db.list_tickets(
        team_id,
        status=(request.args.get('status') or '').strip() or None,
        category=(request.args.get('category') or '').strip() or None,
        target_id=(request.args.get('target_id') or '').strip() or None,
        since=_since(request.args.get('period') or 'all'),
        **_classification_filters(),
        **_filters())
    cfg = config.effective()
    for row in rows:
        _with_reporter_status(row)
        row['zammad_url'] = config.ticket_url(cfg, row['external_id'])
    return jsonify({'success': True, 'tickets': rows})


@feature_zammad_bp.route('/filters', methods=['GET'])
@handle_route_exceptions('zammad:filters')
@require_user_auth
@handle_scope_errors
def filter_options():
    """Team and Project dropdown options: the same source as Monitoring -> AI usage (admin: all, else own)."""
    from backend_server.src.routes.server_ai_routing_routes import _scope_options
    return jsonify({'success': True, **_scope_options()})


@feature_zammad_bp.route('/tickets/stats', methods=['GET'])
@handle_route_exceptions('zammad:stats')
@require_user_auth
@handle_scope_errors
def ticket_stats():
    team_id = _team_id()
    stats = support_tickets_db.ticket_stats(
        team_id, since=_since(request.args.get('period') or 'all'), **_classification_filters(), **_filters())
    return jsonify({'success': True, **stats})


@feature_zammad_bp.route('/tickets/<ticket_id>', methods=['GET'])
@handle_route_exceptions('zammad:get')
@require_user_auth
@handle_scope_errors
def get_ticket(ticket_id: str):
    row = _ticket_in_team(_team_id(), ticket_id)
    try:
        articles = _provider().list_articles(row['external_id'])
    except SupportError as e:
        return _helpdesk_error(e)
    return jsonify({'success': True, 'ticket': _with_reporter_status(row), 'articles': [a.to_dict() for a in articles]})


@feature_zammad_bp.route('/tickets/<ticket_id>/reply', methods=['POST'])
@handle_route_exceptions('zammad:reply')
@require_user_auth
@handle_scope_errors
def reply_ticket(ticket_id: str):
    body = json_body()
    _require_enabled()
    team_id = _team_id()
    row = _ticket_in_team(team_id, ticket_id)
    text = _text(body.get('body'), 'body', MAX_BODY)
    files = _attachments(body.get('attachments'))
    try:
        article = _provider().add_reply(row['external_id'], body=text,
                                        author_email=_requester_email(), attachments=files)
    except SupportError as e:
        return _helpdesk_error(e)
    return jsonify({'success': True, 'article': article.to_dict()}), 201



# ─── plugin page: status / health / config ───────────────────────────────────

def _health_payload(cfg: dict) -> dict:
    """Connection probe for the page. Never raises; `error` carries the readable reason."""
    out = {'config': config.public(cfg), 'reachable': False}
    if not config.is_configured(cfg):
        out['error'] = 'Zammad URL and API token are not configured'
        return out
    try:
        me = _provider().whoami()
    except SupportError as e:
        out['error'] = str(e)
        return out
    out['reachable'] = True
    out['user'] = me.get('email') or me.get('login')
    return out


@feature_zammad_bp.route('/status', methods=['GET'], strict_slashes=False)
@handle_route_exceptions('zammad:status')
@require_user_auth
def status():
    """Cheap, no outbound call: the navbar entry and the dialog gate on this.

    `public_url` is the Zammad web UI the navbar shortcut opens (blank when not set).
    """
    cfg = config.effective()
    return jsonify({'success': True, 'enabled': config.is_enabled(),
                    'configured': config.is_configured(),
                    'public_url': cfg.get('public_url') or ''})


@feature_zammad_bp.route('/health', methods=['GET'], strict_slashes=False)
@handle_route_exceptions('zammad:health')
@require_user_auth
def health():
    return jsonify({'success': True, **_health_payload(config.effective())})


@feature_zammad_bp.route('/config', methods=['PUT'], strict_slashes=False)
@handle_route_exceptions('zammad:save_config')
@require_user_auth
@require_role('admin')
def save_config():
    payload = request.get_json(silent=True) or {}
    base_url = str(payload.get('base_url') or '').strip().rstrip('/')
    token = str(payload.get('token') or '').strip() or config.effective()['token']
    if not base_url:
        return error_json('base_url is required', 400)
    if not token:
        return error_json('token is required', 400)
    # Prove the pair works before the operator leaves the form believing it does.
    try:
        me = ZammadProvider(base_url, token).whoami()
    except SupportError as e:
        return error_json(f'connection test failed, nothing saved: {e}', 502)
    saved = config.upsert({
        'name': payload.get('name'), 'base_url': base_url, 'token': token,
        'public_url': payload.get('public_url'),
        'enabled': payload.get('enabled') if isinstance(payload.get('enabled'), bool) else None,
    })
    if not saved:
        return error_json('could not write the Zammad config', 500)
    return jsonify({'success': True, 'config': config.public(config.effective()),
                    'user': me.get('email') or me.get('login')})


@feature_zammad_bp.route('/enabled', methods=['PUT'], strict_slashes=False)
@handle_route_exceptions('zammad:set_enabled')
@require_user_auth
@require_role('admin')
def set_enabled():
    enabled = (request.get_json(silent=True) or {}).get('enabled')
    if not isinstance(enabled, bool):
        return error_json('enabled must be true or false', 400)
    if not config.upsert({'enabled': enabled}):
        return error_json('could not write the Zammad config', 500)
    return jsonify({'success': True, 'config': config.public(config.effective())})


def register(app):
    app.register_blueprint(feature_zammad_bp)
