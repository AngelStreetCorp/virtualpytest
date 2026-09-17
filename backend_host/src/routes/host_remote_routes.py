"""
Host Remote Routes

Host-side remote control endpoints that execute remote commands using instantiated remote controllers.
"""

from flask import Blueprint, jsonify
from backend_host.src.lib.utils.route_decorators import route_exception_handler
from backend_host.src.lib.utils.host_utils import (
    get_controller,
    get_device_by_id,
    get_remote_controller_by_type
)
from backend_host.src.lib.utils.route_request import get_json_payload, require_field
from backend_host.src.lib.utils.route_response import (
    bad_request,
    controller_missing_for_device
)
import time

# Create blueprint
host_remote_bp = Blueprint('host_remote', __name__, url_prefix='/host/remote')

# =====================================================
# REMOTE CONTROLLER ENDPOINTS
# =====================================================

@host_remote_bp.route('/takeScreenshot', methods=['POST'])
@route_exception_handler()
def take_screenshot():
    data = get_json_payload()
    device_id = data.get('device_id', 'device1')
    
    print(f"[@route:host_remote:take_screenshot] Taking screenshot for device: {device_id}")
    
    # Get remote controller for the specified device
    remote_controller = get_controller(device_id, 'remote')
    
    if not remote_controller:
        return controller_missing_for_device('remote', device_id)
    
    print(f"[@route:host_remote:take_screenshot] Using remote controller: {type(remote_controller).__name__}")
    
    success, screenshot_data, error = remote_controller.take_screenshot()
    
    if success:
        processed_screenshot = screenshot_data
        
        return jsonify({
            'success': True,
            'screenshot': processed_screenshot,
            'device_id': device_id
        })
    else:
        return jsonify({
            'success': False,
            'error': error or 'Screenshot failed'
        }), 400
        
@host_remote_bp.route('/screenshotAndDump', methods=['POST'])
@route_exception_handler()
def screenshot_and_dump():
    data = get_json_payload()
    device_id = data.get('device_id', 'device1')
    
    print(f"[@route:host_remote:screenshot_and_dump] Taking screenshot and dumping UI for device: {device_id}")
    
    # Get remote controller for the specified device
    remote_controller = get_controller(device_id, 'remote')
    
    if not remote_controller:
        return controller_missing_for_device('remote', device_id)
    
    print(f"[@route:host_remote:screenshot_and_dump] Using remote controller: {type(remote_controller).__name__}")
    
    screenshot_success, screenshot_data, screenshot_error = remote_controller.take_screenshot()
    
    ui_success, elements, ui_error = False, [], None
    if hasattr(remote_controller, 'dump_elements'):
        ui_success, elements, ui_error = remote_controller.dump_elements()
        
        # Store elements in controller for subsequent click operations
        if ui_success and elements:
            remote_controller.last_ui_elements = elements
            print(f"[@route:host_remote:screenshot_and_dump] Stored {len(elements)} elements in controller for clicking")
    
    response = {
        'success': screenshot_success and (ui_success or not hasattr(remote_controller, 'dump_elements')),
        'device_id': device_id
    }
    
    if screenshot_success:
        response['screenshot'] = screenshot_data
    
    if ui_success:
        elements_data = []
        for element in elements:
            # Parse bounds string to object format expected by frontend
            bounds_obj = {'left': 0, 'top': 0, 'right': 0, 'bottom': 0}
            if element.bounds and element.bounds != '':
                import re
                # Bounds format: [x1,y1][x2,y2]
                bounds_match = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', element.bounds)
                if bounds_match:
                    x1, y1, x2, y2 = map(int, bounds_match.groups())
                    bounds_obj = {'left': x1, 'top': y1, 'right': x2, 'bottom': y2}
            
            elements_data.append({
                'id': element.id,
                'text': element.text,
                'className': element.class_name,
                'contentDesc': element.content_desc,
                'package': element.resource_id,
                'bounds': bounds_obj,
                'clickable': element.clickable,
                'enabled': element.enabled,
                'xpath': element.xpath if hasattr(element, 'xpath') else None
            })
        response['elements'] = elements_data
    
    if not response['success']:
        error_messages = []
        if not screenshot_success:
            error_messages.append(f"Screenshot: {screenshot_error}")
        if not ui_success and hasattr(remote_controller, 'dump_elements'):
            error_messages.append(f"UI dump: {ui_error}")
        response['error'] = "; ".join(error_messages)
        return jsonify(response), 400
    
    return jsonify(response)
        
@host_remote_bp.route('/getApps', methods=['POST'])
@route_exception_handler()
def get_apps():
    data = get_json_payload()
    device_id = data.get('device_id', 'device1')
    
    print(f"[@route:host_remote:get_apps] Getting installed apps for device: {device_id}")
    
    # Get remote controller for the specified device
    remote_controller = get_controller(device_id, 'remote')
    
    if not remote_controller:
        return controller_missing_for_device('remote', device_id)
    
    print(f"[@route:host_remote:get_apps] Using remote controller: {type(remote_controller).__name__}")
    
    if not hasattr(remote_controller, 'get_installed_apps'):
        return jsonify({
            'success': False,
            'error': 'App listing not supported by this remote controller'
        }), 400
    
    apps = remote_controller.get_installed_apps()
    
    apps_data = []
    for app in apps:
        apps_data.append({
            'packageName': app.package_name,
            'label': app.label
        })
    
    return jsonify({
        'success': True,
        'apps': apps_data,
        'device_id': device_id
    })
        
@host_remote_bp.route('/tapCoordinates', methods=['POST'])
@route_exception_handler()
def tap_coordinates():
    data = get_json_payload()
    x = data.get('x')
    y = data.get('y')
    device_id = data.get('device_id', 'device1')
    
    if x is None or y is None:
        return bad_request('Missing required parameters: x, y')
        
    print(f"[@route:host_remote] Handling tap coordinates: ({x}, {y}) for device: {device_id}")
    
    # Get remote controller for the specified device
    remote_controller = get_controller(device_id, 'remote')
    
    if not remote_controller:
        return controller_missing_for_device('remote', device_id)
        
    # Execute tap command through remote controller
    success = remote_controller.tap_coordinates(x, y)
    
    if success:
        print(f"[@route:host_remote] Tap executed successfully at ({x}, {y}) for device: {device_id}")
        return jsonify({
            'success': True,
            'message': f'Tap executed at coordinates ({x}, {y})',
            'device_id': device_id
        })
    else:
        print(f"[@route:host_remote] Tap failed for device: {device_id}")
        return jsonify({
            'success': False,
            'error': 'Tap execution failed'
        }), 500
        
@host_remote_bp.route('/executeCommand', methods=['POST'])
@route_exception_handler()
def execute_command():
    data = get_json_payload()
    command, command_error = require_field(data, 'command', message='command is required')
    if command_error:
        return command_error

    params = data.get('params', {})
    device_id = data.get('device_id', 'device1')
    remote_type = data.get('remote_type')  # NEW: Get specific remote type
    
    # Read-only status/diagnostic commands (get_pairing_status, get_logs, etc.)
    # are polled continuously by the frontend (every 1-5s). Avoid printing the
    # routing breadcrumbs for them — they pollute journalctl and hide real
    # actions. Real commands (press_key, start_pairing, resume, wake) still log.
    _is_get = command.startswith('get_')
    if not _is_get:
        print(f"[@route:host_remote:execute_command] Executing command: {command} with params: {params} for device: {device_id}")
        if remote_type:
            print(f"[@route:host_remote:execute_command] Requested remote type: {remote_type}")

    # Get remote controller for the specified device
    if remote_type:
        # Use specific remote type if provided
        remote_controller = get_remote_controller_by_type(device_id, remote_type, quiet=_is_get)
    else:
        # Fallback to default behavior (first remote controller)
        remote_controller = get_controller(device_id, 'remote')

    if not remote_controller:
        return controller_missing_for_device('remote', device_id)

    if not _is_get:
        print(f"[@route:host_remote:execute_command] Using remote controller: {type(remote_controller).__name__}")
    
    # Use controller-specific abstraction - single line!
    result = remote_controller.execute_command(command, params)
    
    # Handle dict returns (e.g., from find_element) vs boolean returns
    if isinstance(result, dict):
        success = result.get('success', False)
        # Keep the full result dict to return additional data (matches, etc.)
        result_data = result
    else:
        success = result
        result_data = {'success': success}
    
    # Write action metadata to frame JSON for automatic zap measurement (if successful).
    # Skip read-only status/diagnostic commands (get_pairing_status, get_logs, etc.) —
    # they're polled continuously by the frontend and don't represent a user action that
    # should be correlated with a video frame.
    if success and not command.startswith('get_'):
        try:
            print(f"[@route:host_remote:execute_command] 🎬 Action succeeded, writing to frame JSON and last_action.json...")
            from backend_host.src.lib.utils.frame_metadata_utils import write_action_to_frame_json
            device = get_device_by_id(device_id)
            if device:
                action_completion_timestamp = time.time()
                print(f"[@route:host_remote:execute_command] 📝 Calling write_action_to_frame_json: device={device_id}, cmd={command}, ts={action_completion_timestamp}")
                write_action_to_frame_json(
                    device=device,
                    action={'command': command, 'params': params},
                    action_completion_timestamp=action_completion_timestamp
                )
                print(f"[@route:host_remote:execute_command] ✅ write_action_to_frame_json completed")
            else:
                print(f"[@route:host_remote:execute_command] ❌ Device not found for device_id: {device_id}")
        except Exception as e:
            # Non-blocking - log but don't fail the command
            print(f"[@route:host_remote:execute_command] ❌ Frame JSON write failed (non-blocking): {e}")
            import traceback
            traceback.print_exc()
    
    return jsonify({
        **result_data,  # Include all result data (matches, etc.)
        'message': f'Command {command} {"executed successfully" if success else "failed"}',
        'device_id': device_id
    })
        
@host_remote_bp.route('/dumpUi', methods=['POST'])
@route_exception_handler()
def dump_ui():
    # Get device_id from request (defaults to device1)
    data = get_json_payload()
    device_id = data.get('device_id', 'device1')
    
    print(f"[@route:host_remote:dump_ui] Dumping UI elements without screenshot for device: {device_id}")
    
    # Get remote controller for the specified device
    remote_controller = get_controller(device_id, 'remote')
    
    if not remote_controller:
        return controller_missing_for_device('remote', device_id)
    
    print(f"[@route:host_remote:dump_ui] Using remote controller: {type(remote_controller).__name__}")
    
    if not hasattr(remote_controller, 'dump_elements'):
        return jsonify({
            'success': False,
            'error': 'UI dump not supported by this remote controller'
        }), 400
    
    ui_success, elements, ui_error = remote_controller.dump_elements()
    
    if ui_success:
        # Store elements in controller for subsequent click operations
        if elements:
            remote_controller.last_ui_elements = elements
            print(f"[@route:host_remote:dump_ui] Stored {len(elements)} elements in controller for clicking")
        
        # Serialize elements to JSON format (same as screenshotAndDump)
        elements_data = []
        for element in elements:
            # Parse bounds string to object format expected by frontend
            bounds_obj = {'left': 0, 'top': 0, 'right': 0, 'bottom': 0}
            if element.bounds and element.bounds != '':
                import re
                # Bounds format: [x1,y1][x2,y2]
                bounds_match = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', element.bounds)
                if bounds_match:
                    x1, y1, x2, y2 = map(int, bounds_match.groups())
                    bounds_obj = {'left': x1, 'top': y1, 'right': x2, 'bottom': y2}
            
            elements_data.append({
                'id': element.id,
                'text': element.text,
                'className': element.class_name,
                'contentDesc': element.content_desc,
                'package': element.resource_id,
                'bounds': bounds_obj,
                'clickable': element.clickable,
                'enabled': element.enabled,
                'xpath': element.xpath if hasattr(element, 'xpath') else None
            })
        
        print(f"[@route:host_remote:dump_ui] UI dump successful, found {len(elements_data)} elements")
        
        return jsonify({
            'success': True,
            'elements': elements_data,
            'device_id': device_id
        })
    else:
        print(f"[@route:host_remote:dump_ui] UI dump failed: {ui_error}")
        return jsonify({
            'success': False,
            'error': ui_error or 'UI dump failed'
        }), 400

@host_remote_bp.route('/getOrientation', methods=['POST'])
@route_exception_handler()
def get_orientation():
    # Get device_id from request (defaults to device1)
    data = get_json_payload()
    device_id = data.get('device_id', 'device1')

    # Get remote controller for the specified device
    remote_controller = get_controller(device_id, 'remote')

    if not remote_controller:
        return controller_missing_for_device('remote', device_id)

    if not hasattr(remote_controller, 'get_orientation'):
        return jsonify({
            'success': False,
            'error': 'Orientation detection not supported by this remote controller'
        }), 400

    orientation = remote_controller.get_orientation()

    if orientation:
        return jsonify({
            'success': True,
            'width': orientation['width'],
            'height': orientation['height'],
            'is_landscape': orientation['is_landscape'],
            'device_id': device_id
        })
    else:
        return jsonify({
            'success': False,
            'error': 'Failed to read device orientation'
        }), 400

