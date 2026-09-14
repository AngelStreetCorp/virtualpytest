"""
API Call Block

Execute Postman API requests with context variable substitution.

Features:
- Select from configured Postman workspaces/collections/endpoints
- Auto-substitute variables from execution context (server_url, team_id, device_id, etc.)
- Store response in context for next blocks
- Clean UX with cascading dropdowns

SIMPLIFIED IMPLEMENTATION:
- Reuses existing /server/postman/test endpoint (already working!)
- No duplicate variable substitution logic
- Cleaner, more maintainable code
"""

import requests
from typing import Dict, Any


def get_block_info() -> Dict[str, Any]:
    """
    Get API call block metadata with typed parameters.
    
    Returns:
        Dict with block metadata including cascading dropdown parameters
    """
    return {
        'command': 'api_call',
        'name': 'API Call',
        'category': 'api',
        'description': 'Execute Postman API request with context variables',
        'icon': '🌐',
        'params': [
            {
                'name': 'workspace_id',
                'type': 'select',
                'label': 'Workspace',
                'options_source': 'postman_workspaces',
                'required': True,
                'description': 'Postman workspace'
            },
            {
                'name': 'collection_id',
                'type': 'select',
                'label': 'Collection',
                'options_source': 'postman_collections',
                'required': True,
                'depends_on': 'workspace_id',
                'description': 'API collection'
            },
            {
                'name': 'request_id',
                'type': 'select',
                'label': 'Request',
                'options_source': 'postman_requests',
                'required': True,
                'depends_on': 'collection_id',
                'description': 'API endpoint to call'
            },
            {
                'name': 'environment_id',
                'type': 'select',
                'label': 'Environment',
                'options_source': 'postman_environments',
                'required': False,
                'depends_on': 'workspace_id',
                'description': 'Environment (defines variable templates)'
            },
            {
                'name': 'method',
                'type': 'string',
                'label': 'Method',
                'description': 'HTTP method (auto-filled from selection)',
                'required': True,
                'default': 'GET'
            },
            {
                'name': 'path_preview',
                'type': 'string',
                'label': 'Path',
                'description': 'Request path (auto-filled from selection)',
                'required': True,
                'default': ''
            },
            {
                'name': 'request_name',
                'type': 'string',
                'label': 'Request Name',
                'description': 'Human-readable name (auto-filled from selection)',
                'required': False,
                'default': 'API Call'
            },
            {
                'name': 'store_response_as',
                'type': 'string',
                'label': 'Store Response As',
                'description': 'Variable name to store response (optional)',
                'required': False,
                'default': 'api_response'
            },
            {
                'name': 'fail_on_error',
                'type': 'boolean',
                'label': 'Fail on Error',
                'description': 'Fail block if HTTP status >= 400',
                'required': False,
                'default': True
            },
            {
                'name': 'timeout_ms',
                'type': 'number',
                'label': 'Timeout (ms)',
                'description': 'Request timeout in milliseconds',
                'required': False,
                'default': 5000
            }
        ],
        'outputs': [
            {
                'name': 'response',
                'type': 'object',
                'description': 'API response data'
            },
            {
                'name': 'status_code',
                'type': 'number',
                'description': 'HTTP status code'
            }
        ]
    }


def execute(workspace_id: str = None,
            collection_id: str = None,
            request_id: str = None,
            environment_id: str = None,
            method: str = 'GET',
            path_preview: str = '',
            request_name: str = 'API Call',
            store_response_as: str = 'api_response',
            fail_on_error: bool = True,
            timeout_ms: int = 5000,
            context: Dict[str, Any] = None,
            **kwargs) -> Dict[str, Any]:
    """
    Execute Postman API request using existing /server/postman/test endpoint.
    
    SIMPLIFIED: Reuses the working /server/postman/test endpoint instead of 
    duplicating request fetching/substitution logic.
    
    Args:
        workspace_id: Postman workspace ID
        collection_id: Collection ID (for reference)
        request_id: Request ID (for reference)
        environment_id: Optional environment ID (for variable templates)
        method: HTTP method (GET, POST, etc.)
        path_preview: Request path/URL
        request_name: Human-readable request name
        store_response_as: Variable name to store response in context
        fail_on_error: Fail if status >= 400
        timeout_ms: Request timeout (not used - server controls timeout)
        context: Execution context with variables
        **kwargs: Additional parameters
        
    Returns:
        Dict with success status and response data
    """
    print(f"[@api_call] Executing API request: {request_name} ({method} {path_preview})")
    
    if not context:
        context = {}
    
    try:
        import os
        server_url = os.getenv('BACKEND_SERVER_URL', 'http://localhost:5109')
        
        # Call existing /server/postman/test endpoint (already handles variables, substitution, execution)
        response = requests.post(  # nosec B113 - timeout is set below (expression, not a literal)
            f'{server_url}/server/postman/test',
            json={
                'workspaceId': workspace_id,
                'environmentId': environment_id or None,
                'endpoints': [{
                    'method': method,
                    'path': path_preview,
                    'name': request_name
                }]
            },
            timeout=(timeout_ms / 1000.0) + 5  # Add buffer for server processing
        )
        
        result = response.json()
        
        if result.get('success') and result.get('results') and len(result['results']) > 0:
            api_result = result['results'][0]
            
            # Parse response data
            try:
                response_data = api_result.get('response', {})
            except:
                response_data = api_result.get('response', '')
            
            status_code = api_result.get('statusCode', 0)
            
            # Store response in context
            if store_response_as and context is not None:
                context[store_response_as] = response_data
                context[f'{store_response_as}_status'] = status_code
            
            # Determine success
            is_success = (api_result.get('status') == 'pass') or (status_code < 400 and not fail_on_error)
            
            return {
                'success': is_success,
                'result_success': 0 if is_success else 1,
                'status_code': status_code,
                'response': response_data,
                'message': f'{method} {path_preview} → {status_code}',
                'output_data': {
                    'response': response_data,
                    'status_code': status_code,
                    'headers': {}
                }
            }
        else:
            error_msg = result.get('error', 'API test failed')
            return {
                'success': False,
                'result_success': 1,
                'error': error_msg,
                'message': f'{method} {path_preview} failed: {error_msg}'
            }
        
    except requests.exceptions.Timeout:
        return {
            'success': False,
            'result_success': 1,
            'error': 'Request timeout',
            'message': f'Request timed out after {timeout_ms}ms'
        }
    except Exception as e:
        print(f"[@api_call] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'success': False,
            'result_success': 1,
            'error': str(e),
            'message': f'API call failed: {str(e)}'
        }

