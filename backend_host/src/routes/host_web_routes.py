"""
Host Web Routes

Host-side web automation endpoints that execute commands using instantiated web controllers.
"""

from flask import Blueprint, request, jsonify
from backend_host.src.lib.utils.host_utils import get_controller
from backend_host.src.lib.utils.route_request import get_json_payload, require_field
from backend_host.src.lib.utils.route_response import controller_not_found
import threading
import requests

from shared.src.lib.utils.build_url_utils import server_auth_headers
import time
import asyncio

# Create blueprint
host_web_bp = Blueprint('host_web', __name__, url_prefix='/host/web')

# =====================================================
# WEB CONTROLLER ENDPOINTS
# =====================================================

def _run_async(coro):
    """Run async coroutine using asyncio.run() - same as navigation execution."""
    import asyncio
    return asyncio.run(coro)

@host_web_bp.route('/executeCommand', methods=['POST'])
def execute_command():
    """Execute a web automation command using web controller."""
    try:
        data = get_json_payload()
        command, command_error = require_field(data, 'command', message='command is required')
        if command_error:
            return command_error

        params = data.get('params', {})
        callback_url = data.get('callback_url')
        task_id = data.get('task_id')
        
        print(f"[@route:host_web:execute_command] Executing command: {command} with params: {params}")
        
        if not command:
            return jsonify({
                'success': False,
                'error': 'command is required'
            }), 400
        
        # Get web controller for the host (no device_id needed for host operations)
        web_controller = get_controller(None, 'web')

        if not web_controller:
            return controller_not_found('web', 'host')
        
        print(f"[@route:host_web:execute_command] Using web controller: {type(web_controller).__name__}")
        
        # Handle browser_use_task asynchronously with callback
        if command == 'browser_use_task' and callback_url and task_id:
            def execute_async():
                try:
                    print(f"[@route:host_web:execute_command] Starting async browser_use_task {task_id}")
                    # Run the async command in new event loop (background thread has no loop)
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        result = loop.run_until_complete(web_controller.execute_command(command, params))
                    finally:
                        loop.close()
                    
                    # Send callback with result and execution logs
                    callback_data = {
                        'task_id': task_id,
                        'result': result,
                        'execution_logs': result.get('execution_logs', ''),
                        'error': None
                    }
                    
                    try:
                        print(f"[@route:host_web:execute_command] Sending callback to: {callback_url}")
                        print(f"[@route:host_web:execute_command] Callback data: {callback_data}")
                        
                        callback_response = requests.post(
                            callback_url,
                            json=callback_data,
                            headers=server_auth_headers(),
                            timeout=30,
                            allow_redirects=False  # Prevent POST->GET redirects
                        )
                        
                        print(f"[@route:host_web:execute_command] Callback sent for task {task_id}, status: {callback_response.status_code}")
                        
                        if callback_response.status_code not in [200, 201, 202]:
                            print(f"[@route:host_web:execute_command] Callback error response: {callback_response.text}")
                            
                    except Exception as callback_error:
                        print(f"[@route:host_web:execute_command] Callback failed for task {task_id}: {callback_error}")
                        
                except Exception as e:
                    print(f"[@route:host_web:execute_command] Async execution failed for task {task_id}: {e}")
                    # Send callback with error
                    callback_data = {
                        'task_id': task_id,
                        'result': {},
                        'error': str(e)
                    }
                    
                    try:
                        requests.post(
                            callback_url, json=callback_data,
                            headers=server_auth_headers(), timeout=30,
                        )
                    except:
                        pass  # Ignore callback errors when already handling an error
            
            # Start background execution
            threading.Thread(target=execute_async, daemon=True).start()
            
            return jsonify({
                'success': True,
                'message': f'Browser-use task {task_id} started in background',
                'task_id': task_id
            }), 202
        
        else:
            # Execute other commands with event loop wrapper
            result = _run_async(web_controller.execute_command(command, params))
            return jsonify(result)
            
    except Exception as e:
        print(f"[@route:host_web:execute_command] Error: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Command execution error: {str(e)}'
        }), 500

@host_web_bp.route('/navigateToUrl', methods=['POST'])
def navigate_to_url():
    """Navigate to URL using web controller."""
    try:
        data = get_json_payload()
        url, url_error = require_field(data, 'url', message='url is required')
        if url_error:
            return url_error
        timeout = data.get('timeout', 30000)
        
        print(f"[@route:host_web:navigate_to_url] Navigating to: {url}")
        
        if not url:
            return jsonify({
                'success': False,
                'error': 'url is required'
            }), 400
        
        # Get web controller for the host (no device_id needed for host operations)
        web_controller = get_controller(None, 'web')

        if not web_controller:
            return controller_not_found('web', 'host')
        
        print(f"[@route:host_web:navigate_to_url] Using web controller: {type(web_controller).__name__}")
        
        # Navigate with event loop wrapper
        result = _run_async(web_controller.navigate_to_url(url, timeout=timeout))
        
        return jsonify(result)
            
    except Exception as e:
        print(f"[@route:host_web:navigate_to_url] Error: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Navigation error: {str(e)}'
        }), 500

@host_web_bp.route('/openBrowser', methods=['POST'])
def open_browser():
    """Open browser using web controller."""
    try:
        print(f"[@route:host_web:open_browser] Opening browser")
        
        # Get web controller for the host (no device_id needed for host operations)
        web_controller = get_controller(None, 'web')

        if not web_controller:
            return controller_not_found('web', 'host')
        
        print(f"[@route:host_web:open_browser] Using web controller: {type(web_controller).__name__}")
        
        # Open browser with event loop wrapper
        result = _run_async(web_controller.open_browser())
        
        return jsonify(result)
            
    except Exception as e:
        print(f"[@route:host_web:open_browser] Error: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Browser open error: {str(e)}'
        }), 500

@host_web_bp.route('/closeBrowser', methods=['POST'])
def close_browser():
    """Close browser using web controller."""
    try:
        print(f"[@route:host_web:close_browser] Closing browser")
        
        # Get web controller for the host (no device_id needed for host operations)
        web_controller = get_controller(None, 'web')

        if not web_controller:
            return controller_not_found('web', 'host')
        
        print(f"[@route:host_web:close_browser] Using web controller: {type(web_controller).__name__}")
        
        # Close browser and wait for result
        result = web_controller.close_browser()
        
        return jsonify(result)
            
    except Exception as e:
        print(f"[@route:host_web:close_browser] Error: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Browser close error: {str(e)}'
        }), 500

@host_web_bp.route('/getPageInfo', methods=['POST'])
def get_page_info():
    """Get page information using web controller."""
    try:
        print(f"[@route:host_web:get_page_info] Getting page info")
        
        # Get web controller for the host (no device_id needed for host operations)
        web_controller = get_controller(None, 'web')

        if not web_controller:
            return controller_not_found('web', 'host')
        
        print(f"[@route:host_web:get_page_info] Using web controller: {type(web_controller).__name__}")
        
        # Get page info with event loop wrapper
        result = _run_async(web_controller.get_page_info())
        
        return jsonify(result)
            
    except Exception as e:
        print(f"[@route:host_web:get_page_info] Error: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Page info error: {str(e)}'
        }), 500

@host_web_bp.route('/getStatus', methods=['POST'])
def get_status():
    """Get web controller status."""
    try:
        print(f"[@route:host_web:get_status] Getting status")
        
        # Get web controller for the host (no device_id needed for host operations)
        web_controller = get_controller(None, 'web')

        if not web_controller:
            return controller_not_found('web', 'host')
        
        print(f"[@route:host_web:get_status] Using web controller: {type(web_controller).__name__}")
        
        # Get controller status and wait for result
        status = web_controller.get_status()
        
        return jsonify({
            'success': True,
            'status': status
        })
            
    except Exception as e:
        print(f"[@route:host_web:get_status] Error: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Status check error: {str(e)}'
        }), 500 
