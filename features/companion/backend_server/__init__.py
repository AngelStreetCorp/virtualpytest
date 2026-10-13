"""
features/companion/backend_server — server side of the live-TV companion (TASK-05).

register(app) is called by shared/src/lib/utils/features.py from backend_server/src/app.py:
- declares the feature's AI usage keys (vision.companion, vision.companion.roi,
  text.web.companion) through the core usages.register() hook;
- POST /server/companion/latest {host_name, device_id} -> the host's latest companion result.
"""
from flask import Blueprint, jsonify, request

from backend_server.src.lib.utils.route_utils import proxy_to_host_with_params

from ..lib.usages import register_usages

companion_bp = Blueprint('feature_companion', __name__, url_prefix='/server/companion')


@companion_bp.route('/latest', methods=['POST'])
def latest():
    """Latest companion result of one device (proxied to its host)."""
    data = request.get_json() or {}
    device_id = data.get('device_id', 'device1')
    body, status = proxy_to_host_with_params('/host/companion/latest', 'POST', data, {'device_id': device_id})
    return jsonify(body), status


def register(app) -> None:
    register_usages()
    app.register_blueprint(companion_bp)
