#!/usr/bin/env python3
"""
Campaign Executions Database Operations

Simplified single-table approach for campaign tracking that links to script_results.
"""

import os
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from uuid import uuid4

# Add project root to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))

if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.utils.supabase_utils import get_supabase_client
from shared.src.lib.database.in_filter import chunked_in


def get_supabase():
    """Get Supabase client"""
    return get_supabase_client()


def record_campaign_execution_start(
    team_id: str,
    campaign_name: str,
    campaign_execution_id: str,
    userinterface_name: Optional[str] = None,
    host_name: str = "",
    device_name: str = "",
    description: Optional[str] = None,
    script_configurations: Optional[List[Dict]] = None,
    execution_config: Optional[Dict] = None,
    executed_by: Optional[str] = None,
    metadata: Optional[Dict] = None
) -> Optional[str]:
    """Record campaign execution start in database."""
    try:
        campaign_execution_id_uuid = str(uuid4())
        
        campaign_data = {
            'id': campaign_execution_id_uuid,
            'team_id': team_id,
            'campaign_name': campaign_name,
            'campaign_description': description,
            'campaign_execution_id': campaign_execution_id,
            'userinterface_name': userinterface_name,
            'host_name': host_name,
            'device_name': device_name,
            'status': 'running',
            'started_at': datetime.now(timezone.utc).isoformat(),
            'success': False,
            'script_configurations': script_configurations or [],
            'execution_config': execution_config or {},
            'script_result_ids': [],
            'executed_by': executed_by,
            'metadata': metadata or {}
        }
        
        print(f"[@db:campaign_executions:record_start] Starting campaign execution:")
        print(f"  - campaign_execution_id_uuid: {campaign_execution_id_uuid}")
        print(f"  - team_id: {team_id}")
        print(f"  - campaign_name: {campaign_name}")
        print(f"  - campaign_execution_id: {campaign_execution_id}")
        print(f"  - total_scripts: {len(script_configurations) if script_configurations else 0}")
        
        supabase = get_supabase()
        result = supabase.table('campaign_executions').insert(campaign_data).execute()
        
        if result.data:
            print(f"[@db:campaign_executions:record_start] Success: {campaign_execution_id_uuid}")
            return campaign_execution_id_uuid
        else:
            print(f"[@db:campaign_executions:record_start] Failed")
            return None
            
    except Exception as e:
        print(f"[@db:campaign_executions:record_start] Error: {str(e)}")
        return None


def add_script_result_to_campaign(
    campaign_execution_id_uuid: str,
    script_result_id: str
) -> bool:
    """Add a script result ID to the campaign's script_result_ids array
    and set campaign_execution_uuid on the script_results row."""
    try:
        supabase = get_supabase()

        # Set the backlink on script_results so Grafana JOINs work
        try:
            supabase.table('script_results').update({
                'campaign_execution_uuid': campaign_execution_id_uuid
            }).eq('id', script_result_id).execute()
        except Exception as backlink_err:
            print(f"[@db:campaign_executions:add_script] Backlink update failed (non-critical): {backlink_err}")

        # Read-modify-write: fetch current array, append if absent, update.
        # (Previously this used a void-returning RPC `array_append_campaign_script`
        # whose success branch never fired because `result.data` was always empty,
        # and which is missing entirely on some Supabase instances. Direct R-M-W
        # is correct, idempotent, and one code path.)
        current = supabase.table('campaign_executions').select('script_result_ids').eq('id', campaign_execution_id_uuid).execute()
        if not current.data:
            print(f"[@db:campaign_executions:add_script] Campaign {campaign_execution_id_uuid} not found")
            return False

        current_ids = current.data[0]['script_result_ids'] or []
        if script_result_id in current_ids:
            # Already linked — idempotent success
            return True

        current_ids.append(script_result_id)
        update_result = supabase.table('campaign_executions').update({
            'script_result_ids': current_ids
        }).eq('id', campaign_execution_id_uuid).execute()

        if update_result.data:
            print(f"[@db:campaign_executions:add_script] Added script {script_result_id} to campaign {campaign_execution_id_uuid}")
            return True
        return False

    except Exception as e:
        print(f"[@db:campaign_executions:add_script] Error: {str(e)}")
        return False


def update_campaign_execution_result(
    campaign_execution_id_uuid: str,
    status: Optional[str] = None,
    completed_at: Optional[datetime] = None,
    execution_time_ms: Optional[int] = None,
    success: Optional[bool] = None,
    error_message: Optional[str] = None,
    html_report_r2_path: Optional[str] = None,
    html_report_r2_url: Optional[str] = None,
    logs_r2_path: Optional[str] = None,
    logs_r2_url: Optional[str] = None,
    metadata: Optional[Dict] = None
) -> bool:
    """Update campaign execution result in database."""
    try:
        update_data = {}
        
        if status is not None:
            update_data['status'] = status
        if completed_at is not None:
            update_data['completed_at'] = completed_at.isoformat()
        if execution_time_ms is not None:
            update_data['execution_time_ms'] = execution_time_ms
        if success is not None:
            update_data['success'] = success
        if error_message is not None:
            update_data['error_message'] = error_message
        if html_report_r2_path is not None:
            update_data['html_report_r2_path'] = html_report_r2_path
        if html_report_r2_url is not None:
            update_data['html_report_r2_url'] = html_report_r2_url
        if logs_r2_path is not None:
            update_data['logs_r2_path'] = logs_r2_path
        if logs_r2_url is not None:
            update_data['logs_r2_url'] = logs_r2_url
        if metadata is not None:
            update_data['metadata'] = metadata
        
        update_data['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        print(f"[@db:campaign_executions:update_result] Updating campaign: {campaign_execution_id_uuid}")
        print(f"  - status: {status}")
        print(f"  - success: {success}")
        
        supabase = get_supabase()
        result = supabase.table('campaign_executions').update(update_data).eq('id', campaign_execution_id_uuid).execute()
        
        if result.data:
            print(f"[@db:campaign_executions:update_result] Success")
            return True
        else:
            print(f"[@db:campaign_executions:update_result] Failed")
            return False
            
    except Exception as e:
        print(f"[@db:campaign_executions:update_result] Error: {str(e)}")
        return False


# A read may repair, but not on every 20 s dashboard poll: at most once per team per interval.
RECONCILE_MIN_INTERVAL_SECONDS = 300
_last_reconcile_by_team: Dict[str, float] = {}


def _parse_ts(value: Any) -> Optional[datetime]:
    """An ISO timestamp as an aware datetime, or None when it is missing or unreadable."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def reconcile_stale_campaign_executions(
    team_id: str,
    default_timeout_seconds: int = 3600,
    grace_seconds: int = 300,
) -> int:
    """Close campaign rows left running after their worker disappeared.

    A campaign is reconciled from its linked script results when every expected
    script has a finalized ``execution_time_ms``. Otherwise it is closed only when
    its worker is gone, and age alone is no proof of that: the nightlies are
    configured with 120 minutes and legitimately run for 170. The evidence is
    silence: no campaign start, script start, script update or script completion
    for longer than the configured timeout plus a grace period. Such a row is
    closed ``aborted`` (what the host sweep writes) with the time of its last
    activity and a message that names the cause. A campaign whose every script is
    finished is closed from its results whatever its age; the silence rule applies
    only to unfinished ones and never before the limit. The team filter is
    mandatory so a read-side repair cannot cross tenant boundaries.
    """
    if not team_id:
        return 0

    try:
        supabase = get_supabase()
        running = (
            supabase.table('campaign_executions')
            .select(
                'id, started_at, script_result_ids, script_configurations, '
                'execution_config, status'
            )
            .eq('team_id', team_id)
            .eq('status', 'running')
            .execute()
        )
        rows = running.data or []
        if not rows:
            return 0

        reconciled = 0
        now = datetime.now(timezone.utc)
        for campaign in rows:
            campaign_id = campaign.get('id')
            started_at = _parse_ts(campaign.get('started_at'))
            if started_at is None:
                continue

            execution_config = campaign.get('execution_config') or {}
            configured_timeout = execution_config.get('timeout_minutes')
            try:
                timeout_seconds = max(
                    300,
                    int(configured_timeout) * 60 if configured_timeout is not None
                    else default_timeout_seconds,
                )
            except (TypeError, ValueError):
                timeout_seconds = default_timeout_seconds
            silence_limit = timeout_seconds + grace_seconds

            result_ids = [str(value) for value in (campaign.get('script_result_ids') or [])]
            expected_scripts = len(campaign.get('script_configurations') or [])
            script_rows = chunked_in(
                lambda chunk: supabase.table('script_results')
                .select('id, success, skipped, execution_time_ms, started_at, completed_at, updated_at')
                .eq('team_id', team_id)
                .in_('id', chunk),
                result_ids)

            all_scripts_final = (
                bool(script_rows)
                and len(script_rows) >= expected_scripts
                and len(script_rows) >= len(result_ids)
                and all(row.get('execution_time_ms') is not None for row in script_rows)
            )

            if all_scripts_final:
                # A skipped row (the run never executed because it was not
                # configured) is not a failure: it did not look at anything.
                status = 'completed' if all(
                    row.get('success') or row.get('skipped') for row in script_rows
                ) else 'failed'
                completed_values = [row.get('completed_at') for row in script_rows if row.get('completed_at')]
                completed_at = max(completed_values) if completed_values else now.isoformat()
                execution_time_ms = sum(
                    int(row.get('execution_time_ms') or 0) for row in script_rows
                )
                update_data = {
                    'status': status,
                    'success': status == 'completed',
                    'completed_at': completed_at,
                    'execution_time_ms': execution_time_ms,
                    'updated_at': now.isoformat(),
                }
            elif (now - started_at).total_seconds() <= silence_limit:
                continue  # unfinished and younger than the limit: nothing to judge
            else:
                stamps = [started_at] + [
                    ts for row in script_rows
                    for ts in (_parse_ts(row.get('started_at')),
                               _parse_ts(row.get('completed_at')),
                               _parse_ts(row.get('updated_at')))
                    if ts is not None
                ]
                last_activity = max(stamps)
                silent_seconds = (now - last_activity).total_seconds()
                if silent_seconds <= silence_limit:
                    continue  # scripts are still reporting: the worker is alive
                succeeded = sum(
                    1 for row in script_rows if row.get('success') or row.get('skipped')
                )
                update_data = {
                    'status': 'aborted',
                    'success': False,
                    'completed_at': last_activity.isoformat(),
                    'error_message': (
                        f'Campaign execution abandoned: no activity for '
                        f'{int(silent_seconds // 60)} min (limit {int(silence_limit // 60)} min); '
                        f'{len(script_rows)} of {expected_scripts} expected script results recorded, '
                        f'{succeeded} succeeded'
                    ),
                    'updated_at': now.isoformat(),
                }

            result = (
                supabase.table('campaign_executions')
                .update(update_data)
                .eq('team_id', team_id)
                .eq('id', campaign_id)
                .eq('status', 'running')
                .execute()
            )
            if result.data:
                reconciled += 1

        if reconciled:
            print(
                f"[@db:campaign_executions:reconcile] Reconciled "
                f"{reconciled} stale campaign execution(s) for team {team_id}"
            )
        return reconciled
    except Exception as e:
        print(f"[@db:campaign_executions:reconcile] Error: {e}")
        return 0


def get_campaign_execution_with_scripts(campaign_execution_id: str) -> Optional[Dict]:
    """Get campaign execution with all linked script results."""
    try:
        supabase = get_supabase()
        
        # First get the campaign execution
        campaign_result = supabase.table('campaign_executions').select('*').eq('campaign_execution_id', campaign_execution_id).execute()
        
        if not campaign_result.data:
            return None
            
        campaign = campaign_result.data[0]
        script_result_ids = campaign.get('script_result_ids', [])
        
        # Get all linked script results (chunked to avoid 414 URI Too Long)
        script_results = chunked_in(
            lambda chunk: supabase.table('script_results').select('*').in_('id', chunk),
            script_result_ids or [])
        
        campaign['script_results'] = script_results
        return campaign
        
    except Exception as e:
        print(f"[@db:campaign_executions:get_with_scripts] Error: {str(e)}")
        return None


def get_campaign_results(
    team_id: str,
    campaign_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    script_columns: str = '*',
    host_names: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Get campaign execution results with associated script results using JOIN.

    script_columns: optional comma-separated column list passed to the script_results
    select. Defaults to '*' to preserve existing callers; pass a slim list to cut
    payload size when only a subset of fields is needed.

    host_names: when provided, restrict campaigns to rows whose host_name is in
    this list (multi-server isolation). An empty list returns no results.
    """
    try:
        # Empty registry → no results possible from this server.
        if host_names is not None and len(host_names) == 0:
            return {
                'success': True,
                'data': []
            }

        supabase = get_supabase()

        # Repair rows whose host worker disappeared, but rarely: this read is the
        # dashboard's 20 s poll. The repair is team-scoped and uses the same client.
        now_mono = time.monotonic()
        if now_mono - _last_reconcile_by_team.get(team_id, -RECONCILE_MIN_INTERVAL_SECONDS) >= RECONCILE_MIN_INTERVAL_SECONDS:
            _last_reconcile_by_team[team_id] = now_mono
            reconcile_stale_campaign_executions(team_id)

        # Build query for campaigns
        query = supabase.table('campaign_executions').select('*').eq('team_id', team_id)

        if campaign_id:
            query = query.ilike('campaign_name', f'%{campaign_id}%')

        if status:
            query = query.eq('status', status)

        if host_names is not None:
            query = query.in_('host_name', host_names)

        # Order by most recent first and apply limit
        campaign_result = query.order('created_at', desc=True).limit(limit).execute()

        if not campaign_result.data:
            return {
                'success': True,
                'data': []
            }

        # Collect all script_result_ids across all campaigns and fetch in batched
        # bulk queries, then group in Python — avoids N+1 round-trips to Supabase.
        all_ids = []
        for campaign in campaign_result.data:
            ids = campaign.get('script_result_ids') or []
            if ids:
                all_ids.extend(ids)

        scripts_by_id: Dict[str, Any] = {}
        if all_ids:
            for s in chunked_in(
                    lambda chunk: supabase.table('script_results').select(script_columns).in_('id', chunk),
                    set(all_ids)):
                scripts_by_id[s['id']] = s

        enriched_campaigns = []
        for campaign in campaign_result.data:
            enriched_campaign = campaign.copy()
            ids = campaign.get('script_result_ids') or []
            scripts = [scripts_by_id[i] for i in ids if i in scripts_by_id]
            enriched_campaign['script_results'] = sorted(
                scripts, key=lambda x: x.get('started_at', '')
            )
            enriched_campaigns.append(enriched_campaign)

        print(f"[@db:campaign_executions:get_results] Found {len(enriched_campaigns)} campaign results "
              f"with {len(scripts_by_id)} script results in {1 + (len(set(all_ids)) + 199) // 200} queries")
        return {
            'success': True,
            'data': enriched_campaigns
        }
            
    except Exception as e:
        print(f"[@db:campaign_executions:get_results] Error: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }
