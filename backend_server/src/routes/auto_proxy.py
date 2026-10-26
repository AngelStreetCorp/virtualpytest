"""
Auto Proxy - Simple Passthrough System

Replaces 12 pure proxy route files with a single handler.
No legacy code, no backward compatibility - just clean elimination of duplication.
"""

import time
import threading
from flask import Blueprint, request, jsonify
from backend_server.src.lib.utils.route_utils import proxy_to_host_with_params
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.utils.unmatched_endpoint import explain_unmatched_endpoint
from shared.src.lib.config.constants import CACHE_CONFIG, HTTP_CONFIG

# Contract 38: `system/` is DEFAULT-DENY. /host/system/* is the host's admin surface
# (runCommand = shell as the service user, updateCore, applyBundle, updatePrereqs, envFiles...).
# Every legitimate caller has its own server route (server_system_routes.py) that checks a
# permission. Only the entries below are passthroughs that any authenticated user may use.
# Do not add an admin-ish endpoint here; add a dedicated, permission-checked server route.
SYSTEM_PASSTHROUGH_ALLOWLIST = {
    # (method, endpoint). Hands the dashboard the host's noVNC password (only when
    # HOST_VNC_AUTOCONNECT=true) so the VNC tile connects without a prompt. POST on purpose:
    # the viewer role is blocked from POST.
    ('POST', 'system/vnc-info'),
}

auto_proxy_bp = Blueprint('auto_proxy', __name__)

# ============================================================================
# IN-MEMORY CACHE FOR STREAM URLs
# ============================================================================
_stream_url_cache = {}  # {cache_key: {'data': {...}, 'timestamp': time.time()}}
_cache_lock = threading.Lock()


def invalidate_stream_url_cache(host_name: str) -> int:
    """Drop a host's cached stream URLs. Called on (re-)registration: the host may have
    changed DEVICEn_VIDEO_STREAM_PATH, and a 24h-old URL then 404s for every viewer."""
    prefix = f"{host_name}:"
    with _cache_lock:
        stale = [k for k in _stream_url_cache if k.startswith(prefix)]
        for k in stale:
            del _stream_url_cache[k]
    return len(stale)

@auto_proxy_bp.route('/server/<path:endpoint>', methods=['GET', 'POST', 'PUT', 'DELETE'])
@handle_route_exceptions('auto_proxy')
def auto_proxy(endpoint):
    """
    Auto proxy handler - routes /server/* to /host/* for pure passthrough routes
    
    Examples:
    - /server/ai-execution/executeTask -> /host/ai-execution/executeTask
    - /server/actions/executeBatch -> /host/actions/executeBatch
    - /server/av/getStreamUrl -> /host/av/getStreamUrl (POST->GET conversion)
    - /server/verification/image/execute -> /host/verification/image/execute
    - /server/verification/text/execute -> /host/verification/text/execute
    
    Note: Blueprints registered BEFORE auto_proxy in app.py take precedence.
    Example: server_ai_execution_routes handles /resetCache specifically, auto_proxy handles /executeTask
    
    EXCLUDED from auto-proxy (handled by dedicated blueprints):
    - /server/executable/* (handled by server_executable_bp - no host_name needed for listing)
    - /server/mcp/* (handled by mcp_bp - registered BEFORE auto_proxy, takes precedence)
    """
    # Dot segments would let /server/x/../y reach a host path other than /host/<endpoint>
    # once the HTTP client normalises the URL.
    if any(seg in ('.', '..') for seg in endpoint.split('/')):
        return jsonify({'success': False, 'error': 'Invalid endpoint path'}), 400
    # Normalize endpoint: handle double /server/ prefix
    if endpoint.startswith('server/'):
        endpoint = endpoint[7:]
        print(f"[@auto_proxy] 🔧 Normalized double /server/ prefix: /server/server/{endpoint} -> /server/{endpoint}")
    if endpoint.startswith(('executable/', 'settings/', 'teams/', 'users/', 'workspaces/', 'auth/', 'devices/')):
        return jsonify({'success': False, 'error': f'Endpoint /server/{endpoint} is handled by a dedicated blueprint, not auto-proxy'}), 404
    if endpoint.startswith('system/') and (request.method, endpoint) not in SYSTEM_PASSTHROUGH_ALLOWLIST:
        return jsonify({'success': False, 'error': f'Endpoint /server/{endpoint} is handled by a dedicated server route, not auto-proxy'}), 404
    data = request.get_json() if request.method in ['POST', 'PUT'] else None
    host_endpoint = f'/host/{endpoint}'
    query_params = {}
    team_id = request.args.get('team_id')
    if team_id:
        query_params['team_id'] = team_id
        if request.method == 'POST' and data is not None:
            data['team_id'] = team_id
    if request.method == 'GET':
        query_params.update(request.args.to_dict())
    elif data and 'device_id' in data:
        query_params['device_id'] = data['device_id']
    target_method = request.method
    if endpoint in ['av/getStreamUrl', 'av/getStatus']:
        target_method = 'GET'
        if request.method == 'POST' and data.get('device_id'):
            query_params['device_id'] = data.get('device_id')
    if endpoint == 'av/getStreamUrl':
        host_name = data.get('host_name') if data else query_params.get('host_name')
        device_id = query_params.get('device_id')
        if host_name and device_id:
            cache_key = f"{host_name}:{device_id}"
            with _cache_lock:
                if cache_key in _stream_url_cache:
                    cached = _stream_url_cache[cache_key]
                    age = time.time() - cached['timestamp']
                    if age < CACHE_CONFIG['LONG_TTL']:
                        print(f"[@cache] HIT: Stream URL for {host_name}/{device_id} (age: {age/3600:.1f}h)")
                        return jsonify(cached['data'])
                    del _stream_url_cache[cache_key]

            # Build stream URL server-side without proxying to host
            # Avoids 504 when host gunicorn worker is busy executing a testcase
            try:
                from backend_server.src.lib.utils.server_utils import get_host_manager
                from shared.src.lib.utils.build_url_utils import buildStreamUrl, buildAudioStreamUrl
                host_manager = get_host_manager()
                host_info = host_manager.get_host(host_name)
                if host_info:
                    stream_url = buildStreamUrl(host_info, device_id)
                    response_data = {'success': True, 'stream_url': stream_url, 'device_id': device_id}
                    # host_vnc devices carry a separate audio HLS playlist (BUG-0597 /
                    # BUG-0605). This server-side shortcut used to answer with the
                    # video URL only, so the dashboard's useStream never saw an
                    # audio_stream_url and never rendered the <audio> track.
                    audio_stream_url = buildAudioStreamUrl(host_info, device_id)
                    if audio_stream_url:
                        response_data['audio_stream_url'] = audio_stream_url
                    with _cache_lock:
                        _stream_url_cache[cache_key] = {'data': response_data, 'timestamp': time.time()}
                    print(f"[@auto_proxy] Built stream URL server-side for {host_name}/{device_id}: {stream_url} (audio={audio_stream_url})")
                    return jsonify(response_data)
            except Exception as e:
                print(f"[@auto_proxy] Server-side stream URL build failed, falling back to host proxy: {e}")
    if '/navigation/execute' in endpoint or '/navigation/batch-execute' in endpoint or 'action/executeBatch' in endpoint or 'verification/executeBatch' in endpoint:
        timeout = HTTP_CONFIG['NAVIGATION_TIMEOUT']
    elif 'av/getStreamUrl' in endpoint:
        timeout = HTTP_CONFIG['VERY_SHORT_TIMEOUT']
    elif 'ai-generation/start-validation' in endpoint or 'ai-generation/validate-next-item' in endpoint or 'ai-generation/start-node-verification' in endpoint or 'ai-generation/auto-discover-screen' in endpoint:
        timeout = 300
    elif endpoint == 'av/generateDom':
        # LLM DOM generation (GPT-5.5) runs ~45-60s — well past DEFAULT_TIMEOUT.
        timeout = 300
    elif 'crawl/app' in endpoint:
        timeout = 180
    elif endpoint == 'av/loadVideo':
        # May download the video to the host first (curl, up to 600 s).
        timeout = 600
    else:
        timeout = HTTP_CONFIG['DEFAULT_TIMEOUT']
    print(f"[@auto_proxy] 📡 Proxying {target_method} /server/{endpoint} -> {host_endpoint} with timeout={timeout}s")
    response_data, status_code = proxy_to_host_with_params(
        host_endpoint, target_method, data, query_params, timeout=timeout
    )
    # This catch-all answers for EVERY /server/* path that matched no blueprint, so a caller
    # that got the path wrong lands here too — and the host helper's answer, "host_name
    # required", blames a device parameter. That is how a GitLab route whose project carried an
    # encoded slash (BUG-0507) answered a question about device hosts for an entire afternoon.
    # The explanation itself lives in lib/utils/unmatched_endpoint.py, which imports nothing, so
    # the message can be tested without the whole backend.
    explained = explain_unmatched_endpoint(endpoint, response_data, status_code)
    if explained is not response_data:
        # Log it as what it is. The line above says "Proxying" as if this were a normal device
        # call, which is exactly why the real cause stayed hidden: the logs looked healthy while
        # a feature's requests were being forwarded to a host that had never heard of them.
        print(f"[@auto_proxy] ⚠️  UNMATCHED ROUTE — /server/{endpoint} matched no blueprint and was "
              f"forwarded to a device host anyway. If this is a VirtualPyTest route it did not "
              f"match; if it is a device route it needs a host_name. "
              f"({status_code} {explained.get('error')})", flush=True)
    response_data = explained
    if status_code == 200 and response_data.get('success'):
        cache_invalidation_endpoints = [
            'ai-generation/continue-exploration',
            'ai-generation/finalize-structure',
            'ai-generation/cleanup-temp',
            'ai-generation/approve-node-verifications'
        ]
        if any(endpoint.endswith(ep) for ep in cache_invalidation_endpoints):
            tree_id = data.get('tree_id') if data else None
            if tree_id:
                try:
                    from routes.server_navigation_trees_routes import invalidate_cached_tree
                except ImportError:
                    from backend_server.src.routes.server_navigation_trees_routes import invalidate_cached_tree
                invalidate_cached_tree(tree_id, team_id)
                print(f"[@auto_proxy] 🔄 Cache invalidated for tree {tree_id} after {endpoint}")
    if endpoint == 'av/getStreamUrl' and status_code == 200 and response_data.get('success'):
        host_name = data.get('host_name') if data else query_params.get('host_name')
        device_id = query_params.get('device_id')
        if host_name and device_id:
            cache_key = f"{host_name}:{device_id}"
            with _cache_lock:
                _stream_url_cache[cache_key] = {'data': response_data, 'timestamp': time.time()}
                print(f"[@cache] SET: Stream URL for {host_name}/{device_id} (24h TTL)")
    return jsonify(response_data), status_code