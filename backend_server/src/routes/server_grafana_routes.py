"""
Grafana user-provisioning integration route.

The ONLY /integrations route in the design. Owns just the Grafana user
lifecycle; thin HTTP wrapper over shared.src.lib.utils.grafana_admin so any
caller can use it (the /server/users route calls grafana_admin in-process).
"""
import logging

from flask import Blueprint, request, jsonify

from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from shared.src.lib.utils.grafana_admin import (
    grafana_upsert_user,
    grafana_delete_user,
    grafana_set_org_role,
)

logger = logging.getLogger(__name__)

server_grafana_bp = Blueprint(
    'server_grafana', __name__, url_prefix='/server/integrations/grafana'
)


@server_grafana_bp.route('/users', methods=['POST'])
@handle_route_exceptions('grafana:upsert_user')
def grafana_users_upsert():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip()
    if not email:
        return jsonify({"status": "error", "error": "invalid_payload",
                        "detail": "email is required"}), 400
    try:
        result = grafana_upsert_user(
            email=email,
            password=data.get('password'),
            full_name=data.get('full_name'),
            org_role=data.get('org_role', 'Viewer'),
            org_id=int(data.get('org_id', 1)),
        )
        return jsonify({"status": "ok", **result}), 200
    except ValueError as e:
        return jsonify({"status": "error", "error": "invalid_payload",
                        "detail": str(e)}), 400
    except Exception as e:
        logger.error(f"[grafana_users_upsert] {email}: {e}")
        return jsonify({"status": "error", "error": "grafana_unavailable",
                        "detail": str(e)}), 502


@server_grafana_bp.route('/users/<path:email>', methods=['DELETE'])
@handle_route_exceptions('grafana:delete_user')
def grafana_users_delete(email):
    try:
        result = grafana_delete_user(email=email)
        return jsonify({"status": "ok", **result}), 200
    except Exception as e:
        logger.error(f"[grafana_users_delete] {email}: {e}")
        return jsonify({"status": "error", "error": "grafana_unavailable",
                        "detail": str(e)}), 502


@server_grafana_bp.route('/users/<path:email>/org-role', methods=['PATCH'])
@handle_route_exceptions('grafana:set_org_role')
def grafana_users_set_org_role(email):
    data = request.get_json(silent=True) or {}
    org_role = data.get('org_role')
    if not org_role:
        return jsonify({"status": "error", "error": "invalid_payload",
                        "detail": "org_role is required"}), 400
    try:
        result = grafana_set_org_role(
            email=email, org_role=org_role, org_id=int(data.get('org_id', 1))
        )
        return jsonify({"status": "ok", **result}), 200
    except ValueError as e:
        return jsonify({"status": "error", "error": "invalid_payload",
                        "detail": str(e)}), 400
    except Exception as e:
        logger.error(f"[grafana_users_set_org_role] {email}: {e}")
        return jsonify({"status": "error", "error": "grafana_unavailable",
                        "detail": str(e)}), 502
