"""
System Metrics Database Functions

Database operations for storing and retrieving system monitoring metrics.
"""

import os
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from shared.src.lib.utils.supabase_utils import get_supabase_client

# Whether each "host:capture_folder:component" stream has an open incident. Seeded from the database the
# first time a process sees the stream, so a host restart neither opens a duplicate nor forgets to resolve
# the incident a previous process opened (BUG-0960: 1 464 open rows, most of them duplicates).
_open_incidents: Dict[str, bool] = {}

STREAM_FAILING = ('stuck', 'stopped')
# Models whose video only flows once the device is paired / connected (a Tello streams while the drone is on
# and joined): a silent stream there is idle, not a failure, so it opens no incident and is not counted.
ON_DEMAND_STREAM_MODELS = ('tello',)

def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()


def _open_incident_query(supabase, host_name: str, capture_folder: str, component: str):
    return (supabase.table('system_incident').select('incident_id, detected_at')
            .eq('host_name', host_name).eq('capture_folder', capture_folder)
            .eq('component', component).in_('status', ['open', 'in_progress']))


def _sync_stream_incident(supabase, host_name: str, device_name: str, capture_folder: str,
                          component: str, status: str, now: str) -> tuple:
    """Open one incident while a stream component is stuck/stopped, resolve it once it is active again.

    Returns (created, resolved).
    """
    if status not in STREAM_FAILING and status != 'active':
        return 0, 0
    key = f"{host_name}:{capture_folder}:{component}"
    if key not in _open_incidents:
        _open_incidents[key] = bool(_open_incident_query(supabase, host_name, capture_folder, component).execute().data)

    if status in STREAM_FAILING:
        if _open_incidents[key]:
            return 0, 0
        supabase.table('system_incident').insert({
            'host_name': host_name,
            'device_id': capture_folder,  # Use capture_folder as device_id
            'device_name': device_name,
            'capture_folder': capture_folder,
            'component': component,
            'incident_type': f'{component}_failure',
            'severity': 'critical' if status == 'stopped' else 'high',
            'status': 'open',
            'detected_at': now,
            'description': f'{"FFmpeg" if component == "ffmpeg" else "Monitor"} process {status}'
        }).execute()
        _open_incidents[key] = True
        return 1, 0

    if not _open_incidents[key]:
        return 0, 0
    resolved = 0
    resolved_at = datetime.fromisoformat(now.replace('Z', '+00:00'))
    for incident in _open_incident_query(supabase, host_name, capture_folder, component).execute().data or []:
        detected_at = datetime.fromisoformat(incident['detected_at'].replace('Z', '+00:00'))
        supabase.table('system_incident').update({
            'status': 'resolved',
            'resolved_at': now,
            'total_duration_minutes': int((resolved_at - detected_at).total_seconds() / 60),
            'resolution_notes': f'Auto-resolved: {"FFmpeg" if component == "ffmpeg" else "Monitor"} recovered'
        }).eq('incident_id', incident['incident_id']).execute()
        resolved += 1
    _open_incidents[key] = False
    return 0, resolved


def process_device_incidents(device_name: str, capture_folder: str, ffmpeg_status: str, monitor_status: str,
                             host_name: str = None, device_model: str = None) -> dict:
    """Simple, fast incident processing - host knows its own status, just INSERT/UPDATE directly"""
    created = resolved = 0
    if device_model in ON_DEMAND_STREAM_MODELS:
        return {'incidents_created': 0, 'incidents_resolved': 0}
    supabase = get_supabase()
    if supabase is None:
        return {'incidents_created': 0, 'incidents_resolved': 0}
    now = datetime.now(timezone.utc).isoformat()
    for component, status in (('ffmpeg', ffmpeg_status), ('monitor', monitor_status)):
        try:
            c, r = _sync_stream_incident(supabase, host_name, device_name, capture_folder, component, status, now)
            created += c
            resolved += r
        except Exception as e:
            # Don't let incident processing break metrics storage
            print(f"⚠️ Error syncing {component} incident for {device_name}: {e}")
    return {'incidents_created': created, 'incidents_resolved': resolved}


def get_stream_status(host_name: Optional[str] = None, minutes: int = 10) -> List[Dict[str, Any]]:
    """Latest capture-stream state of every device that reported in the last ``minutes``.

    One row per (host, capture_folder): ffmpeg/monitor status, when it reported, ``state`` (running, failing,
    or idle for an on-demand model that is not streaming) and since when the open incident runs when the
    stream is failing. Hosts report once a minute.
    """
    supabase = get_supabase()
    since = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() - minutes * 60, timezone.utc).isoformat()
    query = (supabase.table('system_device_metrics')
             .select('host_name, device_name, device_model, capture_folder, ffmpeg_status, monitor_status, '
                     'ffmpeg_last_activity, timestamp')
             .gte('timestamp', since).neq('host_name', 'server'))
    if host_name:
        query = query.eq('host_name', host_name)
    latest: Dict[tuple, Dict[str, Any]] = {}
    for row in query.order('timestamp', desc=True).limit(5000).execute().data or []:
        latest.setdefault((row['host_name'], row['capture_folder']), row)

    incidents = supabase.table('system_incident').select('host_name, capture_folder, component, detected_at') \
        .in_('status', ['open', 'in_progress']).order('detected_at').limit(5000).execute().data or []
    first_open: Dict[tuple, str] = {}
    for inc in incidents:
        first_open.setdefault((inc['host_name'], inc['capture_folder']), inc['detected_at'])

    rows = []
    for key, row in sorted(latest.items()):
        down = row.get('ffmpeg_status') in STREAM_FAILING or row.get('monitor_status') in STREAM_FAILING
        state = ('idle' if row.get('device_model') in ON_DEMAND_STREAM_MODELS else 'failing') if down else 'running'
        rows.append({**row, 'state': state, 'failing_since': first_open.get(key) if state == 'failing' else None})
    return rows


def process_incidents() -> dict:
    """Process incidents by calling the database function with backend-level duplicate prevention"""
    try:
        supabase = get_supabase()
        
        # Check if Supabase client is available
        if supabase is None:
            print("❌ Supabase client is None - check environment variables")
            return {'incidents_created': 0, 'incidents_resolved': 0, 'error': 'Supabase client not available'}
        
        # Backend-level duplicate prevention: Check if we recently processed incidents
        # This prevents race conditions and excessive processing
        import time
        current_time = time.time()
        
        # Use a simple in-memory cache to prevent processing more than once per minute
        if not hasattr(process_incidents, '_last_processed'):
            process_incidents._last_processed = 0
            
        time_since_last = current_time - process_incidents._last_processed
        
        # Only process if it's been at least 30 seconds since last processing
        if time_since_last < 30:
            print(f"⏳ Incident processing skipped - last processed {time_since_last:.1f}s ago")
            return {'incidents_created': 0, 'incidents_resolved': 0, 'skipped': True}
        
        # Update last processed time
        process_incidents._last_processed = current_time
        
        result = supabase.rpc('process_incidents').execute()
        
        if result.data:
            incident_result = result.data[0] if isinstance(result.data, list) else result.data
            print(f"🚨 Incident processing: {incident_result}")
            return incident_result
        else:
            print("⚠️ No incident processing result returned (empty data)")
            return {'incidents_created': 0, 'incidents_resolved': 0}
            
    except Exception as e:
        import traceback
        print(f"❌ Error processing incidents: {type(e).__name__}: {str(e)}")
        print(f"📋 Full error details: {traceback.format_exc()}")
        
        # Try to get more details from Supabase error
        if hasattr(e, 'details'):
            print(f"🔍 Supabase error details: {e.details}")
        if hasattr(e, 'message'):
            print(f"💬 Supabase error message: {e.message}")
            
        return {'incidents_created': 0, 'incidents_resolved': 0, 'error': str(e)}


def store_system_metrics(host_name: str, metrics_data: Dict[str, Any]) -> bool:
    """Store server metrics in system_metrics table"""
    try:
        supabase = get_supabase()
        
        insert_data = {
            'host_name': host_name,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'cpu_percent': metrics_data.get('cpu_percent', 0),
            'memory_percent': metrics_data.get('memory_percent', 0),
            'disk_percent': metrics_data.get('disk_percent', 0),
            'uptime_seconds': metrics_data.get('uptime_seconds', 0),
            'platform': metrics_data.get('platform', 'unknown'),
            'architecture': metrics_data.get('architecture', 'unknown'),
            'ffmpeg_status': metrics_data.get('ffmpeg_status', {}),
            'monitor_status': metrics_data.get('monitor_status', {}),
            'ffmpeg_service_uptime_seconds': metrics_data.get('ffmpeg_service_uptime_seconds', 0),
            'monitor_service_uptime_seconds': metrics_data.get('monitor_service_uptime_seconds', 0),
            'cpu_temperature_celsius': metrics_data.get('cpu_temperature_celsius'),
            'load_average_1m': metrics_data.get('load_average_1m'),
            'load_average_5m': metrics_data.get('load_average_5m'),
            'load_average_15m': metrics_data.get('load_average_15m'),
            'download_mbps': metrics_data.get('download_mbps'),
            'upload_mbps': metrics_data.get('upload_mbps'),
            'speedtest_last_run': metrics_data.get('speedtest_last_run'),
            'speedtest_age_seconds': metrics_data.get('speedtest_age_seconds'),
            'disk_write_mb_per_sec': metrics_data.get('disk_write_mb_per_sec', 0)
        }
        
        # Add server_name only if it's provided in metrics_data (server-specific)
        if 'server_name' in metrics_data:
            insert_data['server_name'] = metrics_data['server_name']
        
        result = supabase.table('system_metrics').insert(insert_data).execute()
        
        if result.data:
            server_info = f" (server: {metrics_data.get('server_name')})" if 'server_name' in metrics_data else ""
            print(f"✅ Server metrics stored: {host_name}{server_info}")
            return True
        else:
            return False
            
    except Exception as e:
        server_info = f" (server: {metrics_data.get('server_name')})" if 'server_name' in metrics_data else ""
        print(f"❌ Error storing server metrics for {host_name}{server_info}: {e}")
        return False


def store_device_metrics(host_name: str, device_data: Dict[str, Any], system_stats: Dict[str, Any]) -> bool:
    """Store per-device metrics in system_device_metrics table"""
    try:
        supabase = get_supabase()
        
        # CRITICAL VALIDATION: Reject NULL/empty capture_folder
        capture_folder = device_data.get('capture_folder')
        if not capture_folder or capture_folder in ['unknown', 'null', None]:
            device_name = device_data.get('device_name', 'Unknown Device')
            print(f"🚫 REJECTED: Device {device_name} has invalid capture_folder: {capture_folder}")
            print(f"   Device config incomplete - skipping metrics insertion to prevent data corruption")
            return False
        
        insert_data = {
            'host_name': host_name,
            'device_id': device_data.get('device_id', 'unknown'),
            'device_name': device_data.get('device_name', 'Unknown Device'),
            'device_port': device_data.get('device_port') or 'unknown',
            'device_model': device_data.get('device_model', 'unknown'),
            'capture_folder': capture_folder,  # Already validated above
            'video_device': device_data.get('video_device', 'unknown'),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'cpu_percent': system_stats.get('cpu_percent', 0),
            'memory_percent': system_stats.get('memory_percent', 0),
            'disk_percent': system_stats.get('disk_percent', 0),
            'uptime_seconds': system_stats.get('uptime_seconds', 0),
            'platform': system_stats.get('platform', 'unknown'),
            'architecture': system_stats.get('architecture', 'unknown'),
            'cpu_temperature_celsius': system_stats.get('cpu_temperature_celsius'),
            'load_average_1m': system_stats.get('load_average_1m'),
            'load_average_5m': system_stats.get('load_average_5m'),
            'load_average_15m': system_stats.get('load_average_15m'),
            'ffmpeg_status': device_data.get('ffmpeg_status', 'unknown'),
            'ffmpeg_uptime_seconds': device_data.get('ffmpeg_uptime_seconds', 0),
            'ffmpeg_last_activity': device_data.get('ffmpeg_last_activity'),
            'monitor_status': device_data.get('monitor_status', 'unknown'),
            'monitor_uptime_seconds': device_data.get('monitor_uptime_seconds', 0),
            'monitor_last_activity': device_data.get('monitor_last_activity'),
            'disk_usage_capture': device_data.get('disk_usage')
        }
        
        result = supabase.table('system_device_metrics').insert(insert_data).execute()
        
        if result.data:
            print(f"✅ Device metrics stored: {device_data.get('device_name', 'Unknown')} ({device_data.get('capture_folder', 'unknown')})")
            
            # Process incidents for THIS device only (fast, non-blocking)
            try:
                incident_result = process_device_incidents(device_data.get('device_name'), device_data.get('capture_folder'), device_data.get('ffmpeg_status'), device_data.get('monitor_status'), host_name, device_data.get('device_model'))
                if incident_result.get('incidents_created', 0) > 0 or incident_result.get('incidents_resolved', 0) > 0:
                    print(f"🚨 Device incidents: +{incident_result.get('incidents_created', 0)} created, +{incident_result.get('incidents_resolved', 0)} resolved")
            except Exception as e:
                print(f"⚠️ Error processing device incidents: {e}")
            
            return True
        else:
            return False
            
    except Exception as e:
        print(f"❌ Error storing device metrics: {e}")
        return False


def get_system_metrics(host_name: Optional[str] = None, 
                      hours: int = 24) -> List[Dict[str, Any]]:
    """
    Retrieve system metrics from the database
    
    Args:
        host_name: Optional host name filter
        hours: Number of hours of data to retrieve (default: 24)
    
    Returns:
        List of system metrics records
    """
    try:
        supabase = get_supabase()
        
        # Build query
        query = supabase.table('system_metrics').select('*')
        
        if host_name:
            query = query.eq('host_name', host_name)
        
        # Filter by time range (last N hours)
        from datetime import timedelta
        cutoff_time = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        query = query.gte('timestamp', cutoff_time)
        
        # Order by timestamp descending
        query = query.order('timestamp', desc=True)
        
        # Limit to reasonable number of records
        query = query.limit(1000)
        
        result = query.execute()
        
        if result.data:
            return result.data
        else:
            return []
            
    except Exception as e:
        print(f"❌ [METRICS] Error retrieving system metrics: {e}")
        return []


def get_oldest_disk_sample(host_name: str, hours: int) -> Optional[Dict[str, Any]]:
    """Oldest {timestamp, disk_percent} row of a host within the last `hours`; None without one (disk trend, TASK-156)."""
    try:
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        result = (get_supabase().table('system_metrics').select('timestamp,disk_percent')
                  .eq('host_name', host_name).gte('timestamp', cutoff)
                  .order('timestamp', desc=False).limit(1).execute())
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"❌ [METRICS] Error reading oldest disk sample for {host_name}: {e}")
        return None


def get_latest_system_metrics(host_name: str) -> Optional[Dict[str, Any]]:
    """
    Get the latest system metrics for a specific host
    
    Args:
        host_name: Name of the host
    
    Returns:
        Latest metrics record or None
    """
    try:
        supabase = get_supabase()
        
        result = supabase.table('system_metrics')\
            .select('*')\
            .eq('host_name', host_name)\
            .order('timestamp', desc=True)\
            .limit(1)\
            .execute()
        
        if result.data and len(result.data) > 0:
            return result.data[0]
        else:
            return None
            
    except Exception as e:
        print(f"❌ [METRICS] Error retrieving latest metrics for {host_name}: {e}")
        return None


def cleanup_old_metrics(days: int = 7) -> bool:
    """
    Clean up old system metrics data
    
    Args:
        days: Number of days to keep (default: 7)
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        supabase = get_supabase()
        
        # Calculate cutoff date
        from datetime import timedelta
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        
        # Delete old records
        result = supabase.table('system_metrics')\
            .delete()\
            .lt('timestamp', cutoff_date)\
            .execute()
        
        print(f"✅ [METRICS] Cleaned up metrics older than {days} days")
        return True
        
    except Exception as e:
        print(f"❌ [METRICS] Error cleaning up old metrics: {e}")
        return False
