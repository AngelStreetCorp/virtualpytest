"""
Campaign API Routes

This module contains the campaign management endpoints for:
- Creating campaigns
- Retrieving campaigns
- Updating campaigns
- Deleting campaigns
"""

import glob
import os
from flask import Blueprint, request, jsonify, current_app
from backend_server.src.lib.utils.response_cache import get_cached_response, set_cached_response, invalidate_cached_responses
from backend_server.src.routes.server_executable_routes import invalidate_executable_list_cache
from shared.src.lib.config.constants import CACHE_CONFIG

# Import utility functions
from shared.src.lib.utils.app_utils import get_team_id

# Import database functions from src/lib/supabase (uses absolute import)
from shared.src.lib.database.campaign_executions_db import (
    get_campaign_results
)
from shared.src.lib.database.campaign_db import list_campaigns

from shared.src.lib.utils.app_utils import check_supabase
from backend_server.src.lib.utils.script_utils import get_recursive_campaign_contained_scripts
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.auth_middleware import require_permission
from shared.src.lib.database.library_visibility_db import list_hidden_library_keys
# Create blueprint with abstract server campaign prefix
server_campaign_bp = Blueprint('server_campaign', __name__, url_prefix='/server/campaigns')

# Legacy helper functions moved to services/campaign_service.py
# All business logic has been extracted to the service layer


def _normalize_contained_scripts(script_configurations):
    contained_scripts = []
    for index, script in enumerate(script_configurations or []):
        if not isinstance(script, dict):
            continue
        script_name = (
            script.get('script_name')
            or script.get('testcase_name')
            or script.get('name')
            or script.get('testcase_id')
            or f'item_{index + 1}'
        )
        contained_scripts.append({
            'script_name': script_name,
            'script_type': script.get('script_type') or ('testcase' if script.get('testcase_id') else 'script'),
            'description': script.get('description') or '',
        })
    return contained_scripts

# =====================================================
# CAMPAIGN ENDPOINTS WITH CONSISTENT NAMING
# =====================================================

@server_campaign_bp.route('/getAllCampaigns', methods=['GET'])
@handle_route_exceptions('server_campaign:getAllCampaigns')
def get_all_campaigns_route():
    """Get all campaigns for a team"""
    team_id = request.args.get('team_id')
    include_hidden = request.args.get('include_hidden', 'false').lower() == 'true'
    user_agent = request.headers.get('User-Agent', 'Unknown')
    referer = request.headers.get('Referer', 'Unknown')
    from services.campaign_service import campaign_service
    result = campaign_service.get_all_campaigns(team_id, user_agent, referer, include_hidden=include_hidden)
    if result['success']:
        return jsonify({'success': True, 'campaigns': result['campaigns']})
    return jsonify({'success': False, 'error': result['error']}), result.get('status_code', 500)


@server_campaign_bp.route('/listExecutables', methods=['GET'])
@handle_route_exceptions('server_campaign:listExecutables')
def list_campaign_executables_route():
    """List runnable campaign executables from DB campaigns and test_campaign files."""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400

    include_hidden = request.args.get('include_hidden', 'false').lower() == 'true'
    cache_key = f"server_campaign:listExecutables:{team_id}:{int(include_hidden)}"
    cached_response = get_cached_response(cache_key, CACHE_CONFIG['SHORT_TTL'])
    if cached_response is not None:
        return jsonify(cached_response)

    user_agent = request.headers.get('User-Agent', 'Unknown')
    referer = request.headers.get('Referer', 'Unknown')

    from services.campaign_service import campaign_service
    db_result = campaign_service.get_all_campaigns(team_id, user_agent, referer, include_hidden=include_hidden)
    if not db_result.get('success'):
        return jsonify({'success': False, 'error': db_result.get('error', 'Failed to load campaigns')}), db_result.get('status_code', 500)

    db_campaigns = list_campaigns(team_id, include_config=True)
    if not include_hidden:
        db_campaigns = [
            campaign for campaign in db_campaigns
            if campaign.get('campaign_id') not in list_hidden_library_keys(team_id, 'campaign')
        ]
    hidden_campaign_keys = set()
    if not include_hidden:
        hidden_campaign_keys = list_hidden_library_keys(team_id, 'campaign')

    db_items = [
        {
            'id': campaign.get('campaign_id'),
            'source': 'db',
            'campaign_id': campaign.get('campaign_id'),
            'name': campaign.get('campaign_name') or 'Unnamed Campaign',
            'description': campaign.get('description') or '',
            'userinterface_name': campaign.get('userinterface_name') or '',
            'execution_count': campaign.get('execution_count', 0),
            'last_execution_success': campaign.get('last_execution_success'),
            'created_at': campaign.get('created_at'),
            'updated_at': campaign.get('updated_at'),
            'contained_scripts': _normalize_contained_scripts(campaign.get('script_configurations') or []),
        }
        for campaign in db_campaigns
        if campaign.get('campaign_id') and campaign.get('campaign_id') not in hidden_campaign_keys
    ]

    # Discover campaign scripts from repository test_campaign folder.
    current_dir = os.path.dirname(os.path.abspath(__file__))  # /backend_server/src/routes
    src_dir = os.path.dirname(current_dir)  # /backend_server/src
    backend_server_dir = os.path.dirname(src_dir)  # /backend_server
    project_root = os.path.dirname(backend_server_dir)  # /virtualpytest
    test_campaign_dir = os.path.join(project_root, 'test_campaign')

    file_items = []
    if os.path.isdir(test_campaign_dir):
        for script_path in glob.glob(os.path.join(test_campaign_dir, '**', '*.py'), recursive=True):
            rel_path = os.path.relpath(script_path, test_campaign_dir).replace('\\', '/')
            if rel_path.startswith('.') or '/__pycache__/' in f'/{rel_path}/':
                continue
            if os.path.basename(rel_path).startswith('_'):
                continue
            script_ref = f'test_campaign/{rel_path}'
            if not include_hidden and script_ref in hidden_campaign_keys:
                continue
            display_name = os.path.splitext(os.path.basename(rel_path))[0].replace('_', ' ')
            file_items.append({
                'id': script_ref,
                'source': 'file',
                'script_name': script_ref,
                'name': display_name.title(),
                'description': f'File campaign: {rel_path}',
                'path': rel_path,
                'contained_scripts': get_recursive_campaign_contained_scripts(script_ref),
            })

    file_items.sort(key=lambda item: item['name'].lower())
    db_items.sort(key=lambda item: item['name'].lower())

    response_payload = {
        'success': True,
        'campaigns': db_items,
        'scripts': file_items,
        'executables': [*db_items, *file_items],
    }
    set_cached_response(cache_key, response_payload)
    return jsonify(response_payload)


def invalidate_campaign_executable_cache() -> None:
    invalidate_cached_responses('server_campaign:listExecutables:')


@server_campaign_bp.route('/getContainedScripts', methods=['POST'])
@handle_route_exceptions('server_campaign:getContainedScripts')
def get_contained_scripts_route():
    """Get contained scripts for a file campaign by script path."""
    data = request.get_json() or {}
    script_name = data.get('script_name', '')
    if not script_name:
        return jsonify({'success': False, 'error': 'script_name is required'}), 400
    contained = get_recursive_campaign_contained_scripts(script_name)
    return jsonify({'success': True, 'contained_scripts': contained})


@server_campaign_bp.route('/getCampaign/<campaign_id>', methods=['GET'])
@handle_route_exceptions('server_campaign:getCampaign')
def get_campaign_route(campaign_id):
    """Get a specific campaign by ID"""
    team_id = request.args.get('team_id')
    from services.campaign_service import campaign_service
    result = campaign_service.get_campaign(campaign_id, team_id)
    if result['success']:
        return jsonify({'success': True, 'campaign': result['campaign']})
    return jsonify({'success': False, 'error': result['error']}), result.get('status_code', 500)


@server_campaign_bp.route('/createCampaign', methods=['POST'])
@require_permission('campaigns:create')
@handle_route_exceptions('server_campaign:createCampaign')
def create_campaign_route():
    """Create a new campaign"""
    team_id = request.args.get('team_id')
    campaign_data = request.json or {}
    campaign_data.setdefault('created_by', request.headers.get('X-User-ID'))
    from services.campaign_service import campaign_service
    result = campaign_service.create_campaign(campaign_data, team_id)
    if result['success']:
        invalidate_campaign_executable_cache()
        invalidate_executable_list_cache()
        return jsonify({'success': True, 'campaign': result['campaign']})
    return jsonify({'success': False, 'error': result['error']}), result.get('status_code', 500)


@server_campaign_bp.route('/updateCampaign/<campaign_id>', methods=['PUT'])
@require_permission('campaigns:edit')
@handle_route_exceptions('server_campaign:updateCampaign')
def update_campaign_route(campaign_id):
    """Update an existing campaign"""
    team_id = request.args.get('team_id')
    campaign_data = request.json or {}
    campaign_data.setdefault('modified_by', request.headers.get('X-User-ID'))
    from services.campaign_service import campaign_service
    result = campaign_service.update_campaign(campaign_id, campaign_data, team_id)
    if result['success']:
        invalidate_campaign_executable_cache()
        invalidate_executable_list_cache()
        return jsonify({'success': True, 'campaign': result['campaign']})
    return jsonify({'success': False, 'error': result['error']}), result.get('status_code', 500)


@server_campaign_bp.route('/<campaign_id>/history', methods=['GET'])
@handle_route_exceptions('server_campaign:getCampaignHistory')
def get_campaign_history_route(campaign_id):
    """Get recent campaign definition versions."""
    team_id = request.args.get('team_id')
    from services.campaign_service import campaign_service
    result = campaign_service.get_campaign_history(campaign_id, team_id)
    if result['success']:
        return jsonify({'success': True, 'versions': result['versions']})
    return jsonify({'success': False, 'error': result['error']}), result.get('status_code', 500)


@server_campaign_bp.route('/<campaign_id>/restore/<int:version_number>', methods=['POST'])
@require_permission('campaigns:edit')
@handle_route_exceptions('server_campaign:restoreCampaignVersion')
def restore_campaign_version_route(campaign_id, version_number):
    """Restore an older campaign definition as the new latest version."""
    team_id = request.args.get('team_id')
    restored_by = request.headers.get('X-User-ID')
    from services.campaign_service import campaign_service
    result = campaign_service.restore_campaign_version(campaign_id, version_number, team_id, restored_by=restored_by)
    if result['success']:
        invalidate_campaign_executable_cache()
        invalidate_executable_list_cache()
        return jsonify(result)
    return jsonify({'success': False, 'error': result['error']}), result.get('status_code', 500)


@server_campaign_bp.route('/deleteCampaign/<campaign_id>', methods=['DELETE'])
@require_permission('campaigns:delete')
@handle_route_exceptions('server_campaign:deleteCampaign')
def delete_campaign_route(campaign_id):
    """Delete a campaign"""
    team_id = request.args.get('team_id')
    from services.campaign_service import campaign_service
    result = campaign_service.delete_campaign(campaign_id, team_id)
    if result['success']:
        invalidate_campaign_executable_cache()
        invalidate_executable_list_cache()
        return jsonify({'status': 'success'})
    return jsonify({'error': result['error']}), result.get('status_code', 500)
