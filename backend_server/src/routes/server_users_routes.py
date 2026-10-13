"""
Users Management Routes
Handles user profile management and team assignments
"""
from flask import Blueprint, request, jsonify
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.device_scope import (
    clean_devices,
    intersect as device_intersect,
    outside as device_outside,
    user_scope,
)
from backend_server.src.lib.auth_middleware import (
    ROLE_RANK,
    caller_is_admin,
    forbid_escalation,
    forbid_role_assignment,
    in_org_scope,
    org_scope_team_ids,
    principal_holds_permission,
    require_permission,
    role_default_permissions,
    _caller_is_platform_admin,
)
from typing import Optional
import logging

from shared.src.lib.database import teams_db, users_db
from backend_server.src.lib.error_handler import handle_error

logger = logging.getLogger(__name__)

server_users_bp = Blueprint('server_users', __name__, url_prefix='/server/users')

from backend_server.src.lib.utils.grafana_config import (
    default_role as _default_role,
    grafana_role_for,
    grafana_org_id,
)


def _out_of_scope(user) -> bool:
    """Is `user` outside the teams the caller manages (TASK-31: managers see only their teams)?"""
    return not in_org_scope((user or {}).get('team_ids'), org_scope_team_ids())


def _resolve_role(value):
    """Internal role id for `value` — a role's preferred name or its id, ignoring case.

    An external platform sends the preferred name it knows ("SuperAdmin" -> admin). Raises
    ValueError listing every accepted name.
    """
    from shared.src.lib.database import roles_db
    resolved = roles_db.resolve_name(str(value or ''))
    if resolved in ROLE_RANK:
        return resolved
    raise ValueError(f"unknown role '{value}'. Accepted: {', '.join(roles_db.role_names())}")


def _provision_guard(email, data, role, team_name):
    """For a non-admin caller: the error response that stops this provisioning call, or None.

    A manager may only provision inside their own teams: an existing user must be in scope,
    the team must already exist and be one of theirs (no auto-created team, no landing in the
    default team outside their view), and the role must rank below their own.
    """
    if caller_is_admin():
        return None
    from shared.src.lib.database import teams_db
    existing = users_db.get_user_by_email(email)
    if existing and _out_of_scope(existing):
        return {"status": "error", "error": "forbidden",
                "detail": "this user is not in one of your teams"}, 403
    if data.get('replace_teams'):
        return {"status": "error", "error": "forbidden",
                "detail": "only an admin can move a user out of every other team"}, 403
    if existing is None and not team_name:
        return {"status": "error", "error": "invalid_payload",
                "detail": "team is required: name one of your teams"}, 400
    if team_name:
        scope = org_scope_team_ids() or set()
        team = next((t for t in teams_db.get_all_teams()
                     if t['name'] == team_name and str(t['id']) in scope), None)
        if not team:
            return {"status": "error", "error": "forbidden",
                    "detail": f"'{team_name}' is not one of your teams"}, 403
    current = existing['role'] if existing else None
    new_role = role or (None if existing else _default_role())
    denied = forbid_role_assignment(current, new_role)
    if denied:
        return denied[0].get_json(), 403
    if new_role and new_role != current:
        denied = forbid_escalation(role_default_permissions(new_role), 'give this role')
        if denied:
            return denied[0].get_json(), 403
    return None


def _above_parent(user_id: str, data: dict):
    """The 400 that stops an edit giving a user more than the level above allows, or None.

    No level may hold what its parent does not allow (TASK-31): individual grants must be inside
    the user's team ceiling (grants beyond the role are fine, decision 6), and the user's own
    device limit inside team ∩ role. Applies to admins too — it is structure, not privilege.
    An admin target holds everything and has no limits to check.
    """
    if 'permissions' not in data and 'allowed_devices' not in data:
        return None
    target = users_db.get_user(user_id)
    if not target:
        return jsonify({"error": "User not found"}), 404
    role = data.get('role') or target.get('role')
    if role == 'admin':
        return None

    ceiling = target.get('team_ceiling')
    if 'permissions' in data and ceiling is not None:
        over = sorted(set(data.get('permissions') or []) - set(ceiling))
        if over:
            return jsonify({"error": "Outside the team limit",
                            "message": "These permissions are not allowed by any of the user's teams",
                            "permissions": over}), 400

    if 'allowed_devices' in data:
        devices, error = clean_devices(data['allowed_devices'])
        if error:
            return jsonify({"error": error}), 400
        from shared.src.lib.database import roles_db
        limit = device_intersect(target.get('team_device_ceiling'), roles_db.role_devices(role))
        over = device_outside(devices, limit)
        if over:
            return jsonify({"error": "Outside the team and role device limit",
                            "devices": over}), 400
        data['allowed_devices'] = devices
    return None


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
    # `team` is the documented name, `group` the original one; both mean the same.
    team_name, group = data.get('team'), data.get('group')
    if team_name and group and team_name != group:
        return {"status": "error", "error": "invalid_payload",
                "detail": "send either team or group, not two different teams"}, 400
    team_name = team_name or group
    if data.get('replace_teams') and not team_name:
        return {"status": "error", "error": "invalid_payload",
                "detail": "replace_teams needs a team"}, 400

    role = None
    if data.get('role') is not None:
        try:
            role = _resolve_role(data['role'])
        except ValueError as e:
            return {"status": "error", "error": "invalid_payload", "detail": str(e)}, 400

    blocked = _provision_guard(email, data, role, team_name)
    if blocked:
        return blocked

    try:
        result = users_db.upsert_user(
            email=email,
            password=data.get('password'),
            full_name=data.get('full_name'),
            group=team_name,
            default_role=_default_role(),
            provider_type=data.get('provider_type'),
            tenant=data.get('tenant'),
            role=role,
            replace_teams=bool(data.get('replace_teams')),
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
        "platform": {"role": result["role"], "teams": result.get("teams", []), "team": result["team"],
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
@require_permission('org.users:create')
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
    # Non-admin limits (own teams, lower role, no escalation) are in _provision_guard.
    body, status = _provision_upsert(email, data)
    return jsonify(body), status


@server_users_bp.route('', methods=['GET'])
@require_permission('org.users:view')
@handle_route_exceptions('users:get_users')
def get_users():
    """
    Get all users (admin only)
    Returns user profiles with team information
    """
    scope = org_scope_team_ids()
    users = [u for u in users_db.get_all_users() if in_org_scope(u.get('team_ids'), scope)]
    return jsonify(users), 200
    
@server_users_bp.route('/<user_id>', methods=['GET'])
@require_permission('org.users:view')
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
        if _out_of_scope(u):
            return jsonify({"status": "error", "error": "forbidden",
                            "detail": "this user is not in one of your teams"}), 403
        return jsonify({
            "status": "ok", "exists": True, "email": u["email"],
            "platform": {"user_id": u["id"], "role": u["role"], "team": u["team"],
                         "full_name": u["full_name"],
                         "provider_type": u["provider_type"]},
        }), 200

    user = users_db.get_user(user_id)

    if not user or _out_of_scope(user):
        return jsonify({"error": "User not found"}), 404

    return jsonify(user), 200
    
@server_users_bp.route('/<user_id>/scope', methods=['GET'])
@handle_route_exceptions('users:get_user_scope')
def get_user_scope(user_id: str):
    """The user's device chain (TASK-31 phase C): team, role and own limits and the effective set.

    `effective_devices: null` means every device. Any signed-in user may read their own; reading
    someone else's needs org.users:view and that user in the caller's teams. A UI filter only —
    the device routes do not consult it.
    """
    caller = getattr(request, 'user_id', None)
    if str(user_id) != str(caller) and not principal_holds_permission('org.users:view'):
        return jsonify({"error": "Forbidden"}), 403
    user = users_db.get_user(user_id)
    if not user or (str(user_id) != str(caller) and _out_of_scope(user)):
        return jsonify({"error": "User not found"}), 404
    if user.get('role') == 'admin':
        return jsonify({"user_id": user_id, "team_devices": None, "role_devices": None,
                        "user_devices": None, "effective_devices": None}), 200
    from shared.src.lib.database import roles_db
    return jsonify({"user_id": user_id,
                    **user_scope(user, roles_db.role_devices(user.get('role')))}), 200


@server_users_bp.route('/<user_id>', methods=['PUT'])
@require_permission('org.users:edit')
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

    if 'role' in data and data['role'] not in ROLE_RANK:
        return jsonify({"error": f"Unknown role '{data['role']}'"}), 400

    if not caller_is_admin():
        target = users_db.get_user(user_id)
        if not target or _out_of_scope(target):
            return jsonify({"error": "User not found"}), 404
        new_role = data.get('role') if data.get('role') != target.get('role') else None
        denied = forbid_role_assignment(target.get('role'), new_role)
        if denied:
            return denied
        if data.get('team_id') and str(data['team_id']) not in (org_scope_team_ids() or set()):
            return jsonify({"error": "Forbidden", "message": "That team is not one of yours"}), 403
        # Everything this edit would newly give the user: added grants, lifted denials,
        # and the defaults of a new role.
        granted = set(data.get('permissions') or []) - set(target.get('permissions') or [])
        if 'denied_permissions' in data:
            granted |= set(target.get('denied_permissions') or []) - set(data['denied_permissions'] or [])
        if data.get('role') and data['role'] != target.get('role'):
            granted |= role_default_permissions(data['role'])
        denied = forbid_escalation(granted, 'edit this user')
        if denied:
            return denied

    blocked = _above_parent(user_id, data)
    if blocked:
        return blocked

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
@require_permission('org.users:delete')
@handle_route_exceptions('users:delete_user')
def delete_user(user_id: str):
    """
    Delete a user (admin only)
    Note: This deletes from auth.users which cascades to profiles
    """
    if not caller_is_admin():
        target = users_db.get_user_by_email(user_id) if _is_email(user_id) else users_db.get_user(user_id)
        if target and _out_of_scope(target):
            return jsonify({"error": "User not found"}), 404
        denied = forbid_role_assignment(target.get('role'), None) if target else None
        if denied:
            return denied

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
@require_permission('org.teams:manage_members')
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

    scope = org_scope_team_ids()
    if scope is not None:
        target = users_db.get_user(resolved)
        if not target or str(team_id) not in scope:
            return jsonify({"error": "User or team not found"}), 404
        denied = forbid_role_assignment(target.get('role'), None)
        if denied:
            return denied

    # A team is a ceiling (TASK-31): joining one never gives a permission, so there is no
    # escalation to check — only that the team exists.
    team = teams_db.get_team(team_id)
    if not team:
        return jsonify({"error": "Team not found"}), 404

    success = users_db.assign_user_to_team(resolved, team_id, data.get('team_role', 'member'))
    
    if not success:
        return jsonify({"error": "Failed to assign user to team"}), 500
    
    logger.info(f"User {user_id} assigned to team {team_id}")
    return jsonify({"message": "User assigned to team successfully"}), 200
    
@server_users_bp.route('/<user_id>/remove-team', methods=['POST'])
@require_permission('org.teams:manage_members')
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

    scope = org_scope_team_ids()
    if scope is not None:
        target = users_db.get_user(resolved)
        if not target or _out_of_scope(target) or str(team_id) not in scope:
            return jsonify({"error": "User or team not found"}), 404

    success = users_db.remove_user_from_team(resolved, team_id)
    
    if not success:
        return jsonify({"error": "Failed to remove user from team"}), 500
    
    logger.info(f"User {user_id} removed from team {team_id}")
    return jsonify({"message": "User removed from team successfully"}), 200
    