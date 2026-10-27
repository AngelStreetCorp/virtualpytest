"""
Server stream proxy routes for forwarding requests to hosts
"""

from flask import Blueprint, request, jsonify, Response
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
import json
import re

from shared.src.lib.utils.build_url_utils import call_host
from  backend_server.src.lib.utils.server_utils import get_host_manager

server_stream_proxy_bp = Blueprint('server_stream_proxy', __name__, url_prefix='/server/stream')

@server_stream_proxy_bp.route('/av/screenshot', methods=['POST'])
@handle_route_exceptions('stream_proxy:proxy_screenshot')
def proxy_screenshot():
    """Proxy screenshot request to appropriate host"""
    data = request.get_json()
    host_name = data.get('host_name')
    
    if not host_name:
        return jsonify({'error': 'host_name is required'}), 400
    
    
    print(f"📸 [PROXY] Screenshot request for host: {host_name}")
    
    # Get host from manager
    host_manager = get_host_manager()
    host_data = host_manager.get_host(host_name)
    if not host_data:
        return jsonify({'error': f'Host {host_name} not found'}), 404
    
    # Forward request to host
    print(f"📡 [PROXY] Forwarding screenshot request to host via call_host()")
    
    response_data, status_code = call_host(
        host_data,
        '/host/av/screenshot',
        method='POST',
        data=data,
        timeout=30
    )
    
    if status_code == 200:
        return jsonify(response_data)
    else:
        error_msg = f"Screenshot request failed: {status_code} {response_data.get('error', 'Unknown error')}"
        print(f"❌ [PROXY] {error_msg}")
        return jsonify({'error': error_msg}), status_code
    
@server_stream_proxy_bp.route('/av/streamUrl', methods=['POST'])
@handle_route_exceptions('stream_proxy:proxy_stream_url')
def proxy_stream_url():
    """Proxy stream URL request to appropriate host"""
    data = request.get_json()
    host_name = data.get('host_name')
    
    if not host_name:
        return jsonify({'error': 'host_name is required'}), 400
    
    
    print(f"📺 [PROXY] Stream URL request for host: {host_name}")
    
    # Get host from manager
    host_manager = get_host_manager()
    host_data = host_manager.get_host(host_name)
    if not host_data:
        return jsonify({'error': f'Host {host_name} not found'}), 404
    
    # Forward request to host
    print(f"📡 [PROXY] Forwarding stream URL request to host via call_host()")
    
    response_data, status_code = call_host(
        host_data,
        '/host/av/streamUrl',
        method='POST',
        data=data,
        timeout=30
    )
    
    if status_code == 200:
        return jsonify(response_data)
    else:
        error_msg = f"Stream URL request failed: {status_code} {response_data.get('error', 'Unknown error')}"
        print(f"❌ [PROXY] {error_msg}")
        return jsonify({'error': error_msg}), status_code
    
@server_stream_proxy_bp.route('/verification/execute', methods=['POST'])
@handle_route_exceptions('stream_proxy:proxy_verification')
def proxy_verification():
    """Proxy verification request to appropriate host"""
    data = request.get_json()
    host_name = data.get('host_name')
    
    if not host_name:
        return jsonify({'error': 'host_name is required'}), 400
    
    
    print(f"✅ [PROXY] Verification request for host: {host_name}")
    
    # Get host from manager
    host_manager = get_host_manager()
    host_data = host_manager.get_host(host_name)
    if not host_data:
        return jsonify({'error': f'Host {host_name} not found'}), 404
    
    # Forward request to host with async support
    print(f"📡 [PROXY] Forwarding verification request to host via call_host()")
    
    response_data, status_code = call_host(
        host_data,
        '/host/verification/execute',
        method='POST',
        data=data,
        timeout=60  # Longer timeout for verification
    )
    
    if status_code == 200:
        return jsonify(response_data)
    else:
        error_msg = f"Verification request failed: {status_code} {response_data.get('error', 'Unknown error')}"
        print(f"❌ [PROXY] {error_msg}")
        return jsonify({'error': error_msg}), status_code
    

@server_stream_proxy_bp.route('/hostFile', methods=['GET'])
@handle_route_exceptions('stream_proxy:host_file')
def proxy_host_file():
    """Bytes of one capture a host serves under ``/host/<host_name>/stream/...``, fetched by this server.

    TASK-179 P4: Atlas on another server cannot reach a host's LAN address, so it asks the host's owner server
    for the image. Only that one path shape is relayed (no other host endpoint, no ``..``)."""
    host_name = (request.args.get('host_name') or '').strip()
    path = (request.args.get('path') or '').strip()
    if not host_name or not path:
        return jsonify({'error': 'host_name and path are required'}), 400
    if '..' in path or '//' in path or not re.fullmatch(r'/host/[A-Za-z0-9_.-]+/stream/[A-Za-z0-9_./-]+', path) \
            or path.split('/')[2] != host_name:
        return jsonify({'error': 'path must be /host/<host_name>/stream/<file>'}), 400

    host_data = get_host_manager().get_host(host_name)
    if not host_data:
        return jsonify({'error': f'Host {host_name} not found'}), 404

    content, status_code = call_host(host_data, path, method='GET', timeout=10, raw_response=True)
    if status_code != 200 or not isinstance(content, (bytes, bytearray)) or not content:
        detail = content.get('error') if isinstance(content, dict) else ''
        return jsonify({'error': f'HTTP {status_code} from host {host_name}{": " + detail if detail else ""}'}), \
            status_code if status_code >= 400 else 502
    mimetype = 'image/png' if bytes(content[:8]) == b'\x89PNG\r\n\x1a\n' else 'image/jpeg'
    return Response(bytes(content), mimetype=mimetype, headers={'Cache-Control': 'no-store'})
