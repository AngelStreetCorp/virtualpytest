"""
Tenants Management Routes — TASK-23

CRUD for the `tenants` table. Gated by @require_platform_admin — only the
super admin sees tenants; everyone else gets 403 even with role='admin'
(design decision Q3: regular admins are unaware tenants exist).

URL prefix: /server/tenants
"""

from flask import Blueprint, request, jsonify
import logging

from shared.src.lib.database import tenants_db
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.auth_middleware import require_platform_admin

logger = logging.getLogger(__name__)

server_tenants_bp = Blueprint('server_tenants', __name__, url_prefix='/server/tenants')


@server_tenants_bp.route('', methods=['GET'])
@require_platform_admin
@handle_route_exceptions('server_tenants:get_tenants')
def get_tenants():
    """List all tenants with team + user counts."""
    tenants = tenants_db.get_all_tenants()
    return jsonify(tenants), 200


@server_tenants_bp.route('/<tenant_id>', methods=['GET'])
@require_platform_admin
@handle_route_exceptions('server_tenants:get_tenant')
def get_tenant(tenant_id: str):
    """Fetch a single tenant by id (UUID) or slug."""
    tenant = tenants_db.get_tenant(tenant_id)
    if not tenant:
        # Slug path? Try by-slug.
        all_tenants = tenants_db.get_all_tenants()
        for t in all_tenants:
            if t.get('slug') == tenant_id:
                return jsonify(t), 200
        return jsonify({"error": "Tenant not found"}), 404
    return jsonify(tenant), 200


@server_tenants_bp.route('', methods=['POST'])
@require_platform_admin
@handle_route_exceptions('server_tenants:create_tenant')
def create_tenant():
    """Create a new tenant.

    Body: {name: str, slug: str, description?: str}
    Slug is required and must match ^[a-z0-9][a-z0-9-]{0,62}$ (DB enforced).
    """
    body = request.get_json(silent=True) or {}
    name = (body.get('name') or '').strip()
    slug = (body.get('slug') or '').strip()
    description = (body.get('description') or '').strip()
    created_by = body.get('created_by')

    if not name:
        return jsonify({"error": "name is required"}), 400
    if not slug:
        return jsonify({"error": "slug is required"}), 400

    created = tenants_db.create_tenant(name=name, slug=slug,
                                       description=description,
                                       created_by=created_by)
    if not created:
        return jsonify({
            "error": "Could not create tenant",
            "message": "Slug may already exist or be malformed (must match ^[a-z0-9][a-z0-9-]{0,62}$)",
        }), 400
    return jsonify(created), 201


@server_tenants_bp.route('/<tenant_id>', methods=['PUT'])
@require_platform_admin
@handle_route_exceptions('server_tenants:update_tenant')
def update_tenant(tenant_id: str):
    """Update mutable fields (name, description, slug, footer branding).

    Footer branding fields are accepted but only stored if they pass the DB
    CHECK constraints (https URL, hex color). A 400 is returned if the DB
    rejects the value.
    """
    body = request.get_json(silent=True) or {}
    name = body.get('name')
    description = body.get('description')
    slug = body.get('slug')
    footer_logo_url = body.get('footer_logo_url')
    footer_logo_alt = body.get('footer_logo_alt')
    footer_text_color = body.get('footer_text_color')

    if name is not None:
        name = name.strip() or None
    if description is not None:
        description = description.strip()
    if slug is not None:
        slug = slug.strip() or None

    # Q6: default tenant name + slug are editable in v1 but is_default cannot be unset.
    # is_default is not exposed in the update path, so it cannot be flipped by this route.

    try:
        updated = tenants_db.update_tenant(
            tenant_id, name=name, description=description, slug=slug,
            footer_logo_url=footer_logo_url,
            footer_logo_alt=footer_logo_alt,
            footer_text_color=footer_text_color,
        )
    except Exception as e:
        # Postgres CHECK violation surfaces as a Supabase 400-ish error.
        msg = str(e)
        if 'tenants_footer_logo_url_https' in msg:
            return jsonify({
                "error": "Invalid footer_logo_url",
                "message": "URL must start with https://",
            }), 400
        if 'tenants_footer_text_color_hex' in msg:
            return jsonify({
                "error": "Invalid footer_text_color",
                "message": "Must be a hex color like #1a73e8 or #1a73e8cc",
            }), 400
        raise
    if not updated:
        return jsonify({"error": "Tenant not found"}), 404
    return jsonify(updated), 200


@server_tenants_bp.route('/<tenant_id>', methods=['DELETE'])
@require_platform_admin
@handle_route_exceptions('server_tenants:delete_tenant')
def delete_tenant(tenant_id: str):
    """Delete a tenant.

    Refuses (409) if any team still references it.
    The default tenant (`0000…000`) is undeletable in policy — the route
    checks the is_default flag and returns 409 before even attempting the delete.
    """
    target = tenants_db.get_tenant(tenant_id)
    if not target:
        return jsonify({"error": "Tenant not found"}), 404
    if target.get('is_default'):
        return jsonify({
            "error": "Cannot delete the default tenant",
            "message": "The Default tenant is the home of open signups and pre-existing teams.",
        }), 409

    deleted = tenants_db.delete_tenant(tenant_id)
    if not deleted:
        return jsonify({
            "error": "Tenant has teams",
            "message": "Move or delete its teams first.",
        }), 409
    return jsonify({"deleted": True, "tenant_id": tenant_id}), 200