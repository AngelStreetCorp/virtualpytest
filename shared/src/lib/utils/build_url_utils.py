"""
Centralized URL Building Utilities

Single source of truth for all URL construction patterns.
Eliminates hardcoded URLs and inconsistent building patterns.
Supports multi-device hosts with device-specific paths.
"""
import os
import glob
import requests
import json
import urllib3
from typing import Optional
from urllib.parse import urlparse

# Disable InsecureRequestWarning for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# =====================================================
# LOCAL PATH NORMALIZATION HELPERS
# =====================================================
# These helpers centralize hot/cold path handling across OSes.

def normalize_local_path(path: str) -> str:
    """Normalize local filesystem path to forward slashes (non-destructive)."""
    if not path:
        return path
    return path.replace('\\', '/')


def is_hot_storage_path(path: str) -> bool:
    """Return True if the path is in hot storage (supports Windows separators)."""
    if not path:
        return False
    normalized = normalize_local_path(path)
    return '/hot/' in normalized


def convert_hot_to_cold_path(path: str) -> str:
    """
    Convert a hot storage path to its cold storage equivalent.
    If path is not hot, returns the original path.
    Preserves Windows-style separators when possible.
    """
    if not path or path.startswith(('http://', 'https://')):
        return path
    normalized = normalize_local_path(path)
    if '/hot/' not in normalized:
        return path
    cold_normalized = normalized.replace('/hot/', '/')
    if '\\' in path and '/' not in path:
        return cold_normalized.replace('/', '\\')
    return cold_normalized


def normalize_capture_base_dir(capture_path: str) -> str:
    """
    Normalize a capture path to the device base directory.
    Handles paths that already include subfolders like /captures or /hot/captures.
    """
    if not capture_path:
        return capture_path
    normalized = normalize_local_path(capture_path).rstrip('/')
    base_name = os.path.basename(normalized)
    if base_name in ['captures', 'segments', 'thumbnails', 'metadata', 'audio', 'transcript', 'status']:
        parent = os.path.dirname(normalized)
        if os.path.basename(parent) == 'hot':
            normalized = os.path.dirname(parent)
        else:
            normalized = parent
    if '\\' in capture_path and '/' not in capture_path:
        return normalized.replace('/', '\\')
    return normalized

# =====================================================
# CORE URL BUILDING FUNCTION (No Dependencies)
# =====================================================

def call_host(
    host_info: dict,
    endpoint: str,
    method: str = 'POST',
    data: dict = None,
    query_params: dict = None,
    timeout: int = 30,
    extra_headers: dict = None
) -> tuple:
    """
    **SINGLE SOURCE OF TRUTH** for all server-to-host API calls.
    
    This function centralizes:
    - URL building (buildHostUrl)
    - API key injection (X-API-Key header) - the "decorator equivalent" for server side
    - Request execution (requests.post/get)
    - Error handling
    
    This is the server-side equivalent of @app.before_request decorator on host.
    
    Args:
        host_info: Complete host information (from get_host_manager)
        endpoint: The endpoint path (e.g., '/host/monitoring/latest-json')
        method: HTTP method ('GET', 'POST', 'PUT', 'DELETE')
        data: Request body data (dict)
        query_params: URL query parameters (dict)
        timeout: Request timeout in seconds (default: 30)
        extra_headers: Additional headers to include (dict)
        
    Returns:
        Tuple of (response_data, status_code)
        
    Example:
        response_data, status = call_host(
            host_info,
            '/host/monitoring/latest-json',
            method='POST',
            data={'device_id': 'device1'}
        )
    """
    try:
        # Build URL
        full_url = buildHostUrl(host_info, endpoint)
        
        # Log connection attempt for debugging
        host_name = host_info.get('host_name', 'unknown')
        host_api_url = host_info.get('host_api_url', 'not set')
        print(f"[@call_host] 🔗 Connecting to host '{host_name}'")
        print(f"[@call_host]    URL: {full_url}")
        print(f"[@call_host]    Method: {method}")
        print(f"[@call_host]    host_api_url: {host_api_url}")
        if query_params:
            print(f"[@call_host]    Query params: {query_params}")
        
        # Prepare request kwargs
        # connect_timeout is short (3s) so unreachable hosts fail fast — a 60s
        # connect timeout combined with stale host IPs blocks API requests for
        # tens of seconds on cold paths. read_timeout stays caller-controlled.
        kwargs = {
            'timeout': (3, timeout),
            'verify': False
        }
        
        # Add query parameters
        if query_params:
            kwargs['params'] = query_params
        
        # Build headers with automatic API key injection
        headers = {}
        
        # Add Content-Type for POST/PUT with data
        if data and method.upper() in ['POST', 'PUT']:
            headers['Content-Type'] = 'application/json'
            kwargs['json'] = data
        
        # **AUTOMATIC API KEY INJECTION** - the "decorator equivalent" for server side
        # This single line replaces all scattered os.getenv('API_KEY') calls
        api_key = os.getenv('API_KEY')
        if api_key:
            headers['X-API-Key'] = api_key
        else:
            print(f"[@call_host] ⚠️ WARNING: API_KEY not found in environment - request to {endpoint} will fail!")
        
        # Merge with extra headers
        if extra_headers:
            headers.update(extra_headers)
        
        if headers:
            kwargs['headers'] = headers
        
        # DEBUG: Log headers being sent (especially for cache/populate endpoint)
        if 'cache/populate' in endpoint:
            print(f"[@call_host] DEBUG for {endpoint}:")
            print(f"[@call_host]   - headers dict: {headers}")
            print(f"[@call_host]   - kwargs['headers']: {kwargs.get('headers', 'NOT SET')}")
            print(f"[@call_host]   - kwargs keys: {list(kwargs.keys())}")
            print(f"[@call_host]   - API_KEY in env: {bool(os.getenv('API_KEY'))}")
        
        # Execute request (timeout passed explicitly: (connect, read) — never unbounded)
        method_upper = method.upper()
        request_timeout = kwargs.pop('timeout')
        if method_upper not in ('GET', 'POST', 'PUT', 'DELETE'):
            return {
                'success': False,
                'error': f'Unsupported HTTP method: {method}'
            }, 400
        response = requests.request(method_upper, full_url, timeout=request_timeout, **kwargs)
        
        # Parse response
        try:
            response_data = response.json()
        except json.JSONDecodeError:
            response_data = {
                'success': False,
                'error': 'Invalid JSON response from host',
                'raw_response': response.text[:500]
            }
        
        return response_data, response.status_code
        
    except requests.exceptions.Timeout:
        host_name = host_info.get('host_name', 'unknown')
        host_api_url = host_info.get('host_api_url', 'not set')
        print(f"[@call_host] ❌ TIMEOUT connecting to host '{host_name}'")
        print(f"[@call_host]    URL: {full_url}")
        print(f"[@call_host]    host_api_url: {host_api_url}")
        print(f"[@call_host]    Timeout: {timeout}s")
        return {
            'success': False,
            'error': f'Request to host timed out (timeout={timeout}s)'
        }, 504
    except requests.exceptions.ConnectionError as e:
        host_name = host_info.get('host_name', 'unknown')
        host_api_url = host_info.get('host_api_url', 'not set')
        print(f"[@call_host] ❌ CONNECTION ERROR connecting to host '{host_name}'")
        print(f"[@call_host]    URL: {full_url}")
        print(f"[@call_host]    host_api_url: {host_api_url}")
        print(f"[@call_host]    Error: {str(e)}")
        print(f"[@call_host]    Error type: {type(e).__name__}")
        if hasattr(e, 'request'):
            print(f"[@call_host]    Request URL: {e.request.url if e.request else 'N/A'}")
        return {
            'success': False,
            'error': f'Could not connect to host: {str(e)}'
        }, 503
    except Exception as e:
        host_name = host_info.get('host_name', 'unknown')
        host_api_url = host_info.get('host_api_url', 'not set')
        print(f"[@call_host] ❌ UNEXPECTED ERROR connecting to host '{host_name}'")
        print(f"[@call_host]    URL: {full_url}")
        print(f"[@call_host]    host_api_url: {host_api_url}")
        print(f"[@call_host]    Error: {str(e)}")
        print(f"[@call_host]    Error type: {type(e).__name__}")
        import traceback
        print(f"[@call_host]    Traceback: {traceback.format_exc()}")
        return {
            'success': False,
            'error': f'Host call error: {str(e)}'
        }, 500

def _get_nginx_host_url(host_info: dict) -> str:
    """
    Get host URL for nginx static file serving (strips Flask server port)
    
    Args:
        host_info: Host information from registry
        
    Returns:
        Host URL without port for nginx serving (preserves original protocol)
    """
    host_url = host_info.get('host_url', '')
    
    # Strip port numbers but preserve protocol
    if ':' in host_url:
        import re
        # Only strip port numbers, not the protocol
        # Preserves original protocol (http:// stays http://, https:// stays https://)
        host_url = re.sub(r':(\d+)$', '', host_url)
    
    # For local IP addresses without protocol, default to HTTP
    if host_url and ('192.168.' in host_url or '10.' in host_url or '127.0.0.1' in host_url):
        if not host_url.startswith(('http://', 'https://')):
            # No protocol specified, default to HTTP for local IPs
            host_url = f'http://{host_url}'
    
    return host_url


def _resolve_host_name_from_info(host_info: dict) -> Optional[str]:
    """Resolve host_name even if it needs to be parsed from host_url/host_api_url."""
    host_name = host_info.get('host_name')
    if host_name:
        return host_name

    host_url = host_info.get('host_url') or host_info.get('host_api_url')
    if not host_url:
        return None

    path = host_url
    if '://' in host_url:
        parsed = urlparse(host_url)
        path = parsed.path or ''

    segments = [segment for segment in path.split('/') if segment]
    for index, segment in enumerate(segments):
        if segment.lower() == 'host' and index + 1 < len(segments):
            resolved = segments[index + 1]
            host_info['host_name'] = resolved
            return resolved

    return None


def _get_host_route_prefix(host_info: dict) -> str:
    """Get the canonical `/host/<host-name>` prefix used across the product."""
    host_name = _resolve_host_name_from_info(host_info)
    if host_name:
        return f"/host/{host_name}"

    # Fallback to any path we can derive from host_url/host_api_url
    host_url = host_info.get('host_url') or host_info.get('host_api_url') or '/host'

    if '://' in host_url:
        parsed = urlparse(host_url)
        path = parsed.path or ''
    else:
        path = host_url

    clean = '/' + path.lstrip('/')
    clean = clean.rstrip('/')

    return clean or '/host'


def get_host_api_origin(host_info: dict) -> str:
    """The origin a *process* should call a host on, e.g. http://192.168.0.109:6109.

    Prefers `host_api_url` — the direct address the server itself uses in
    call_host(). `host_url` is usually browser-relative (`/host/<name>`), a route
    only the reverse proxy resolves: prefixing it with the backend server's own
    origin yields a 404, because :5109 does not serve `/host/<name>` (BUG-0091).
    It is used here only when it already carries a scheme.

    Returns '' when neither key gives an absolute URL.
    """
    for key in ('host_api_url', 'host_url'):
        value = host_info.get(key, '')
        if value and value.startswith(('http://', 'https://')):
            return value.rstrip('/')
    return ''


# Back-compat alias for the previous private name.
_get_host_absolute_base_url = get_host_api_origin


def _build_host_relative_url(host_info: dict, suffix: str) -> str:
    """Attach suffix to canonical host prefix (ensures `/host/<name>` appears exactly once)."""
    prefix = _get_host_route_prefix(host_info)
    return f"{prefix}{suffix}"


def _build_host_absolute_url(host_info: dict, relative_url: str) -> str:
    """Convert relative host route into absolute URL when a base with protocol is available."""
    base = get_host_api_origin(host_info)
    if base:
        return f"{base}{relative_url}"
    return relative_url

def buildHostUrl(host_info: dict, endpoint: str) -> str:
    """
    Build URL for SERVER-TO-SERVER API calls to host
    
    This function is used by backend servers to call host APIs directly.
    It uses host_api_url (HTTP direct connection) instead of host_url (HTTPS via nginx).
    
    Args:
        host_info: Complete host information (from registration)
        endpoint: The endpoint path to append
        
    Returns:
        Complete URL to the host API endpoint for direct server-to-server communication
        
    Examples:
        # Same network (direct HTTP):
        buildHostUrl(host_data, '/host/av/takeScreenshot')
        -> 'http://192.168.1.34:6109/host/av/takeScreenshot'
        
        # Different networks (HTTPS):
        buildHostUrl(host_data, '/host/av/takeScreenshot')
        -> 'https://remote-host.com/host/av/takeScreenshot'
    """
    if not host_info:
        raise ValueError("host_info is required for buildHostUrl")
    
    # Prefer host_api_url for server-to-server communication (direct, HTTP)
    # Falls back to host_url if host_api_url not available (backward compatibility)
    host_base_url = host_info.get('host_api_url') or host_info.get('host_url')
    
    if not host_base_url:
        raise ValueError(f"Host missing host_api_url and host_url: {host_info.get('host_name', 'unknown')}")
    
    # Clean endpoint
    clean_endpoint = endpoint.lstrip('/')
    
    return f"{host_base_url}/{clean_endpoint}"

# =====================================================
# SPECIALIZED URL BUILDERS
# =====================================================

def buildCaptureUrl(host_info: dict, filename: str, device_id: str) -> str:
    """
    Build URL for live screenshot captures (served by nginx, not Flask)

    Args:
        host_info: Host information from registry
        filename: Screenshot filename (sequential format like 'capture_0001.jpg')
        device_id: Device ID for multi-device hosts (required)

    Returns:
        Relative URL to screenshot capture (browser resolves against origin)

    Example:
        buildCaptureUrl(host_info, 'capture_0001.jpg', 'device1')
        -> '/host/myhost/stream/capture1/captures/capture_0001.jpg'
    """
    # Get device-specific capture path
    capture_path = _get_device_capture_path(host_info, device_id)

    return _build_host_relative_url(host_info, f"{capture_path}/{filename}")

def buildThumbnailUrl(host_info: dict, filename: str, device_id: str) -> str:
    """
    Build URL for thumbnail images (hot/cold architecture - separate folder)
    
    Args:
        host_info: Host information from registry
        filename: Thumbnail filename (e.g., 'capture_0001_thumbnail.jpg')
        device_id: Device ID for multi-device hosts (required)
        
    Returns:
        Complete URL to thumbnail image
        
    Example:
        buildThumbnailUrl(host_info, 'capture_0001_thumbnail.jpg', 'device1')
        -> 'https://host/host/stream/capture1/thumbnails/capture_0001_thumbnail.jpg'
    """
    # Get device-specific stream path (not capture path)
    stream_path = _get_device_stream_path(host_info, device_id)
    
    relative = _build_host_relative_url(host_info, f"{stream_path}/thumbnails/{filename}")
    return _build_host_absolute_url(host_info, relative)

def buildMetadataUrl(host_info: dict, filename: str, device_id: str) -> str:
    """
    Build URL for metadata JSON files (hot/cold architecture - separate folder)
    
    Args:
        host_info: Host information from registry
        filename: Metadata filename (e.g., 'capture_0001.json')
        device_id: Device ID for multi-device hosts (required)
        
    Returns:
        Complete URL to metadata file
        
    Example:
        buildMetadataUrl(host_info, 'capture_0001.json', 'device1')
        -> 'https://host/host/stream/capture1/metadata/capture_0001.json'
    """
    # Get device-specific stream path
    stream_path = _get_device_stream_path(host_info, device_id)
    
    relative = _build_host_relative_url(host_info, f"{stream_path}/metadata/{filename}")
    return _build_host_absolute_url(host_info, relative)

def buildCroppedImageUrl(host_info: dict, filename: str, device_id: str) -> str:
    """
    Build URL for cropped images (served by nginx, not Flask)
    
    Args:
        host_info: Host information from registry
        filename: Cropped image filename
        device_id: Device ID for multi-device hosts (required)
        
    Returns:
        Complete URL to cropped image
        
    Example:
        buildCroppedImageUrl(host_info, 'cropped_button_20250117134500.jpg', 'device1')
        -> 'https://host/host/stream/capture1/captures/cropped/cropped_button_20250117134500.jpg'
    """
    # Get device-specific capture path
    capture_path = _get_device_capture_path(host_info, device_id)
    
    relative = _build_host_relative_url(host_info, f"{capture_path}/cropped/{filename}")
    return _build_host_absolute_url(host_info, relative)

def buildReferenceImageUrl(host_info: dict, device_model: str, filename: str) -> str:
    """
    Build URL for reference images (served by nginx, not Flask)
    
    Args:
        host_info: Host information from registry
        device_model: Device model (e.g., 'android_mobile', 'pixel_7')
        filename: Reference image filename
        
    Returns:
        Complete URL to reference image
        
    Example:
        buildReferenceImageUrl(host_info, 'android_mobile', 'login_button.jpg')
        -> 'https://host/host/stream/resources/android_mobile/login_button.jpg'
    """
    relative = _build_host_relative_url(host_info, f"/stream/resources/{device_model}/{filename}")
    return _build_host_absolute_url(host_info, relative)

def buildVerificationResultUrl(host_info: dict, filename: str, device_id: str) -> str:
    """
    Build URL for verification result images (served by nginx, not Flask)
    
    Args:
        host_info: Host information from registry
        filename: Verification result filename
        device_id: Device ID for multi-device hosts (required)
        
    Returns:
        Complete URL to verification result image
        
    Example:
        buildVerificationResultUrl(host_info, 'source_image_0.png', 'device1')
        -> 'https://host/host/stream/capture1/captures/verification_results/source_image_0.png'
    """
    # Get device-specific capture path
    capture_path = _get_device_capture_path(host_info, device_id)
    
    relative = _build_host_relative_url(host_info, f"{capture_path}/verification_results/{filename}")
    return _build_host_absolute_url(host_info, relative)

def buildStreamUrl(host_info: dict, device_id: str) -> str:
    """
    Build stream URL for any device (HLS for video devices, direct HTTPS URL for VNC)
    
    Args:
        host_info: Host information from registry
        device_id: Device ID for multi-device hosts (required)
        
    Returns:
        Complete URL to stream for the device (HLS for video, direct HTTPS for VNC)
        
    Examples:
        buildStreamUrl(host_info, 'device1')
        -> 'https://host:444/host/stream/capture1/segments/output.m3u8'
        
        buildStreamUrl(host_info, 'host_vnc')
        -> 'https://192.168.1.x:6080/vnc_lite.html'
    """
    # Check if this is a VNC device
    device = get_device_by_id(host_info, device_id)
    if device and device.get('device_model') == 'host_vnc':
        vnc_path = device.get('video_stream_path')
        if not vnc_path:
            raise ValueError(f"VNC device {device_id} has no video_stream_path configured")
        
        # Case 1: Relative path (nginx proxy mode)
        # e.g., "/host/host-debian12/vnc_lite.html?password=admin1234"
        # Return as-is, frontend prepends origin
        if vnc_path.startswith('/'):
            return vnc_path
        
        # Case 2: Full URL already configured (direct mode or custom)
        # e.g., "https://custom-domain.com/vnc_lite.html"
        # Return as-is
        if vnc_path.startswith(('http://', 'https://')):
            return vnc_path
        
        # Case 3: Path without leading slash (legacy/direct mode)
        # Build direct HTTPS URL to websockify (port 6080)
        # For standalone hosts without nginx
        host_ip = host_info.get('host_ip')
        if not host_ip:
            raise ValueError("host_ip is required to build VNC URL for direct mode")
        
        clean_path = vnc_path.lstrip('/')
        vnc_stream_url = f"https://{host_ip}:6080/{clean_path}"

        # For Linux hosts in direct mode, append password if not already present
        host_os = host_info.get('host_os', '').lower()
        if host_os == 'linux' and 'password=' not in vnc_stream_url:
            if '?' in vnc_stream_url:
                vnc_stream_url += '&password=admin1234'
            else:
                vnc_stream_url += '?password=admin1234'

        return vnc_stream_url
    else:
        # For regular devices, return HLS stream URL
        # Get device-specific stream path
        stream_path = _get_device_stream_path(host_info, device_id)

        # Clean stream_path to avoid double /host/ prefix
        # Remove /host prefix if present (defensive programming)
        clean_stream_path = stream_path
        if '/host/' in stream_path or stream_path.startswith('/host'):
            # Remove /host prefix: /host/stream/... -> /stream/...
            clean_stream_path = stream_path.replace('/host/', '/').replace('/host', '/')
            print(f"[@build_url_utils:buildStreamUrl] Cleaned stream_path: {stream_path} -> {clean_stream_path}")

        relative = _build_host_relative_url(host_info, f"{clean_stream_path}/segments/output.m3u8")
        return relative

def buildHostImageUrl(host_info: dict, image_path: str) -> str:
    """
    Build URL for BROWSER to access images stored on host (nginx-served, not Flask)

    This function is used by frontend/browser to fetch static files (images, videos).
    Returns relative URL with host_name for nginx routing (matches buildCaptureUrl pattern).

    Args:
        host_info: Host information from registry
        image_path: Relative or absolute image path on host

    Returns:
        Relative URL to host-served image for browser access via nginx

    Example:
        buildHostImageUrl(host_info, '/stream/captures/screenshot.jpg')
        -> '/host/myhost/stream/captures/screenshot.jpg'
    """
    # Handle absolute paths by converting to stream-relative URL (cross-platform)
    import platform
    if image_path.startswith('/var/www/html/'):
        image_path = image_path.replace('/var/www/html/', '')
    elif platform.system() == 'Windows' or '\\' in image_path or (len(image_path) > 1 and image_path[1] == ':'):
        # Windows absolute path (e.g., C:\virtualpytest\stream\capture\captures\file.jpg)
        # Extract stream-relative path by finding 'stream' component
        normalized = image_path.replace('\\', '/')
        stream_idx = normalized.find('/stream/')
        if stream_idx >= 0:
            image_path = normalized[stream_idx + 1:]  # 'stream/capture/captures/file.jpg'

    # Drop the /hot/ tier marker — nginx serves these via try_files /$dev/hot/$sub/$file
    # /$dev/$sub/$file =404, so the *URL* must not encode the storage tier. If we leave
    # /hot/ in the URL the browser request becomes /host/<name>/stream/<dev>/hot/<sub>/<file>,
    # which doesn't match the proxy regex (which captures stream subfolders) and 400s.
    image_path = image_path.replace('/hot/', '/')

    # Ensure path doesn't start with /
    clean_path = image_path.lstrip('/')

    # Return relative URL with host identifier for nginx routing
    # Nginx expects: /host/{hostname}/stream/...
    # This matches the pattern used by buildCaptureUrl and buildStreamUrl
    host_name = _resolve_host_name_from_info(host_info)
    if host_name:
        return f"/host/{host_name}/{clean_path}"

    # Fallback without hostname (direct access)
    host_url = host_info.get('host_api_url') or _get_nginx_host_url(host_info)
    host_url = host_url.rstrip('/')
    if '/host/' in host_url or host_url.endswith('/host'):
        separator = '' if host_url.endswith('/') else '/'
        return f"{host_url}{separator}{clean_path}"
    return f"{host_url}/host/{clean_path}"

def buildCloudImageUrl(bucket_name: str, image_path: str, base_url: str = None) -> str:
    """
    Build URL for images stored in cloud storage (R2, S3, MinIO, etc.)

    Args:
        bucket_name: Cloud storage bucket name
        image_path: Path to image in cloud storage
        base_url: Optional base URL (defaults to local MinIO or R2 public URL)

    Returns:
        Complete URL to cloud-stored image

    Example:
        buildCloudImageUrl('references', 'android_mobile/login_button.jpg')
        -> Local MinIO: 'http://localhost:9000/virtualpytest/references/android_mobile/login_button.jpg'
        -> R2: 'https://pub-account.r2.dev/virtualpytest/references/android_mobile/login_button.jpg'
    """
    import os

    # If no base_url provided, determine from environment
    if not base_url:
        # Get bucket name from env var
        bucket_name = os.environ.get('MINIO_BUCKET', 'virtualpytest')
        # Check for R2 public URL first
        r2_public_url = os.environ.get('CLOUDFLARE_R2_PUBLIC_URL')
        if r2_public_url:
            base_url = r2_public_url
        else:
            # Use local MinIO
            minio_endpoint = os.environ.get('MINIO_ENDPOINT', 'http://localhost:9000')
            base_url = minio_endpoint

    # Clean the image path
    clean_path = image_path.lstrip('/')

    return f"{base_url.rstrip('/')}/{bucket_name}/{clean_path}"

def buildServerUrl(endpoint: str) -> str:
    """
    Host URL builder - Build URLs for server endpoints from host context
    
    Args:
        endpoint: The endpoint path to append
        
    Returns:
        Complete URL to the server endpoint for host use
    """
    import os
    import re
    
    # Host uses SERVER_URL environment variable to reach server
    server_url = os.getenv('SERVER_URL', 'http://localhost:5109')
    
    # Auto-detect local installation and force HTTP instead of HTTPS
    # This prevents SSL connection errors for local development/testing
    if _is_local_installation(server_url):
        original_url = server_url
        server_url = _convert_to_http_for_local(server_url)
        if original_url != server_url:
            print(f"🔄 [URL] Auto-converted local HTTPS to HTTP: {original_url} -> {server_url}")
    
    # Clean endpoint
    clean_endpoint = endpoint.lstrip('/')

    return f"{server_url}/{clean_endpoint}"


def server_auth_headers() -> dict:
    """Service-auth headers for host -> server calls.

    Returns the shared service key as ``X-API-Key`` so host->server requests
    (register / ping / unregister / execution-lock) still authenticate once the
    server enforces frontend JWT (ENFORCE_FRONTEND_JWT=true). Harmless while
    enforcement is off — the server ignores the header. Empty dict when no
    API_KEY is configured, so behaviour is unchanged on hosts without one.
    """
    api_key = (os.getenv('API_KEY') or '').strip()
    return {'X-API-Key': api_key} if api_key else {}


def _is_local_network_host(host_url: str) -> bool:
    """
    Check if a host URL is on the local network (should use HTTP instead of HTTPS)
    
    Args:
        host_url: The host URL to check
        
    Returns:
        True if the host is on local network, False if remote
    """
    import re
    
    # Extract hostname/IP from URL
    match = re.search(r'://([^:/]+)', host_url)
    if not match:
        return False
    
    hostname = match.group(1).lower()
    
    # Local network patterns
    local_patterns = [
        r'^192\.168\.',      # 192.168.x.x (most common home/office networks)
        r'^10\.',            # 10.x.x.x (corporate networks)
        r'^172\.(1[6-9]|2[0-9]|3[0-1])\.',  # 172.16.x.x - 172.31.x.x (private networks)
        r'^127\.',           # 127.x.x.x (localhost)
        r'^localhost$',      # localhost
        r'^.*\.local$',      # .local domains (mDNS)
    ]
    
    # Check if hostname matches any local pattern
    for pattern in local_patterns:
        if re.match(pattern, hostname):
            return True
    
    return False

def _is_local_installation(server_url: str) -> bool:
    """
    Detect if this is a local installation that should use HTTP instead of HTTPS.
    
    Args:
        server_url: The server URL to check
        
    Returns:
        True if this appears to be a local installation
    """
    import re
    
    if not server_url:
        return True
    
    # Convert to lowercase for checking
    url_lower = server_url.lower()
    
    # Local indicators
    local_patterns = [
        'localhost',
        '127.0.0.1',
        '0.0.0.0',
        # Private IP ranges (RFC 1918)
        r'192\.168\.\d+\.\d+',
        r'10\.\d+\.\d+\.\d+', 
        r'172\.(1[6-9]|2[0-9]|3[0-1])\.\d+\.\d+',
        # Link-local addresses
        r'169\.254\.\d+\.\d+',
        # Docker/container common addresses
        r'172\.17\.\d+\.\d+',
        r'172\.18\.\d+\.\d+',
    ]
    
    # Check for local patterns
    for pattern in local_patterns:
        if re.search(pattern, url_lower):
            return True
    
    # Check for development/local domains
    local_domains = [
        '.local',
        '.localhost',
        '.dev',
        '.test',
        'virtualpytest-local',
    ]
    
    for domain in local_domains:
        if domain in url_lower:
            return True
    
    return False

def _convert_to_http_for_local(server_url: str) -> str:
    """
    Convert HTTPS URLs to HTTP for local installations.
    
    Args:
        server_url: The server URL to convert
        
    Returns:
        HTTP version of the URL for local use
    """
    import re
    
    if not server_url:
        return 'http://localhost:5109'
    
    # If already HTTP, return as-is
    if server_url.startswith('http://'):
        return server_url
    
    # Convert HTTPS to HTTP
    if server_url.startswith('https://'):
        http_url = server_url.replace('https://', 'http://', 1)
        
        # For local installations, also check if we need to adjust the port
        # HTTPS typically uses 443, but local HTTP servers often use different ports
        if ':443' in http_url or http_url.endswith(':443'):
            # Replace 443 with common local server port
            http_url = http_url.replace(':443', ':5109')
        elif not re.search(r':\d+', http_url.split('//')[1]):
            # No port specified, add default local server port
            # Extract the domain part and add port
            parts = http_url.split('/')
            if len(parts) >= 3:
                domain_part = parts[2]
                if ':' not in domain_part:
                    parts[2] = f"{domain_part}:5109"
                    http_url = '/'.join(parts)
        
        return http_url
    
    # If no protocol specified, assume HTTP for local
    if not server_url.startswith(('http://', 'https://')):
        # Add http:// prefix and ensure port is specified
        if ':' not in server_url:
            return f"http://{server_url}:5109"
        else:
            return f"http://{server_url}"
    
    return server_url

# =====================================================
# MULTI-DEVICE HELPER FUNCTIONS
# =====================================================

def get_device_local_captures_path(host_info: dict, device_id: str) -> str:
    """
    Get device-specific local captures path for file system operations.
    
    Args:
        host_info: Host information from registry
        device_id: Device ID (required - no fallbacks)
        
    Returns:
        Local file system path for captures from device configuration (DEVICE1_VIDEO_CAPTURE_PATH)
        
    Raises:
        ValueError: If device configuration or capture path is not found
    """
    if not host_info:
        raise ValueError("host_info is required for device path resolution")
    
    if not device_id:
        raise ValueError("device_id is required - no fallbacks allowed")
    
    # Get devices configuration from host_info
    devices = host_info.get('devices', [])
    if not devices:
        raise ValueError(f"No devices configured in host_info for device_id: {device_id}")
    
    # Find the specific device
    for device in devices:
        if device.get('device_id') == device_id:
            capture_path = device.get('video_capture_path')
            if not capture_path:
                raise ValueError(f"Device {device_id} has no video_capture_path configured (DEVICE{device_id.replace('device', '')}_VIDEO_CAPTURE_PATH missing)")
            
            print(f"[@build_url_utils:get_device_local_captures_path] Using device {device_id} capture path: {capture_path}")
            return capture_path
    
    raise ValueError(f"Device {device_id} not found in host configuration. Available devices: {[d.get('device_id') for d in devices]}")

def get_device_local_stream_path(host_info: dict, device_id: str) -> str:
    """
    Get device-specific local stream path for file system operations.
    
    Args:
        host_info: Host information from registry
        device_id: Device ID (required - no fallbacks)
        
    Returns:
        Local file system path for stream from device configuration (DEVICE1_VIDEO_STREAM_PATH)
        
    Raises:
        ValueError: If device configuration or stream path is not found
    """
    if not host_info:
        raise ValueError("host_info is required for device path resolution")
    
    if not device_id:
        raise ValueError("device_id is required - no fallbacks allowed")
    
    # Get devices configuration from host_info
    devices = host_info.get('devices', [])
    if not devices:
        raise ValueError(f"No devices configured in host_info for device_id: {device_id}")
    
    # Find the specific device
    for device in devices:
        if device.get('device_id') == device_id:
            stream_path = device.get('video_stream_path')
            if not stream_path:
                raise ValueError(f"Device {device_id} has no video_stream_path configured (DEVICE{device_id.replace('device', '')}_VIDEO_STREAM_PATH missing)")
            
            # Convert URL path to local file system path
            # Remove '/host' prefix and convert to absolute path
            clean_path = stream_path.replace('/host', '')
            local_path = f'/var/www/html{clean_path}'
            
            print(f"[@build_url_utils:get_device_local_stream_path] Using device {device_id} stream path: {local_path}")
            return local_path
    
    raise ValueError(f"Device {device_id} not found in host configuration. Available devices: {[d.get('device_id') for d in devices]}")

def get_device_local_thumbnails_path(capture_path: str) -> str:
    """
    Get local thumbnails path from a capture image path.
    HOT/COLD ARCHITECTURE: Thumbnails are in /thumbnails/ folder (sibling to /captures/)
    
    Args:
        capture_path: Full path to capture image (e.g., /var/www/html/stream/capture1/captures/image.jpg)
        
    Returns:
        Local file system path to thumbnails folder (e.g., /var/www/html/stream/capture1/thumbnails)
        
    Example:
        get_device_local_thumbnails_path('/var/www/html/stream/capture1/captures/image.jpg')
        -> '/var/www/html/stream/capture1/thumbnails'
    """
    # Get parent directory of captures folder
    captures_dir = os.path.dirname(capture_path)  # /var/www/html/stream/captureX/captures
    device_dir = os.path.dirname(captures_dir)    # /var/www/html/stream/captureX
    thumbnails_dir = os.path.join(device_dir, 'thumbnails')
    
    return thumbnails_dir

def get_device_directory_from_captures(captures_dir: str) -> str:
    """
    Get device base directory from captures directory.
    HOT/COLD ARCHITECTURE: Device dir is parent of /captures/, /thumbnails/, /segments/
    
    Args:
        captures_dir: Full path to captures directory (e.g., /var/www/html/stream/capture1/captures)
        
    Returns:
        Device base directory (e.g., /var/www/html/stream/capture1)
        
    Example:
        get_device_directory_from_captures('/var/www/html/stream/capture1/captures')
        -> '/var/www/html/stream/capture1'
    """
    # Remove trailing slash if present
    captures_dir = captures_dir.rstrip('/')
    
    # Get parent directory (device base)
    device_dir = os.path.dirname(captures_dir)
    
    return device_dir

def get_current_device_id() -> str:
    """
    Get the current device ID from Flask app context.
    This helps routes determine which device they're working with.
    
    Returns:
        Device ID (e.g., 'device1', 'device2') or raises error if not available
    """
    try:
        from flask import current_app, request
        
        # First try to get device_id from request parameters
        if request and request.method in ['POST', 'GET']:
            if request.method == 'POST' and request.is_json:
                data = request.get_json() or {}
                device_id = data.get('device_id')
                if device_id:
                    return device_id
            elif request.method == 'GET':
                device_id = request.args.get('device_id')
                if device_id:
                    return device_id
        
        # No fallbacks - device_id must be explicitly provided
        raise ValueError("device_id is required in request parameters - no fallbacks allowed")
        
    except Exception as e:
        print(f"[@build_url_utils:get_current_device_id] Error getting device ID: {e}")
        raise ValueError("device_id is required in request parameters - no fallbacks allowed")

def _get_device_stream_path(host_info: dict, device_id: str) -> str:
    """
    Get device-specific stream path from host configuration.
    
    Args:
        host_info: Host information from registry
        device_id: Device ID (required - no fallbacks)
        
    Returns:
        Stream path for the device from device configuration (DEVICE1_VIDEO_STREAM_PATH)
        
    Raises:
        ValueError: If device configuration or stream path is not found
    """
    if not host_info:
        raise ValueError("host_info is required for device path resolution")
    
    if not device_id:
        raise ValueError("device_id is required - no fallbacks allowed")
    
    # Get devices configuration from host_info
    devices = host_info.get('devices', [])
    if not devices:
        raise ValueError(f"No devices configured in host_info for device_id: {device_id}")
    
    # Find the specific device
    for device in devices:
        if device.get('device_id') == device_id:
            stream_path = device.get('video_stream_path')
            if not stream_path:
                raise ValueError(f"Device {device_id} has no video_stream_path configured (DEVICE{device_id.replace('device', '')}_VIDEO_STREAM_PATH missing)")
            
            # Remove '/host' prefix if present and ensure starts with /
            clean_path = stream_path.replace('/host', '').lstrip('/')
            url_path = f'/{clean_path}'
            
            print(f"[@build_url_utils:_get_device_stream_path] Using device {device_id} stream path: {url_path}")
            return url_path
    
    raise ValueError(f"Device {device_id} not found in host configuration. Available devices: {[d.get('device_id') for d in devices]}")

def _get_device_capture_path(host_info: dict, device_id: str) -> str:
    """
    Get device-specific capture path from host configuration.
    
    Args:
        host_info: Host information from registry
        device_id: Device ID (required - no fallbacks)
        
    Returns:
        Capture path for the device from device configuration (DEVICE1_VIDEO_STREAM_PATH + /captures)
        
    Raises:
        ValueError: If device configuration or stream path is not found
    """
    if not host_info:
        raise ValueError("host_info is required for device path resolution")
    
    if not device_id:
        raise ValueError("device_id is required - no fallbacks allowed")
    
    # Get devices configuration from host_info
    devices = host_info.get('devices', [])
    if not devices:
        raise ValueError(f"No devices configured in host_info for device_id: {device_id}")
    
    # Find the specific device
    for device in devices:
        if device.get('device_id') == device_id:
            # Special handling for VNC devices - they use video_capture_path directly
            if device.get('device_model') == 'host_vnc':
                capture_path = device.get('video_capture_path')
                if not capture_path:
                    raise ValueError(f"VNC device {device_id} has no video_capture_path configured")
                
                # Extract device folder name from capture path (cross-platform)
                # Use centralized helper to handle paths that include /captures or /hot
                # Linux:   /var/www/html/stream/capture1 -> capture1
                # Windows: C:\virtualpytest\stream\capture -> capture
                from shared.src.lib.utils.storage_path_utils import get_capture_folder
                device_folder = get_capture_folder(capture_path)
                if not device_folder:
                    raise ValueError(f"Unable to determine capture folder from path: {capture_path}")
                url_path = f'/stream/{device_folder}/captures'
                
                return url_path
            else:
                # Regular devices derive capture path from video_stream_path
                stream_path = device.get('video_stream_path')
                if not stream_path:
                    raise ValueError(f"Device {device_id} has no video_stream_path configured (DEVICE{device_id.replace('device', '')}_VIDEO_STREAM_PATH missing)")
                
                # Remove '/host' prefix if present and ensure starts with /
                clean_path = stream_path.replace('/host', '').lstrip('/')
                url_path = f'/{clean_path}/captures'
                
                return url_path
    
    raise ValueError(f"Device {device_id} not found in host configuration. Available devices: {[d.get('device_id') for d in devices]}")

def get_device_by_id(host_info: dict, device_id: str) -> dict:
    """
    Get device configuration by device ID.
    
    Args:
        host_info: Host information from registry
        device_id: Device ID to find (e.g., 'device1', 'device2')
        
    Returns:
        Device configuration dictionary or None if not found
    """
    if not host_info or not device_id:
        return None
    
    devices = host_info.get('devices', [])
    
    for device in devices:
        if device.get('device_id') == device_id:
            return device
    
    return None

def buildCaptureUrlFromPath(host_info: dict, capture_path: str, device_id: str) -> str:
    """
    Build URL for capture from a local file path by extracting filename
    
    Args:
        host_info: Host information from registry
        capture_path: Local file path to capture (e.g., '/path/capture_0001.jpg')
        device_id: Device ID for multi-device hosts (required)
        
    Returns:
        Complete URL to capture
        
    Raises:
        ValueError: If filename cannot be extracted from path
        
    Example:
        buildCaptureUrlFromPath(host_info, '/tmp/capture_0001.jpg', 'device1')
        -> 'https://host:444/host/stream/capture1/captures/capture_0001.jpg'
    """
    import os
    
    # Extract filename from capture path
    filename = os.path.basename(capture_path)
    # Allow 'verification_source.jpg' (fixed name for verification persistence) or standard 'capture_*' format
    if not (filename.startswith('capture_') or filename == 'verification_source.jpg'):
        raise ValueError(f'Invalid capture filename format: {filename}')
    
    # Use existing buildCaptureUrl function
    return buildCaptureUrl(host_info, filename, device_id)


def resolveCaptureFilePath(filename: str) -> str:
    """
    Resolve local file path for a capture filename
    
    Args:
        filename: Capture filename (e.g., 'capture_0001.jpg')
        
    Returns:
        Local file path to capture
        
    Raises:
        ValueError: If filename is invalid or unsafe
        
    Example:
        resolveCaptureFilePath('capture_0001.jpg')
        -> '/tmp/captures/capture_0001.jpg'
    """
    # Extract the base filename without query parameters
    base_filename = (filename or '').split('?')[0]

    # Security validation - a capture is a single file name, never a path
    if (not base_filename or base_filename != os.path.basename(base_filename)
            or base_filename in ('.', '..') or '\x00' in base_filename):
        raise ValueError(f'Invalid filename: {filename}')

    # Use host's tmp directory for captures; resolve symlinks and re-check containment
    from werkzeug.utils import secure_filename
    safe_name = secure_filename(base_filename)
    if safe_name != base_filename:
        raise ValueError(f'Invalid filename: {filename}')
    captures_root = os.path.realpath('/tmp/captures')
    capture_path = os.path.realpath(os.path.join(captures_root, safe_name))
    if os.path.dirname(capture_path) != captures_root:
        raise ValueError(f'Invalid filename: {filename}')

    return capture_path

def resolveImageFilePath(image_path: str) -> str:
    """
    Resolve and validate local file path for an image
    
    Args:
        image_path: Image path from request
        
    Returns:
        Validated local file path to image
        
    Raises:
        ValueError: If path is invalid, unsafe, or not allowed
        
    Example:
        resolveImageFilePath('/tmp/verification_results/source_image_0.png')
        -> '/tmp/verification_results/source_image_0.png'
    """
    if not image_path:
        raise ValueError('No image path specified')
    
    # Security check - block path traversal attempts
    if '..' in image_path or '\x00' in image_path:
        raise ValueError(f'Path traversal not allowed: {image_path}')
    
    # Resolve symbolic links and redundant separators so the allow-list check below
    # sees the real target, not a link that points outside an allowed root.
    normalized_path = os.path.realpath(image_path)
    
    # Security check - allow /tmp/ paths and project paths
    project_root = os.getenv('PROJECT_ROOT', '/home/pi/virtualpytest')  # fallback for compatibility
    from shared.src.lib.utils.storage_path_utils import get_stream_base_path
    stream_base_path = get_stream_base_path()
    document_root = os.path.dirname(stream_base_path)
    allowed_paths = ['/tmp/', project_root, document_root]

    normalized_check_path = os.path.normcase(normalized_path)
    normalized_allowed_paths = []
    for path in allowed_paths:
        if not path:
            continue
        norm_allowed = os.path.normpath(path)
        if not norm_allowed.endswith(os.sep):
            norm_allowed = norm_allowed + os.sep
        normalized_allowed_paths.append(os.path.normcase(norm_allowed))

    if not any(normalized_check_path.startswith(prefix) for prefix in normalized_allowed_paths):
        raise ValueError(f'Invalid image path: {image_path}. Allowed paths: {allowed_paths}')

    return normalized_path


def convertHostUrlToLocalPath(host_url: str) -> str:
    """
    Convert a host URL back to local file system path.
    This is the reverse operation of buildHostImageUrl.
    
    Args:
        host_url: Host URL (e.g., 'https://host.com/host/stream/capture1/captures/image.jpg')
        
    Returns:
        Local file system path (e.g., '/var/www/html/stream/capture1/captures/image.jpg')
        
    Raises:
        ValueError: If URL format is invalid or unsafe
        
    Example:
        convertHostUrlToLocalPath('https://host.com/host/stream/capture1/captures/image.jpg')
        -> '/var/www/html/stream/capture1/captures/image.jpg'
    """
    if not host_url:
        raise ValueError("host_url is required")
    
    from urllib.parse import urlparse
    from shared.src.lib.utils.storage_path_utils import get_stream_base_path

    def _build_local_path_from_relative(relative: str) -> str:
        stream_base = get_stream_base_path()
        document_root = os.path.dirname(stream_base)
        segments = [segment for segment in relative.split('/') if segment]
        if not segments:
            raise ValueError(f"Could not determine local path from URL: {host_url}")
        return os.path.join(document_root, *segments)
    
    try:
        parsed_url = urlparse(host_url)
        url_path = parsed_url.path
        
        # Handle URLs that are missing /host/ prefix (common issue with server port URLs)
        if '/host/' not in url_path:
            # Check if this looks like a direct nginx path (starts with /stream/, /captures/, etc.)
            if url_path.startswith(('/stream/', '/captures/', '/resources/')):
                # This is a direct nginx path, just convert to local path
                relative_path = url_path.lstrip('/')
                return _build_local_path_from_relative(relative_path)
            else:
                raise ValueError(f"Invalid host URL format - expected /host/ in path or direct nginx path: {host_url}")
        
        # Find and remove everything up to and including '/host/' to get the relative path
        host_index = url_path.find('/host/')
        relative_path = url_path[host_index + 6:]  # Remove everything up to and including '/host/'
        relative_path = relative_path.lstrip('/')

        # Strip host_name segment (e.g., /host/{host_name}/stream/...) so we focus on the nginx folders
        cleaned_path = relative_path
        prefix_candidates = ('stream/', 'captures/', 'resources/')
        first_prefix_index = None
        for prefix in prefix_candidates:
            prefix_index = cleaned_path.find(prefix)
            if prefix_index >= 0 and (first_prefix_index is None or prefix_index < first_prefix_index):
                first_prefix_index = prefix_index

        if first_prefix_index is not None:
            cleaned_path = cleaned_path[first_prefix_index:]

        if not cleaned_path:
            raise ValueError(f"Could not determine local path from URL: {host_url}")

        relative_path = cleaned_path.lstrip('/')

        # Security validation - prevent path traversal
        if '..' in relative_path or relative_path.startswith('/'):
            raise ValueError(f"Unsafe path detected in URL: {host_url}")

        # Convert to absolute local path using nginx document root
        local_path = _build_local_path_from_relative(relative_path)
        
        return local_path
        
    except Exception as e:
        raise ValueError(f"Failed to convert host URL to local path: {e}")


def resolveImageSourceToLocalPath(image_source: str) -> str:
    """
    Resolve image source input (URL, nginx path, absolute path, or filename)
    into a local filesystem path.

    Args:
        image_source: Image source string from API request.

    Returns:
        Absolute local path to the image.

    Raises:
        ValueError: If image source cannot be resolved to a valid local path.
    """
    if not image_source:
        raise ValueError("image_source is required")

    source = image_source.strip()
    if not source:
        raise ValueError("image_source is empty")

    # URL and nginx-style paths (/host/... or /stream/...) can be reversed.
    if source.startswith(('http://', 'https://', '/host/', '/stream/', '/captures/', '/resources/')):
        return convertHostUrlToLocalPath(source)

    # Absolute filesystem path
    if os.path.isabs(source):
        return resolveImageFilePath(source)

    # Relative stream path (e.g., stream/capture/captures/file.jpg)
    if '/' in source or '\\' in source:
        from shared.src.lib.utils.storage_path_utils import get_stream_base_path
        normalized = source.replace('\\', '/').lstrip('/')
        stream_base = get_stream_base_path()
        document_root = os.path.dirname(stream_base)
        candidate = os.path.join(document_root, normalized)
        return resolveImageFilePath(candidate)

    # Bare filename fallback (e.g., verification_source.jpg)
    from shared.src.lib.utils.storage_path_utils import get_stream_base_path
    stream_base = get_stream_base_path()
    candidate_patterns = [
        os.path.join(stream_base, '*', 'captures', source),
        os.path.join(stream_base, '*', 'hot', 'captures', source),
    ]
    candidates = []
    for pattern in candidate_patterns:
        candidates.extend(glob.glob(pattern))

    if candidates:
        # Prefer newest file if multiple devices have same filename.
        latest = max(candidates, key=lambda p: os.path.getmtime(p))
        return resolveImageFilePath(latest)

    raise ValueError(f"Could not resolve image source to local path: {image_source}")

def buildScriptReportUrl(device_model: str, script_name: str, timestamp: str, base_url: str = None) -> str:
    """
    Build URL for script reports stored in cloud storage (R2).
    
    Args:
        device_model: Device model (e.g., 'android_mobile')
        script_name: Script name (e.g., 'validation')
        timestamp: Timestamp in YYYYMMDDHHMMSS format
        base_url: Optional custom base URL (defaults to R2)
        
    Returns:
        Complete URL to script report
        
    Example:
        buildScriptReportUrl('android_mobile', 'validation', '20250117134500')
        -> 'https://r2-bucket-url/script-reports/android_mobile/validation_20250117_20250117134500/report.html'
    """
    if base_url is None:
        # Use environment variable for R2 public URL
        import os
        base_url = os.environ.get('CLOUDFLARE_R2_PUBLIC_URL', 'https://your-r2-domain.com')
    
    # Create folder structure: script-reports/{device_model}/{script_name}_{date}_{timestamp}/
    date_str = timestamp[:8]  # YYYYMMDD from YYYYMMDDHHMMSS
    folder_name = f"{script_name}_{date_str}_{timestamp}"
    report_path = f"script-reports/{device_model}/{folder_name}/report.html"
    
    # Clean the base URL and build complete URL
    clean_base_url = base_url.rstrip('/')
    
    return f"{clean_base_url}/{report_path}"
