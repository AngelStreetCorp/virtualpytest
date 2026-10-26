"""
Script Results Management Routes

This module contains the script results management API endpoints for:
- Script results retrieval
- Script results filtering
"""

import json
import logging
import uuid

from flask import Blueprint, jsonify, request
from datetime import datetime, timezone

from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.routes.server_dashboard_routes import RANGES as DASH_RANGES, _is_running_row, _verdict

# Import database functions from src/lib/supabase (uses absolute import)
from shared.src.lib.database.script_results_db import (
    get_script_results,
    get_script_by_id,
    update_script_checked_status,
    update_script_discard_status
)

from shared.src.lib.utils.app_utils import check_supabase
from shared.src.lib.utils.cloudflare_utils import fetch_text_from_storage
from shared.src.lib.utils.upload_error_utils import sanitize_upload_error
from backend_server.src.lib.utils.server_utils import get_host_manager

# Create blueprint
server_script_results_bp = Blueprint('server_script_results', __name__, url_prefix='/server/script-results')

logger = logging.getLogger(__name__)

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

    # Run-governance filters (TASK-42), applied in the query before the limit.
    governance_filters = {}
    for name in ('milestone_id', 'run_group_id', 'label_id'):
        value = (request.args.get(name) or '').strip()
        if value:
            try:
                governance_filters[name] = str(uuid.UUID(value))
            except ValueError:
                return jsonify({'error': f'{name} must be a UUID'}), 400

    # Dashboard deep links (TASK-123): ?status=passed|failed and ?range=24h|7d|30d, applied before the limit so a
    # dashboard count opens the rows it counted. 'failed' / 'aborted' match the dashboard's verdict, minus rows still running.
    status = request.args.get('status')
    if status not in (None, 'passed', 'failed', 'aborted'):
        return jsonify({'error': 'status must be passed, failed or aborted'}), 400
    range_key = request.args.get('range')
    if range_key is not None and range_key not in DASH_RANGES:
        return jsonify({'error': f'range must be one of {", ".join(DASH_RANGES)}'}), 400
    since = (datetime.now(timezone.utc) - DASH_RANGES[range_key]).isoformat() if range_key else None

    # Get script results from database (include all records for complete view). A dashboard deep link counts
    # like the dashboard: discarded runs (AI-triaged false failures) are not in its numbers.
    result = get_script_results(
        team_id,
        script_name=script_name,
        host_name=host_name,
        include_discarded=status is None and range_key is None,
        limit=limit,
        host_names=registered_host_names,
        host_filter=host_filter,
        success=None if status is None else status == 'passed',
        since=since,
        **governance_filters,
    )
    
    if result['success']:
        rows = result['script_results']
        if status in ('failed', 'aborted'):
            rows = [r for r in rows if not _is_running_row(r) and _verdict(r) == status]
        return jsonify(rows)
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
        _label_script_training_samples(script_result_id, discard, team_id)
        return jsonify({'status': 'success'})
    else:
        return jsonify({'error': 'Script result not found or failed to update'}), 404


def _label_script_training_samples(script_result_id, discard, team_id):
    """TASK-27 step 3a: a discarded script result means its verification verdicts were
    wrong. Each training sample recorded for this result (``source_ref.script_result_id``)
    whose ``model_answer`` carries a boolean ``verified`` gets the opposite as its human
    label. Samples without a recorded verdict are skipped and logged. Best effort, never
    raises, and never changes the route's response.
    """
    try:
        if not discard or not team_id:
            return
        from shared.src.lib.ai import training_samples
        from shared.src.lib.database import ai_training_samples_db as samples_db
        if not training_samples.enabled():
            return
        samples = samples_db.get_samples_by_source_ref(team_id, 'script_result_id', script_result_id)
        for sample in samples:
            answer = sample.get('model_answer')
            verdict = answer.get('verified') if isinstance(answer, dict) else None
            if not isinstance(verdict, bool) or not sample.get('object_key'):
                logger.info(f"[training] sample {sample.get('id')} of script result {script_result_id} "
                            f"has no verification verdict or frame, skipped")
                continue
            training_samples.attach_ground_truth(sample['id'], team_id, {'verified': not verdict}, 'human')
    except Exception as e:
        logger.warning(f"[training] labelling samples of script result {script_result_id} failed: {e}")


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

    # Fallback for older records generated before markdown pack existed, and for
    # runs whose own pack never reached storage.
    if not markdown:
        report_url = record.get('html_report_r2_url') or 'n/a'
        logs_url = record.get('logs_r2_url') or record.get('logs_url') or 'n/a'
        status = 'PASS' if record.get('success') else 'FAIL'
        # BUG-0770: this is the pack a reader actually gets when the host could
        # not upload anything — and it used to say only "n/a", so a missing
        # report looked like a missing test instead of a broken storage
        # configuration. The host kept the reason in the run metadata; read it
        # from there and say it here too.
        # Older rows hold the raw storage error: sanitize again on the way out.
        upload_error = sanitize_upload_error(
            metadata.get('artifact_upload_error')
            or (metadata.get('verification_review') or {}).get('artifact_upload_error')
            or ''
        )
        lines = [
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
        ]
        if upload_error and report_url == 'n/a' and logs_url == 'n/a':
            lines.append(f"- Artifact upload failed: `{upload_error}`")
        lines += [
            '',
            '## How To Verify False Positives',
            '1. Validate screenshot/report evidence against failure logs.',
            '2. Distinguish script timing/selector issues from real product regressions.',
            '3. Mark `discard=true` only for `SCRIPT_ISSUE` or `SYSTEM_ISSUE`; keep external blocks as `EXTERNAL_BLOCK` with `discard=false`.',
        ]
        markdown = "\n".join(lines)

    return jsonify({
        'script_result_id': script_result_id,
        'team_id': record_team_id,
        'markdown_url': markdown_url or None,
        'markdown_path': markdown_path or None,
        'markdown': markdown
    })
        
