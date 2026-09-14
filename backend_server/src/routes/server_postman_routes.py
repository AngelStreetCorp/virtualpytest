from flask import Blueprint, jsonify, request
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
import re
import os
import json
import requests
import time
import threading
from pathlib import Path
from shared.src.lib.config.constants import CACHE_CONFIG

server_postman_bp = Blueprint('server_postman_bp', __name__, url_prefix='/server/postman')

# Path to config file
BACKEND_SERVER_ROOT = Path(__file__).parent.parent.parent
CONFIG_PATH = BACKEND_SERVER_ROOT / 'config' / 'postman' / 'postman_config.json'

# ============================================================================
# IN-MEMORY CACHE FOR POSTMAN COLLECTIONS
# ============================================================================
_postman_cache = {}  # {cache_key: {'data': {...}, 'timestamp': time.time()}}
_cache_lock = threading.Lock()

def load_config():
    """Load Postman configuration (workspaces + environments)"""
    try:
        if not CONFIG_PATH.exists():
            print(f"[@postman_routes] Config file not found: {CONFIG_PATH}")
            return {'workspaces': [], 'environments': []}
        
        with open(CONFIG_PATH, 'r') as f:
            config = json.load(f)
        
        print(f"[@postman_routes] Loaded config: {len(config.get('workspaces', []))} workspace(s), {len(config.get('environments', []))} environment(s)")
        return config
    except Exception as e:
        print(f"[@postman_routes] Error loading config: {e}")
        return {'workspaces': [], 'environments': []}

def load_workspaces_config():
    """Get workspaces from config"""
    config = load_config()
    return config.get('workspaces', [])

def get_workspace_by_id(workspace_id):
    """Get workspace config by ID"""
    workspaces = load_workspaces_config()
    for workspace in workspaces:
        if workspace['id'] == workspace_id:
            return workspace
    return None

def get_environments_by_workspace(workspace_id):
    """Get all environments for a workspace"""
    config = load_config()
    environments = config.get('environments', [])
    return [env for env in environments if env.get('workspaceId') == workspace_id]

def normalize_environment_variables(variables):
    """Convert environment variables from array format to dict format
    
    Supports two formats:
    1. Array format (Postman standard): [{"key": "x", "value": "y", "type": "secret"}, ...]
    2. Object format (simple): {"x": "y", ...}
    
    Returns: dict format {"x": "y", ...}
    """
    if isinstance(variables, list):
        # Convert array to dict, extracting just key-value pairs
        return {var['key']: var['value'] for var in variables if 'key' in var}
    elif isinstance(variables, dict):
        # Already in dict format
        return variables
    return {}

def get_environment_by_id(environment_id):
    """Get environment by ID"""
    config = load_config()
    environments = config.get('environments', [])
    for env in environments:
        if env['id'] == environment_id:
            return env
    return None

def substitute_variables(text, variables):
    """Replace {{variable}} placeholders with values from environment variables"""
    if not text or not variables:
        return text
    
    import re
    def replacer(match):
        var_name = match.group(1)
        value = variables.get(var_name)
        return str(value) if value is not None else match.group(0)
    
    # Replace {{variable}} with value
    result = re.sub(r'\{\{(\w+)\}\}', replacer, str(text))
    return result

# Postman API paths we build: '/collections/<id>', '/environments?workspace=<id>' ...
# Ids come from URL/query params, so restrict to the characters those paths need.
_POSTMAN_ENDPOINT_RE = re.compile(r'^/[A-Za-z0-9/_?=&-]*$')


def _allowed_test_hosts() -> set:
    """Hostnames the Postman runner may call: this server and its registered hosts."""
    from urllib.parse import urlparse
    from shared.src.lib.utils.build_url_utils import buildServerUrl
    from backend_server.src.lib.utils.server_utils import get_host_manager

    hosts = {'localhost', '127.0.0.1', '::1'}
    server_host = urlparse(buildServerUrl('')).hostname
    if server_host:
        hosts.add(server_host.lower())
    for host in get_host_manager().get_all_hosts().values():
        for key in ('host_url', 'host_ip'):
            value = host.get(key) or ''
            parsed = urlparse(value if '://' in value else f'http://{value}')
            if parsed.hostname:
                hosts.add(parsed.hostname.lower())
    return hosts


def _is_allowed_test_target(url: str) -> bool:
    """SSRF guard for run_api_test: only http(s) to this server or a registered host."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        return False
    return parsed.hostname.lower() in _allowed_test_hosts()


def call_postman_api(endpoint, api_key):
    """Call Postman API (security layer - API keys never exposed to frontend)"""
    try:
        if not _POSTMAN_ENDPOINT_RE.match(str(endpoint)) or '..' in endpoint or '//' in endpoint:
            raise ValueError(f'Invalid Postman API endpoint: {endpoint!r}')
        from urllib.parse import quote
        endpoint = quote(str(endpoint), safe='/?=&-')
        headers = {
            "X-Api-Key": api_key,
            "Content-Type": "application/json"
        }
        url = f"https://api.getpostman.com{endpoint}"
        
        print(f"[@postman_routes] Calling Postman API: {endpoint}")
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"[@postman_routes] Postman API error: {e}")
        raise


@server_postman_bp.route('/workspaces', methods=['GET'])
@handle_route_exceptions('server_postman:get_user_workspaces')
def get_user_workspaces():
    """Get list of configured user workspaces"""
    try:
        workspaces = load_workspaces_config()
        
        # Return sanitized data (no API keys!)
        result = []
        for ws in workspaces:
            result.append({
                'id': ws['id'],
                'name': ws['name'],
                'description': ws.get('description', ''),
                'workspaceId': ws.get('workspaceId', ''),
                'postmanUrl': ws.get('postmanUrl', ''),
            })
        
        return jsonify({
            'success': True,
            'workspaces': result
        })
    except Exception as e:
        print(f"[@postman_routes:get_user_workspaces] Error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@server_postman_bp.route('/environments', methods=['GET'])
@handle_route_exceptions('server_postman:get_config_environments')
def get_config_environments():
    """Get environments for a workspace from config file"""
    try:
        workspace_id = request.args.get('workspaceId')
        if not workspace_id:
            return jsonify({
                'success': False,
                'error': 'workspaceId parameter required'
            }), 400
        
        environments = get_environments_by_workspace(workspace_id)
        
        # Return sanitized data (variable values are safe to expose for testing)
        result = []
        for env in environments:
            result.append({
                'id': env['id'],
                'name': env['name'],
                'workspaceId': env.get('workspaceId'),
                'variables': env.get('variables', {})
            })
        
        return jsonify({
            'success': True,
            'environments': result
        })
    except Exception as e:
        print(f"[@postman_routes:get_workspace_environments] Error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@server_postman_bp.route('/workspaces/<workspace_id>/collections', methods=['GET'])
@handle_route_exceptions('server_postman:get_workspace_collections')
def get_workspace_collections(workspace_id):
    """Get collections for a workspace using Postman API (with 5-minute cache)"""
    try:
        # Check cache first
        cache_key = f"collections:{workspace_id}"
        with _cache_lock:
            if cache_key in _postman_cache:
                cached = _postman_cache[cache_key]
                age = time.time() - cached['timestamp']
                if age < CACHE_CONFIG['POSTMAN_TTL']:
                    print(f"[@cache] HIT: Postman collections for {workspace_id} (age: {age:.1f}s)")
                    return jsonify(cached['data'])
                else:
                    del _postman_cache[cache_key]
                    print(f"[@cache] EXPIRED: Postman collections for {workspace_id} (age: {age:.1f}s)")
        
        workspace = get_workspace_by_id(workspace_id)
        if not workspace:
            return jsonify({
                'success': False,
                'error': 'Workspace not found'
            }), 404
        
        # Call Postman API (backend handles API key - secure!)
        api_key = workspace['postmanApiKey']
        postman_workspace_id = workspace['workspaceId']
        
        print(f"[@postman_routes] Fetching collections from Postman API for workspace {workspace_id}...")
        
        # Get collections in workspace
        data = call_postman_api(f"/collections?workspace={postman_workspace_id}", api_key)
        
        collections = data.get('collections', [])
        
        # Enhance with request counts (fetch each collection details)
        enhanced_collections = []
        for collection in collections:
            collection_id = collection['uid']
            
            # Get collection details to count requests
            try:
                collection_data = call_postman_api(f"/collections/{collection_id}", api_key)
                collection_detail = collection_data.get('collection', {})
                
                # Count requests recursively
                request_count = count_requests_in_items(collection_detail.get('item', []))
                
                enhanced_collections.append({
                    'id': collection['uid'],
                    'name': collection['name'],
                    'description': collection_detail.get('info', {}).get('description', ''),
                    'requestCount': request_count
                })
            except Exception as e:
                print(f"[@postman_routes] Error fetching collection {collection_id}: {e}")
                # Add basic info even if detailed fetch fails
                enhanced_collections.append({
                    'id': collection['uid'],
                    'name': collection['name'],
                    'description': '',
                    'requestCount': 0
                })
        
        response_data = {
            'success': True,
            'collections': enhanced_collections
        }
        
        # Store in cache
        with _cache_lock:
            _postman_cache[cache_key] = {
                'data': response_data,
                'timestamp': time.time()
            }
            print(f"[@cache] SET: Postman collections for {workspace_id} (TTL: {CACHE_CONFIG['POSTMAN_TTL']}s)")
        
        return jsonify(response_data)
    except Exception as e:
        print(f"[@postman_routes:get_workspace_collections] Error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@server_postman_bp.route('/workspaces/<workspace_id>/environments', methods=['GET'])
@handle_route_exceptions('server_postman:get_workspace_environments')
def get_workspace_environments(workspace_id):
    """Get environments for a workspace using Postman API (with 5-minute cache)"""
    try:
        # Check cache first
        cache_key = f"environments:{workspace_id}"
        with _cache_lock:
            if cache_key in _postman_cache:
                cached = _postman_cache[cache_key]
                age = time.time() - cached['timestamp']
                if age < CACHE_CONFIG['POSTMAN_TTL']:
                    print(f"[@cache] HIT: Postman environments for {workspace_id} (age: {age:.1f}s)")
                    return jsonify(cached['data'])
                else:
                    del _postman_cache[cache_key]
                    print(f"[@cache] EXPIRED: Postman environments for {workspace_id} (age: {age:.1f}s)")
        
        workspace = get_workspace_by_id(workspace_id)
        if not workspace:
            return jsonify({
                'success': False,
                'error': 'Workspace not found'
            }), 404
        
        print(f"[@postman_routes] Fetching environments from Postman API for workspace {workspace_id}...")
        
        # Call Postman API
        api_key = workspace['postmanApiKey']
        postman_workspace_id = workspace['workspaceId']
        
        # Get environments in workspace
        data = call_postman_api(f"/environments?workspace={postman_workspace_id}", api_key)
        
        environments = data.get('environments', [])
        
        # Format environments
        formatted_environments = []
        for env in environments:
            formatted_environments.append({
                'id': env['uid'],
                'name': env['name'],
            })
        
        response_data = {
            'success': True,
            'environments': formatted_environments
        }
        
        # Store in cache
        with _cache_lock:
            _postman_cache[cache_key] = {
                'data': response_data,
                'timestamp': time.time()
            }
            print(f"[@cache] SET: Postman environments for {workspace_id} (TTL: {CACHE_CONFIG['POSTMAN_TTL']}s)")
        
        return jsonify(response_data)
    except Exception as e:
        print(f"[@postman_routes:get_workspace_environments] Error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@server_postman_bp.route('/environments/<environment_id>', methods=['GET'])
@handle_route_exceptions('server_postman:get_environment_details')
def get_environment_details(environment_id):
    """Get environment variables"""
    try:
        # Extract workspace_id from query params
        workspace_id = request.args.get('workspace_id')
        if not workspace_id:
            return jsonify({
                'success': False,
                'error': 'workspace_id query parameter required'
            }), 400
        
        workspace = get_workspace_by_id(workspace_id)
        if not workspace:
            return jsonify({
                'success': False,
                'error': 'Workspace not found'
            }), 404
        
        # Call Postman API
        api_key = workspace['postmanApiKey']
        data = call_postman_api(f"/environments/{environment_id}", api_key)
        
        environment = data.get('environment', {})
        
        # Extract variables
        variables = {}
        for var in environment.get('values', []):
            if var.get('enabled', True):
                variables[var['key']] = var['value']
        
        return jsonify({
            'success': True,
            'environment': {
                'id': environment.get('id'),
                'name': environment.get('name'),
                'variables': variables
            }
        })
    except Exception as e:
        print(f"[@postman_routes:get_environment_details] Error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@server_postman_bp.route('/collections/<collection_id>/requests', methods=['GET'])
@handle_route_exceptions('server_postman:get_collection_requests')
def get_collection_requests(collection_id):
    """Get all requests/endpoints from a collection (with 5-minute cache)"""
    try:
        # Extract workspace_id from query params
        workspace_id = request.args.get('workspace_id')
        if not workspace_id:
            return jsonify({
                'success': False,
                'error': 'workspace_id query parameter required'
            }), 400
        
        # Check cache first
        cache_key = f"requests:{collection_id}"
        with _cache_lock:
            if cache_key in _postman_cache:
                cached = _postman_cache[cache_key]
                age = time.time() - cached['timestamp']
                if age < CACHE_CONFIG['POSTMAN_TTL']:
                    print(f"[@cache] HIT: Postman requests for collection {collection_id} (age: {age:.1f}s)")
                    return jsonify(cached['data'])
                else:
                    del _postman_cache[cache_key]
                    print(f"[@cache] EXPIRED: Postman requests for collection {collection_id} (age: {age:.1f}s)")
        
        workspace = get_workspace_by_id(workspace_id)
        if not workspace:
            return jsonify({
                'success': False,
                'error': 'Workspace not found'
            }), 404
        
        print(f"[@postman_routes] Fetching requests from Postman API for collection {collection_id}...")
        
        # Call Postman API
        api_key = workspace['postmanApiKey']
        data = call_postman_api(f"/collections/{collection_id}", api_key)
        
        collection = data.get('collection', {})
        
        # Extract all requests recursively
        requests_list = []
        extract_requests_from_items(collection.get('item', []), requests_list)
        
        response_data = {
            'success': True,
            'requests': requests_list
        }
        
        # Store in cache
        with _cache_lock:
            _postman_cache[cache_key] = {
                'data': response_data,
                'timestamp': time.time()
            }
            print(f"[@cache] SET: Postman requests for collection {collection_id} (TTL: {CACHE_CONFIG['POSTMAN_TTL']}s)")
        
        return jsonify(response_data)
    except Exception as e:
        print(f"[@postman_routes:get_collection_requests] Error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@server_postman_bp.route('/requests/<request_id>/definition', methods=['GET'])
@handle_route_exceptions('server_postman:get_request_definition')
def get_request_definition(request_id):
    """Get full request definition (url, method, body, headers) from a request ID"""
    try:
        # Extract params
        workspace_id = request.args.get('workspace_id')
        collection_id = request.args.get('collection_id')
        
        if not workspace_id or not collection_id:
            return jsonify({
                'success': False,
                'error': 'workspace_id and collection_id query parameters required'
            }), 400
        
        # Check cache first
        cache_key = f"request_def:{request_id}"
        with _cache_lock:
            if cache_key in _postman_cache:
                cached = _postman_cache[cache_key]
                age = time.time() - cached['timestamp']
                if age < CACHE_CONFIG['POSTMAN_TTL']:
                    print(f"[@cache] HIT: Request definition {request_id} (age: {age:.1f}s)")
                    return jsonify(cached['data'])
                else:
                    del _postman_cache[cache_key]
                    print(f"[@cache] EXPIRED: Request definition {request_id} (age: {age:.1f}s)")
        
        workspace = get_workspace_by_id(workspace_id)
        if not workspace:
            return jsonify({
                'success': False,
                'error': 'Workspace not found'
            }), 404
        
        print(f"[@postman_routes] Fetching request definition from Postman for {request_id}...")
        
        # Fetch collection to find the request
        api_key = workspace['postmanApiKey']
        data = call_postman_api(f"/collections/{collection_id}", api_key)
        
        collection = data.get('collection', {})
        
        # Find request in collection items
        request_def = find_request_in_items(collection.get('item', []), request_id)
        
        if not request_def:
            return jsonify({
                'success': False,
                'error': 'Request not found in collection'
            }), 404
        
        # Extract request details
        request_data = request_def.get('request', {})
        
        # Parse URL
        url_data = request_data.get('url', {})
        if isinstance(url_data, str):
            url = url_data
        else:
            # Construct from parts
            protocol = url_data.get('protocol', 'https')
            host = url_data.get('host', [])
            path = url_data.get('path', [])
            
            # Join host and path
            if isinstance(host, list):
                host_str = '.'.join(host)
            else:
                host_str = str(host)
            
            if isinstance(path, list):
                path_str = '/' + '/'.join(path)
            else:
                path_str = str(path)
            
            url = f"{protocol}://{host_str}{path_str}"
        
        # Parse body
        body_data = request_data.get('body', {})
        body = None
        if body_data:
            mode = body_data.get('mode')
            if mode == 'raw':
                raw_body = body_data.get('raw', '')
                # Try to parse as JSON
                try:
                    import json
                    body = json.loads(raw_body)
                except:
                    body = raw_body
            elif mode == 'urlencoded':
                body = {item['key']: item['value'] for item in body_data.get('urlencoded', []) if 'key' in item}
            elif mode == 'formdata':
                body = {item['key']: item['value'] for item in body_data.get('formdata', []) if 'key' in item}
        
        # Parse headers
        headers_list = request_data.get('header', [])
        headers = {h['key']: h['value'] for h in headers_list if 'key' in h and not h.get('disabled')}
        
        response_data = {
            'success': True,
            'request': {
                'id': request_id,
                'name': request_def.get('name', ''),
                'method': request_data.get('method', 'GET'),
                'url': url,
                'body': body,
                'headers': headers
            }
        }
        
        # Store in cache
        with _cache_lock:
            _postman_cache[cache_key] = {
                'data': response_data,
                'timestamp': time.time()
            }
            print(f"[@cache] SET: Request definition {request_id} (TTL: {CACHE_CONFIG['POSTMAN_TTL']}s)")
        
        return jsonify(response_data)
    except Exception as e:
        print(f"[@postman_routes:get_request_definition] Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


def find_request_in_items(items, request_id):
    """Recursively find request by ID in collection items"""
    for item in items:
        # Check if this item is a request with matching ID
        if 'request' in item and item.get('id') == request_id:
            return item
        
        # Check nested items (folders)
        if 'item' in item:
            found = find_request_in_items(item['item'], request_id)
            if found:
                return found
    
    return None


@server_postman_bp.route('/test', methods=['POST'])
@handle_route_exceptions('server_postman:run_api_test')
def run_api_test():
    """Run API test immediately for selected endpoints with environment variable substitution"""
    try:
        from shared.src.lib.utils.build_url_utils import buildServerUrl
        
        data = request.json
        workspace_id = data.get('workspaceId')
        workspace_name = data.get('workspaceName')
        environment_id = data.get('environmentId')  # NEW: Environment ID for variable substitution
        endpoints = data.get('endpoints', [])
        
        # Load environment variables if specified
        env_variables = {}
        if environment_id:
            environment = get_environment_by_id(environment_id)
            if environment:
                raw_variables = environment.get('variables', {})
                # Normalize to dict format (supports both array and object formats)
                env_variables = normalize_environment_variables(raw_variables)
                print(f"[@postman_routes] Using environment '{environment.get('name')}' with {len(env_variables)} variables: {list(env_variables.keys())}")
            else:
                print(f"[@postman_routes] Warning: Environment '{environment_id}' not found")
        else:
            print(f"[@postman_routes] No environment selected, requests will use raw paths")
        
        if not endpoints:
            return jsonify({
                'success': False,
                'error': 'No endpoints provided'
            }), 400
        
        workspace = get_workspace_by_id(workspace_id)
        if not workspace:
            return jsonify({
                'success': False,
                'error': 'Workspace not found'
            }), 404
        
        print(f"[@postman_routes:run_api_test] Testing {len(endpoints)} endpoints")
        
        # Execute tests using requests
        results = []
        success_count = 0
        
        for ep in endpoints:
            method = ep.get('method', 'GET')
            path = ep.get('path', '')
            name = ep.get('name', path)
            body = ep.get('body', {})  # Get request body from endpoint definition
            
            # ==================================================================
            # STEP 1: Variable Substitution (like real Postman!)
            # ==================================================================
            # Substitute {{variables}} in path, params, and body
            path = substitute_variables(path, env_variables)
            
            # If path contains full URL (already substituted), use it directly
            if path.startswith('http://') or path.startswith('https://'):
                url = path
                print(f"[@postman_routes] Using full URL from path: {url}")
            else:
                # Path is relative, determine which base URL to use based on path
                # /host/* endpoints → host_url, everything else → server_url
                if path.startswith('/host/') or '/host/' in path:
                    base_url = env_variables.get('host_url')
                    url_type = 'host_url'
                else:
                    base_url = env_variables.get('server_url')
                    url_type = 'server_url'
                
                if not base_url:
                    # Fallback to buildServerUrl for server endpoints
                    base_url = buildServerUrl('')
                    print(f"[@postman_routes] No {{{{{url_type}}}}} in environment, using buildServerUrl fallback: {base_url}")
                else:
                    print(f"[@postman_routes] Using {{{{{url_type}}}}} from environment: {base_url}")
                
                # Ensure path starts with /
                if not path.startswith('/'):
                    path = '/' + path
                
                url = f"{base_url.rstrip('/')}{path}"
                print(f"[@postman_routes] Constructed URL: {url}")
            
            start_time = time.time()
            result_entry = {
                'name': name,
                'method': method,
                'path': path,
                'status': 'pending'
            }

            if not _is_allowed_test_target(url):
                print(f"[@postman_routes] BLOCKED {method} {url}: target is not this server or a registered host")
                result_entry['status'] = 'error'
                result_entry['error'] = 'Target host is not this server or a registered host'
                result_entry['statusCode'] = 0
                results.append(result_entry)
                continue
            
            try:
                print(f"[@postman_routes] Executing {method} {url}")
                
                # ==================================================================
                # STEP 2: Build Request (params, body, headers) with variables
                # ==================================================================
                params = {}
                json_data = None
                headers = {}
                
                # Add API key from environment if available
                api_key = env_variables.get('api_key')
                if api_key:
                    headers['X-API-Key'] = api_key
                    print(f"[@postman_routes] Using api_key from environment")
                
                # Add query parameters from environment variables
                # Common variables: team_id, host_name, device_id, userinterface, etc.
                if 'team_id' in env_variables:
                    params['team_id'] = env_variables['team_id']
                
                if 'host_name' in env_variables:
                    params['host_name'] = env_variables['host_name']
                
                if 'device_id' in env_variables:
                    params['device_id'] = env_variables['device_id']
                
                if 'userinterface' in env_variables:
                    # Map to userinterface_name for host routes
                    params['userinterface_name'] = env_variables['userinterface']
                
                # For /host/* endpoints, add context to request body (server will proxy)
                if path.startswith('/host/'):
                    json_data = {}
                    if 'host_name' in env_variables:
                        json_data['host_name'] = env_variables['host_name']
                    if 'device_id' in env_variables:
                        json_data['device_id'] = env_variables['device_id']
                    if 'userinterface' in env_variables:
                        json_data['userinterface'] = env_variables['userinterface']
                    print(f"[@postman_routes] Adding environment vars to request body: {json_data}")
                
                # Execute request
                response = requests.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json_data,
                    headers=headers,
                    timeout=10
                )
                
                duration = (time.time() - start_time) * 1000
                result_entry['statusCode'] = response.status_code
                result_entry['duration'] = round(duration, 2)
                result_entry['status'] = 'pass' if response.ok else 'fail'
                
                # Try to parse response body if JSON
                try:
                    result_entry['response'] = response.json()
                except:
                    result_entry['response'] = response.text[:500]  # Truncate text
                
                if response.ok:
                    success_count += 1
                    
            except Exception as e:
                print(f"[@postman_routes] Error executing {name}: {e}")
                result_entry['status'] = 'error'
                result_entry['error'] = str(e)
                result_entry['statusCode'] = 0
            
            results.append(result_entry)
        
        return jsonify({
            'success': True,
            'message': f'Completed {len(endpoints)} tests',
            'results': results,
            'passed': success_count,
            'total': len(endpoints)
        })
    except Exception as e:
        print(f"[@postman_routes:run_api_test] Error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# Helper functions

def count_requests_in_items(items):
    """Recursively count requests in collection items"""
    count = 0
    for item in items:
        if 'request' in item:
            count += 1
        if 'item' in item:  # Folder with nested items
            count += count_requests_in_items(item['item'])
    return count


def extract_requests_from_items(items, requests_list, folder_path=""):
    """Recursively extract all requests from collection items"""
    for item in items:
        if 'request' in item:
            # It's a request
            req = item['request']
            
            # Extract URL
            url = req.get('url', {})
            if isinstance(url, str):
                path = url
            else:
                path = url.get('raw', '')
                # Try to extract just the path
                if 'path' in url:
                    path = '/' + '/'.join(url['path'])
            
            # Extract method
            method = req.get('method', 'GET')
            
            # Build full path with folder
            full_name = f"{folder_path}/{item['name']}" if folder_path else item['name']
            
            # Postman API always provides uid for collection items
            item_id = item.get('uid') or item.get('id') or item.get('_postman_id')

            requests_list.append({
                'id': item_id,
                'name': item['name'],
                'fullName': full_name,
                'method': method,
                'path': path,
                'description': item.get('request', {}).get('description', '')
            })
        
        if 'item' in item:
            # It's a folder - recurse
            folder_name = item['name']
            new_path = f"{folder_path}/{folder_name}" if folder_path else folder_name
            extract_requests_from_items(item['item'], requests_list, new_path)

