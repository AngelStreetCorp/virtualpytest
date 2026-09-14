"""
Storage Routes - R2 Pre-signed URL Generation

This module provides authenticated endpoints for generating temporary signed URLs
to access private files in Cloudflare R2 storage.

Security:
- All endpoints require Supabase user authentication
- Pre-signed URLs are time-limited (default: 1 hour)
- URLs are cryptographically signed by AWS S3-compatible signature
- No proxy - direct R2 access after URL generation

Architecture:
    Frontend (with Supabase JWT) 
    → POST /server/storage/signed-url
    → Backend validates JWT + generates signed URL
    → Frontend uses signed URL to access R2 directly
"""

from flask import Blueprint, request, jsonify
from backend_server.src.lib.auth_middleware import require_user_auth, optional_user_auth
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils
from typing import List, Dict

# Create blueprint
server_storage_bp = Blueprint('server_storage', __name__, url_prefix='/server/storage')


@server_storage_bp.route('/signed-url', methods=['POST'])
@require_user_auth
@handle_route_exceptions('storage:signed-url')
def generate_signed_url():
    """
    Generate a pre-signed URL for secure access to a private R2 file.
    
    Requires: Supabase authentication (JWT token in Authorization header)
    
    Request Body:
        {
            "path": "captures/device1/capture_123.jpg",  // Required: R2 file path
            "expires_in": 3600  // Optional: Seconds until expiration (default: 3600 = 1 hour)
        }
    
    Response (Success):
        {
            "success": true,
            "url": "https://account.r2.cloudflarestorage.com/...?X-Amz-Signature=...",
            "expires_in": 3600,
            "expires_at": "2025-12-05T15:30:00Z",
            "path": "captures/device1/capture_123.jpg"
        }
    
    Response (Error):
        {
            "success": false,
            "error": "Error message"
        }
    
    Status Codes:
        200 - Success
        400 - Bad request (missing path)
        401 - Unauthorized (invalid/missing JWT)
        500 - Server error
    
    Example:
        curl -X POST https://api.virtualpytest.com/server/storage/signed-url \
             -H "Authorization: Bearer <supabase-jwt>" \
             -H "Content-Type: application/json" \
             -d '{"path": "verification/test.jpg", "expires_in": 7200}'
    """
    data = request.get_json() or {}
    remote_path = data.get('path')
    if not remote_path:
        return jsonify({'success': False, 'error': 'Missing required field: path'}), 400
    expires_in = data.get('expires_in', 3600)
    if not isinstance(expires_in, int) or expires_in < 60 or expires_in > 604800:
        return jsonify({
            'success': False,
            'error': 'expires_in must be between 60 (1 min) and 604800 (7 days) seconds'
        }), 400
    print(f"[@storage] User {request.user_email} requesting signed URL for: {remote_path} (expires: {expires_in}s)")
    uploader = get_cloudflare_utils()
    result = uploader.generate_presigned_url(remote_path, expires_in)
    if result['success']:
        return jsonify({
            'success': True,
            'url': result['url'],
            'expires_in': result['expires_in'],
            'expires_at': result['expires_at'],
            'path': remote_path
        }), 200
    print(f"[@storage] Failed to generate signed URL for {remote_path}: {result.get('error')}")
    return jsonify({
        'success': False,
        'error': result.get('error', 'Failed to generate signed URL')
    }), 500


@server_storage_bp.route('/signed-urls-batch', methods=['POST'])
@require_user_auth
@handle_route_exceptions('storage:signed-urls-batch')
def generate_signed_urls_batch():
    """
    Generate multiple pre-signed URLs in a single request (for efficiency).
    
    Useful when displaying pages with many images/files - reduces API calls.
    
    Requires: Supabase authentication (JWT token in Authorization header)
    
    Request Body:
        {
            "paths": [
                "captures/device1/capture_1.jpg",
                "captures/device1/capture_2.jpg",
                "captures/device1/capture_3.jpg"
            ],
            "expires_in": 3600  // Optional: Seconds until expiration (default: 3600)
        }
    
    Response (Success):
        {
            "success": true,
            "urls": [
                {
                    "path": "captures/device1/capture_1.jpg",
                    "url": "https://...?X-Amz-Signature=...",
                    "expires_at": "2025-12-05T15:30:00Z",
                    "expires_in": 3600
                },
                ...
            ],
            "failed": [
                {
                    "path": "captures/device1/missing.jpg",
                    "error": "File not found"
                }
            ],
            "generated_count": 2,
            "failed_count": 1
        }
    
    Status Codes:
        200 - Success (even if some URLs failed - check 'failed' array)
        400 - Bad request (missing/invalid paths)
        401 - Unauthorized
        500 - Server error
    
    Example:
        curl -X POST https://api.virtualpytest.com/server/storage/signed-urls-batch \
             -H "Authorization: Bearer <supabase-jwt>" \
             -H "Content-Type: application/json" \
             -d '{"paths": ["file1.jpg", "file2.jpg"], "expires_in": 7200}'
    """
    data = request.get_json() or {}
    paths = data.get('paths')
    if not paths:
        return jsonify({'success': False, 'error': 'Missing required field: paths (array of strings)'}), 400
    if not isinstance(paths, list) or len(paths) == 0:
        return jsonify({'success': False, 'error': 'paths must be a non-empty array'}), 400
    MAX_BATCH_SIZE = 100
    if len(paths) > MAX_BATCH_SIZE:
        return jsonify({'success': False, 'error': f'Batch size exceeds maximum of {MAX_BATCH_SIZE} URLs'}), 400
    expires_in = data.get('expires_in', 3600)
    if not isinstance(expires_in, int) or expires_in < 60 or expires_in > 604800:
        return jsonify({'success': False, 'error': 'expires_in must be between 60 and 604800 seconds'}), 400
    print(f"[@storage] User {request.user_email} requesting {len(paths)} signed URLs (expires: {expires_in}s)")
    uploader = get_cloudflare_utils()
    result = uploader.generate_presigned_urls_batch(paths, expires_in)
    return jsonify({
        'success': result['success'],
        'urls': result['urls'],
        'failed': result['failed'],
        'generated_count': result['generated_count'],
        'failed_count': result['failed_count']
    }), 200


@server_storage_bp.route('/health', methods=['GET'])
@handle_route_exceptions('storage:health')
def storage_health():
    """
    Health check endpoint for storage service.
    No authentication required.
    
    Returns:
        {
            "status": "healthy",
            "r2_configured": true,
            "service": "storage"
        }
    """
    uploader = get_cloudflare_utils()
    r2_configured = uploader.s3_client is not None
    return jsonify({
        'status': 'healthy',
        'r2_configured': r2_configured,
        'service': 'storage',
        'features': ['signed_urls', 'batch_generation']
    }), 200


# Optional: Role-based access example (uncomment if needed)
# from backend_server.src.lib.auth_middleware import require_role
#
# @server_storage_bp.route('/admin/test-connection', methods=['POST'])
# @require_user_auth
# @require_role('admin')
# def test_r2_connection():
#     """Admin-only endpoint to test R2 connection"""
#     uploader = get_cloudflare_utils()
#     result = uploader.test_connection()
#     return jsonify(result)

