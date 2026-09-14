"""
Host Control Routes

This module contains host-side control endpoints that:
- Handle controller status checking on host devices
- Manage local device control operations
- Execute device-specific control commands
- Use stored host_device objects for controller access
"""

from flask import Blueprint, jsonify, current_app
from backend_host.src.lib.utils.route_decorators import route_exception_handler
from backend_host.src.lib.utils.host_utils import get_controller, get_device_by_id, list_available_devices
from backend_host.src.lib.utils.route_request import get_json_payload

# Create blueprint
host_control_bp = Blueprint('host_control', __name__, url_prefix='/host')

# =====================================================
# HOST-SIDE DEVICE CONTROL ENDPOINTS
# =====================================================

@host_control_bp.route('/takeControl', methods=['POST'])
@route_exception_handler()
def take_control():
    data = get_json_payload()
    device_id = data.get('device_id', 'default')
    
    print(f"[@route:take_control] Host checking controllers for device: {device_id}")
    
    # Check AV controller
    av_available = False
    try:
        av_controller = get_controller(device_id, 'av')
        
        if av_controller:
            print(f"[@route:take_control] Using AV controller: {type(av_controller).__name__}")
            av_status = av_controller.get_status()
            print(f"[@route:take_control] AV controller status: {av_status}")
            av_available = av_status.get('success', False)
        else:
            print(f"[@route:take_control] ⚠️ WARNING: No AV controller found for device {device_id}")
        
    except Exception as e:
        print(f"[@route:take_control] ⚠️ WARNING: AV controller error: {e}")
    
    # Check remote controller
    remote_available = False
    remote_error = None
    try:
        remote_controller = get_controller(device_id, 'remote')
        
        if remote_controller:
            controller_type = type(remote_controller).__name__
            print(f"[@route:take_control] Using remote controller: {controller_type}")
            
            if controller_type == 'AppiumRemoteController':
                print(f"[@route:take_control] Appium controller - checking server status only")
                remote_status = remote_controller.get_status()
                remote_available = remote_status.get('success', False)
                print(f"[@route:take_control] Appium server status: {remote_status}")
            else:
                if not remote_controller.is_connected:
                    print(f"[@route:take_control] Connecting remote controller to device...")
                    connection_success = remote_controller.connect()
                    remote_available = connection_success
                    if not connection_success:
                        # Get device IP/port for error message
                        device_info = get_device_by_id(device_id)
                        if device_info:
                            device_ip = getattr(device_info, 'device_ip', None)
                            device_port = getattr(device_info, 'device_port', None)
                            if device_ip and device_port:
                                remote_error = f"Failed to connect to Android device {device_ip}:{device_port}"
                            else:
                                remote_error = "Failed to connect to remote controller"
                        else:
                            remote_error = "Failed to connect to remote controller"
                else:
                    print(f"[@route:take_control] Remote controller already connected")
                    remote_available = True
                
                if remote_available:
                    remote_status = remote_controller.get_status()
                    print(f"[@route:take_control] Remote controller status: {remote_status}")
                    remote_available = remote_status.get('success', False)
        else:
            print(f"[@route:take_control] ⚠️ WARNING: No remote controller found for device {device_id}")
                
    except Exception as e:
        print(f"[@route:take_control] ⚠️ WARNING: Remote controller error: {e}")
        remote_error = str(e)
    
    # Build list of available controllers
    available_controllers = []
    if av_available:
        available_controllers.append('av')
    if remote_available:
        available_controllers.append('remote')
    
    # ALWAYS succeed - just warn if no controllers available (needed for localhost testing)
    if not av_available and not remote_available:
        print(f"[@route:take_control] ⚠️ WARNING: No controllers available for device {device_id}, but allowing control for localhost testing")
    
    print(f"[@route:take_control] SUCCESS: Take control succeeded for device: {device_id} with controllers: {available_controllers}")
    
    response = {
        'success': True,
        'available_controllers': available_controllers
    }
    
    # Add warning if remote controller (ADB) failed
    if not remote_available and remote_error:
        response['warning'] = remote_error
        print(f"[@route:take_control] Including warning for frontend toast: {remote_error}")
    
    return jsonify(response)
        
@host_control_bp.route('/releaseControl', methods=['POST'])
@route_exception_handler()
def release_control():
    print(f"[@route:release_control] Host releasing control using own stored host_device")
    
    host_device = getattr(current_app, 'my_host_device', None)
    
    if not host_device:
        print(f"[@route:release_control] No host_device found, assuming already released")
        return jsonify({'success': True})
    
    if not isinstance(host_device, dict):
        return jsonify({
            'success': False,
            'error': 'Host device object invalid'
        }), 500
        
    print(f"[@route:release_control] Host device releasing controllers")
    
    return jsonify({'success': True})
        
@host_control_bp.route('/devices', methods=['GET'])
@route_exception_handler()
def list_devices():
    print(f"[@route:list_devices] Getting available devices")
    
    # Use host_devices registry created in app.py
    host_devices = getattr(current_app, 'host_devices', {})
    
    if not host_devices:
        return jsonify({
            'success': False,
            'error': 'Host device object not initialized'
        })
    
    # Build devices list from registered devices
    devices = []
    for device_id, device in host_devices.items():
        device_info = {
            'device_id': device_id,
            'device_name': getattr(device, 'device_name', device_id),
            'device_model': getattr(device, 'device_model', 'unknown'),
            'device_ip': getattr(device, 'device_ip', None),
            'device_port': getattr(device, 'device_port', None),
            'video_device': None,
            'video_stream_path': None,
            'video_capture_path': None
        }
        devices.append(device_info)
    
    # Get available controller types for each device
    available_device_ids = list_available_devices()
    
    for device in devices:
        device_id = device.get('device_id')
        device['controllers'] = {}
        device['controller_status'] = 'unknown'
        
        # Check if controllers exist for this device
        if device_id in available_device_ids or device_id == 'default':
            # Check AV controller
            av_controller = get_controller(device_id, 'av')
            if av_controller:
                device['controllers']['av'] = {
                    'available': True,
                    'type': type(av_controller).__name__
                }
            
            # Check remote controller
            remote_controller = get_controller(device_id, 'remote')
            if remote_controller:
                device['controllers']['remote'] = {
                    'available': True,
                    'type': type(remote_controller).__name__
                }
            
            # Check verification controller
            verification_controller = get_controller(device_id, 'verification')
            if verification_controller:
                device['controllers']['verification'] = {
                    'available': True,
                    'type': type(verification_controller).__name__
                }
            
            # Check power controller
            power_controller = get_controller(device_id, 'power')
            if power_controller:
                device['controllers']['power'] = {
                    'available': True,
                    'type': type(power_controller).__name__
                }
            
            device['controller_status'] = 'ready' if device['controllers'] else 'no_controllers'
        else:
            device['controller_status'] = 'not_registered'
    
    return jsonify({
        'success': True,
        'devices': devices
    })
    
@host_control_bp.route('/controllerStatus', methods=['GET'])
@route_exception_handler()
def controller_status():
    print(f"[@route:controller_status] Getting controller status")
    
    host_device = getattr(current_app, 'my_host_device', None)
    
    if not host_device:
        return jsonify({
            'success': False,
            'error': 'Host device object not initialized'
        })
    
    if not isinstance(host_device, dict):
        return jsonify({
            'success': False,
            'error': 'Host device object invalid'
        }), 500
        
    controller_status = {}
    controller_objects = host_device.get('controller_objects', {})
    
    # Check each controller
    for controller_name, controller_obj in controller_objects.items():
        try:
            if hasattr(controller_obj, 'get_status'):
                status = controller_obj.get_status()
                controller_status[controller_name] = {
                    'available': True,
                    'status': status,
                    'type': type(controller_obj).__name__
                }
            else:
                controller_status[controller_name] = {
                    'available': True,
                    'status': {'message': 'No status method available'},
                    'type': type(controller_obj).__name__
                }
        except Exception as e:
            controller_status[controller_name] = {
                'available': False,
                'error': str(e),
                'type': type(controller_obj).__name__
            }
    
    return jsonify({
        'success': True,
        'controllers': controller_status
    })
    
