"""
Campaign Results Management Routes

This module contains the campaign results management API endpoints for:
- Campaign results retrieval
- Campaign results filtering
"""

from flask import Blueprint, request, jsonify
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions

# Import database functions from src/lib/supabase (uses absolute import)
from shared.src.lib.database.campaign_executions_db import (
    get_campaign_results
)

from shared.src.lib.utils.app_utils import check_supabase
from backend_server.src.lib.utils.server_utils import get_host_manager

# Create blueprint
server_campaign_results_bp = Blueprint('server_campaign_results', __name__, url_prefix='/server/campaign-results')

# =====================================================
# CAMPAIGN RESULTS ENDPOINTS
# =====================================================

@server_campaign_results_bp.route('/getAllCampaignResults', methods=['GET'])
@handle_route_exceptions('campaign_results:get_all_campaign_results')
def get_all_campaign_results():
    """Get all campaign results for the team"""
    error = check_supabase()
    if error:
        return error
        
    team_id = request.args.get('team_id')

    # Frontend (TestReports) only renders these script_results columns; pulling
    # the slim set keeps payloads small (skips heavy metadata jsonb / error_msg).
    script_columns = 'id,script_name,success,execution_time_ms,started_at,html_report_r2_url,logs_r2_url'

    # Multi-server isolation: only return campaigns whose host belongs to this
    # backend_server's registered hosts (see server_script_results_routes.py).
    registered_host_names = list(get_host_manager().get_all_hosts().keys())

    # Get campaign results from database
    result = get_campaign_results(
        team_id,
        limit=100,
        script_columns=script_columns,
        host_names=registered_host_names,
    )
    
    if result['success']:
        return jsonify(result['data'])
    else:
        return jsonify({'error': result.get('error', 'Failed to fetch campaign results')}), 500
        
# Note: getCampaignScripts endpoint removed - script results now included in main campaign results