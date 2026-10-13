"""
features/companion/backend_host — host side of the live-TV companion (TASK-05).

The pipeline itself runs in its own service (vpt-companion, companion_monitor.py), separate from
capture_monitor so it can never touch the realtime detection path. This in-process part only
serves the result that service writes:

POST /host/companion/latest {device_id} -> {success, companion} (companion null when the device
is not opted in or nothing has been identified yet).
"""
import os
import time

from flask import Blueprint, jsonify, request

from ..lib.store import read_result, result_path

companion_host_bp = Blueprint('feature_companion_host', __name__, url_prefix='/host/companion')

# A result older than this means the service is not running for the device.
STALE_S = 120


@companion_host_bp.route('/latest', methods=['POST'])
def latest():
    device_id = (request.get_json(silent=True) or {}).get('device_id', 'device1')
    try:
        path = result_path(device_id)
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 404
    try:
        fresh = time.time() - os.path.getmtime(path) < STALE_S
    except OSError:
        fresh = False
    return jsonify({'success': True, 'companion': read_result(path) if fresh else None})


def register(app) -> None:
    app.register_blueprint(companion_host_bp)
