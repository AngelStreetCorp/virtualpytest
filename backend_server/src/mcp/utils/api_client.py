"""
API Client for MCP Server

Provides HTTP client to communicate with backend_server routes.
Returns raw API responses - formatting is handled by callers.
"""

import requests
from typing import Dict, Any, Optional
from shared.src.lib.utils.build_url_utils import server_auth_headers
import os


class MCPAPIClient:
    """HTTP client for backend_server API calls - returns raw responses"""
    
    def __init__(self):
        # MCP server runs inside backend_server, so it calls itself
        # Default to localhost:5109 (backend_server port)
        # Set SERVER_BASE_URL env var to override (e.g., for remote backend_server)
        self.base_url = os.getenv('SERVER_BASE_URL', 'http://localhost:5109')
        self.timeout = 30
        # Per-request headers forwarded by the MCP tool layer. The frontend
        # uses the top-bar `ProjectSelector` to pick a project; the Atlas
        # agent and the `/server/mcp/*` proxy set `X-Project-Id` so the
        # backend can scope the request (TASK-65 G5). Tools call
        # `set_header('X-Project-Id', project_id)` and every subsequent
        # `get()` / `post()` until the next `clear_headers()` carries it.
        self.headers: Dict[str, str] = {}
    
    def resolve_userinterface_name(self, userinterface_name: str, team_id: str) -> tuple:
        """
        Resolve userinterface name to get tree_id, userinterface_id, and device_model.

        This is the standard 2-step resolution pattern used across all MCP tools:
        1. Get userinterface by name → userinterface_id + device_model
        2. Get tree by userinterface_id → tree_id

        Args:
            userinterface_name: Human-readable UI name (e.g., 'example_mobile')
            team_id: Team ID for the request

        Returns:
            tuple: (tree_id, userinterface_id, device_model, error_message)
            - Success: ('uuid-tree-id', 'uuid-userinterface-id', 'android_mobile', None)
            - Error: (None, None, None, 'error message')
        """
        # Step 1: Get userinterface by name
        ui_result = self.get(
            f'/server/userinterface/getUserInterfaceByName/{userinterface_name}',
            params={'team_id': team_id}
        )
        if not ui_result or not ui_result.get('id'):
            return None, None, None, f"User interface '{userinterface_name}' not found"

        userinterface_id = ui_result['id']
        models = ui_result.get('models', [])
        device_model = models[0] if models else 'unknown'

        # Step 2: Get tree by userinterface_id
        tree_result = self.get(
            f'/server/navigationTrees/getTreeByUserInterfaceId/{userinterface_id}',
            params={'team_id': team_id}
        )

        if not tree_result.get('success') or not tree_result.get('tree'):
            return None, userinterface_id, device_model, f"No navigation tree found for '{userinterface_name}'"

        tree_id = tree_result['tree']['id']
        return tree_id, userinterface_id, device_model, None

    def get_device_model_from_userinterface(self, userinterface_id: str, team_id: str) -> tuple:
        """
        Get device model from userinterface ID.

        This queries the userinterface database directly (no host required).

        Args:
            userinterface_id: Userinterface UUID
            team_id: Team ID for the request

        Returns:
            tuple: (device_model, error_message)
            - Success: ('android_mobile', None)
            - Error: (None, 'error message')
        """
        # Get userinterface from database
        ui_result = self.get(
            f'/server/userinterface/getUserInterface/{userinterface_id}',
            params={'team_id': team_id}
        )

        # The route answers with the bare userinterface dict ({id, name, models,
        # ...}), not {success, data}; only this client's own error wrapper
        # carries success=False. Reading 'success' made every call fail with
        # "Failed to fetch userinterface: Unknown error".
        if not isinstance(ui_result, dict) or ui_result.get('success') is False or not ui_result.get('id'):
            error = ui_result.get('error') if isinstance(ui_result, dict) else None
            return None, f"Failed to fetch userinterface: {error or 'not found'}"

        models = ui_result.get('models') or []
        device_model = models[0] if models else 'unknown'

        return device_model, None
    
    def post(self, endpoint: str, data: Dict[str, Any] = None, params: Dict[str, Any] = None,
             timeout: Optional[float] = None, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        POST request to backend_server API
        
        Args:
            endpoint: API endpoint (e.g., '/server/control/takeControl')
            data: JSON body
            params: Query parameters (e.g., {'team_id': 'xxx'})
            timeout: Read timeout in seconds for this call (default self.timeout = 30 s).
                Routes that block on a host for longer (navigation execute) pass their own.
            
        Returns:
            Raw API response dict with 'success', 'error', and data fields
        """
        url = f"{self.base_url}{endpoint}"
        read_timeout = timeout or self.timeout
        merged_headers = {**server_auth_headers(), **self.headers, **(headers or {})}

        try:
            response = requests.post(
                url,
                headers=merged_headers,
                json=data or {},
                params=params or {},
                timeout=read_timeout
            )
            
            # Return raw JSON response
            # Accept 200 (success), 201 (created), and 202 (async started) as valid responses
            if response.status_code in [200, 201, 202]:
                return response.json()
            else:
                # Preserve structured error responses (e.g., 423 lock conflict has errorType, owner_type, etc.)
                try:
                    error_json = response.json()
                    error_json.setdefault('success', False)
                    error_json.setdefault('status_code', response.status_code)
                    return error_json
                except Exception:
                    return {
                        'success': False,
                        'error': f'HTTP {response.status_code}: {response.text}',
                        'status_code': response.status_code
                    }
                
        except requests.exceptions.Timeout:
            return {
                'success': False,
                'error': f'Request timeout ({read_timeout}s)',
                'timeout': True
            }
        except requests.exceptions.RequestException as e:
            return {
                'success': False,
                'error': f'Network error: {str(e)}',
                'network_error': True
            }
    
    def put(self, endpoint: str, data: Dict[str, Any] = None, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        PUT request to backend_server API
        
        Args:
            endpoint: API endpoint
            data: JSON body
            params: Query parameters
            
        Returns:
            Raw API response dict
        """
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = requests.put(
                url,
                headers=server_auth_headers(),
                json=data or {},
                params=params or {},
                timeout=self.timeout
            )
            
            if response.status_code in [200, 201, 202]:
                return response.json()
            else:
                return {
                    'success': False,
                    'error': f'HTTP {response.status_code}: {response.text}',
                    'status_code': response.status_code
                }
                
        except requests.exceptions.Timeout:
            return {
                'success': False,
                'error': f'Request timeout ({self.timeout}s)',
                'timeout': True
            }
        except requests.exceptions.RequestException as e:
            return {
                'success': False,
                'error': f'Network error: {str(e)}',
                'network_error': True
            }
    
    def delete(self, endpoint: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        DELETE request to backend_server API
        
        Args:
            endpoint: API endpoint
            params: Query parameters
            
        Returns:
            Raw API response dict
        """
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = requests.delete(
                url,
                headers=server_auth_headers(),
                params=params or {},
                timeout=self.timeout
            )
            
            if response.status_code in [200, 202, 204]:
                # 204 No Content might have empty body
                if response.status_code == 204 or not response.text:
                    return {'success': True}
                return response.json()
            else:
                return {
                    'success': False,
                    'error': f'HTTP {response.status_code}: {response.text}',
                    'status_code': response.status_code
                }
                
        except requests.exceptions.Timeout:
            return {
                'success': False,
                'error': f'Request timeout ({self.timeout}s)',
                'timeout': True
            }
        except requests.exceptions.RequestException as e:
            return {
                'success': False,
                'error': f'Network error: {str(e)}',
                'network_error': True
            }
    
    def get(self, endpoint: str, params: Dict[str, Any] = None, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        GET request to backend_server API
        
        Args:
            endpoint: API endpoint
            params: Query parameters
            
        Returns:
            Raw API response dict
        """
        url = f"{self.base_url}{endpoint}"
        merged_headers = {**server_auth_headers(), **self.headers, **(headers or {})}

        try:
            response = requests.get(
                url,
                headers=merged_headers,
                params=params or {},
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                return {
                    'success': False,
                    'error': f'HTTP {response.status_code}: {response.text}',
                    'status_code': response.status_code
                }
                
        except requests.exceptions.Timeout:
            return {
                'success': False,
                'error': f'Request timeout ({self.timeout}s)',
                'timeout': True
            }
        except requests.exceptions.RequestException as e:
            return {
                'success': False,
                'error': f'Network error: {str(e)}',
                'network_error': True
            }

