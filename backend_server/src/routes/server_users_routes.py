"""
Users Management Routes
Handles user profile management and team assignments
"""
from flask import Blueprint, request, jsonify
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.auth_middleware import require_admin_role, _caller_is_platform_admin
from typing import Optional
import logging

from shared.src.lib.database import users_db
from backend_server.src.lib.error_handler import handle_error

logger = logging.getLogger(__name__)

server_users_bp = Blueprint('server_users', __name__, url_prefix='/server/users')

from backend_server.src.lib.utils.grafana_config import (
    default_role as _default_role,
    grafana_role_for,
    grafana_org_id,
)


def _is_email(identifier: str) -> bool:
    return '@' in (identifier or '')


def _grafana_requested() -> bool:
    if (request.args.get('grafana') or '').lower() in ('1', 'true', 'yes'):
        return True
    data = request.get_json(silent=True) or {}
    return bool(data.get('grafana'))


def _password_supplied() -> bool:
    if request.args.get('password'):
        return True
    data = request.get_json(silent=True) or {}
    return bool(data.get('password'))


def _mirror_grafana_upsert(email, password, full_name, role):
    from shared.src.lib.utils.grafana_admin import grafana_upsert_user
    return grafana_upsert_user(
        email=email, password=password, full_name=full_name,
        org_role=grafana_role_for(role), org_id=grafana_org_id(),
    )


def _mirror_grafana_delete(email):
    from shared.src.lib.utils.grafana_admin import grafana_delete_user
    return grafana_delete_user(email=email)


def _provision_upsert(email, data):
    """Shared create/edit upsert + optional Grafana mirror. Returns (json, status).

    TASK-23: when the caller supplies `tenant` (slug or UUID) and is a platform
    super admin, the user is created in that tenant (Q7 explicit only). The
    caller-side check is on the route — _provision_upsert just forwards.
    """
    try:
        result = users_db.upsert_user(
            email=email,
            password=data.get('password'),
            full_name=data.get('full_name'),
            group=data.get('group'),
            default_role=_default_role(),
            provider_type=data.get('provider_type'),
            tenant=data.get('tenant'),
        )
    except ValueError as e:
        return {"status": "error", "error": "invalid_payload", "detail": str(e)}, 400
    except RuntimeError as e:
        return {"status": "error", "error": "internal_error", "detail": str(e)}, 500

    resp = {
        "status": "ok",
        "action": result["action"],
        "user_id": result["user_id"],
        "email": result["email"],
        "platform": {"role": result["role"], "team": result["team"],
                     "full_name": result["full_name"],
                     "provider_type": result["provider_type"]},
    }
    if data.get('tenant'):
        # Echo back the resolved tenant so the caller knows which one was used.
        # Only present when the caller sent `tenant` — never leaks to regular admins.
        resp["platform"]["tenant"] = result.get("tenant") or data.get('tenant')
    if _grafana_requested():
        try:
            resp["grafana"] = _mirror_grafana_upsert(
                email, data.get('password'), result["full_name"], result["role"]
            )
        except Exception as e:  # Supabase already written; do not roll back (§7)
            logger.error(f"[provision_upsert] Grafana mirror failed for {email}: {e}")
            return {"status": "error", "error": "grafana_unavailable", "detail": str(e)}, 502
    logger.info(f"User upserted via provisioning: {email} ({result['action']})")
    return resp, 200


@server_users_bp.route('', methods=['POST'])
@require_admin_role
@handle_route_exceptions('users:create_user')
def create_user():
    """Create / upsert a user (external provisioning). Idempotent: create-if-absent then update."""
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip()
    if not email:
        return jsonify({"status": "error", "error": "invalid_payload",
                        "detail": "email is required"}), 400
    # TASK-23: `tenant` is super-admin only. Regular admins (role='admin',
    # is_platform_admin=false) cannot scope a user into a specific tenant —
    # they don't even know tenants exist.
    if data.get('tenant') and not _caller_is_platform_admin():
        return jsonify({
            "status": "error",
            "error": "forbidden",
            "detail": "tenant scoping requires platform-admin (super admin) access",
        }), 403
    body, status = _provision_upsert(email, data)
    return jsonify(body), status


@server_users_bp.route('', methods=['GET'])
@require_admin_role
@handle_route_exceptions('users:get_users')
def get_users():
    """
    Get all users (admin only)
    Returns user profiles with team information
    """
    users = users_db.get_all_users()
    return jsonify(users), 200
    
@server_users_bp.route('/<user_id>', methods=['GET'])
@require_admin_role
@handle_route_exceptions('users:get_user')
def get_user(user_id: str):
    """
    Get a specific user. UUID -> full profile (VirtualPyTest UI, unchanged).
    Email -> read-only VirtualPyTest-only status (§3.4): exists:false + 200 when absent.
    """
    if _is_email(user_id):
        # A GET on this address only READS status — it never writes a password. Callers land
        # here by mistake: they copy the password-reset curl from the provisioning doc and
        # drop `-X PUT` (and the `-d`, or curl would send POST), so the reset never runs while
        # the read answers `200 {"exists": true}` — which reads exactly like success. Anything
        # carrying write intent (`?grafana=`, the mirror flag, or a password) is that mistake,
        # not a status check, so name the right call instead of answering 200.
        if _grafana_requested() or _password_supplied():
            return jsonify({
                "status": "error",
                "error": "method_not_allowed",
                "detail": (
                    "GET only reads this user's status and never changes a password. "
                    f"To set the password, use: PUT /server/users/{user_id}?grafana=true "
                    'with body {"password": "..."}.'
                ),
            }), 405, {"Allow": "GET, PUT, DELETE"}

        u = users_db.get_user_by_email(user_id)
        if not u:
            return jsonify({"status": "ok", "exists": False, "email": user_id}), 200
        return jsonify({
            "status": "ok", "exists": True, "email": u["email"],
            "platform": {"user_id": u["id"], "role": u["role"], "team": u["team"],
                         "full_name": u["full_name"],
                         "provider_type": u["provider_type"]},
        }), 200

    user = users_db.get_user(user_id)

    if not user:
        return jsonify({"error": "User not found"}), 404

    return jsonify(user), 200
    
@server_users_bp.route('/<user_id>', methods=['PUT'])
@require_admin_role
@handle_route_exceptions('users:update_user')
def update_user(user_id: str):
    """
    Update a user profile
    """
    data = request.get_json(silent=True)

    if _is_email(user_id):
        # Provisioning edit = upsert (self-heals if absent); role/permissions untouched.
        # `password` is optional here: with one the call resets it, without one it edits
        # full_name / provider_type / group and leaves the password untouched. It is only
        # required when the user does not exist yet and the upsert has to create them.
        # Errors keep the provisioning shape (status/error/detail) external callers parse,
        # not the UI shape below.
        if not data:
            return jsonify({"status": "error", "error": "invalid_payload",
                            "detail": "a body with at least one field to change is required"}), 400
        body, status = _provision_upsert(user_id, data)
        return jsonify(body), status

    if not data:
        return jsonify({"error": "No data provided"}), 400

    user = users_db.update_user(user_id, data)

    if not user:
        return jsonify({"error": "User not found"}), 404

    # VirtualPyTest owns role; when an admin changes it here, keep Grafana's org role
    # in sync. Best-effort: a Grafana hiccup must not fail the VirtualPyTest update.
    if 'role' in data and user.get('email'):
        try:
            from shared.src.lib.utils.grafana_admin import grafana_set_org_role
            grafana_set_org_role(user['email'], grafana_role_for(user.get('role', 'viewer')),
                                 org_id=grafana_org_id())
        except Exception as e:
            logger.warning(f"[update_user] Grafana org-role sync skipped for {user_id}: {e}")

    logger.info(f"User updated: {user_id}")
    return jsonify(user), 200
    
@server_users_bp.route('/<user_id>', methods=['DELETE'])
@require_admin_role
@handle_route_exceptions('users:delete_user')
def delete_user(user_id: str):
    """
    Delete a user (admin only)
    Note: This deletes from auth.users which cascades to profiles
    """
    if _is_email(user_id):
        existed = users_db.get_user_by_email(user_id) is not None
        # Report a failed delete instead of a false success. delete_user_by_email
        # returns True when the user is absent, so False means the delete itself
        # failed — and offboarding is the worst place to claim success wrongly.
        # Do NOT fall through to Grafana: that would strip the person's dashboards
        # while leaving their platform access intact.
        if not users_db.delete_user_by_email(user_id):
            logger.error(f"[delete_user] Platform delete failed for {user_id}")
            return jsonify({"status": "error", "error": "internal_error",
                            "detail": "Failed to delete the platform user"}), 500
        if _grafana_requested():
            try:
                _mirror_grafana_delete(user_id)
            except Exception as e:
                logger.error(f"[delete_user] Grafana delete failed for {user_id}: {e}")
                return jsonify({"status": "error", "error": "grafana_unavailable",
                                "detail": str(e)}), 502
        return jsonify({"status": "ok",
                        "action": "deleted" if existed else "absent",
                        "email": user_id}), 200

    # users_db.delete_user returns False for "absent" AND for "delete failed";
    # resolve the user first so a real failure is not reported as a 404.
    if not users_db.get_user(user_id):
        return jsonify({"error": "User not found"}), 404

    if not users_db.delete_user(user_id):
        logger.error(f"[delete_user] Delete failed for {user_id}")
        return jsonify({"error": "Failed to delete user"}), 500

    logger.info(f"User deleted: {user_id}")
    return jsonify({"message": "User deleted successfully"}), 200
    
@server_users_bp.route('/<user_id>/assign-team', methods=['POST'])
@require_admin_role
@handle_route_exceptions('users:assign_user_to_team')
def assign_user_to_team(user_id: str):
    """
    Assign a user to a team (admin only)
    Sets the primary team_id and optionally adds to team_members
    """
    data = request.get_json()
    
    if not data or not data.get('team_id'):
        return jsonify({"error": "team_id is required"}), 400
    
    team_id = data['team_id']
    # Accepts an email as well as a UUID — provisioning callers only hold the email.
    resolved = users_db.resolve_user_id(user_id)
    if not resolved:
        return jsonify({"error": "User not found"}), 404

    success = users_db.assign_user_to_team(resolved, team_id, data.get('team_role', 'member'))
    
    if not success:
        return jsonify({"error": "Failed to assign user to team"}), 500
    
    logger.info(f"User {user_id} assigned to team {team_id}")
    return jsonify({"message": "User assigned to team successfully"}), 200
    
@server_users_bp.route('/<user_id>/remove-team', methods=['POST'])
@require_admin_role
@handle_route_exceptions('users:remove_user_from_team')
def remove_user_from_team(user_id: str):
    """
    Remove a user from a team (admin only)
    """
    data = request.get_json()
    
    if not data or not data.get('team_id'):
        return jsonify({"error": "team_id is required"}), 400
    
    team_id = data['team_id']
    # Accepts an email as well as a UUID — provisioning callers only hold the email.
    resolved = users_db.resolve_user_id(user_id)
    if not resolved:
        return jsonify({"error": "User not found"}), 404

    success = users_db.remove_user_from_team(resolved, team_id)
    
    if not success:
        return jsonify({"error": "Failed to remove user from team"}), 500
    
    logger.info(f"User {user_id} removed from team {team_id}")
    return jsonify({"message": "User removed from team successfully"}), 200
    