"""
Route Utilities

Shared utilities for server routes including host proxying and request handling.

IMPORTANT: All functions now use the centralized call_host() from build_url_utils.py
which automatically handles API key injection (the "decorator equivalent" for server side).
"""

from flask import request
from shared.src.lib.utils.build_url_utils import call_host


def get_host_from_request():
    """Get host information from request data using host_name lookup"""
    try:
        # Check both JSON body (for POST requests) and query parameters (for GET requests)
        try:
            data = request.get_json() or {}
        except:
            # GET requests don't have JSON body, that's fine
            data = {}
        host_name = data.get('host_name') or request.args.get('host_name')
        
        if not host_name:
            return None, 'host_name required in request body or query parameters'
            
        from  backend_server.src.lib.utils.server_utils import get_host_manager
        host_manager = get_host_manager()
        host_info = host_manager.get_host(host_name)
        
        if not host_info:
            return None, f'Host "{host_name}" not found'
            
        return host_info, None
                
    except Exception as e:
        return None, f'Error getting host from request: {str(e)}'


def proxy_to_host(endpoint, method='GET', data=None, timeout=30, headers=None):
    """
    Proxy a request to the specified host's endpoint.
    Uses centralized call_host() which automatically handles API key injection.
    
    Args:
        endpoint: The host endpoint to call (e.g., '/host/av/get-stream-url')
        method: HTTP method ('GET', 'POST', etc.')
        data: Request data for POST requests (should include host info)
        timeout: Request timeout in seconds (default: 30)
        headers: Additional headers to include in the request (dict)
    
    Returns:
        Tuple of (response_data, status_code)
    """
    # Get host information from request
    host_info, error = get_host_from_request()
    if not host_info:
        return {
            'success': False,
            'error': error or 'Host information required'
        }, 400
    
    # Use centralized call_host() - API key injection handled automatically
    return call_host(
        host_info,
        endpoint,
        method=method,
        data=data,
        timeout=timeout,
        extra_headers=headers
    )


def proxy_to_host_with_params(endpoint, method='GET', data=None, query_params=None, timeout=30, headers=None):
    """
    Proxy a request to the specified host's endpoint with query parameters.
    Uses centralized call_host() which automatically handles API key injection.
    
    Args:
        endpoint: The host endpoint to call (e.g., '/host/av/get-stream-url')
        method: HTTP method ('GET', 'POST', etc.')
        data: Request data for POST requests (should include host info)
        query_params: Query parameters to add to the URL (dict)
        timeout: Request timeout in seconds (default: 30)
        headers: Additional headers to include in the request (dict)
    
    Returns:
        Tuple of (response_data, status_code)
    """
    # Get host information from request
    host_info, error = get_host_from_request()
    if not host_info:
        return {
            'success': False,
            'error': error or 'Host information required'
        }, 400
    
    # Log which host we're proxying to
    host_name = host_info.get('host_name', 'unknown')
    host_api_url = host_info.get('host_api_url', host_info.get('host_url', 'not set'))
    print(f"[@proxy_to_host] 📡 Proxying to host '{host_name}'")
    print(f"[@proxy_to_host]    Endpoint: {endpoint}")
    print(f"[@proxy_to_host]    host_api_url: {host_api_url}")
    print(f"[@proxy_to_host]    Method: {method}")
    
    # Use centralized call_host() - API key injection handled automatically
    return call_host(
        host_info,
        endpoint,
        method=method,
        data=data,
        query_params=query_params,
        timeout=timeout,
        extra_headers=headers
    )


def proxy_to_host_direct(host_info, endpoint, method='GET', data=None, timeout=30, headers=None):
    """
    Proxy a request to the specified host's endpoint using provided host_info.
    Uses centralized call_host() which automatically handles API key injection.
    (for use in background threads where Flask request context is not available)
    
    Args:
        host_info: Host information dict (required)
        endpoint: The host endpoint to call (e.g., '/host/web/executeCommand')
        method: HTTP method ('GET', 'POST', etc.')
        data: Request data for POST requests
        timeout: Request timeout in seconds (default: 30)
        headers: Additional headers to include in the request (dict)
    
    Returns:
        Tuple of (response_data, status_code)
    """
    if not host_info:
        return {
            'success': False,
            'error': 'Host information required'
        }, 400
    
    # Use centralized call_host() - API key injection handled automatically
    return call_host(
        host_info,
        endpoint,
        method=method,
        data=data,
        timeout=timeout,
        extra_headers=headers
    )
