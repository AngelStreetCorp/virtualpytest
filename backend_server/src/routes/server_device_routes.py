"""
Device Management Routes

API endpoints for device management.
Queries device_flags table which contains devices auto-registered from hosts.
"""

from flask import Blueprint, request, jsonify

from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.utils.route_response import service_result_simple

server_device_bp = Blueprint('server_device', __name__, url_prefix='/server/devices')


@server_device_bp.route('/getAllDevices', methods=['GET'])
@handle_route_exceptions('server_device:getAllDevices')
def get_devices():
    """Get all devices from device_flags table"""
    from services.device_service import device_service
    result = device_service.get_all_devices()
    return service_result_simple(result, success_data_key='devices')


@server_device_bp.route('/createDevice', methods=['POST'])
@handle_route_exceptions('server_device:createDevice')
def create_device_endpoint():
    """Create a new device in device_flags table"""
    device_data = request.json
    from services.device_service import device_service
    result = device_service.save_device(device_data)
    return service_result_simple(
        result,
        success_data_key='device',
        success_status=201,
        success_wrapper=lambda d: {'status': 'success', 'device': d}
    )


@server_device_bp.route('/getDevice/<device_id>', methods=['GET'])
@handle_route_exceptions('server_device:getDevice')
def get_device_endpoint(device_id):
    """Get a specific device by device_id"""
    host_name = request.args.get('host_name')
    from services.device_service import device_service
    result = device_service.get_device(device_id, host_name)
    return service_result_simple(result, success_data_key='device')


@server_device_bp.route('/updateDevice/<device_id>', methods=['PUT'])
@handle_route_exceptions('server_device:updateDevice')
def update_device_endpoint(device_id):
    """Update a specific device"""
    device_data = request.json or {}
    device_data['device_id'] = device_id
    from services.device_service import device_service
    result = device_service.save_device(device_data)
    return service_result_simple(
        result,
        success_data_key='device',
        success_wrapper=lambda d: {'status': 'success', 'device': d}
    )


@server_device_bp.route('/deleteDevice/<device_id>', methods=['DELETE'])
@handle_route_exceptions('server_device:deleteDevice')
def delete_device_endpoint(device_id):
    """Delete a specific device"""
    host_name = request.args.get('host_name')
    from services.device_service import device_service
    result = device_service.delete_device(device_id, host_name)
    return service_result_simple(result, success_payload={'status': 'success'})
