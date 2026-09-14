#!/usr/bin/env python3
"""
Campaign Executions Database Operations

Simplified single-table approach for campaign tracking that links to script_results.
"""

import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from uuid import uuid4

# Add project root to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))

if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.utils.supabase_utils import get_supabase_client


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
        
        # Get all linked script results (batched to avoid 414 URI Too Long)
        script_results = []
        if script_result_ids:
            BATCH_SIZE = 50
            for i in range(0, len(script_result_ids), BATCH_SIZE):
                batch = script_result_ids[i:i + BATCH_SIZE]
                scripts_result = supabase.table('script_results').select('*').in_('id', batch).execute()
                if scripts_result.data:
                    script_results.extend(scripts_result.data)
        
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
            # 200 UUIDs ≈ 7.4KB of query string, well under typical 8KB proxy limits.
            BATCH_SIZE = 200
            unique_ids = list(set(all_ids))
            for i in range(0, len(unique_ids), BATCH_SIZE):
                batch = unique_ids[i:i + BATCH_SIZE]
                script_response = supabase.table('script_results').select(script_columns).in_('id', batch).execute()
                for s in script_response.data or []:
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
