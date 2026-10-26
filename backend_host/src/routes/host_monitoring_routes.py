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
    result = av_controller.monitoring_helpers.get_latest_monitoring_json(
        capture_fallback=bool(data.get('capture_fallback'))
    )
    
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
    


def _ad_device_base(device_id):
    """The device folder ad_meter writes into (ad_breaks.jsonl, ads/), or None."""
    from shared.src.lib.utils.storage_path_utils import get_capture_folder, get_device_base_path
    av_controller = get_controller(device_id, 'av')
    if not av_controller:
        return None, None
    capture_folder = get_capture_folder(av_controller.video_capture_path)
    return (capture_folder, get_device_base_path(capture_folder)) if capture_folder else (capture_folder, None)


@host_monitoring_bp.route('/ad-breaks', methods=['POST'])
@route_exception_handler()
def get_ad_breaks():
    """The commercial breaks ad_meter found on one device in the last `hours` (24 by default), newest first, each with its
    thumbnails (ads/<break>/<t>.jpg, served by the stream route) and whether a person marked it as not an ad."""
    import json
    import os
    import time
    data = get_json_payload()
    device_id = data.get('device_id', 'device1')
    hours = min(72.0, max(1.0, float(data.get('hours', 24))))
    capture_folder, base = _ad_device_base(device_id)
    if not base:
        return controller_missing_for_device('AV', device_id)
    path = os.path.join(base, 'ad_breaks.jsonl')
    since = time.time() - hours * 3600
    breaks, not_ad = [], set()
    if os.path.isfile(path):
        with open(path) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get('type') == 'correction' and r.get('not_ad'):
                    not_ad.add(r.get('id'))
                elif r.get('type') == 'break' and (r.get('end') or 0) >= since:
                    breaks.append(r)
    out = [{'id': r.get('id'), 'start': r.get('start'), 'end': r.get('end'), 'duration_s': r.get('duration_s'),
            'kind': r.get('kind'), 'confidence': r.get('confidence'), 'opened_by': r.get('opened_by'),
            'thumbs': r.get('thumbs') or [], 'not_ad': r.get('id') in not_ad} for r in breaks]
    out.sort(key=lambda b: b['start'] or 0, reverse=True)
    return jsonify({'success': True, 'device_id': device_id, 'capture_folder': capture_folder, 'hours': hours, 'breaks': out})


@host_monitoring_bp.route('/ad-breaks/not-ad', methods=['POST'])
@route_exception_handler()
def mark_ad_break_not_ad():
    """A person says a break was not an ad. The monitor process owns ad_meter's state, so this only drops a request file into
    ads/requests/; ad_meter applies it within ~5 s (unlearns its frames, records the correction)."""
    import json
    import os
    import re
    import time
    data = get_json_payload()
    device_id = data.get('device_id', 'device1')
    break_id = str(data.get('break_id') or '')
    if not re.fullmatch(r'[A-Za-z0-9_\-]+:\d+', break_id):
        return jsonify({'success': False, 'error': 'break_id must look like capture5:1793000000'}), 400
    _, base = _ad_device_base(device_id)
    if not base:
        return controller_missing_for_device('AV', device_id)
    req_dir = os.path.join(base, 'ads', 'requests')
    os.makedirs(req_dir, exist_ok=True)
    name = f"{int(time.time() * 1000)}_{break_id.replace(':', '_')}.json"
    with open(os.path.join(req_dir, name), 'w') as f:
        json.dump({'break_id': break_id, 'requested_at': time.time()}, f)
    return jsonify({'success': True, 'break_id': break_id, 'queued': True})
