"""
System Metrics Database Functions

Database operations for storing and retrieving system monitoring metrics.
"""

import os
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from shared.src.lib.utils.supabase_utils import get_supabase_client

# Simple cache to track existing open incidents and avoid 409 conflicts
_open_incidents = set()

def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()


def process_device_incidents(device_name: str, capture_folder: str, ffmpeg_status: str, monitor_status: str, host_name: str = None) -> dict:
    """Simple, fast incident processing - host knows its own status, just INSERT/UPDATE directly"""
    try:
        supabase = get_supabase()
        if supabase is None:
            return {'incidents_created': 0, 'incidents_resolved': 0}
        
        incidents_created = 0
        incidents_resolved = 0
        current_time = datetime.now(timezone.utc).isoformat()
        
        # FFmpeg incident handling
        ffmpeg_key = f"{host_name}:{capture_folder}:ffmpeg"
        if ffmpeg_status in ['stuck', 'stopped']:
            # Check cache first to avoid 409 conflicts
            if ffmpeg_key not in _open_incidents:
                try:
                    incident_data = {
                        'host_name': host_name,
                        'device_id': capture_folder,  # Use capture_folder as device_id
                        'device_name': device_name,
                        'capture_folder': capture_folder,
                        'component': 'ffmpeg',
                        'incident_type': 'ffmpeg_failure',
                        'severity': 'critical' if ffmpeg_status == 'stopped' else 'high',
                        'status': 'open',
                        'detected_at': current_time,
                        'description': f'FFmpeg process {ffmpeg_status}'
                    }
                    result = supabase.table('system_incident').insert(incident_data).execute()
                    if result.data:
                        incidents_created += 1
                        _open_incidents.add(ffmpeg_key)  # Cache the incident
                except:
                    pass  # Incident already exists, that's fine
                
        elif ffmpeg_status == 'active':
            # UPDATE any open FFmpeg incidents to resolved with duration calculation
            if ffmpeg_key in _open_incidents:
                try:
                    # First get the open incidents to calculate duration
                    open_incidents = supabase.table('system_incident').select('incident_id, detected_at').eq('device_name', device_name).eq('capture_folder', capture_folder).eq('component', 'ffmpeg').in_('status', ['open', 'in_progress']).execute()
                    
                    if open_incidents.data:
                        for incident in open_incidents.data:
                            # Calculate duration in minutes
                            detected_at = datetime.fromisoformat(incident['detected_at'].replace('Z', '+00:00'))
                            resolved_at = datetime.fromisoformat(current_time.replace('Z', '+00:00'))
                            duration_minutes = int((resolved_at - detected_at).total_seconds() / 60)
                            
                            # Update with duration
                            supabase.table('system_incident').update({
                                'status': 'resolved',
                                'resolved_at': current_time,
                                'total_duration_minutes': duration_minutes,
                                'resolution_notes': 'Auto-resolved: FFmpeg recovered'
                            }).eq('incident_id', incident['incident_id']).execute()
                            
                            incidents_resolved += 1
                        _open_incidents.discard(ffmpeg_key)  # Remove from cache
                except Exception as e:
                    print(f"⚠️ Error resolving FFmpeg incident: {e}")
                    pass
        
        # Monitor incident handling  
        monitor_key = f"{host_name}:{capture_folder}:monitor"
        if monitor_status in ['stuck', 'stopped']:
            # Check cache first to avoid 409 conflicts
            if monitor_key not in _open_incidents:
                try:
                    incident_data = {
                        'host_name': host_name,
                        'device_id': capture_folder,  # Use capture_folder as device_id
                        'device_name': device_name,
                        'capture_folder': capture_folder,
                        'component': 'monitor',
                        'incident_type': 'monitor_failure',
                        'severity': 'critical' if monitor_status == 'stopped' else 'high',
                        'status': 'open',
                        'detected_at': current_time,
                        'description': f'Monitor process {monitor_status}'
                    }
                    result = supabase.table('system_incident').insert(incident_data).execute()
                    if result.data:
                        incidents_created += 1
                        _open_incidents.add(monitor_key)  # Cache the incident
                except:
                    pass  # Incident already exists, that's fine
                
        elif monitor_status == 'active':
            # UPDATE any open Monitor incidents to resolved with duration calculation
            if monitor_key in _open_incidents:
                try:
                    # First get the open incidents to calculate duration
                    open_incidents = supabase.table('system_incident').select('incident_id, detected_at').eq('device_name', device_name).eq('capture_folder', capture_folder).eq('component', 'monitor').in_('status', ['open', 'in_progress']).execute()
                    
                    if open_incidents.data:
                        for incident in open_incidents.data:
                            # Calculate duration in minutes
                            detected_at = datetime.fromisoformat(incident['detected_at'].replace('Z', '+00:00'))
                            resolved_at = datetime.fromisoformat(current_time.replace('Z', '+00:00'))
                            duration_minutes = int((resolved_at - detected_at).total_seconds() / 60)
                            
                            # Update with duration
                            supabase.table('system_incident').update({
                                'status': 'resolved',
                                'resolved_at': current_time,
                                'total_duration_minutes': duration_minutes,
                                'resolution_notes': 'Auto-resolved: Monitor recovered'
                            }).eq('incident_id', incident['incident_id']).execute()
                            
                            incidents_resolved += 1
                        _open_incidents.discard(monitor_key)  # Remove from cache
                except Exception as e:
                    print(f"⚠️ Error resolving Monitor incident: {e}")
                    pass
        
        return {'incidents_created': incidents_created, 'incidents_resolved': incidents_resolved}
        
    except Exception as e:
        # Don't let incident processing break metrics storage
        return {'incidents_created': 0, 'incidents_resolved': 0}


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
                incident_result = process_device_incidents(device_data.get('device_name'), device_data.get('capture_folder'), device_data.get('ffmpeg_status'), device_data.get('monitor_status'), host_name)
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
