"""
Server Web Routes

Server-side web automation proxy endpoints that forward requests to host web controllers.
"""

from flask import Blueprint, request, jsonify, current_app
from backend_server.src.lib.utils.route_utils import proxy_to_host_with_params, proxy_to_host_direct, get_host_from_request
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.utils.task_manager import task_manager
import threading
import uuid

# Create blueprint
server_web_bp = Blueprint('server_web', __name__, url_prefix='/server/web')

# =====================================================
# WEB CONTROLLER ENDPOINTS
# =====================================================

@server_web_bp.route('/executeCommand', methods=['POST'])
@handle_route_exceptions('server_web:execute_command')
def execute_command():
    """Proxy execute web command request to selected host"""
    print("[@route:server_web:execute_command] Proxying execute command request")
    request_data = request.get_json() or {}
    command = request_data.get('command', '')
        
    host_info, error = get_host_from_request()
    if not host_info:
        return jsonify({'success': False, 'error': error or 'Host information required'}), 400
    host_request_data = {k: v for k, v in request_data.items() if k != 'host'}
    if command == 'browser_use_task':
        task_id = task_manager.create_task(command, request_data.get('params', {}))
        from shared.src.lib.utils.build_url_utils import buildServerUrl
        callback_url = buildServerUrl('server/web/taskComplete')
        host_request_data['callback_url'] = callback_url
        host_request_data['task_id'] = task_id
        print(f"[@route:server_web:execute_command] Generated callback URL: {callback_url}")
        print(f"[@route:server_web:execute_command] Task ID: {task_id}")

        def execute_async():
                print(f"[@route:server_web:execute_command] Starting background execution for task {task_id}")
                print(f"[@route:server_web:execute_command] Host request data: {host_request_data}")
                
                # Use proxy_to_host with direct host_info (no Flask request context needed)
                response_data, status_code = proxy_to_host_direct(host_info, '/host/web/executeCommand', 'POST', host_request_data, timeout=600)
                
                print(f"[@route:server_web:execute_command] Host response for task {task_id}: status={status_code}, data={response_data}")
                
                if status_code != 200:
                    # Host execution failed, complete task with error
                    print(f"[@route:server_web:execute_command] Host execution failed for task {task_id}")
                    task_manager.complete_task(task_id, {}, error=response_data.get('error', 'Host execution failed'))
                else:
                    print(f"[@route:server_web:execute_command] Host execution completed for task {task_id}")
                    # Task will be completed by the host's callback
        threading.Thread(target=execute_async, daemon=True).start()
        return jsonify({
            'success': True,
            'task_id': task_id,
            'status': 'started',
            'message': 'Browser-use task started in background'
        }), 202
    timeout = 30
    response_data, status_code = proxy_to_host_with_params('/host/web/executeCommand', 'POST', host_request_data, timeout=timeout)
    return jsonify(response_data), status_code


@server_web_bp.route('/taskComplete', methods=['POST'])
@handle_route_exceptions('server_web:task_complete')
def task_complete():
    """Receive task completion callback from host and notify frontend via WebSocket"""
    print("[@route:server_web:task_complete] Received task completion callback")
    callback_data = request.get_json() or {}
    task_id = callback_data.get('task_id')
    result = callback_data.get('result', {})
    error = callback_data.get('error')
    if not task_id:
        return jsonify({'success': False, 'error': 'task_id required'}), 400
    task_manager.complete_task(task_id, result, error)
    if hasattr(current_app, 'socketio'):
        current_app.socketio.emit('task_complete', {
            'task_id': task_id,
            'success': not bool(error),
            'result': result,
            'error': error,
            'execution_time': result.get('execution_time', 0)
        })
        print(f"[@route:server_web:task_complete] WebSocket notification sent for task {task_id}")
    return jsonify({'success': True, 'message': 'Task completion processed'}), 200


@server_web_bp.route('/navigateToUrl', methods=['POST'])
@handle_route_exceptions('server_web:navigate_to_url')
def navigate_to_url():
    """Proxy navigate to URL request to selected host"""
    print("[@route:server_web:navigate_to_url] Proxying navigate to URL request")
    request_data = request.get_json() or {}
    host_info, error = get_host_from_request()
    if not host_info:
        return jsonify({'success': False, 'error': error or 'Host information required'}), 400
    host_request_data = {k: v for k, v in request_data.items() if k != 'host'}
    response_data, status_code = proxy_to_host_with_params('/host/web/navigateToUrl', 'POST', host_request_data)
    return jsonify(response_data), status_code


@server_web_bp.route('/getPageInfo', methods=['POST'])
@handle_route_exceptions('server_web:get_page_info')
def get_page_info():
    """Proxy get page info request to selected host"""
    print("[@route:server_web:get_page_info] Proxying get page info request")
    request_data = request.get_json() or {}
    host_info, error = get_host_from_request()
    if not host_info:
        return jsonify({'success': False, 'error': error or 'Host information required'}), 400
    host_request_data = {k: v for k, v in request_data.items() if k != 'host'}
    response_data, status_code = proxy_to_host_with_params('/host/web/getPageInfo', 'POST', host_request_data)
    return jsonify(response_data), status_code


@server_web_bp.route('/openBrowser', methods=['POST'])
@handle_route_exceptions('server_web:open_browser')
def open_browser():
    """Proxy open browser request to selected host"""
    print("[@route:server_web:open_browser] Proxying open browser request")
    request_data = request.get_json() or {}
    host_info, error = get_host_from_request()
    if not host_info:
        return jsonify({'success': False, 'error': error or 'Host information required'}), 400
    host_request_data = {k: v for k, v in request_data.items() if k != 'host'}
    response_data, status_code = proxy_to_host_with_params('/host/web/openBrowser', 'POST', host_request_data)
    return jsonify(response_data), status_code


@server_web_bp.route('/closeBrowser', methods=['POST'])
@handle_route_exceptions('server_web:close_browser')
def close_browser():
    """Proxy close browser request to selected host"""
    print("[@route:server_web:close_browser] Proxying close browser request")
    request_data = request.get_json() or {}
    host_info, error = get_host_from_request()
    if not host_info:
        return jsonify({'success': False, 'error': error or 'Host information required'}), 400
    host_request_data = {k: v for k, v in request_data.items() if k != 'host'}
    response_data, status_code = proxy_to_host_with_params('/host/web/closeBrowser', 'POST', host_request_data)
    return jsonify(response_data), status_code


@server_web_bp.route('/getStatus', methods=['POST'])
@handle_route_exceptions('server_web:get_status')
def get_status():
    """Proxy get web controller status request to selected host"""
    print("[@route:server_web:get_status] Proxying get status request")
    request_data = request.get_json() or {}
    response_data, status_code = proxy_to_host_with_params('/host/web/getStatus', 'POST', request_data, {})
    return jsonify(response_data), status_code