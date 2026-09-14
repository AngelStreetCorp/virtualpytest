"""
Core API Routes

This module contains the core API endpoints for:
- Health check
- Feature status
"""

from flask import Blueprint, jsonify

# Import utility functions
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from shared.src.lib.utils.app_utils import get_team_id

# Create blueprint
server_core_bp = Blueprint('server_core', __name__, url_prefix='/server')

# =====================================================
# HEALTH CHECK ENDPOINT
# =====================================================

@server_core_bp.route('/health')
@handle_route_exceptions('server_core:health')
def health():
    """Health check endpoint with lazy-loaded feature status"""
    # Try to get Supabase (will load if not already loaded)
    try:
        from shared.src.lib.utils.supabase_utils import get_supabase_client, get_db_key_role
        supabase_client = get_supabase_client()
        supabase_status = "connected" if supabase_client else "disconnected"
        db_key_role = get_db_key_role()  # TASK-10 rollout signal: service_role | anon | none
    except Exception:
        supabase_status = "unavailable"
        db_key_role = "unknown"

    # Check Redis connectivity
    try:
        from shared.src.lib.utils.redis_queue import RedisQueueProcessor
        redis_processor = RedisQueueProcessor()
        redis_status = "connected" if redis_processor.health_check() else "disconnected"
    except Exception:
        redis_status = "unavailable"

    return jsonify({
        'status': 'ok',
        'supabase': supabase_status,
        'db_key_role': db_key_role,
        'redis': redis_status,
        'team_id': get_team_id()
    })
