"""
Script Results Database Operations

This module provides functions for managing script execution results in the database.
Script results track validation and test script executions with reports and metrics.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import uuid4

from shared.src.lib.utils.supabase_utils import get_supabase_client

def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()

def record_script_execution_start(
    team_id: str,
    script_name: str,
    script_type: str,
    host_name: str,
    device_name: str,
    userinterface_name: Optional[str] = None,
    environment: str = 'prod',
    metadata: Optional[Dict] = None
) -> Optional[str]:
    """Record script execution start in database."""
    try:
        script_result_id = str(uuid4())

        script_data = {
            'id': script_result_id,
            'team_id': team_id,
            'script_name': script_name,
            'script_type': script_type,
            'userinterface_name': userinterface_name,
            'host_name': host_name,
            'device_name': device_name,
            'success': False,  # Will be updated on completion
            'started_at': datetime.now(timezone.utc).isoformat(),
            'completed_at': datetime.now(timezone.utc).isoformat(),  # Temporary, will be updated
            'environment': environment if environment in ('dev', 'test', 'prod') else 'prod',
            'metadata': metadata
        }
        
        print(f"[@db:script_results:record_script_execution_start] Starting script execution:")
        print(f"  - script_result_id: {script_result_id}")
        print(f"  - team_id: {team_id}")
        print(f"  - script_name: {script_name}")
        print(f"  - script_type: {script_type}")
        print(f"  - host_name: {host_name}")
        print(f"  - device_name: {device_name}")
        print(f"  - userinterface_name: {userinterface_name}")
        
        supabase = get_supabase()
        result = supabase.table('script_results').insert(script_data).execute()
        
        if result.data:
            print(f"[@db:script_results:record_script_execution_start] Success: {script_result_id}")
            return script_result_id
        else:
            print(f"[@db:script_results:record_script_execution_start] Failed")
            return None
            
    except Exception as e:
        print(f"[@db:script_results:record_script_execution_start] Error: {str(e)}")
        return None

def update_script_execution_result(
    script_result_id: str,
    success: bool,
    execution_time_ms: Optional[int] = None,
    html_report_r2_path: Optional[str] = None,
    html_report_r2_url: Optional[str] = None,
    logs_r2_path: Optional[str] = None,
    logs_r2_url: Optional[str] = None,
    error_msg: Optional[str] = None,
    metadata: Optional[Dict] = None
) -> bool:
    """Update script execution with final results."""
    try:
        update_data = {
            'success': success,
            'completed_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        
        if execution_time_ms is not None:
            update_data['execution_time_ms'] = execution_time_ms
        if html_report_r2_path:
            update_data['html_report_r2_path'] = html_report_r2_path
        if html_report_r2_url:
            update_data['html_report_r2_url'] = html_report_r2_url
        if logs_r2_path:
            update_data['logs_r2_path'] = logs_r2_path
        if logs_r2_url:
            update_data['logs_r2_url'] = logs_r2_url
        if error_msg:
            update_data['error_msg'] = error_msg
        if metadata:
            update_data['metadata'] = metadata
            print(f"[@db:script_results:update_script_execution_result] 🔍 Metadata will be stored:")
            print(f"  - metadata type: {type(metadata)}")
            print(f"  - metadata keys: {list(metadata.keys()) if isinstance(metadata, dict) else 'N/A'}")
            print(f"  - metadata value: {metadata}")
        else:
            print(f"[@db:script_results:update_script_execution_result] No metadata provided for storage")
        
        print(f"[@db:script_results:update_script_execution_result] Updating script execution:")
        print(f"  - script_result_id: {script_result_id}")
        print(f"  - success: {success}")
        print(f"  - execution_time_ms: {execution_time_ms}")
        print(f"  - html_report_r2_url: {html_report_r2_url}")
        print(f"  - logs_r2_url: {logs_r2_url}")
        print(f"  - error_msg: {error_msg}")
        
        supabase = get_supabase()
        result = supabase.table('script_results').update(update_data).eq('id', script_result_id).execute()
        
        if result.data:
            print(f"[@db:script_results:update_script_execution_result] Success")
            
            # Add to analysis queue to be processed by the agent
            try:
                from shared.src.lib.utils.redis_queue import get_queue_processor
                queue_processor = get_queue_processor()
                
                # Get script_name from the updated record
                record = result.data[0] if result.data else {}
                script_name = record.get('script_name', 'unknown')
                metadata = record.get('metadata') if isinstance(record, dict) else None
                verification_review_url = ''
                verification_review_path = ''
                if isinstance(metadata, dict):
                    verification_review_url = metadata.get('verification_review_r2_url', '')
                    verification_review_path = metadata.get('verification_review_r2_path', '')
                
                # Pass all data expects (from manager.py _build_task_message)
                queue_processor.add_script_to_queue(script_result_id, {
                    'id': script_result_id,
                    'type': 'script_result',
                    'script_name': script_name,
                    'success': success,
                    'error_msg': error_msg or 'None',
                    'execution_time_ms': execution_time_ms or 0,
                    'html_report_r2_url': html_report_r2_url or '',
                    'logs_url': logs_r2_url or '',
                    'metadata': metadata if isinstance(metadata, dict) else {},
                    'verification_review_url': verification_review_url,
                    'verification_review_path': verification_review_path
                })
                print(f"[@db:script_results:update_script_execution_result] Added to analysis queue: {script_result_id}")
            except Exception as e:
                print(f"[@db:script_results:update_script_execution_result] Warning: Failed to add to analysis queue: {e}")
            
            return True
        else:
            print(f"[@db:script_results:update_script_execution_result] Failed")
            return False
            
    except Exception as e:
        print(f"[@db:script_results:update_script_execution_result] Error: {str(e)}")
        return False

def _flatten_rerun_payload(row: Dict) -> Dict:
    """Lift the embedded deployment rerun_payload to a top-level field.

    The embed arrives as deployment_executions[].deployments.rerun_payload — a
    list, because the FK points at script_results. In practice a result row is
    written by exactly one execution, so the first non-empty payload wins. The
    embed itself is dropped so the row shape the frontend sees stays flat.
    """
    if not isinstance(row, dict):
        return row

    executions = row.pop('deployment_executions', None)
    if isinstance(executions, dict):
        executions = [executions]

    payload = None
    for execution in executions or []:
        deployment = (execution or {}).get('deployments')
        if isinstance(deployment, list):
            deployment = deployment[0] if deployment else None
        candidate = (deployment or {}).get('rerun_payload')
        if candidate:
            payload = candidate
            break

    row['rerun_payload'] = payload
    return row


def get_script_results(
    team_id: str,
    script_name: Optional[str] = None,
    script_type: Optional[str] = None,
    userinterface_name: Optional[str] = None,
    host_name: Optional[str] = None,
    include_discarded: bool = False,
    limit: int = 50,
    host_names: Optional[List[str]] = None,
    host_filter: Optional[List[str]] = None
) -> Dict:
    """Get script results with filtering.

    host_names: when provided, restrict results to rows whose host_name is in
    this list. Used by the route to scope results to hosts registered to the
    backend_server handling the request (multi-server deployment isolation).
    An empty list returns no results.

    host_filter: when provided, additionally restrict to these host_names. This
    is the active workspace's host set, applied BEFORE the `limit` so a busy
    workspace (e.g. high-frequency web checks) can't push another workspace's
    rows (e.g. STB runs on a different host) off the end of the latest-N window.
    Combined with host_names via intersection. An empty list returns no results.
    """
    try:
        print(f"[@db:script_results:get_script_results] Getting script results:")
        print(f"  - team_id: {team_id}")
        print(f"  - script_name: {script_name}")
        print(f"  - script_type: {script_type}")
        print(f"  - userinterface_name: {userinterface_name}")
        print(f"  - host_name: {host_name}")
        print(f"  - host_names (registry scope): {host_names if host_names is None else len(host_names)} hosts")
        print(f"  - include_discarded: {include_discarded}")
        print(f"  - limit: {limit}")

        # Empty registry → no results possible from this server. Same for an
        # explicit-but-empty workspace host scope (workspace allows no hosts).
        if (host_names is not None and len(host_names) == 0) or \
           (host_filter is not None and len(host_filter) == 0):
            return {
                'success': True,
                'script_results': [],
                'count': 0
            }

        supabase = get_supabase()
        # Reverse-embed the launching deployment's rerun_payload over the existing
        # deployment_executions.script_result_id FK. Deployment-launched runs
        # (RunTests, cron, campaigns) already carry a full launch config there, so
        # a result row inherits it instead of the caller re-deriving one. Rows with
        # no deployment behind them (campaign steps, direct API) embed nothing —
        # those fall back to metadata.parameters, written at record time.
        query = supabase.table('script_results').select(
            '*, deployment_executions(deployments(rerun_payload))'
        ).eq('team_id', team_id)

        # Add filters
        if script_name:
            query = query.eq('script_name', script_name)
        if script_type:
            query = query.eq('script_type', script_type)
        if userinterface_name:
            query = query.eq('userinterface_name', userinterface_name)
        if host_name:
            query = query.eq('host_name', host_name)
        if host_names is not None:
            query = query.in_('host_name', host_names)
        if host_filter is not None:
            # Workspace host scope — AND'd with the registry scope above so the
            # latest-N limit applies per-workspace, not globally.
            query = query.in_('host_name', host_filter)
        if not include_discarded:
            query = query.eq('discard', False)

        # Execute query with ordering and limit
        result = query.order('created_at', desc=True).limit(limit).execute()

        rows = [_flatten_rerun_payload(row) for row in (result.data or [])]

        print(f"[@db:script_results:get_script_results] Found {len(rows)} script results")
        return {
            'success': True,
            'script_results': rows,
            'count': len(rows)
        }
        
    except Exception as e:
        print(f"[@db:script_results:get_script_results] Error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'script_results': [],
            'count': 0
        }

def get_script_history(team_id: str, script_name: str, script_type: str, limit: int = 20) -> Dict:
    """Get execution history for a specific script."""
    try:
        print(f"[@db:script_results:get_script_history] Getting history for {script_name} ({script_type})")
        
        supabase = get_supabase()
        result = supabase.table('script_results').select('*').eq('team_id', team_id).eq('script_name', script_name).eq('script_type', script_type).eq('discard', False).order('created_at', desc=True).limit(limit).execute()
        
        print(f"[@db:script_results:get_script_history] Found {len(result.data)} history entries")
        return {
            'success': True,
            'history': result.data,
            'count': len(result.data)
        }
        
    except Exception as e:
        print(f"[@db:script_results:get_script_history] Error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'history': [],
            'count': 0
        }

def mark_script_discarded(team_id: str, script_result_id: str, discard: bool = True) -> bool:
    """Mark script result as discarded (false positive)."""
    try:
        print(f"[@db:script_results:mark_script_discarded] Marking script {script_result_id} as discarded: {discard}")
        
        supabase = get_supabase()
        result = supabase.table('script_results').update({
            'discard': discard,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }).eq('id', script_result_id).eq('team_id', team_id).execute()
        
        if result.data:
            print(f"[@db:script_results:mark_script_discarded] Success")
            return True
        else:
            print(f"[@db:script_results:mark_script_discarded] Failed - script not found")
            return False
            
    except Exception as e:
        print(f"[@db:script_results:mark_script_discarded] Error: {str(e)}")
        return False

def update_script_checked_status(team_id: str, script_result_id: str, checked: bool, check_type: str = 'manual') -> bool:
    """Update script result checked status."""
    try:
        print(f"[@db:script_results:update_script_checked_status] Updating script {script_result_id}: checked={checked}, check_type={check_type}")
        
        supabase = get_supabase()
        result = supabase.table('script_results').update({
            'checked': checked,
            'check_type': check_type,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }).eq('id', script_result_id).eq('team_id', team_id).execute()
        
        if result.data:
            print(f"[@db:script_results:update_script_checked_status] Success")
            return True
        else:
            print(f"[@db:script_results:update_script_checked_status] Failed - script not found")
            return False
            
    except Exception as e:
        print(f"[@db:script_results:update_script_checked_status] Error: {str(e)}")
        return False

def update_script_discard_status(team_id: str, script_result_id: str, discard: bool, discard_comment: Optional[str] = None, check_type: str = 'manual') -> bool:
    """Update script result discard status with optional comment append."""
    try:
        print(f"[@db:script_results:update_script_discard_status] Updating script {script_result_id}: discard={discard}")
        
        supabase = get_supabase()
        
        # Get current record to append to existing comment if needed
        current_result = supabase.table('script_results').select('discard_comment, check_type').eq('id', script_result_id).eq('team_id', team_id).execute()
        
        update_data = {
            'discard': discard,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        
        # Handle comment appending
        if discard_comment:
            existing_comment = current_result.data[0].get('discard_comment', '') if current_result.data else ''
            existing_check_type = current_result.data[0].get('check_type', '') if current_result.data else ''
            
            if existing_comment and existing_check_type == 'ai':
                # Append human comment to AI comment
                update_data['discard_comment'] = f"{existing_comment}\n\nHuman: {discard_comment}"
                update_data['check_type'] = 'ai_and_human'
            else:
                # Replace or set new comment
                update_data['discard_comment'] = discard_comment
                update_data['check_type'] = check_type
        else:
            # Just update check_type if no comment provided
            update_data['check_type'] = check_type
        
        result = supabase.table('script_results').update(update_data).eq('id', script_result_id).eq('team_id', team_id).execute()
        
        if result.data:
            print(f"[@db:script_results:update_script_discard_status] Success")
            return True
        else:
            print(f"[@db:script_results:update_script_discard_status] Failed - script not found")
            return False
            
    except Exception as e:
        print(f"[@db:script_results:update_script_discard_status] Error: {str(e)}")
        return False

def delete_script_result(team_id: str, script_result_id: str) -> bool:
    """Delete script result from shared.src.lib.utils."""
    try:
        print(f"[@db:script_results:delete_script_result] Deleting script result: {script_result_id}")
        
        supabase = get_supabase()
        result = supabase.table('script_results').delete().eq('id', script_result_id).eq('team_id', team_id).execute()
        
        if result.data:
            print(f"[@db:script_results:delete_script_result] Success")
            return True
        else:
            print(f"[@db:script_results:delete_script_result] Failed - script not found")
            return False
            
    except Exception as e:
        print(f"[@db:script_results:delete_script_result] Error: {str(e)}")
        return False

def get_script_by_id(script_id: str) -> Optional[Dict]:
    """Get a single script result by ID.
    
    Args:
        script_id: The UUID of the script result to retrieve
        
    Returns:
        Script result data dict if found, None otherwise
    """
    try:
        print(f"[@db:script_results:get_script_by_id] Getting script: {script_id}")
        
        supabase = get_supabase()
        result = supabase.table('script_results').select('*').eq('id', script_id).single().execute()
        
        if result.data:
            print(f"[@db:script_results:get_script_by_id] Found script: {result.data.get('script_name', 'Unknown')}")
            return result.data
        else:
            print(f"[@db:script_results:get_script_by_id] Script not found: {script_id}")
            return None
            
    except Exception as e:
        print(f"[@db:script_results:get_script_by_id] Error: {str(e)}")
        return None 
