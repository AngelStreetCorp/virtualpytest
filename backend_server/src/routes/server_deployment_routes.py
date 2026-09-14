"""Server Deployment Routes - Proxy to hosts and manage deployments"""
from datetime import datetime, timezone
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple
from flask import Blueprint, request, jsonify
from apscheduler.triggers.cron import CronTrigger
import gevent
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.utils.server_utils import get_host_manager
from backend_server.src.lib.utils.completion_notifier import notify_completion
from backend_server.src.lib.utils.lock_utils import release_device_lock
from shared.src.lib.utils.build_url_utils import call_host
from shared.src.lib.utils.supabase_utils import get_supabase_client
from backend_server.src.routes.server_system_socket_routes import emit_system_update

server_deployment_bp = Blueprint('server_deployment', __name__, url_prefix='/server/deployment')


def _normalize_cron_expression(cron_expression: str) -> str:
    """
    Normalize cron expression at deployment creation time.

    For hourly runs, avoid synchronized :00 bursts by using the current minute.
    Example: "0 * * * *" created at xx:05 becomes "5 * * * *".
    """
    cron = (cron_expression or '').strip()
    if cron == '0 * * * *':
        current_minute = datetime.now(timezone.utc).minute
        return f'{current_minute} * * * *'
    return cron


def _parse_iso_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None


def _calculate_next_run(deployment):
    cron_expression = (deployment.get('cron_expression') or '').strip()
    if not cron_expression:
        return None

    # Queue artifacts and one-shot schedules are not periodic schedules.
    if deployment.get('max_executions') == 1:
        return None

    now = datetime.now(timezone.utc)
    start_date = _parse_iso_datetime(deployment.get('start_date'))
    end_date = _parse_iso_datetime(deployment.get('end_date'))

    try:
        minute, hour, day, month, day_of_week = cron_expression.split()
        trigger = CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
            timezone='UTC',
        )
    except Exception:
        return None

    reference_now = now
    if start_date and start_date > reference_now:
        reference_now = start_date

    try:
        next_run = trigger.get_next_fire_time(None, reference_now - timedelta(seconds=1))
    except Exception:
        return None

    if not next_run:
        return None

    if start_date and next_run < start_date:
        try:
            next_run = trigger.get_next_fire_time(next_run, start_date)
        except Exception:
            return None

    if end_date and next_run > end_date:
        return None

    return next_run.isoformat()


def _abort_stale_queued_executions(supabase, team_id: str, stale_cutoff: str) -> int:
    """Mark queued executions older than the stale cutoff as aborted."""
    # Use inner join to filter by team_id directly, avoiding .in_() with large ID lists
    stale_result = supabase.table('deployment_executions').select(
        'id, deployments!inner(team_id)'
    ).eq('deployments.team_id', team_id).eq(
        'status', 'queued'
    ).lt('scheduled_at', stale_cutoff).execute()
    stale_ids = [row.get('id') for row in (stale_result.data or []) if row.get('id')]
    if not stale_ids:
        return 0

    now_iso = datetime.now(timezone.utc).isoformat()
    BATCH_SIZE = 50
    for i in range(0, len(stale_ids), BATCH_SIZE):
        batch = stale_ids[i:i + BATCH_SIZE]
        supabase.table('deployment_executions').update({
            'status': 'aborted',
            'completed_at': now_iso,
            'success': False,
            'error_message': 'Execution auto-aborted after staying queued for more than 4 hours',
            'skip_reason': 'stale_queue_timeout',
        }).in_('id', batch).execute()
    return len(stale_ids)

@server_deployment_bp.route('/execution/<execution_id>/abort', methods=['POST'])
@handle_route_exceptions('deployment:abort_execution')
def abort_queued_execution(execution_id):
    """Abort a queued deployment execution."""
    supabase = get_supabase_client()
    try:
        row = supabase.table('deployment_executions').select(
            'id, status'
        ).eq('id', execution_id).single().execute()
    except Exception:
        return jsonify({'success': False, 'error': 'Execution not found'}), 404

    if row.data.get('status') != 'queued':
        return jsonify({'success': False, 'error': f"Cannot abort execution with status '{row.data.get('status')}' (only queued)"}), 409

    supabase.table('deployment_executions').update({
        'status': 'aborted',
        'completed_at': datetime.now(timezone.utc).isoformat(),
        'success': False,
        'error_message': 'Manually aborted from UI',
        'skip_reason': 'manual_abort',
    }).eq('id', execution_id).execute()

    emit_system_update('deployment_execution_changed', {
        'domain': 'deployment',
        'action': 'aborted',
        'execution_id': execution_id,
    })

    return jsonify({'success': True, 'message': 'Queued execution aborted'}), 200


@server_deployment_bp.route('/create', methods=['POST'])
@handle_route_exceptions('deployment:create_deployment')
def create_deployment():
    data = request.get_json()
    team_id = request.args.get('team_id')
    supabase = get_supabase_client()
    
    # Build deployment data
    normalized_cron = _normalize_cron_expression(data['cron_expression'])
    deployment_data = {
        'team_id': team_id,
        'name': data['name'],
        'host_name': data['host_name'],
        'device_id': data['device_id'],
        'script_name': data['script_name'],
        'userinterface_name': data['userinterface_name'],
        'parameters': data.get('parameters'),
        'campaign_id': data.get('campaign_id'),
        'cron_expression': normalized_cron,
        'status': 'active'
    }
    
    # Optional constraints
    if 'start_date' in data and data['start_date']:
        deployment_data['start_date'] = data['start_date']
    if 'end_date' in data and data['end_date']:
        deployment_data['end_date'] = data['end_date']
    if 'max_executions' in data and data['max_executions']:
        deployment_data['max_executions'] = data['max_executions']

    # Optional rerun_payload (full launch-time config so "Last Executions" can
    # rerun this row in one click without refetching anything). Supabase
    # accepts dicts as JSONB.
    if 'rerun_payload' in data and data['rerun_payload'] is not None:
        deployment_data['rerun_payload'] = data['rerun_payload']

    # Optional per-device device_info: manually-provided metadata.info applied to
    # every script this deployment runs (merged into the run's metadata.info).
    if isinstance(data.get('device_info'), dict) and data['device_info']:
        deployment_data['device_info'] = data['device_info']

    # Virtual-script deployments: which dev/test/prod row to materialize and
    # run (deployment_scheduler.py already resolves this — see
    # backend_host/src/services/deployment_scheduler.py). Absent for
    # disk-script/campaign deployments.
    if data.get('virtual_script_id'):
        deployment_data['virtual_script_id'] = data['virtual_script_id']

    # Capacity/KPI tag this run counts as. Only set when the caller supplies
    # one — the column default ('prod') covers every other caller.
    if data.get('environment') in ('dev', 'test', 'prod'):
        deployment_data['environment'] = data['environment']

    # Insert into Supabase
    result = supabase.table('deployments').insert(deployment_data).execute()
    
    deployment = result.data[0]
    
    # Call host to add to scheduler
    host_manager = get_host_manager()
    host_info = host_manager.get_host(data['host_name'])
    if host_info:
        call_host(host_info, '/host/deployment/add', method='POST', data=deployment, timeout=10)
    emit_system_update('deployment_changed', {'domain': 'deployment', 'action': 'created', 'deployment_id': deployment.get('id')})
    
    return jsonify({'success': True, 'deployment': deployment})
@server_deployment_bp.route('/update/<deployment_id>', methods=['PUT'])
@handle_route_exceptions('deployment:update_deployment')
def update_deployment(deployment_id):
    data = request.get_json()
    supabase = get_supabase_client()
    
    # Get existing deployment
    dep = supabase.table('deployments').select('*').eq('id', deployment_id).single().execute().data
    
    # Build update data
    update_data = {}
    if 'cron_expression' in data:
        update_data['cron_expression'] = (data['cron_expression'] or '').strip()
    if 'parameters' in data:
        update_data['parameters'] = data['parameters']
    if 'start_date' in data:
        update_data['start_date'] = data['start_date']
    if 'end_date' in data:
        update_data['end_date'] = data['end_date']
    if 'max_executions' in data:
        update_data['max_executions'] = data['max_executions']
    
    # Update in database
    supabase.table('deployments').update(update_data).eq('id', deployment_id).execute()
    updated_deployment = supabase.table('deployments').select('*').eq('id', deployment_id).single().execute().data
    
    # Notify host to update scheduler
    host_manager = get_host_manager()
    host_info = host_manager.get_host(dep['host_name'])
    if host_info:
        call_host(
            host_info,
            f'/host/deployment/update/{deployment_id}',
            method='PUT',
            data=updated_deployment,
            timeout=10,
        )
    emit_system_update('deployment_changed', {'domain': 'deployment', 'action': 'updated', 'deployment_id': deployment_id})

    updated_deployment['next_run'] = _calculate_next_run(updated_deployment)
    return jsonify({'success': True, 'deployment': updated_deployment})
@server_deployment_bp.route('/list', methods=['GET'])
@handle_route_exceptions('deployment:list_deployments')
def list_deployments():
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'error': 'team_id is required'
        }), 400
    # Validate UUID format
    import re
    uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
    if not uuid_pattern.match(team_id):
        return jsonify({
            'success': False,
            'error': 'team_id must be a valid UUID'
        }), 400
    supabase = get_supabase_client()
    # Only return schedulable deployments: active (cron fires it) or paused
    # (temporarily disabled). 'completed' rows are inert — either exhausted
    # schedules or ad-hoc "Run Now" receipts from adhoc_execution.py that exist
    # solely for the execution-history join, never rendered in the UI list.
    # Including them flooded the response and pushed real schedules past the
    # PostgREST 1000-row cap.
    result = (
        supabase.table('deployments')
        .select('*')
        .eq('team_id', team_id)
        .in_('status', ['active', 'paused'])
        .order('created_at', desc=True)
        .execute()
    )
    deployments = result.data or []
    for deployment in deployments:
        deployment['next_run'] = _calculate_next_run(deployment)
    return jsonify({'success': True, 'deployments': deployments})
@server_deployment_bp.route('/pause/<deployment_id>', methods=['POST'])
@handle_route_exceptions('deployment:pause_deployment')
def pause_deployment(deployment_id):
    supabase = get_supabase_client()
    dep = supabase.table('deployments').select('*').eq('id', deployment_id).single().execute().data
    supabase.table('deployments').update({'status': 'paused'}).eq('id', deployment_id).execute()
    
    host_manager = get_host_manager()
    host_info = host_manager.get_host(dep['host_name'])
    if host_info:
        call_host(host_info, f'/host/deployment/pause/{deployment_id}', method='POST', timeout=10)
    emit_system_update('deployment_changed', {'domain': 'deployment', 'action': 'paused', 'deployment_id': deployment_id})
    
    return jsonify({'success': True})
@server_deployment_bp.route('/resume/<deployment_id>', methods=['POST'])
@handle_route_exceptions('deployment:resume_deployment')
def resume_deployment(deployment_id):
    supabase = get_supabase_client()
    dep = supabase.table('deployments').select('*').eq('id', deployment_id).single().execute().data
    supabase.table('deployments').update({'status': 'active'}).eq('id', deployment_id).execute()
    
    host_manager = get_host_manager()
    host_info = host_manager.get_host(dep['host_name'])
    if host_info:
        call_host(host_info, f'/host/deployment/resume/{deployment_id}', method='POST', timeout=10)
    emit_system_update('deployment_changed', {'domain': 'deployment', 'action': 'resumed', 'deployment_id': deployment_id})
    
    return jsonify({'success': True})


@server_deployment_bp.route('/run/<deployment_id>', methods=['POST'])
@handle_route_exceptions('deployment:run_deployment')
def run_deployment(deployment_id):
    supabase = get_supabase_client()
    dep = supabase.table('deployments').select('*').eq('id', deployment_id).single().execute().data
    if not dep:
        return jsonify({'success': False, 'error': 'Deployment not found'}), 404

    host_manager = get_host_manager()
    host_info = host_manager.get_host(dep['host_name'])
    if host_info:
        call_host(host_info, f'/host/deployment/run/{deployment_id}', method='POST', timeout=10)
    emit_system_update('deployment_execution_changed', {'domain': 'deployment', 'action': 'run_now', 'deployment_id': deployment_id})

    return jsonify({'success': True})
@server_deployment_bp.route('/delete/<deployment_id>', methods=['DELETE'])
@handle_route_exceptions('deployment:delete_deployment')
def delete_deployment(deployment_id):
    supabase = get_supabase_client()
    dep = supabase.table('deployments').select('*').eq('id', deployment_id).single().execute().data
    supabase.table('deployments').delete().eq('id', deployment_id).execute()
    
    host_manager = get_host_manager()
    host_info = host_manager.get_host(dep['host_name'])
    if host_info:
        call_host(host_info, f'/host/deployment/remove/{deployment_id}', method='DELETE', timeout=10)
    emit_system_update('deployment_changed', {'domain': 'deployment', 'action': 'deleted', 'deployment_id': deployment_id})
    
    return jsonify({'success': True})
@server_deployment_bp.route('/history/<deployment_id>', methods=['GET'])
@handle_route_exceptions('deployment:deployment_history')
def deployment_history(deployment_id):
    supabase = get_supabase_client()
    result = supabase.table('deployment_executions').select('*').eq('deployment_id', deployment_id).order('started_at', desc=True).limit(100).execute()
    return jsonify({'success': True, 'executions': result.data})
@server_deployment_bp.route('/executions/recent', methods=['GET'])
@handle_route_exceptions('deployment:recent_executions')
def recent_executions():
    import time as _time
    _t_route_start = _time.time()
    team_id = request.args.get('team_id')
    supabase = get_supabase_client()

    # Stale threshold: executions still marked queued/running after 4 hours are dead
    stale_cutoff = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()

    # Trimmed column list — only what flatten() and the frontend mappers consume.
    # `*` previously dragged unused fields (skip_reason, etc.) into a 124KB payload.
    select_cols = (
        'id, deployment_id, script_result_id, scheduled_at, started_at, '
        'completed_at, status, success, error_message, '
        'deployments!inner(team_id, name, script_name, host_name, device_id, '
        'cron_expression, campaign_id, parameters, rerun_payload), '
        'script_results!script_result_id(html_report_r2_url, logs_r2_url)'
    )
    terminal_statuses = ['completed', 'failed']

    # --- Optional workspace scoping (frontend WorkspaceContext). Applied to the
    # embedded `deployments` resource BEFORE the limit so each workspace gets its
    # own N most-recent rows instead of being starved when another workspace
    # already filled the global limit. device_filter = exact `host:device` pairs
    # (applies to every row); script_filter = script names (applies to script
    # rows only — file-campaigns stay visible via the campaign-name leg). ---
    import json as _json

    def _safe(value: str) -> bool:
        # PostgREST embedded-filter values would need quoting for these chars;
        # real host/device/script names never contain them, so just drop unsafe.
        return bool(value) and not any(c in value for c in ',()"')

    device_pairs = []
    raw_devices = request.args.get('device_filter')
    if raw_devices:
        try:
            for entry in _json.loads(raw_devices):
                host, _, device = str(entry).partition(':')
                if _safe(host) and _safe(device):
                    device_pairs.append((host, device))
        except (ValueError, TypeError):
            pass

    script_names = []
    raw_scripts = request.args.get('script_filter')
    if raw_scripts:
        try:
            for name in _json.loads(raw_scripts):
                bare = str(name)[:-3] if str(name).endswith('.py') else str(name)
                for variant in (bare, f'{bare}.py'):
                    if _safe(variant) and variant not in script_names:
                        script_names.append(variant)
        except (ValueError, TypeError):
            pass

    def _device_inner():
        return ','.join(f'and(host_name.eq.{h},device_id.eq.{d})' for h, d in device_pairs)

    def _script_inner():
        return f'script_name.in.({",".join(script_names)}),script_name.ilike.*campaign*'

    def _scope(query, include_script=False):
        use_device = bool(device_pairs)
        use_script = include_script and bool(script_names)
        if use_device and use_script:
            # postgrest-py has no and_(reference_table=...): inject the documented
            # `deployments.and=(or(devices),or(scripts))` embedded-logic param.
            query.params = query.params.add(
                'deployments.and', f'(or({_device_inner()}),or({_script_inner()}))'
            )
        elif use_device:
            query = query.or_(_device_inner(), reference_table='deployments')
        elif use_script:
            query = query.or_(_script_inner(), reference_table='deployments')
        return query

    def _q_running():
        q = supabase.table('deployment_executions').select(select_cols).eq(
            'deployments.team_id', team_id
        ).eq('status', 'running').gte('started_at', stale_cutoff)
        return _scope(q).order('started_at', desc=True).execute()

    def _q_queued():
        q = supabase.table('deployment_executions').select(select_cols).eq(
            'deployments.team_id', team_id
        ).eq('status', 'queued')
        return _scope(q).order('scheduled_at', desc=True).limit(50).execute()

    def _q_completed_scripts():
        q = supabase.table('deployment_executions').select(select_cols).eq(
            'deployments.team_id', team_id
        ).is_('deployments.campaign_id', 'null').in_('status', terminal_statuses)
        return _scope(q, include_script=True).order('started_at', desc=True).limit(20).execute()

    def _q_completed_campaigns():
        q = supabase.table('deployment_executions').select(select_cols).eq(
            'deployments.team_id', team_id
        ).not_.is_('deployments.campaign_id', 'null').in_('status', terminal_statuses)
        return _scope(q).order('started_at', desc=True).limit(20).execute()

    # Fire the four list queries + stale-abort concurrently. abort_stale runs
    # a sequential SELECT-then-UPDATE; on the common (zero stale) path it's a
    # pure ~250ms SELECT that we shouldn't block on. The queued query may race
    # ahead of the abort, leaking an about-to-be-aborted row into the response;
    # the next refresh corrects it.
    g_running = gevent.spawn(_q_running)
    g_queued = gevent.spawn(_q_queued)
    g_completed_scripts = gevent.spawn(_q_completed_scripts)
    g_completed_campaigns = gevent.spawn(_q_completed_campaigns)
    g_abort_stale = gevent.spawn(_abort_stale_queued_executions, supabase, team_id, stale_cutoff)
    gevent.joinall([g_running, g_queued, g_completed_scripts, g_completed_campaigns, g_abort_stale])
    for g in (g_running, g_queued, g_completed_scripts, g_completed_campaigns):
        if g.exception:
            raise g.exception
    running_result = g_running.value
    queued_result = g_queued.value
    completed_scripts_result = g_completed_scripts.value
    completed_campaigns_result = g_completed_campaigns.value
    if g_abort_stale.exception:
        # Don't fail the whole route — log and continue.
        print(f"[@route:deployment:recent_executions] abort_stale failed: {g_abort_stale.exception}")
    elif g_abort_stale.value:
        print(f"[@route:deployment:recent_executions] Auto-aborted {g_abort_stale.value} stale queued execution(s)")
    _t_after_queries = _time.time()

    completed_result_data = (completed_scripts_result.data or []) + (completed_campaigns_result.data or [])

    def _format_artifacts(campaign_row, scripts_by_id):
        script_result_ids = campaign_row.get('script_result_ids') or []
        campaign_scripts = [scripts_by_id[sid] for sid in script_result_ids if sid in scripts_by_id]
        campaign_scripts.sort(key=lambda r: r.get('started_at') or '')
        return {
            'campaign_name': campaign_row.get('campaign_name'),
            'campaign_status': campaign_row.get('status'),
            'report_url': campaign_row.get('html_report_r2_url'),
            'logs_url': campaign_row.get('logs_r2_url'),
            'campaign_success': campaign_row.get('success'),
            'campaign_scripts': campaign_scripts,
        }

    def _batch_resolve_campaign_artifacts(execution_rows):
        """
        Precompute artifacts for every campaign execution in `execution_rows`
        using at most three Supabase round-trips (one campaign_executions
        lookup, one script_results lookup batched by 50, plus one optional
        time-window fallback). This replaces the previous per-row pattern
        that fired ≥2 round-trips per campaign row.
        """
        artifacts_by_exec_id: Dict[str, Dict[str, Any]] = {}
        db_campaign_exec_ids: List[str] = []
        file_campaign_targets: List[Dict[str, Any]] = []  # {exec_id, host, device, start_dt}

        for exec_row in execution_rows:
            deployment = exec_row.get('deployments') or {}
            exec_id = exec_row.get('id')
            if not exec_id:
                continue
            if deployment.get('campaign_id'):
                db_campaign_exec_ids.append(exec_id)
                continue
            script_name = deployment.get('script_name') or ''
            if 'campaign' not in script_name.lower():
                continue
            host_name = deployment.get('host_name')
            started_at = exec_row.get('started_at')
            if not host_name or not started_at:
                continue
            try:
                start_dt = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
            except Exception:
                continue
            file_campaign_targets.append({
                'exec_id': exec_id,
                'host': host_name,
                'device': deployment.get('device_id'),
                'start_dt': start_dt,
            })

        if not db_campaign_exec_ids and not file_campaign_targets:
            return artifacts_by_exec_id

        ce_select = (
            'id, campaign_name, started_at, status, html_report_r2_url, '
            'logs_r2_url, script_result_ids, success, host_name, device_name, metadata'
        )

        # 1) DB campaigns: one OR query per batch of 100 deployment_execution_ids.
        # 2) File campaigns: one window-bounded query, filtered per row in Python.
        # Both target campaign_executions on independent filters — run concurrently.
        def _q_db_campaigns():
            matches: List[Dict[str, Any]] = []
            if not db_campaign_exec_ids:
                return matches
            BATCH = 100  # PostgREST URL length cap
            for i in range(0, len(db_campaign_exec_ids), BATCH):
                ids_batch = db_campaign_exec_ids[i:i + BATCH]
                or_filter = ','.join(
                    f'metadata.cs.{{"deployment_execution_id":"{eid}"}}'
                    for eid in ids_batch
                )
                ce_resp = supabase.table('campaign_executions').select(ce_select).eq(
                    'team_id', team_id
                ).or_(or_filter).execute()
                matches.extend(ce_resp.data or [])
            return matches

        def _q_file_campaigns():
            if not file_campaign_targets:
                return []
            earliest = min(t['start_dt'] for t in file_campaign_targets) - timedelta(seconds=30)
            latest = max(t['start_dt'] for t in file_campaign_targets) + timedelta(minutes=30)
            ce_resp = supabase.table('campaign_executions').select(ce_select).eq(
                'team_id', team_id
            ).gte('started_at', earliest.isoformat()).lte(
                'started_at', latest.isoformat()
            ).execute()
            return ce_resp.data or []

        g_db = gevent.spawn(_q_db_campaigns)
        g_file = gevent.spawn(_q_file_campaigns)
        gevent.joinall([g_db, g_file])
        for g in (g_db, g_file):
            if g.exception:
                raise g.exception
        db_matches: List[Dict[str, Any]] = g_db.value or []
        file_matches: List[Dict[str, Any]] = g_file.value or []

        # 3) Bulk-fetch every linked script_result in one batched .in_() call.
        all_script_result_ids: List[str] = []
        for ce in db_matches + file_matches:
            all_script_result_ids.extend(ce.get('script_result_ids') or [])
        scripts_by_id: Dict[str, Dict[str, Any]] = {}
        if all_script_result_ids:
            unique_ids = list({sid for sid in all_script_result_ids if sid})
            BATCH = 50
            sr_select = (
                'id, script_name, success, started_at, completed_at, '
                'execution_time_ms, html_report_r2_url, logs_r2_url, error_msg'
            )
            for i in range(0, len(unique_ids), BATCH):
                batch = unique_ids[i:i + BATCH]
                sr_resp = supabase.table('script_results').select(sr_select).in_('id', batch).execute()
                for row in sr_resp.data or []:
                    scripts_by_id[row['id']] = row

        # Wire DB-campaign matches back to their deployment_execution_id.
        for ce in db_matches:
            metadata = ce.get('metadata') or {}
            dep_exec_id = metadata.get('deployment_execution_id')
            if dep_exec_id and dep_exec_id not in artifacts_by_exec_id:
                artifacts_by_exec_id[dep_exec_id] = _format_artifacts(ce, scripts_by_id)

        # Wire file-campaign matches by (host, device) + time window.
        if file_matches:
            by_target: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
            for ce in file_matches:
                key = (ce.get('host_name') or '', ce.get('device_name') or '')
                by_target.setdefault(key, []).append(ce)
            for target in file_campaign_targets:
                if target['exec_id'] in artifacts_by_exec_id:
                    continue
                key = (target['host'] or '', target['device'] or '')
                candidates = by_target.get(key) or []
                window_start = target['start_dt'] - timedelta(seconds=30)
                window_end = target['start_dt'] + timedelta(minutes=30)
                best: Optional[Dict[str, Any]] = None
                for ce in candidates:
                    started = ce.get('started_at')
                    if not started:
                        continue
                    try:
                        ce_dt = datetime.fromisoformat(started.replace('Z', '+00:00'))
                    except Exception:
                        continue
                    if window_start <= ce_dt <= window_end:
                        if best is None or ce_dt > datetime.fromisoformat(
                            best['started_at'].replace('Z', '+00:00')
                        ):
                            best = ce
                if best is not None:
                    artifacts_by_exec_id[target['exec_id']] = _format_artifacts(best, scripts_by_id)

        return artifacts_by_exec_id

    def _batch_resolve_script_fallback(execution_rows):
        """
        Replacement for the per-row script_results time-window fallback. Some
        legacy deployment_executions rows have script_result_id=NULL so the FK
        embed returns nothing — for those we look up script_results by
        team_id + script_name + host_name + a generous window. One round-trip
        across all such rows instead of one per row.
        """
        results_by_exec_id: Dict[str, Dict[str, Optional[str]]] = {}
        candidates = []  # (exec_id, bare_name, host_name, start_dt)
        for exec_row in execution_rows:
            deployment = exec_row.get('deployments') or {}
            exec_id = exec_row.get('id')
            if not exec_id:
                continue
            if deployment.get('campaign_id'):
                continue
            script_name = deployment.get('script_name') or ''
            if not script_name or 'campaign' in script_name.lower():
                continue
            joined = exec_row.get('script_results')
            if isinstance(joined, dict) and joined.get('html_report_r2_url'):
                continue
            if isinstance(joined, list) and joined and joined[0].get('html_report_r2_url'):
                continue
            host_name = deployment.get('host_name') or ''
            started_at = exec_row.get('started_at')
            if not host_name or not started_at:
                continue
            try:
                start_dt = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
            except Exception:
                continue
            bare_name = script_name.rsplit('/', 1)[-1].replace('.py', '')
            candidates.append((exec_id, bare_name, host_name, start_dt))

        if not candidates:
            return results_by_exec_id

        bare_names = list({c[1] for c in candidates})
        host_names = list({c[2] for c in candidates})
        earliest = min(c[3] for c in candidates) - timedelta(seconds=30)
        latest = max(c[3] for c in candidates) + timedelta(minutes=30)

        # `record_script_execution_start` inserts script_results with
        # placeholder completed_at = started_at and success = False so the
        # NOT NULL columns are satisfied; execution_time_ms stays NULL until
        # `update_script_execution_result` runs at script completion. Filter
        # in-flight rows out here, otherwise the reconciler below would flip
        # every just-started run to "failed" the moment /executions/recent
        # is polled.
        try:
            sr_resp = supabase.table('script_results').select(
                'id, script_name, host_name, started_at, completed_at, success, '
                'execution_time_ms, html_report_r2_url, logs_r2_url'
            ).eq('team_id', team_id).in_(
                'script_name', bare_names
            ).in_(
                'host_name', host_names
            ).gte('started_at', earliest.isoformat()).lte(
                'started_at', latest.isoformat()
            ).not_.is_('execution_time_ms', 'null').order(
                'started_at', desc=True
            ).execute()
        except Exception as e:
            print(f"[@recent_executions] script_results batched fallback failed: {e}")
            return results_by_exec_id

        # Bucket by (script_name, host_name) for fast per-row matching.
        by_key: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for row in sr_resp.data or []:
            key = (row.get('script_name') or '', row.get('host_name') or '')
            by_key.setdefault(key, []).append(row)

        for exec_id, bare_name, host_name, start_dt in candidates:
            window_start = start_dt - timedelta(seconds=30)
            window_end = start_dt + timedelta(minutes=30)
            best = None
            for sr in by_key.get((bare_name, host_name), ()):
                started = sr.get('started_at')
                if not started:
                    continue
                try:
                    sr_dt = datetime.fromisoformat(started.replace('Z', '+00:00'))
                except Exception:
                    continue
                if window_start <= sr_dt <= window_end:
                    if best is None or sr_dt > datetime.fromisoformat(
                        best['started_at'].replace('Z', '+00:00')
                    ):
                        best = sr
            if best is not None:
                results_by_exec_id[exec_id] = {
                    'report_url': best.get('html_report_r2_url'),
                    'logs_url': best.get('logs_r2_url'),
                    'script_result_id': best.get('id'),
                    'success': best.get('success'),
                    'completed_at': best.get('completed_at'),
                    'execution_time_ms': best.get('execution_time_ms'),
                }
        return results_by_exec_id

    def flatten(rows, artifacts_by_exec_id, script_fallback_by_exec_id, include_campaign_artifacts=True):
        result = []
        for exec in rows:
            execution_data = {**exec}
            deployment = exec.get('deployments') or {}
            is_campaign = bool(deployment.get('campaign_id'))
            is_file_campaign = not is_campaign and 'campaign' in (deployment.get('script_name') or '').lower()

            if is_campaign or is_file_campaign:
                if include_campaign_artifacts:
                    campaign_artifacts = artifacts_by_exec_id.get(exec.get('id'))
                    if campaign_artifacts:
                        execution_data.update({
                            'campaign_name': campaign_artifacts.get('campaign_name'),
                            'report_url': campaign_artifacts.get('report_url'),
                            'logs_url': campaign_artifacts.get('logs_url'),
                            'campaign_success': campaign_artifacts.get('campaign_success'),
                            'campaign_scripts': campaign_artifacts.get('campaign_scripts', []),
                        })
            else:
                script_results_joined = exec.get('script_results')
                report_url = None
                logs_url = None
                if isinstance(script_results_joined, dict):
                    report_url = script_results_joined.get('html_report_r2_url')
                    logs_url = script_results_joined.get('logs_r2_url')
                elif isinstance(script_results_joined, list) and script_results_joined:
                    report_url = script_results_joined[0].get('html_report_r2_url')
                    logs_url = script_results_joined[0].get('logs_r2_url')

                if not report_url:
                    fallback = script_fallback_by_exec_id.get(exec.get('id'))
                    if fallback:
                        report_url = fallback.get('report_url')
                        logs_url = fallback.get('logs_url')

                if report_url:
                    execution_data['report_url'] = report_url
                if logs_url:
                    execution_data['logs_url'] = logs_url
            execution_data['is_campaign'] = is_campaign or is_file_campaign
            result.append(execution_data)
        return result

    # One pass to compute campaign artifacts and script-results fallbacks across
    # every running + completed row, instead of issuing per-row queries inside
    # flatten(). Queued executions don't have artifacts yet (no script_result_id,
    # no campaign_execution row) so they're excluded from the precompute.
    # The two resolvers are independent — run concurrently.
    artifacts_inputs = (running_result.data or []) + completed_result_data
    g_artifacts = gevent.spawn(_batch_resolve_campaign_artifacts, artifacts_inputs)
    g_fallback = gevent.spawn(_batch_resolve_script_fallback, artifacts_inputs)
    gevent.joinall([g_artifacts, g_fallback])
    for g in (g_artifacts, g_fallback):
        if g.exception:
            raise g.exception
    artifacts_by_exec_id = g_artifacts.value
    script_fallback_by_exec_id = g_fallback.value
    _t_after_artifacts = _time.time()

    running = flatten(running_result.data or [], artifacts_by_exec_id, script_fallback_by_exec_id)
    queued = flatten(
        queued_result.data or [], artifacts_by_exec_id, script_fallback_by_exec_id,
        include_campaign_artifacts=False,
    )
    completed = flatten(completed_result_data, artifacts_by_exec_id, script_fallback_by_exec_id)

    # De-duplicate: an execution can appear in both running and completed results
    # when its status changes between the two Supabase queries (race condition).
    running_and_queued_ids = {r['id'] for r in running} | {q['id'] for q in queued}
    completed = [c for c in completed if c['id'] not in running_and_queued_ids]

    # Reconcile stale "running" campaign and script executions whose underlying
    # work already completed. This handles cases where post-processing silently
    # died (gevent/APScheduler thread issue, host->server callback failure, etc.)
    # and never updated deployment_executions.status.
    still_running = []
    for exec_row in running:
        campaign_status = exec_row.get('campaign_status')
        script_fallback = script_fallback_by_exec_id.get(exec_row.get('id')) or {}
        script_completed_at = script_fallback.get('completed_at')
        script_success = script_fallback.get('success')

        reconciled_status = None
        reconciled_success = None

        if campaign_status in {'completed', 'failed', 'aborted'}:
            # Campaign actually finished — fix the stale deployment_execution record
            if campaign_status == 'aborted':
                reconciled_status = 'aborted'
                reconciled_success = exec_row.get('campaign_success')
            else:
                reconciled_success = exec_row.get('campaign_success')
                reconciled_status = 'completed' if reconciled_success else 'failed'
        elif script_fallback.get('execution_time_ms') is not None:
            # script_results has been finalized by update_script_execution_result
            # (execution_time_ms is NULL until then; completed_at and success are
            # placeholder values from record_script_execution_start, so they're
            # unreliable signals on their own). Treat this deployment_execution
            # row as stale-running and adopt the script's real outcome.
            reconciled_success = bool(script_success)
            reconciled_status = 'completed' if reconciled_success else 'failed'

        if reconciled_status is None:
            still_running.append(exec_row)
            continue

        exec_row['status'] = reconciled_status
        exec_row['success'] = reconciled_success
        completed.append(exec_row)
        try:
            update_payload = {
                'status': reconciled_status,
                'success': reconciled_success,
                'completed_at': script_completed_at or datetime.now(timezone.utc).isoformat(),
            }
            script_result_id = script_fallback.get('script_result_id')
            if script_result_id and not exec_row.get('script_result_id'):
                update_payload['script_result_id'] = script_result_id
            supabase.table('deployment_executions').update(update_payload).eq('id', exec_row['id']).execute()
            kind = 'campaign' if campaign_status else 'script'
            print(f"[@route:deployment:recent_executions] Reconciled stale {kind} execution {exec_row['id']} → {reconciled_status}")
        except Exception as reconcile_error:
            print(f"[@route:deployment:recent_executions] Failed to reconcile execution {exec_row.get('id')}: {reconcile_error}")
        # Release any stale device lock the scheduler never released
        dep = exec_row.get('deployments') or {}
        dep_host = dep.get('host_name')
        dep_device = dep.get('device_id')
        if dep_host and dep_device:
            try:
                rel = release_device_lock(
                    host_name=dep_host, device_id=dep_device,
                    owner_type='deployment_execution', force=True,
                )
                if rel.get('released'):
                    emit_system_update('lock_changed', {
                        'host_name': dep_host, 'device_id': dep_device,
                        'is_locked': False, 'lock_info': rel.get('lock_info'),
                    })
            except Exception:
                pass
    running = still_running

    # Strip fields the frontend doesn't read — the script_results embed alone is
    # ~30KB of redundant signed-URL bytes (we already pulled report_url/logs_url
    # up to the top level inside flatten()). Trimming these from the response
    # noticeably cuts JSON serialization on the Pi and download size on clients.
    _STRIPPED = ('script_results', 'script_result_id')
    def _strip(rows):
        for row in rows:
            for key in _STRIPPED:
                row.pop(key, None)
        return rows
    running = _strip(running)
    queued = _strip(queued)
    completed = _strip(completed)

    _t_end = _time.time()
    print(
        f"[@route:deployment:recent_executions] timing total={_t_end - _t_route_start:.3f}s "
        f"queries={_t_after_queries - _t_route_start:.3f}s "
        f"artifacts={_t_after_artifacts - _t_after_queries:.3f}s "
        f"flatten_recon={_t_end - _t_after_artifacts:.3f}s"
    )

    return jsonify({
        'success': True,
        'running_executions': running,
        'queued_executions': queued,
        'completed_executions': completed,
        'running_count': len(running),
        'queued_count': len(queued),
        'completed_count': len(completed),
    })


@server_deployment_bp.route('/executionComplete', methods=['POST'])
@handle_route_exceptions('deployment:execution_complete')
def execution_complete():
    """
    Receive deployment execution completion from host scheduler and fan out notifications.

    Expected payload:
      deployment_id, execution_id, host_name, device_id, script_name,
      started_at, completed_at, success, status, result, error, callback_url(optional)
    """
    data = request.get_json() or {}
    deployment_id = data.get('deployment_id')
    execution_id = data.get('execution_id')
    if not deployment_id or not execution_id:
        return jsonify({
            'success': False,
            'error': 'deployment_id and execution_id are required',
        }), 400

    status = data.get('status')
    success = data.get('success')
    error = data.get('error')
    if not status:
        if success is False or error:
            status = 'failed'
        else:
            status = 'completed'

    supabase = get_supabase_client()
    deployment = None
    try:
        dep_res = supabase.table('deployments').select(
            'id, team_id, name, host_name, device_id, script_name'
        ).eq('id', deployment_id).single().execute()
        deployment = dep_res.data
    except Exception:
        deployment = None

    callback_url = data.get('callback_url')
    lock_owner_session_id = data.get('lock_owner_session_id')
    lock_owner_job_id = data.get('lock_owner_job_id')

    host_name = data.get('host_name') or (deployment.get('host_name') if deployment else None)
    device_id = data.get('device_id') or (deployment.get('device_id') if deployment else None)
    team_id = data.get('team_id') or (deployment.get('team_id') if deployment else None)

    if host_name and device_id and status in ('completed', 'failed', 'skipped', 'aborted'):
        release_result = release_device_lock(
            host_name=host_name,
            device_id=device_id,
            owner_session_id=lock_owner_session_id,
            owner_type='deployment_execution',
            owner_job_id=lock_owner_job_id,
            force=False,
        )
        if release_result.get('success'):
            emit_system_update('lock_changed', {
                'host_name': host_name,
                'device_id': device_id,
                'is_locked': False,
                'lock_info': release_result.get('lock_info'),
            })
        else:
            print(
                f"[@route:deployment:execution_complete] Lock release failed for "
                f"{host_name}:{device_id}: {release_result.get('error')}"
            )

    result_payload = data.get('result') or {}
    result_payload.update({
        'deployment_id': deployment_id,
        'deployment_execution_id': execution_id,
        'script_name': data.get('script_name') or (deployment.get('script_name') if deployment else None),
        'started_at': data.get('started_at'),
        'completed_at': data.get('completed_at'),
        'success': bool(success) if success is not None else status != 'failed',
    })

    notify_result = notify_completion(
        {
            'task_id': execution_id,
            'execution_type': 'deployment',
            'status': status,
            'success': bool(success) if success is not None else status != 'failed',
            'host_name': host_name,
            'device_id': device_id,
            'team_id': team_id,
            'deployment_id': deployment_id,
            'deployment_execution_id': execution_id,
            'result': result_payload,
            'error': error,
            'action': 'deployment_execution_complete',
        },
        callback_url=callback_url,
    )

    return jsonify({
        'success': True,
        'notified': True,
        'webhook_sent': notify_result.get('webhook_sent', False),
        'webhook_error': notify_result.get('webhook_error'),
    }), 200
