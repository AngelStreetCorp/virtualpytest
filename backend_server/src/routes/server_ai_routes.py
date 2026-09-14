"""Server AI Routes - Unified AI operations"""

from flask import Blueprint, request, jsonify
from backend_server.src.lib.utils.route_utils import proxy_to_host_with_params
from backend_server.src.lib.utils.route_handlers import require_json, require_team_id_from_args
from backend_server.src.lib.utils.route_response import validation_error_response

server_ai_bp = Blueprint('server_ai', __name__, url_prefix='/server/ai')


def _proxy_ai_post(endpoint: str):
    """Proxy AI POST endpoints with shared JSON/team validation."""
    json_error = require_json()
    if json_error:
        return validation_error_response('No JSON data provided')
    data = request.get_json()
    team_id, team_err = require_team_id_from_args()
    if team_err:
        return team_err
    query_params = {'device_id': data.get('device_id'), 'team_id': team_id} if data.get('device_id') else {'team_id': team_id}
    response_data, status_code = proxy_to_host_with_params(endpoint, 'POST', data, query_params)
    return jsonify(response_data), status_code

@server_ai_bp.route('/analyzeCompatibility', methods=['POST'])
def analyze_compatibility():
    """Analyze AI task compatibility"""
    return _proxy_ai_post('/host/ai/analyzeCompatibility')

@server_ai_bp.route('/generatePlan', methods=['POST'])
def generate_plan():
    """Generate AI execution plan"""
    return _proxy_ai_post('/host/ai/generatePlan')

@server_ai_bp.route('/getStatus', methods=['POST'])
def get_status():
    """Get AI execution status"""
    return _proxy_ai_post('/host/ai/getStatus')

@server_ai_bp.route('/stopExecution', methods=['POST'])
def stop_execution():
    """Stop AI execution"""
    return _proxy_ai_post('/host/ai/stopExecution')

@server_ai_bp.route('/resetCache', methods=['POST'])
def reset_cache():
    """Reset AI graph cache"""
    json_error = require_json()
    if json_error:
        return validation_error_response('No JSON data provided')
    data = request.get_json()
    
    host_name = data.get('host_name') or request.args.get('host_name')
    if not host_name:
        return jsonify({'success': False, 'error': 'host_name required'}), 400
    
    team_id, team_err = require_team_id_from_args()
    if team_err:
        return team_err
    
    from shared.src.lib.utils.supabase_utils import get_supabase_client
    supabase = get_supabase_client()
    
    count_result = supabase.table('ai_graph_cache').select('id', count='exact').eq('team_id', team_id).execute()
    deleted_count = count_result.count if count_result.count else 0
    
    supabase.table('ai_graph_cache').delete().eq('team_id', team_id).execute()
    
    return jsonify({
        'success': True,
        'message': f'Cache cleared: {deleted_count} graphs deleted',
        'deleted_count': deleted_count
    }), 200

@server_ai_bp.route('/analyzePrompt', methods=['POST'])
def analyze_prompt():
    """Pre-analyze prompt for disambiguation"""
    return _proxy_ai_post('/host/ai/analyzePrompt')

@server_ai_bp.route('/saveDisambiguation', methods=['POST'])
def save_disambiguation():
    """Save disambiguation preferences"""
    json_error = require_json()
    if json_error:
        return validation_error_response('No JSON data provided')
    data = request.get_json()
    
    team_id = request.args.get('team_id')
    query_params = {'team_id': team_id} if team_id else {}
    
    response_data, status_code = proxy_to_host_with_params(
        '/host/ai/saveDisambiguation', 'POST', data, query_params
    )
    return jsonify(response_data), status_code

