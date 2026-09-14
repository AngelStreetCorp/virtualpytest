"""
MCP HTTP Routes - HTTP endpoint for Model Context Protocol

Exposes MCP tools via HTTP for external LLM clients (Cursor, Claude Desktop, etc.)
Requires Bearer token authentication for security.
"""

from flask import Blueprint, request, jsonify
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
import os
from functools import wraps

# Import MCP server - use relative import for proper module resolution
import sys
from pathlib import Path

# Add backend_server/src to path if needed
current_dir = Path(__file__).parent.parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

from mcp.mcp_instance import get_mcp_server

# Create blueprint - accessible at /server/mcp via Flask routing
# Note: Routes are prefixed with /server/ for API organization
mcp_bp = Blueprint('mcp', __name__, url_prefix='/server/mcp')

# Get shared MCP server instance (singleton)
mcp_server = get_mcp_server()

# MCP bearer secret. No default on purpose: when MCP_SECRET_KEY is unset every
# /server/mcp request is refused (503) instead of accepting a well-known value.
MCP_SECRET_KEY = os.getenv('MCP_SECRET_KEY')


def _format_tool_error_result(error_text: str):
    """Return MCP-compatible tool error payload."""
    return {
        'isError': True,
        'content': [
            {
                'type': 'text',
                'text': error_text,
            }
        ],
    }


def require_mcp_auth(f):
    """Decorator to require MCP authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Get Authorization header
        auth_header = request.headers.get('Authorization')
        
        if not auth_header:
            return jsonify({
                'error': 'Missing Authorization header',
                'message': 'MCP endpoint requires Bearer token authentication'
            }), 401
        
        # Check Bearer token format
        if not auth_header.startswith('Bearer '):
            return jsonify({
                'error': 'Invalid Authorization header format',
                'message': 'Expected: Authorization: Bearer <token>'
            }), 401
        
        # Extract token
        token = auth_header.replace('Bearer ', '').strip()
        
        # Validate token (fail closed when the server has no secret configured)
        if not MCP_SECRET_KEY:
            return jsonify({
                'error': 'MCP disabled',
                'message': 'MCP_SECRET_KEY is not configured on this server'
            }), 503
        if token != MCP_SECRET_KEY:
            return jsonify({
                'error': 'Invalid MCP authentication token',
                'message': 'Access denied'
            }), 403
        
        # Token valid, proceed
        return f(*args, **kwargs)
    
    return decorated_function


@mcp_bp.route('/', methods=['GET', 'POST'], strict_slashes=False)
@require_mcp_auth
def mcp_endpoint():
    """
    MCP HTTP endpoint - JSON-RPC 2.0 protocol
    
    Supports GET for SSE/handshake and POST for JSON-RPC requests.
    
    JSON-RPC 2.0 format (POST):
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list" | "tools/call" | "initialize",
        "params": {
            "name": "tool_name",
            "arguments": {...}
        }
    }
    """
    # Handle GET requests (for SSE or health checks)
    if request.method == 'GET':
        return jsonify({
            'status': 'ready',
            'protocol': 'MCP',
            'version': '2024-11-05',
            'serverInfo': {
                'name': 'virtualpytest',
                'version': '1.0.0'
            }
        }), 200
    
    # Handle POST requests (JSON-RPC)
    data = request.get_json()
    
    if not data:
        return jsonify({
            'jsonrpc': '2.0',
            'id': None,
            'error': {
                'code': -32600,
                'message': 'Invalid Request - No JSON data provided'
            }
        }), 400
    
    # Check if this is a JSON-RPC request
    if 'jsonrpc' in data and data.get('jsonrpc') == '2.0':
        return handle_jsonrpc_request(data)
    
    # Legacy REST format
    tool_name = data.get('tool')
    params = data.get('params', {})
    
    if not tool_name:
        return jsonify({
            'error': 'tool name is required'
        }), 400
    
    # Handle tool call
    try:
        result = mcp_server.handle_tool_call(tool_name, params)
    except ValueError as exc:
        # Tool-level errors should be returned as MCP payloads, not Flask 500 HTML.
        result = _format_tool_error_result(str(exc))
    
    return jsonify(result), 200
    
def handle_jsonrpc_request(data):
    """Handle JSON-RPC 2.0 requests according to MCP 2025-06-18 spec"""
    request_id = data.get('id')
    method = data.get('method')
    params = data.get('params', {})
    
    # Handle initialize method (MCP handshake)
    if method == 'initialize':
        return jsonify({
            'jsonrpc': '2.0',
            'id': request_id,
            'result': {
                'protocolVersion': '2024-11-05',  # Using stable version compatible with most clients
                'capabilities': {
                    'tools': {
                        'listChanged': True  # We support tools/list_changed notifications
                    }
                },
                'serverInfo': {
                    'name': 'virtualpytest',
                    'version': '1.0.0'
                }
            }
        })
    
    # Handle tools/list method
    elif method == 'tools/list':
        tools = mcp_server.get_available_tools()
        # Tools are already in proper MCP format
        
        return jsonify({
            'jsonrpc': '2.0',
            'id': request_id,
            'result': {
                'tools': tools
            }
        })
    
    # Handle tools/call method
    elif method == 'tools/call':
        tool_name = params.get('name')
        arguments = params.get('arguments', {})
        
        if not tool_name:
            return jsonify({
                'jsonrpc': '2.0',
                'id': request_id,
                'error': {
                'code': -32602,
                'message': 'Invalid params - tool name is required'
            }
        }), 200  # JSON-RPC errors should return HTTP 200
        
        # Execute tool - return tool-level failures as MCP isError payload.
        try:
            tool_result = mcp_server.handle_tool_call(tool_name, arguments)
        except ValueError as exc:
            tool_result = _format_tool_error_result(str(exc))
        
        # Ensure isError field exists (default to False if not present)
        if 'isError' not in tool_result:
            tool_result['isError'] = False
        
        return jsonify({
            'jsonrpc': '2.0',
            'id': request_id,
            'result': tool_result
        })
    
    else:
        return jsonify({
            'jsonrpc': '2.0',
            'id': request_id,
            'error': {
                'code': -32601,
                'message': f'Method not found: {method}'
            }
        }), 200  # JSON-RPC errors should return HTTP 200
        
@mcp_bp.route('/tools', methods=['GET'], strict_slashes=False)
@require_mcp_auth
def list_mcp_tools():
    """
    List available MCP tools
    
    Returns:
    {
        "tools": [
            {
                "name": "take_control",
                "description": "...",
                "category": "control",
                "required_params": [...],
                "optional_params": [...]
            },
            ...
        ]
    }
    """
    tools = mcp_server.get_available_tools()
    return jsonify({
        'tools': tools,
        'count': len(tools)
    })
@mcp_bp.route('/health', methods=['GET'], strict_slashes=False)
@handle_route_exceptions('mcp:mcp_health')
def mcp_health():
    """MCP server health check"""
    return jsonify({
        'status': 'healthy',
        'mcp_version': '1.0.0',
        'tools_count': len(mcp_server.tool_handlers)
    })
