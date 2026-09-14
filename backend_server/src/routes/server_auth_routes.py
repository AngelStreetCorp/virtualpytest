"""
User Authentication Routes

Provides endpoints for user profile and authentication management.
These routes demonstrate the new user auth middleware.
"""

from flask import Blueprint, request, jsonify
from backend_server.src.lib.auth_middleware import require_user_auth, require_role, require_permission, optional_user_auth

# Create blueprint
server_auth_bp = Blueprint('server_auth', __name__, url_prefix='/server/auth')


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
    """
    if hasattr(request, 'user_id'):
        return jsonify({
            'authenticated': True,
            'user': {
                'id': request.user_id,
                'email': request.user_email,
                'role': request.user_role
            }
        })
    else:
        return jsonify({
            'authenticated': False
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

