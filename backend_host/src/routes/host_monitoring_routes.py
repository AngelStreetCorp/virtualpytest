"""
Host Monitoring Routes

Monitoring system endpoints for capture frame listing and JSON analysis file retrieval.
"""

from flask import Blueprint, request, jsonify
from backend_host.src.lib.utils.route_decorators import route_exception_handler
from backend_host.src.lib.utils.host_utils import get_controller
from backend_host.src.lib.utils.route_request import get_json_payload
from backend_host.src.lib.utils.route_response import controller_missing_for_device
from backend_host.src.services.disk_usage_service import DiskUsageService

host_monitoring_bp = Blueprint('host_monitoring', __name__, url_prefix='/host/monitoring')

@host_monitoring_bp.route('/listCaptures', methods=['POST'])
@route_exception_handler()
def list_captures():
    data = get_json_payload()
    device_id = data.get('device_id', 'device1')
    limit = data.get('limit', 180)
    
    # Get AV controller to access monitoring helpers
    av_controller = get_controller(device_id, 'av')
    
    if not av_controller:
        return controller_missing_for_device('AV', device_id)
    
    # Use monitoring helpers
    result = av_controller.monitoring_helpers.list_captures(limit)
    
    return jsonify(result)
    
@host_monitoring_bp.route('/latest-json', methods=['POST'])
@route_exception_handler()
def get_latest_monitoring_json():
    data = get_json_payload()
    device_id = data.get('device_id', 'device1')
    
    # Get AV controller to access monitoring helpers
    av_controller = get_controller(device_id, 'av')
    
    if not av_controller:
        return controller_missing_for_device('AV', device_id)
    
    # Use monitoring helpers
    result = av_controller.monitoring_helpers.get_latest_monitoring_json()
    
    return jsonify(result)
    
# REMOVED: /json-by-time endpoint (Legacy)
# Frontend now fetches metadata chunks directly via nginx (see useMonitoring.ts)
# Direct chunk fetching is faster, simpler, and allows client-side caching

@host_monitoring_bp.route('/disk-usage', methods=['GET'])
@route_exception_handler()
def disk_usage_diagnostics():
    capture_filter = request.args.get('capture_dir', 'all')
    result = DiskUsageService.get_complete_diagnostics(capture_filter)
    
    if not result.get('success'):
        return jsonify(result), 404
    
    return jsonify(result)
    
@host_monitoring_bp.route('/live-events', methods=['POST'])
@route_exception_handler()
def get_live_events():
    import os
    import json
    from datetime import datetime
    from shared.src.lib.utils.storage_path_utils import get_metadata_path, get_capture_folder
    
    data = get_json_payload()
    device_id = data.get('device_id', 'device1')
    
    # Get av_controller to access video_capture_path (same pattern as host_av_routes.py)
    av_controller = get_controller(device_id, 'av')
    if not av_controller:
        return controller_missing_for_device('AV', device_id)
    
    # Get capture folder from controller's video_capture_path
    capture_folder = get_capture_folder(av_controller.video_capture_path)
    if not capture_folder:
        return jsonify({
            'success': False,
            'error': f'Could not determine capture folder for device {device_id}'
        }), 404
    
    metadata_path = get_metadata_path(capture_folder)
    live_events_file = os.path.join(metadata_path, 'live_events.json')
    
    # Read live events
    events = []
    if os.path.exists(live_events_file):
        try:
            with open(live_events_file, 'r') as f:
                file_data = json.load(f)
                events = file_data.get('events', [])
                
            # Filter out expired events
            current_time = datetime.now().timestamp()
            events = [e for e in events if e.get('expires_at', 0) > current_time]
            
        except Exception as e:
            # If file is corrupted or being written, return empty list
            events = []
    
    return jsonify({
        'success': True,
        'events': events,
        'count': len(events)
    })
    
