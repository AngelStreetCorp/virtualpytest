"""
User-Tenants Routes — TASK-23

Per-user tenant membership (super-admin only). URL prefix:
/server/users/<user_id>/tenants

This is the API surface for the Tenants tab on the Users edit dialog
(visible only when the caller is a platform admin).
"""

from flask import Blueprint, request, jsonify
import logging

from shared.src.lib.database import user_tenants_db, tenants_db
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.auth_middleware import require_platform_admin

logger = logging.getLogger(__name__)

server_user_tenants_bp = Blueprint('server_user_tenants', __name__,
                                    url_prefix='/server/users')


@server_user_tenants_bp.route('/<user_id>/tenants', methods=['GET'])
@require_platform_admin
@handle_route_exceptions('server_user_tenants:get_user_tenants')
def get_user_tenants(user_id: str):
    """List the tenants this user belongs to."""
    rows = user_tenants_db.get_user_tenants(user_id)
    return jsonify(rows), 200


@server_user_tenants_bp.route('/<user_id>/tenants', methods=['POST'])
@require_platform_admin
@handle_route_exceptions('server_user_tenants:add_user_tenant')
def add_user_tenant(user_id: str):
    """Grant the user membership in a tenant.

    Body: {tenant_id: str, role?: 'member' | 'admin' | 'owner', granted_by?: str}
    `role` is currently always 'member' in v1; the other values are reserved
    for a future tenant-admin concept.
    """
    body = request.get_json(silent=True) or {}
    tenant_id = (body.get('tenant_id') or body.get('tenant') or '').strip()
    role = (body.get('role') or 'member').strip()
    granted_by = body.get('granted_by')

    if not tenant_id:
        return jsonify({"error": "tenant_id is required"}), 400

    # Resolve slug -> id if necessary
    if not _is_uuid(tenant_id):
        all_tenants = tenants_db.get_all_tenants()
        match = next((t for t in all_tenants if t.get('slug') == tenant_id), None)
        if not match:
            return jsonify({"error": "Tenant not found"}), 404
        tenant_id = match['id']

    # Validate tenant exists
    tenant = tenants_db.get_tenant(tenant_id)
    if not tenant:
        return jsonify({"error": "Tenant not found"}), 404

    if role not in ('owner', 'admin', 'member'):
        return jsonify({"error": "role must be one of owner/admin/member"}), 400

    row = user_tenants_db.add_user_tenant(user_id, tenant_id, role=role,
                                          granted_by=granted_by)
    if not row:
        return jsonify({"error": "Could not grant tenant"}), 500
    return jsonify(row), 201


@server_user_tenants_bp.route('/<user_id>/tenants/<tenant_id>',
                                methods=['DELETE'])
@require_platform_admin
@handle_route_exceptions('server_user_tenants:remove_user_tenant')
def remove_user_tenant(user_id: str, tenant_id: str):
    """Revoke the user's membership in a tenant.

    Note: revoking the default tenant leaves the user without any tenant
    membership, which means they fail the tenant scope check on every
    team-scoped route. Q7 says we do not auto-grant the default tenant
    on provisioning, but revoking it explicitly should be the super admin's
    conscious choice; we still allow it, and route handlers downstream
    will reflect the new state on the user's next JWT refresh.
    """
    ok = user_tenants_db.remove_user_tenant(user_id, tenant_id)
    if not ok:
        return jsonify({"error": "Tenant membership not found"}), 404
    return jsonify({"deleted": True, "user_id": user_id, "tenant_id": tenant_id}), 200


def _is_uuid(value: str) -> bool:
    """Crude UUID format check. Good enough for routing."""
    if not value or len(value) != 36:
        return False
    parts = value.split('-')
    return len(parts) == 5 and all(
        len(parts[i]) == _UUID_SEGMENTS[i] for i in range(5)
    )


_UUID_SEGMENTS = (8, 4, 4, 4, 12)