"""Host Timeline Routes (TASK-94): is the Timeline built for a device, and how far along.

The sprites and tracks themselves are static files under `thumbnails/<hour>/` (served by the
host nginx like the other archive files); only this status needs a route."""

import os

from flask import Blueprint, request, jsonify

from backend_host.src.lib.utils.route_decorators import route_exception_handler

host_timeline_bp = Blueprint('host_timeline', __name__, url_prefix='/host/timeline')


@host_timeline_bp.route('/status', methods=['GET'])
@route_exception_handler()
def timeline_status():
    """`enabled` (opted in), `chunks` (in the archive manifest), `backlog` (finished chunks without a sprite)."""
    from backend_host.scripts.timeline import service
    from shared.src.lib.utils.storage_path_utils import get_capture_folder_from_device_id

    device_id = request.args.get('device_id')
    if not device_id:
        return jsonify({'success': False, 'error': 'device_id is required'}), 400
    capture_folder = get_capture_folder_from_device_id(device_id)
    if not capture_folder:
        return jsonify({'success': False, 'error': f'unknown device {device_id}'}), 404
    capture_dir = os.path.join('/var/www/html/stream', capture_folder)
    return jsonify({'success': True, 'device_id': device_id, **service.status(capture_dir)})
