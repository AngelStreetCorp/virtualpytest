"""
Per-Tenant Branding Routes — TASK-23 footer-logo follow-up

Public read endpoint that returns the branding overrides for the **caller's
current tenant**. Resolved from the JWT (tenant_ids claim), so non-super-admin
users get their own tenant's branding with no leak of other tenants' data.

URL prefix: /server/branding/tenant
"""

from flask import Blueprint, jsonify
import logging

from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.auth_middleware import (
    require_user_auth, _caller_tenant_ids, _caller_is_platform_admin,
)
from shared.src.lib.database import tenants_db

logger = logging.getLogger(__name__)

server_branding_tenant_bp = Blueprint('server_branding_tenant', __name__,
                                       url_prefix='/server/branding/tenant')


@server_branding_tenant_bp.route('', methods=['GET'])
@require_user_auth
@handle_route_exceptions('server_branding_tenant:get_tenant_branding')
def get_tenant_branding():
    """Return the footer-branding overrides for the caller's current tenant.

    Multi-tenant users (Q2) may belong to more than one tenant; this endpoint
    returns branding for the *first* tenant in their tenant_ids set, which is
    the same tenant the existing UI surfaces as the user's "home" tenant. A
    platform admin sees the branding of every tenant they belong to under the
    same rule (their JWT tenant_ids is the union of every tenant they were
    explicitly granted, plus the default tenant).

    Returns an empty object `{}` if the caller has no tenant_ids claim yet
    (their token predates TASK-23 and the DB fallback failed) — the frontend
    falls through to the deployment-level and build-time branding in that case.
    """
    tenant_ids = _caller_tenant_ids()
    if not tenant_ids:
        # Caller has no tenant membership. Default tenant branding is the
        # next-best signal, but a JWT with no tenant_ids is usually a stale
        # token pre-TASK-23 — return empty so the frontend falls through.
        return jsonify({}), 200

    # Pick the first tenant — deterministic for a single-tenant user, and a
    # platform admin typically has at most a handful of tenants so order is
    # stable enough for footer rendering. A future v2 could let the UI pick
    # which tenant to display if the user is in >1.
    chosen = sorted(tenant_ids)[0]
    branding = tenants_db.get_tenant_branding(chosen)
    # Trim empty strings to None for a clean response.
    cleaned = {k: v for k, v in branding.items() if v}
    return jsonify(cleaned), 200