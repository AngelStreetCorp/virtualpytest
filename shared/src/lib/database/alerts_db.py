"""
Alerts Database Operations

This module provides functions for managing alerts in the database.
Alerts track monitoring incidents with start/end times and device information.
"""

import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from uuid import uuid4

from shared.src.lib.utils.supabase_utils import get_supabase_client

def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()


def _alert_log(message: str) -> None:
    """Print alert log lines with explicit UTC timestamp."""
    ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
    print(f"[{ts}] {message}")

def get_all_alerts(
    host_name: Optional[str] = None,
    device_id: Optional[str] = None,
    incident_type: Optional[str] = None,
    active_limit: int = 100,
    resolved_limit: int = 100
) -> Dict:
    """Get all alerts (both active and resolved) with optional filtering.
    
    OPTIMIZED: Splits into 2 separate queries (active + resolved) for better performance.
    Uses indexes on (status, start_time) for fast queries.
    """
    try:
        print(f"[@db:alerts:get_all_alerts] Getting alerts with split queries:")
        print(f"  - host_name: {host_name}")
        print(f"  - device_id: {device_id}")
        print(f"  - incident_type: {incident_type}")
        print(f"  - active_limit: {active_limit}")
        print(f"  - resolved_limit: {resolved_limit}")
        
        supabase = get_supabase()
        
        # Query 1: Get active alerts (typically very few - 8 total)
        active_query = supabase.table('alerts').select('*').eq('status', 'active')
        
        # Add filters to active query
        if host_name:
            active_query = active_query.eq('host_name', host_name)
        if device_id:
            active_query = active_query.eq('device_id', device_id)
        if incident_type:
            active_query = active_query.eq('incident_type', incident_type)
        
        # Execute active query - uses idx_alerts_status_start_time index
        active_result = active_query.order('start_time', desc=True).limit(active_limit).execute()
        active_alerts = active_result.data
        print(f"  - Found {len(active_alerts)} active alerts")
        
        # Query 2: Get resolved alerts (many more, but indexed)
        resolved_query = supabase.table('alerts').select('*').eq('status', 'resolved')
        
        # Add filters to resolved query
        if host_name:
            resolved_query = resolved_query.eq('host_name', host_name)
        if device_id:
            resolved_query = resolved_query.eq('device_id', device_id)
        if incident_type:
            resolved_query = resolved_query.eq('incident_type', incident_type)
        
        # Execute resolved query - uses idx_alerts_status_start_time index
        resolved_result = resolved_query.order('start_time', desc=True).limit(resolved_limit).execute()
        resolved_alerts = resolved_result.data
        print(f"  - Found {len(resolved_alerts)} resolved alerts")
        
        # Combine and sort by start_time desc
        all_alerts = active_alerts + resolved_alerts
        all_alerts.sort(key=lambda x: x['start_time'], reverse=True)
        
        print(f"[@db:alerts:get_all_alerts] Total: {len(all_alerts)} alerts ({len(active_alerts)} active, {len(resolved_alerts)} resolved)")
        
        return {
            'success': True,
            'alerts': all_alerts,
            'count': len(all_alerts),
            'active_count': len(active_alerts),
            'resolved_count': len(resolved_alerts)
        }
        
    except Exception as e:
        print(f"[@db:alerts:get_all_alerts] Error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'alerts': [],
            'count': 0,
            'active_count': 0,
            'resolved_count': 0
        }

def get_active_alerts(
    host_name: Optional[str] = None,
    device_id: Optional[str] = None,
    incident_type: Optional[str] = None,
    limit: int = 100
) -> Dict:
    """Get active alerts with filtering and deduplication.
    
    Ensures only the most recent active alert per host/device/incident_type combination.
    """
    try:
        print(f"[@db:alerts:get_active_alerts] Getting active alerts:")
        print(f"  - host_name: {host_name}")
        print(f"  - device_id: {device_id}")
        print(f"  - incident_type: {incident_type}")
        print(f"  - limit: {limit}")
        
        supabase = get_supabase()
        query = supabase.table('alerts').select('*').eq('status', 'active')
        
        # Add filters
        if host_name:
            query = query.eq('host_name', host_name)
            print(f"  - Applied host_name filter: {host_name}")
        if device_id:
            query = query.eq('device_id', device_id)
            print(f"  - Applied device_id filter: {device_id}")
        if incident_type:
            query = query.eq('incident_type', incident_type)
            print(f"  - Applied incident_type filter: {incident_type}")
        
        # Execute query with ordering and limit
        result = query.order('start_time', desc=True).limit(limit).execute()
        
        # Post-process to remove duplicates (keep most recent per host/device/incident_type)
        alerts = result.data
        unique_alerts = {}
        
        for alert in alerts:
            key = f"{alert['host_name']}-{alert['device_id']}-{alert['incident_type']}"
            
            if key not in unique_alerts:
                unique_alerts[key] = alert
            else:
                # Keep the one with the most recent start_time
                existing_time = unique_alerts[key]['start_time']
                current_time = alert['start_time']
                
                if current_time > existing_time:
                    unique_alerts[key] = alert
                    print(f"  - Replaced duplicate active alert for {key} with more recent one")
        
        # Convert back to list and sort by start_time desc
        final_alerts = list(unique_alerts.values())
        final_alerts.sort(key=lambda x: x['start_time'], reverse=True)
        
        print(f"[@db:alerts:get_active_alerts] Found {len(final_alerts)} unique active alerts (removed {len(alerts) - len(final_alerts)} duplicates)")
        
        return {
            'success': True,
            'alerts': final_alerts,
            'count': len(final_alerts)
        }
        
    except Exception as e:
        print(f"[@db:alerts:get_active_alerts] Error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'alerts': [],
            'count': 0
        }

def get_closed_alerts(
    host_name: Optional[str] = None,
    device_id: Optional[str] = None,
    incident_type: Optional[str] = None,
    limit: int = 100
) -> Dict:
    """Get closed/resolved alerts with filtering."""
    try:
        print(f"[@db:alerts:get_closed_alerts] Getting closed alerts:")
        print(f"  - host_name: {host_name}")
        print(f"  - device_id: {device_id}")
        print(f"  - incident_type: {incident_type}")
        print(f"  - limit: {limit}")
        
        supabase = get_supabase()
        query = supabase.table('alerts').select('*').eq('status', 'resolved')
        
        # Add filters
        if host_name:
            query = query.eq('host_name', host_name)
        if device_id:
            query = query.eq('device_id', device_id)
        if incident_type:
            query = query.eq('incident_type', incident_type)
        
        # Execute query with ordering and limit
        result = query.order('end_time', desc=True).limit(limit).execute()
        
        print(f"[@db:alerts:get_closed_alerts] Found {len(result.data)} closed alerts")
        return {
            'success': True,
            'alerts': result.data,
            'count': len(result.data)
        }
        
    except Exception as e:
        print(f"[@db:alerts:get_closed_alerts] Error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'alerts': [],
            'count': 0
        }

def create_alert(
    host_name: str,
    device_id: str,
    incident_type: str,
    consecutive_count: int = 3,
    metadata: Optional[Dict] = None,
    device_name: Optional[str] = None
) -> Dict:
    """Create a new alert in the database."""
    try:
        alert_id = str(uuid4())
        
        alert_data = {
            'id': alert_id,
            'host_name': host_name,
            'device_id': device_id,
            'device_name': device_name,
            'incident_type': incident_type,
            'status': 'active',
            'consecutive_count': consecutive_count,
            'start_time': datetime.now(timezone.utc).isoformat(),
            'metadata': metadata or {}
        }
        
        _alert_log(f"[@db:alerts:create_alert] Creating alert:")
        _alert_log(f"  - alert_id: {alert_id}")
        _alert_log(f"  - host_name: {host_name}")
        _alert_log(f"  - device_id: {device_id}")
        _alert_log(f"  - device_name: {device_name}")
        _alert_log(f"  - incident_type: {incident_type}")
        _alert_log(f"  - consecutive_count: {consecutive_count}")
        
        supabase = get_supabase()
        result = supabase.table('alerts').insert(alert_data).execute()
        
        if result.data:
            _alert_log(f"[@db:alerts:create_alert] Success: {alert_id}")
            
            # Add to analysis queue for Nightwatch/Sherlock to process
            # Include FULL alert data so AI can analyze without DB lookup
            try:
                from shared.src.lib.utils.redis_queue import get_queue_processor
                queue_processor = get_queue_processor()
                queue_processor.add_alert_to_queue(alert_id, {
                    **alert_data,  # Full alert: host_name, device_id, incident_type, metadata, etc.
                    'alert_type': incident_type,  # Alias for handler compatibility
                })
                _alert_log(f"[@db:alerts:create_alert] Added to analysis queue: {alert_id}")
            except Exception as e:
                _alert_log(f"[@db:alerts:create_alert] Warning: Failed to add to analysis queue: {e}")
            
            return {
                'success': True,
                'alert_id': alert_id,
                'alert': result.data[0]
            }
        else:
            _alert_log(f"[@db:alerts:create_alert] Failed")
            return {
                'success': False,
                'error': 'No data returned from database'
            }
            
    except Exception as e:
        _alert_log(f"[@db:alerts:create_alert] Error: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }

def resolve_alert(alert_id: str, closure_metadata: Dict = None) -> Dict:
    """Resolve an alert by setting status to resolved and end_time.
    
    Args:
        alert_id: Alert ID to resolve
        closure_metadata: Optional dict with closure data (e.g., closure image URLs)
    """
    try:
        _alert_log(f"[@db:alerts:resolve_alert] Resolving alert: {alert_id}")
        
        supabase = get_supabase()
        
        # First get the alert to check start_time and metadata
        alert_result = supabase.table('alerts').select('start_time, metadata').eq('id', alert_id).execute()
        if not alert_result.data:
            return {
                'success': False,
                'error': 'Alert not found'
            }
        
        start_time = alert_result.data[0]['start_time']
        existing_metadata = alert_result.data[0].get('metadata', {})
        end_time = datetime.now(timezone.utc).isoformat()
        
        # Ensure end_time is not before start_time
        start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        end_dt = datetime.now(timezone.utc)
        
        if end_dt < start_dt:
            _alert_log(f"[@db:alerts:resolve_alert] Warning: end_time would be before start_time, using start_time + 1 second")
            end_time = (start_dt + timedelta(seconds=1)).isoformat()
        
        # Merge closure metadata into existing metadata
        update_data = {
            'status': 'resolved',
            'end_time': end_time
        }
        
        if closure_metadata:
            # Merge r2_images if provided
            if 'r2_images' in closure_metadata:
                if 'r2_images' in existing_metadata:
                    # Merge with existing r2_images
                    existing_metadata['r2_images'].update(closure_metadata['r2_images'])
                else:
                    existing_metadata['r2_images'] = closure_metadata['r2_images']
            
            update_data['metadata'] = existing_metadata
            _alert_log(f"[@db:alerts:resolve_alert] Updated metadata with closure data")
        
        result = supabase.table('alerts').update(update_data).eq('id', alert_id).execute()
        
        if result.data:
            _alert_log(f"[@db:alerts:resolve_alert] Success: {alert_id}")
            return {
                'success': True,
                'alert': result.data[0]
            }
        else:
            _alert_log(f"[@db:alerts:resolve_alert] Failed: {alert_id}")
            return {
                'success': False,
                'error': 'Alert not found or already resolved'
            }
            
    except Exception as e:
        _alert_log(f"[@db:alerts:resolve_alert] Error: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        } 

def get_active_alert_for_incident(
    host_name: str,
    device_id: str,
    incident_type: str
) -> Dict:
    """Get active alert for specific host/device/incident_type combination."""
    try:
        _alert_log(f"[@db:alerts:get_active_alert_for_incident] Checking for existing active alert:")
        _alert_log(f"  - host_name: {host_name}")
        _alert_log(f"  - device_id: {device_id}")
        _alert_log(f"  - incident_type: {incident_type}")
        
        supabase = get_supabase()
        result = supabase.table('alerts').select('*').eq('status', 'active').eq('host_name', host_name).eq('device_id', device_id).eq('incident_type', incident_type).execute()
        
        if result.data:
            _alert_log(f"[@db:alerts:get_active_alert_for_incident] Found existing active alert: {result.data[0]['id']}")
            return {
                'success': True,
                'alert': result.data[0]
            }
        else:
            _alert_log(f"[@db:alerts:get_active_alert_for_incident] No existing active alert found")
            return {
                'success': True,
                'alert': None
            }
        
    except Exception as e:
        _alert_log(f"[@db:alerts:get_active_alert_for_incident] Error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'alert': None
        }

def create_alert_safe(
    host_name: str,
    device_id: str,
    incident_type: str,
    consecutive_count: int = 3,
    metadata: Optional[Dict] = None,
    device_name: Optional[str] = None
) -> Dict:
    """Create a new alert safely - resolves any existing active alert first."""
    try:
        _alert_log(f"[@db:alerts:create_alert_safe] Creating alert safely:")
        _alert_log(f"  - host_name: {host_name}")
        _alert_log(f"  - device_id: {device_id}")
        _alert_log(f"  - device_name: {device_name}")
        _alert_log(f"  - incident_type: {incident_type}")
        _alert_log(f"  - consecutive_count: {consecutive_count}")
        
        # Step 1: Check for existing active alert
        existing_result = get_active_alert_for_incident(host_name, device_id, incident_type)
        
        if not existing_result['success']:
            return {
                'success': False,
                'error': f"Failed to check existing alerts: {existing_result['error']}"
            }
        
        # Step 2: Resolve existing alert if found
        if existing_result['alert']:
            existing_alert = existing_result['alert']
            existing_alert_id = existing_alert['id']
            
            _alert_log(f"[@db:alerts:create_alert_safe] Found existing active alert {existing_alert_id}, resolving it first")
            
            resolve_result = resolve_alert(existing_alert_id)
            if not resolve_result['success']:
                _alert_log(f"[@db:alerts:create_alert_safe] Warning: Failed to resolve existing alert {existing_alert_id}: {resolve_result['error']}")
                # Continue anyway - we'll let the database constraint handle it
        
        # Step 3: Create new alert
        return create_alert(host_name, device_id, incident_type, consecutive_count, metadata, device_name)
        
    except Exception as e:
        _alert_log(f"[@db:alerts:create_alert_safe] Error: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        } 

def add_unique_constraint_for_active_alerts() -> Dict:
    """Add unique constraint to prevent multiple active alerts for same host/device/incident_type.
    
    This should be called once during deployment to add the database constraint.
    """
    try:
        print("[@db:alerts:add_unique_constraint] Adding unique constraint for active alerts")
        
        supabase = get_supabase()
        
        # Create a unique partial index that only applies to active alerts
        # This allows multiple resolved alerts but only one active alert per host/device/incident_type
        constraint_sql = """
        CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS unique_active_alerts 
        ON alerts (host_name, device_id, incident_type) 
        WHERE status = 'active';
        """
        
        # Note: Supabase/PostgreSQL doesn't support direct SQL execution through the client
        # This would need to be executed manually in the database or through a migration
        print("[@db:alerts:add_unique_constraint] Constraint SQL generated:")
        print(constraint_sql)
        print("[@db:alerts:add_unique_constraint] This constraint should be applied manually to the database")
        
        return {
            'success': True,
            'constraint_sql': constraint_sql,
            'message': 'Constraint SQL generated - apply manually to database'
        }
        
    except Exception as e:
        print(f"[@db:alerts:add_unique_constraint] Error: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }

def update_alert_checked_status(alert_id: str, checked: bool, check_type: str = 'manual') -> bool:
    """Update alert checked status."""
    try:
        print(f"[@db:alerts:update_alert_checked_status] Updating alert {alert_id}: checked={checked}, check_type={check_type}")
        
        supabase = get_supabase()
        result = supabase.table('alerts').update({
            'checked': checked,
            'check_type': check_type,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }).eq('id', alert_id).execute()
        
        if result.data:
            print(f"[@db:alerts:update_alert_checked_status] Success")
            return True
        else:
            print(f"[@db:alerts:update_alert_checked_status] Failed - alert not found")
            return False
            
    except Exception as e:
        print(f"[@db:alerts:update_alert_checked_status] Error: {str(e)}")
        return False

def update_alert_discard_status(alert_id: str, discard: bool, discard_comment: Optional[str] = None, check_type: str = 'manual') -> bool:
    """Update alert discard status with optional comment append."""
    try:
        print(f"[@db:alerts:update_alert_discard_status] Updating alert {alert_id}: discard={discard}")
        
        supabase = get_supabase()
        
        # Get current record to append to existing comment if needed
        current_result = supabase.table('alerts').select('discard_comment, check_type').eq('id', alert_id).execute()
        
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
        
        result = supabase.table('alerts').update(update_data).eq('id', alert_id).execute()
        
        if result.data:
            print(f"[@db:alerts:update_alert_discard_status] Success")
            return True
        else:
            print(f"[@db:alerts:update_alert_discard_status] Failed - alert not found")
            return False
            
    except Exception as e:
        print(f"[@db:alerts:update_alert_discard_status] Error: {str(e)}")
        return False

def delete_all_alerts() -> Dict:
    """Delete all alerts from the database using efficient database function."""
    try:
        print("[@db:alerts:delete_all_alerts] Deleting all alerts from database")
        
        supabase = get_supabase()
        
        # Use database function for efficient deletion
        # This executes entirely in Postgres without returning data to client
        result = supabase.rpc('delete_all_alerts').execute()
        
        # The function returns a JSON object with success, deleted_count, and message
        if result.data is not None:
            # Handle different return types from Supabase RPC
            if isinstance(result.data, dict):
                response = result.data
            elif isinstance(result.data, list) and len(result.data) > 0:
                response = result.data[0]
            elif isinstance(result.data, str):
                # Handle string response - parse as JSON
                try:
                    response = json.loads(result.data)
                except json.JSONDecodeError:
                    print(f"[@db:alerts:delete_all_alerts] Failed to parse JSON string: {result.data}")
                    response = {}
            elif isinstance(result.data, bytes):
                # Handle bytes response - decode and parse as JSON
                try:
                    response = json.loads(result.data.decode('utf-8'))
                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    print(f"[@db:alerts:delete_all_alerts] Failed to parse bytes: {e}")
                    response = {}
            else:
                response = {}
            
            print(f"[@db:alerts:delete_all_alerts] Result: {response}")
            
            # Ensure we have a valid response structure
            if response and response.get('success'):
                return {
                    'success': True,
                    'deleted_count': response.get('deleted_count', 0),
                    'message': response.get('message', 'Alerts deleted successfully')
                }
            else:
                return {
                    'success': False,
                    'error': response.get('error', 'Unknown error during deletion'),
                    'deleted_count': 0
                }
        else:
            print("[@db:alerts:delete_all_alerts] No data returned from function")
            return {
                'success': False,
                'error': 'No data returned from delete function',
                'deleted_count': 0
            }
        
    except Exception as e:
        error_str = str(e)
        print(f"[@db:alerts:delete_all_alerts] Error: {error_str}")

        # Supabase/PostgREST sometimes throws an APIError even on success (code 200)
        # when it can't serialize the json return type. Parse the result from the error details.
        try:
            # APIError has .code and .details as direct attributes
            code = getattr(e, 'code', None)
            details = getattr(e, 'details', None)
            if code and str(code) == '200' and details:
                # Details may be a bytes-repr string like "b'{...}'"
                if isinstance(details, str) and details.startswith("b'") and details.endswith("'"):
                    details = details[2:-1]
                parsed = json.loads(details)
                if parsed.get('success'):
                    print(f"[@db:alerts:delete_all_alerts] Parsed success from error details: {parsed}")
                    return {
                        'success': True,
                        'deleted_count': parsed.get('deleted_count', 0),
                        'message': parsed.get('message', 'Alerts deleted successfully')
                    }
        except Exception:
            pass

        return {
            'success': False,
            'error': error_str,
            'deleted_count': 0
        }

def get_alert_by_id(alert_id: str) -> Optional[Dict]:
    """Get a single alert by ID.
    
    Args:
        alert_id: The UUID of the alert to retrieve
        
    Returns:
        Alert data dict if found, None otherwise
    """
    try:
        print(f"[@db:alerts:get_alert_by_id] Getting alert: {alert_id}")
        
        supabase = get_supabase()
        result = supabase.table('alerts').select('*').eq('id', alert_id).single().execute()
        
        if result.data:
            print(f"[@db:alerts:get_alert_by_id] Found alert: {result.data.get('incident_type', 'Unknown')}")
            return result.data
        else:
            print(f"[@db:alerts:get_alert_by_id] Alert not found: {alert_id}")
            return None
            
    except Exception as e:
        print(f"[@db:alerts:get_alert_by_id] Error: {str(e)}")
        return None 