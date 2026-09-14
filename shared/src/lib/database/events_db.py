"""
Events Database Operations

Sync database layer for event logging using Supabase client.
"""

import json
from typing import Dict, List, Optional, Any
from datetime import datetime
from shared.src.lib.utils.supabase_utils import get_supabase_client

DEFAULT_TEAM_ID = 'default'


def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()


def log_event(
    event_id: str,
    event_type: str,
    payload: Dict[str, Any],
    priority: int,
    timestamp: datetime,
    team_id: str = DEFAULT_TEAM_ID
) -> bool:
    """Log event to database."""
    supabase = get_supabase()
    if not supabase:
        return False
    
    try:
        data = {
            'event_id': event_id,
            'event_type': event_type,
            'payload': payload,
            'priority': priority,
            'timestamp': timestamp.isoformat(),
            'team_id': team_id
        }
        
        supabase.table('event_log').insert(data).execute()
        return True
    except Exception as e:
        print(f"[@events_db] ⚠️ Failed to log event: {e}")
        return False


def get_routing_stats(team_id: str = DEFAULT_TEAM_ID) -> Dict[str, Any]:
    """Get event routing statistics for last 24 hours."""
    supabase = get_supabase()
    if not supabase:
        return {
            'total_events': 0,
            'processed_events': 0,
            'unprocessed_events': 0,
            'unique_event_types': 0,
            'avg_processing_time_seconds': 0
        }
    
    # Get counts using separate queries (Supabase doesn't support complex aggregates easily)
    result = supabase.table('event_log').select('*', count='exact').eq('team_id', team_id).execute()
    total = result.count or 0
    
    processed = supabase.table('event_log').select('*', count='exact').eq('team_id', team_id).not_.is_('processed_by', 'null').execute()
    processed_count = processed.count or 0
    
    # Get unique event types
    types_result = supabase.table('event_log').select('event_type').eq('team_id', team_id).execute()
    unique_types = len(set(r['event_type'] for r in (types_result.data or [])))
    
    return {
        'total_events': total,
        'processed_events': processed_count,
        'unprocessed_events': total - processed_count,
        'unique_event_types': unique_types,
        'avg_processing_time_seconds': 0  # Would need more complex query
    }


def get_event_types(team_id: str = DEFAULT_TEAM_ID) -> List[str]:
    """Get list of all event types seen."""
    supabase = get_supabase()
    if not supabase:
        return []
    
    result = supabase.table('event_log').select('event_type').eq('team_id', team_id).execute()
    
    if not result.data:
        return []
    
    # Get unique types
    return sorted(set(r['event_type'] for r in result.data))

