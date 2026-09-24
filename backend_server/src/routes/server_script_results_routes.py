"""
Script Results Management Routes

This module contains the script results management API endpoints for:
- Script results retrieval
- Script results filtering
"""

import json

from flask import Blueprint, jsonify, request
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions

# Import database functions from src/lib/supabase (uses absolute import)
from shared.src.lib.database.script_results_db import (
    get_script_results,
    get_script_by_id,
    update_script_checked_status,
    update_script_discard_status
)

from shared.src.lib.utils.app_utils import check_supabase
from shared.src.lib.utils.cloudflare_utils import fetch_text_from_storage
from backend_server.src.lib.utils.server_utils import get_host_manager

# Create blueprint
server_script_results_bp = Blueprint('server_script_results', __name__, url_prefix='/server/script-results')

# =====================================================
# SCRIPT RESULTS ENDPOINTS
# =====================================================

@server_script_results_bp.route('/getAllScriptResults', methods=['GET'])
@handle_route_exceptions('script_results:get_all_script_results')
def get_all_script_results():
    """Get all script results for the team"""
    error = check_supabase()
    if error:
        return error
        
    team_id = request.args.get('team_id')
    script_name = request.args.get('script_name')
    host_name = request.args.get('host_name')
    limit = int(request.args.get('limit', '100'))

    # Active workspace host scope (JSON array of host names). Applied before the
    # row limit so a high-frequency workspace can't starve another workspace's
    # rows out of the latest-N window. Sent by the frontend from the active
    # workspace's device_filter (deduped to host names).
    host_filter = None
    raw_host_filter = request.args.get('host_filter')
    if raw_host_filter:
        try:
            parsed = json.loads(raw_host_filter)
            if isinstance(parsed, list):
                host_filter = [str(h) for h in parsed if h]
        except (ValueError, TypeError):
            host_filter = None

    # Multi-server isolation: only return rows whose host_name belongs to this
    # backend_server's registered hosts. The shared Supabase database is queried
    # by every server for the same team_id, so without this scope rpitest would
    # show awesomation's results and vice versa.
    registered_host_names = list(get_host_manager().get_all_hosts().keys())

    # Get script results from database (include all records for complete view)
    result = get_script_results(
        team_id,
        script_name=script_name,
        host_name=host_name,
        include_discarded=True,
        limit=limit,
        host_names=registered_host_names,
        host_filter=host_filter,
    )
    
    if result['success']:
        return jsonify(result['script_results'])
    else:
        return jsonify({'error': result.get('error', 'Failed to fetch script results')}), 500
        
@server_script_results_bp.route('/updateCheckedStatus/<script_result_id>', methods=['PUT'])
@handle_route_exceptions('script_results:update_script_checked_status_route')
def update_script_checked_status_route(script_result_id):
    """Update script result checked status"""
    error = check_supabase()
    if error:
        return error
        
    team_id = request.args.get('team_id')
    
    data = request.json
    checked = data.get('checked', False)
    check_type = data.get('check_type', 'manual')
    
    success = update_script_checked_status(team_id, script_result_id, checked, check_type)
    
    if success:
        return jsonify({'status': 'success'})
    else:
        return jsonify({'error': 'Script result not found or failed to update'}), 404
        
@server_script_results_bp.route('/updateDiscardStatus/<script_result_id>', methods=['PUT'])
@handle_route_exceptions('script_results:update_script_discard_status_route')
def update_script_discard_status_route(script_result_id):
    """Update script result discard status"""
    error = check_supabase()
    if error:
        return error
        
    team_id = request.args.get('team_id')
    
    data = request.json
    discard = data.get('discard', False)
    discard_comment = data.get('discard_comment')
    check_type = data.get('check_type', 'manual')
    
    success = update_script_discard_status(team_id, script_result_id, discard, discard_comment, check_type)
    
    if success:
        return jsonify({'status': 'success'})
    else:
        return jsonify({'error': 'Script result not found or failed to update'}), 404


@server_script_results_bp.route('/getVerificationReviewMarkdown/<script_result_id>', methods=['GET'])
@handle_route_exceptions('script_results:get_verification_review_markdown_route')
def get_verification_review_markdown_route(script_result_id):
    """Get markdown verification review pack for one script result."""
    error = check_supabase()
    if error:
        return error

    team_id = request.args.get('team_id')
    record = get_script_by_id(script_result_id)

    if not record:
        return jsonify({'error': 'Script result not found'}), 404

    record_team_id = record.get('team_id')
    if team_id and record_team_id and record_team_id != team_id:
        return jsonify({'error': 'Script result not found for this team'}), 404

    metadata = record.get('metadata') if isinstance(record.get('metadata'), dict) else {}
    markdown_url = metadata.get('verification_review_r2_url', '')
    markdown_path = metadata.get('verification_review_r2_path', '')
    markdown = ''

    markdown_source = markdown_path or markdown_url
    if markdown_source:
        fetch_result = fetch_text_from_storage(markdown_source)
        if fetch_result.get('success'):
            markdown = fetch_result.get('text') or ''
        else:
            return jsonify({
                'error': 'Failed to fetch verification review markdown from storage',
                'script_result_id': script_result_id,
                'markdown_url': markdown_url,
                'markdown_path': markdown_path,
                'resolved_path': fetch_result.get('remote_path'),
                'details': fetch_result.get('error'),
            }), 502

    # Fallback for older records generated before markdown pack existed.
    if not markdown:
        report_url = record.get('html_report_r2_url') or 'n/a'
        logs_url = record.get('logs_r2_url') or record.get('logs_url') or 'n/a'
        status = 'PASS' if record.get('success') else 'FAIL'
        markdown = "\n".join([
            '# Script Verification Review Pack',
            '',
            '## Execution Snapshot',
            f"- script_name: `{record.get('script_name', 'unknown')}`",
            f"- script_result_id: `{record.get('id', 'unknown')}`",
            f"- status: `{status}`",
            f"- execution_time_ms: `{record.get('execution_time_ms', 'n/a')}`",
            '',
            '## Log Sources',
            f"- report_url: {report_url}",
            f"- logs_url: {logs_url}",
            '',
            '## How To Verify False Positives',
            '1. Validate screenshot/report evidence against failure logs.',
            '2. Distinguish script timing/selector issues from real product regressions.',
            '3. Mark `discard=true` only for `SCRIPT_ISSUE` or `SYSTEM_ISSUE`; keep external blocks as `EXTERNAL_BLOCK` with `discard=false`.',
        ])

    return jsonify({
        'script_result_id': script_result_id,
        'team_id': record_team_id,
        'markdown_url': markdown_url or None,
        'markdown_path': markdown_path or None,
        'markdown': markdown
    })
        
