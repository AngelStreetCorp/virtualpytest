"""
User Authentication Routes

Provides endpoints for user profile and authentication management.
These routes demonstrate the new user auth middleware.
"""

import os

from flask import Blueprint, request, jsonify
from backend_server.src.lib.auth_middleware import (
    require_user_auth,
    require_role,
    require_permission,
    optional_user_auth,
    has_supabase_jwt_secret_configured,
    is_server_open_mode,
    is_server_public_key_configured,
)

# Create blueprint
server_auth_bp = Blueprint('server_auth', __name__, url_prefix='/server/auth')


def _auth_discovery() -> dict:
    """
    Describe THIS server's auth identity for the frontend server picker (TASK-18).

    Discovery only — this adds no check and rejects nothing. The frontend needs it
    because a server's Supabase cannot be derived from its own hostname: RPI1-server
    lives on `rpitest.angelstreet.io` but authenticates against
    `virtualpytest.angelstreet.io/supabase` (`rpitest.angelstreet.io/supabase` is a 404).
    Guessing by convention would split one identity in two and prompt the user for a
    second, pointless login.

    `identity` is the session key the frontend groups by: two servers advertising the
    same value share one Supabase session, a different value gets its own. It is
    deliberately NOT `SUPABASE_URL` — that is the server's own reachability path
    (`http://192.168.0.102:54321` on the LAN), which is neither browser-reachable nor
    unique across environments. Deployments that never set `SUPABASE_PUBLIC_URL` omit
    `identity`, and the frontend falls back to its single-session behaviour.
    """
    identity = (os.getenv('SUPABASE_PUBLIC_URL') or '').strip()
    anon_key = (os.getenv('SUPABASE_ANON_KEY') or '').strip()

    if is_server_open_mode():
        mode = 'open'
    elif has_supabase_jwt_secret_configured():
        mode = 'supabase'
    elif is_server_public_key_configured():
        mode = 'public_key'
    else:
        mode = 'closed'

    discovery = {
        'mode': mode,
        'server_name': (os.getenv('SERVER_NAME') or '').strip() or 'Unknown Server',
    }
    # Only advertise a usable identity: without both halves the frontend cannot build a
    # client, and a half-filled block would read as "configured" when it is not.
    if mode == 'supabase' and identity and anon_key:
        discovery['identity'] = identity
        discovery['anon_key'] = anon_key
    return discovery


@server_auth_bp.route('/profile', methods=['GET'])
@require_user_auth
def get_user_profile():
    """
    Get current user's profile information.
    Requires authentication.
    
    Returns user data from JWT token.
    """
    return jsonify({
        'success': True,
        'user': {
            'id': request.user_id,
            'email': request.user_email,
            'role': request.user_role,
            'metadata': request.user_metadata
        }
    })


@server_auth_bp.route('/check', methods=['GET'])
@optional_user_auth
def check_auth():
    """
    Check authentication status without requiring it.
    Returns user info if authenticated, or anonymous status.

    Also advertises this server's own auth identity (`auth`, see `_auth_discovery`) so
    the frontend can tell which Supabase to authenticate against per server (TASK-18).
    """
    if hasattr(request, 'user_id'):
        return jsonify({
            'authenticated': True,
            'user': {
                'id': request.user_id,
                'email': request.user_email,
                'role': request.user_role
            },
            'auth': _auth_discovery()
        })
    else:
        return jsonify({
            'authenticated': False,
            'auth': _auth_discovery()
        })


@server_auth_bp.route('/admin/test', methods=['GET'])
@require_user_auth
@require_role('admin')
def admin_only_endpoint():
    """
    Test endpoint that requires admin role.
    Demonstrates role-based access control.
    """
    return jsonify({
        'success': True,
        'message': 'Welcome, admin!',
        'user': request.user_email
    })


@server_auth_bp.route('/permissions/test', methods=['GET'])
@require_user_auth
@require_permission('api_testing')
def permission_test_endpoint():
    """
    Test endpoint that requires specific permission.
    Demonstrates permission-based access control.
    """
    return jsonify({
        'success': True,
        'message': 'You have api_testing permission!',
        'user': request.user_email
    })

