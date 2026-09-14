"""
Database operations for zap_results table
"""

from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from shared.src.lib.utils.supabase_utils import get_supabase_client


def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()


def record_zap_iteration(
    script_result_id: Optional[str],  # ✅ Now nullable for automatic zapping
    team_id: str,
    host_name: str,
    device_name: str,
    device_model: str,
    userinterface_name: str,
    iteration_index: int,
    action_command: str,
    started_at: datetime,
    completed_at: datetime,
    duration_seconds: float,
    motion_detected: bool = False,
    subtitles_detected: bool = False,
    audio_speech_detected: bool = False,
    blackscreen_freeze_detected: bool = False,
    subtitle_language: Optional[str] = None,
    subtitle_text: Optional[str] = None,
    audio_language: Optional[str] = None,
    audio_transcript: Optional[str] = None,
    blackscreen_freeze_duration_seconds: Optional[float] = None,
    transition_type: Optional[str] = None,  # 'freeze' | 'blackscreen' — type of zap transition
    detection_method: Optional[str] = None,
    channel_name: Optional[str] = None,
    channel_number: Optional[str] = None,
    program_name: Optional[str] = None,
    program_start_time: Optional[str] = None,
    program_end_time: Optional[str] = None,
    audio_silence_duration: Optional[float] = None,  # ✅ Audio silence duration during zapping
    action_params: Optional[Dict[str, Any]] = None,  # ✅ Action parameters (e.g., {"key": "CHANNEL_UP"})
    time_since_action_ms: Optional[int] = None,  # ✅ NEW: Time from action to blackscreen end
    total_zap_duration_ms: Optional[int] = None,  # ✅ NEW: Total zap duration
    report_url: Optional[str] = None  # ✅ NEW: Per-event zap report URL (R2)
) -> Optional[str]:
    """
    Record a single zap iteration result in database.
    
    Args:
        script_result_id: UUID of parent script execution. 
                         Can be None for automatic zapping detection during monitoring.
        ... (other args)
    """
    try:
        # Let Supabase auto-generate ID (gen_random_uuid() default)
        # Don't include 'id' in insert - database will handle it
        zap_data = {
            'script_result_id': script_result_id,
            'team_id': team_id,
            'host_name': host_name,
            'device_name': device_name,
            'device_model': device_model,
            'userinterface_name': userinterface_name,
            'execution_date': datetime.now(timezone.utc).isoformat(),
            'iteration_index': iteration_index,
            'action_command': action_command,
            'action_params': action_params,  # ✅ Action parameters
            'started_at': started_at.isoformat(),
            'completed_at': completed_at.isoformat(),
            'duration_seconds': duration_seconds,
            'motion_detected': motion_detected,
            'subtitles_detected': subtitles_detected,
            'audio_speech_detected': audio_speech_detected,
            'blackscreen_freeze_detected': blackscreen_freeze_detected,
            'subtitle_language': subtitle_language,
            'subtitle_text': subtitle_text,
            'audio_language': audio_language,
            'audio_transcript': audio_transcript,
            'blackscreen_freeze_duration_seconds': blackscreen_freeze_duration_seconds,
            'transition_type': transition_type,  # 'freeze' | 'blackscreen'
            'detection_method': detection_method,
            'channel_name': channel_name,
            'channel_number': channel_number,
            'program_name': program_name,
            'program_start_time': program_start_time,
            'program_end_time': program_end_time,
            'audio_silence_duration': audio_silence_duration,  # ✅ Audio silence tracking
            'time_since_action_ms': time_since_action_ms,  # ✅ NEW: Time from action to blackscreen end
            'total_zap_duration_ms': total_zap_duration_ms,  # ✅ NEW: Total zap duration
            'report_url': report_url  # ✅ NEW: Per-event zap report URL (R2)
        }
        
        print(f"[@db:zap_results:record_zap_iteration] Recording zap iteration:")
        print(f"  - script_result_id: {script_result_id}")
        print(f"  - userinterface: {userinterface_name}")
        print(f"  - iteration: {iteration_index}")
        print(f"  - action: {action_command}")
        print(f"  - started_at: {started_at.isoformat()}")
        print(f"  - completed_at: {completed_at.isoformat()}")
        print(f"  - duration: {duration_seconds}s")
        print(f"  - motion: {motion_detected}, subtitles: {subtitles_detected}, audio: {audio_speech_detected}, blackscreen/freeze: {blackscreen_freeze_detected}")
        print(f"  - channel_name: '{channel_name}', channel_number: '{channel_number}', program_name: '{program_name}'")
        print(f"  - program_start_time: '{program_start_time}', program_end_time: '{program_end_time}'")
        
        supabase = get_supabase()
        result = supabase.table('zap_results').insert(zap_data).execute()
        
        if result.data and len(result.data) > 0:
            # Get auto-generated ID from database response
            generated_id = result.data[0].get('id')
            print(f"[@db:zap_results:record_zap_iteration] Success: {generated_id}")
            return generated_id
        else:
            print(f"[@db:zap_results:record_zap_iteration] Failed")
            return None
            
    except Exception as e:
        print(f"[@db:zap_results:record_zap_iteration] ❌ ERROR: {str(e)}")
        print(f"[@db:zap_results:record_zap_iteration] Error type: {type(e).__name__}")
        
        # Log full error details for debugging
        if hasattr(e, 'code'):
            print(f"[@db:zap_results:record_zap_iteration] Error code: {e.code}")
        if hasattr(e, 'message'):
            print(f"[@db:zap_results:record_zap_iteration] Error message: {e.message}")
        if hasattr(e, 'details'):
            print(f"[@db:zap_results:record_zap_iteration] Error details: {e.details}")
        
        # Log the data we tried to insert (for debugging conflicts)
        print(f"[@db:zap_results:record_zap_iteration] Data attempted:")
        print(f"  - device_name: {zap_data.get('device_name')}")
        print(f"  - host_name: {zap_data.get('host_name')}")
        print(f"  - started_at: {zap_data.get('started_at')}")
        print(f"  - completed_at: {zap_data.get('completed_at')}")
        print(f"  - action_command: {zap_data.get('action_command')}")
        print(f"  - detection_method: {zap_data.get('detection_method')}")
        
        import traceback
        traceback.print_exc()
        return None


def get_zap_results(
    team_id: str,
    script_result_id: Optional[str] = None,
    host_name: Optional[str] = None,
    device_name: Optional[str] = None,
    limit: int = 100
) -> Dict[str, Any]:
    """Get zap results with filtering."""
    try:
        print(f"[@db:zap_results:get_zap_results] Getting zap results:")
        print(f"  - team_id: {team_id}")
        print(f"  - script_result_id: {script_result_id}")
        print(f"  - host_name: {host_name}")
        print(f"  - device_name: {device_name}")
        print(f"  - limit: {limit}")
        
        supabase = get_supabase()
        query = supabase.table('zap_results').select('*').eq('team_id', team_id)
        
        # Add filters
        if script_result_id:
            query = query.eq('script_result_id', script_result_id)
        if host_name:
            query = query.eq('host_name', host_name)
        if device_name:
            query = query.eq('device_name', device_name)
        
        # Execute query with ordering and limit
        result = query.order('execution_date', desc=True).order('iteration_index', desc=False).limit(limit).execute()
        
        print(f"[@db:zap_results:get_zap_results] Found {len(result.data)} zap results")
        return {
            'success': True,
            'zap_results': result.data,
            'count': len(result.data)
        }
        
    except Exception as e:
        print(f"[@db:zap_results:get_zap_results] Error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'zap_results': [],
            'count': 0
        }


def get_zap_summary_for_script(script_result_id: str) -> Dict[str, Any]:
    """Get zap summary data for generating summary table."""
    try:
        print(f"[@db:zap_results:get_zap_summary_for_script] Getting summary for script: {script_result_id}")
        
        supabase = get_supabase()
        result = supabase.table('zap_results').select('*').eq('script_result_id', script_result_id).order('iteration_index', desc=False).execute()
        
        if result.data:
            print(f"[@db:zap_results:get_zap_summary_for_script] Found {len(result.data)} zap iterations")
            return {
                'success': True,
                'zap_iterations': result.data,
                'count': len(result.data)
            }
        else:
            print(f"[@db:zap_results:get_zap_summary_for_script] No zap results found")
            return {
                'success': True,
                'zap_iterations': [],
                'count': 0
            }
            
    except Exception as e:
        print(f"[@db:zap_results:get_zap_summary_for_script] Error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'zap_iterations': [],
            'count': 0
        }
