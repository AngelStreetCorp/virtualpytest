"""
VirtualPyTest - Host Stream File Serving Routes
Serves HLS video streams (.m3u8, .ts) and related files when Nginx is not available
"""

import os
from flask import Blueprint, send_from_directory, request, current_app, jsonify
from werkzeug.utils import secure_filename
from backend_host.src.lib.utils.route_decorators import route_exception_handler
from shared.src.lib.utils.storage_path_utils import get_capture_folder, get_capture_storage_path, get_stream_base_path, sanitize_folder_name
from shared.src.lib.utils.app_utils import cors_allowed_origins


def _is_under(base_path: str, file_path: str) -> bool:
    """True when file_path (after resolving symlinks) lives inside base_path."""
    real_base = os.path.realpath(base_path)
    real_file = os.path.realpath(file_path)
    return real_file == real_base or real_file.startswith(real_base + os.sep)

host_stream_bp = Blueprint('host_stream', __name__)


@host_stream_bp.after_request
def _add_stream_cors_headers(response):
    """Put the CORS headers on EVERY response of this blueprint, errors included.

    They used to be added next to each `send_from_directory`, so a 404/400/500 —
    which is a plain `jsonify(...)` — went out with no `Access-Control-Allow-Origin`
    at all. A cross-origin caller then does not see the 404: the browser refuses to
    expose the response and reports "blocked by CORS policy", which is what made a
    missing manifest on one device look like a CORS misconfiguration of the whole
    site (BUG-0101 investigation). The status has to survive the error path, not
    just the happy one.

    `setdefault` so a handler that already set a header (or a future stricter
    origin) is never duplicated or overridden.

    The origin is echoed, not `*`, whenever the caller sends one we allow. These
    paths now sit behind the host-session cookie gate (BUG-0107 step 2), and a
    cross-origin caller that must send that cookie fetches with credentials — for
    which the browser rejects a wildcard `Access-Control-Allow-Origin` outright,
    whatever the status code. That is the mobile app: a Capacitor shell on its own
    `https://localhost` origin, so every stream request it makes is cross-origin.
    `*` is kept for callers that send no Origin or an unlisted one, so a plain
    uncredentialed fetch of a public stream keeps working exactly as before.
    """
    origin = request.headers.get('Origin')
    if origin and origin.rstrip('/') in (cors_allowed_origins() or []):
        response.headers.setdefault('Access-Control-Allow-Origin', origin)
        response.headers.setdefault('Access-Control-Allow-Credentials', 'true')
        # The cached response for one origin must not be replayed to another.
        response.headers.add('Vary', 'Origin')
    else:
        response.headers.setdefault('Access-Control-Allow-Origin', '*')
    response.headers.setdefault('Access-Control-Allow-Methods', 'GET, OPTIONS')
    response.headers.setdefault('Access-Control-Allow-Headers', 'Content-Type, Range')
    response.headers.setdefault('Access-Control-Expose-Headers', 'Content-Length, Content-Range')
    return response

@host_stream_bp.route('/stream/<device_folder>/<content_type>/<path:filename>', methods=['GET', 'OPTIONS'])
@host_stream_bp.route('/host/stream/<device_folder>/<content_type>/<path:filename>', methods=['GET', 'OPTIONS'])
def serve_stream_file(device_folder, content_type, filename):
    """
    Serve HLS stream files (.m3u8, .ts) and related content.
    
    Supports two URL patterns for compatibility:
      - /stream/...        (direct access, no nginx)
      - /host/stream/...   (via nginx proxy or legacy URLs)
    
    URL Pattern: /stream/{device_folder}/{content_type}/{filename}
    Examples:
      - /stream/capture1/segments/output.m3u8
      - /stream/capture1/segments/segment_000000001.ts
      - /stream/capture1/captures/capture_000000001.jpg
      - /stream/capture1/thumbnails/capture_000000001_thumbnail.jpg
      - /stream/capture1/metadata/capture_000000001.json
      - /stream/capture1/audio/chunk_10min_0_en.mp3
    
    Also accessible via:
      - /host/stream/capture1/segments/output.m3u8 (etc.)
    
    Storage Architecture:
      - Checks hot storage first (RAM disk): /var/www/html/stream/{device}/hot/{content_type}/
      - Falls back to cold storage (SD card): /var/www/html/stream/{device}/{content_type}/
    
    Authentication: Public (no API key required)
    """
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        # headers come from _add_stream_cors_headers
        return current_app.response_class()
    
    try:
        # device_folder is joined into a filesystem path below: a plain folder name only
        try:
            device_folder = secure_filename(sanitize_folder_name(device_folder))
        except ValueError as e:
            return jsonify({'success': False, 'error': str(e)}), 400

        # Base path for streams (centralized - handles Windows auto-detection)
        base_path = get_stream_base_path()

        # Special-case running log (hot storage only)
        if content_type == 'hot' and filename == 'running.log':
            hot_path = os.path.join(base_path, device_folder, 'hot')
            hot_file = os.path.join(hot_path, filename)

            if not os.path.exists(hot_file) or not os.path.isfile(hot_file) or not _is_under(base_path, hot_file):
                print(f"[@host_stream] ❌ Running log not found: {device_folder}/hot/{filename}")
                print(f"[@host_stream]    STREAM_BASE_PATH: {base_path}")
                print(f"[@host_stream]    Checked hot: {hot_file} (exists={os.path.exists(hot_file)})")
                return jsonify({
                    'success': False,
                    'error': 'File not found'
                }), 404

            mimetype = 'application/json'
            directory = hot_path
            response = send_from_directory(
                directory,
                filename,
                mimetype=mimetype
            )
            response.headers.add('Cache-Control', 'no-cache, no-store, must-revalidate')
            response.headers.add('Pragma', 'no-cache')
            response.headers.add('Expires', '0')
            return response

        # Valid content types
        valid_types = ['segments', 'captures', 'thumbnails', 'metadata', 'audio', 'transcript', 'reports']
        if content_type not in valid_types:
            return jsonify({
                'success': False,
                'error': f'Invalid content type: {content_type}'
            }), 400

        # Try hot storage first (RAM disk)
        hot_path = os.path.join(base_path, device_folder, 'hot', content_type)
        cold_path = os.path.join(base_path, device_folder, content_type)
        
        
        file_path = None
        storage_type = None
        
        # Check hot storage (send_from_directory re-checks `filename` with safe_join;
        # the realpath containment below also covers symlinks inside the tree)
        hot_file = os.path.join(hot_path, filename)
        if os.path.exists(hot_file) and os.path.isfile(hot_file) and _is_under(base_path, hot_file):
            file_path = hot_file
            storage_type = 'hot'
            directory = hot_path
        else:
            # Fallback to cold storage
            cold_file = os.path.join(cold_path, filename)
            if os.path.exists(cold_file) and os.path.isfile(cold_file) and _is_under(base_path, cold_file):
                file_path = cold_file
                storage_type = 'cold'
                directory = cold_path
        
        if not file_path:
            # Detailed diagnostics for debugging
            print(f"[@host_stream] ❌ File not found: {device_folder}/{content_type}/{filename}")
            print(f"[@host_stream]    STREAM_BASE_PATH: {base_path}")
            print(f"[@host_stream]    Checked hot: {hot_file} (exists={os.path.exists(hot_file)})")
            print(f"[@host_stream]    Checked cold: {cold_file} (exists={os.path.exists(cold_file)})")
            print(f"[@host_stream]    Cold dir exists: {os.path.exists(cold_path)}")
            if os.path.exists(cold_path):
                try:
                    files = os.listdir(cold_path)[:10]
                    print(f"[@host_stream]    Files in cold dir ({len(files)}): {files}")
                except Exception as e:
                    print(f"[@host_stream]    Error listing cold dir: {e}")
            else:
                # Check parent to help diagnose
                parent = os.path.dirname(cold_path)
                if os.path.exists(parent):
                    try:
                        dirs = os.listdir(parent)[:10]
                        print(f"[@host_stream]    Parent dir {parent} contains: {dirs}")
                    except Exception as e:
                        print(f"[@host_stream]    Error listing parent: {e}")
                else:
                    print(f"[@host_stream]    Parent dir does not exist: {parent}")
            return jsonify({
                'success': False,
                'error': 'File not found'
            }), 404
        
        # Determine MIME type
        if filename.endswith('.m3u8'):
            mimetype = 'application/vnd.apple.mpegurl'
        elif filename.endswith('.ts'):
            mimetype = 'video/mp2t'
        elif filename.endswith('.mp4'):
            mimetype = 'video/mp4'
        elif filename.endswith('.jpg') or filename.endswith('.jpeg'):
            mimetype = 'image/jpeg'
        elif filename.endswith('.png'):
            mimetype = 'image/png'
        elif filename.endswith('.json'):
            mimetype = 'application/json'
        elif filename.endswith('.mp3'):
            mimetype = 'audio/mpeg'
        elif filename.endswith('.vtt'):
            mimetype = 'text/vtt'
        elif filename.endswith('.html') or filename.endswith('.htm'):
            mimetype = 'text/html'
        else:
            mimetype = 'application/octet-stream'
        
        # Log access for debugging
        #print(f"[@host_stream] 📡 Serving: {device_folder}/{content_type}/{filename} ({storage_type})")
        
        # Send file with appropriate headers
        response = send_from_directory(
            directory,
            filename,
            mimetype=mimetype
        )
        
        # Cache control based on file type
        if filename.endswith('.m3u8'):
            # Live playlist MUST never be cached — a stale playlist makes every
            # player (hls.js, native, VLC) replay an old segment window, adding
            # up to max-age seconds of latency. Always revalidate for the live edge.
            response.headers.add('Cache-Control', 'no-cache, no-store, must-revalidate')
            response.headers.add('Pragma', 'no-cache')
            response.headers.add('Expires', '0')
        elif filename.endswith('.ts') or filename.endswith('.m4s'):
            # Segments are immutable once written — safe to cache briefly
            response.headers.add('Cache-Control', 'public, max-age=30')
        elif filename.endswith('.json'):
            # No cache for metadata
            response.headers.add('Cache-Control', 'no-cache, no-store, must-revalidate')
            response.headers.add('Pragma', 'no-cache')
            response.headers.add('Expires', '0')
        else:
            # Medium cache for images/audio
            response.headers.add('Cache-Control', 'public, max-age=300')
        
        return response
        
    except Exception as e:
        print(f"[@host_stream] ❌ Error serving file: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@host_stream_bp.route('/stream/<device_folder>/<content_type>/', methods=['GET'])
@route_exception_handler()
def list_stream_directory(device_folder, content_type):
    base_path = get_stream_base_path()
    
    # Try hot first, then cold
    hot_path = os.path.join(base_path, device_folder, 'hot', content_type)
    cold_path = os.path.join(base_path, device_folder, content_type)
    
    files = {'hot': [], 'cold': []}
    
    if os.path.exists(hot_path):
        files['hot'] = [f for f in os.listdir(hot_path) if os.path.isfile(os.path.join(hot_path, f))]
    
    if os.path.exists(cold_path):
        files['cold'] = [f for f in os.listdir(cold_path) if os.path.isfile(os.path.join(cold_path, f))]
    
    return jsonify({
        'success': True,
        'device': device_folder,
        'content_type': content_type,
        'files': files
    })


# Backwards compatible route for nginx proxy paths
host_stream_bp.add_url_rule(
    '/host/stream/<device_folder>/<content_type>/',
    endpoint='list_stream_directory_host',
    view_func=list_stream_directory,
    methods=['GET'],
)
