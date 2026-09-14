"""
Agent Runtime Database Operations

Sync database layer for agent runtime using Supabase client.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
from shared.src.lib.utils.supabase_utils import get_supabase_client

DEFAULT_TEAM_ID = 'default'


def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()


def record_instance_start(
    instance_id: str,
    agent_id: str,
    version: str,
    state: str,
    team_id: str = DEFAULT_TEAM_ID
) -> bool:
    """Record agent instance start in database."""
    supabase = get_supabase()
    if not supabase:
        return False
    
    data = {
        'instance_id': instance_id,
        'agent_id': agent_id,
        'version': version,
        'state': state,
        'started_at': datetime.utcnow().isoformat(),
        'team_id': team_id
    }
    
    result = supabase.table('agent_instances').insert(data).execute()
    return bool(result.data)


def record_instance_stop(instance_id: str) -> bool:
    """Record agent instance stop in database."""
    supabase = get_supabase()
    if not supabase:
        return False
    
    result = supabase.table('agent_instances').update({
        'stopped_at': datetime.utcnow().isoformat(),
        'state': 'stopped'
    }).eq('instance_id', instance_id).execute()
    
    return bool(result.data)


def update_instance_state(
    instance_id: str,
    state: str,
    current_task: Optional[str] = None,
    task_id: Optional[str] = None
) -> bool:
    """Update agent instance state in database."""
    supabase = get_supabase()
    if not supabase:
        return False
    
    data = {
        'state': state,
        'current_task': current_task,
        'task_id': task_id,
        'last_activity': datetime.utcnow().isoformat()
    }
    
    result = supabase.table('agent_instances').update(data).eq('instance_id', instance_id).execute()
    return bool(result.data)


def record_execution_history(
    instance_id: str,
    agent_id: str,
    version: str,
    task_id: str,
    event_type: str,
    event_id: str,
    started_at: datetime,
    completed_at: datetime,
    status: str,
    team_id: str = DEFAULT_TEAM_ID,
    error_message: Optional[str] = None
) -> bool:
    """Record task execution in history."""
    supabase = get_supabase()
    if not supabase:
        return False
    
    duration = (completed_at - started_at).total_seconds()
    
    data = {
        'instance_id': instance_id,
        'agent_id': agent_id,
        'version': version,
        'task_id': task_id,
        'event_type': event_type,
        'event_id': event_id,
        'started_at': started_at.isoformat(),
        'completed_at': completed_at.isoformat(),
        'duration_seconds': duration,
        'status': status,
        'error_message': error_message,
        'team_id': team_id
    }
    
    result = supabase.table('agent_execution_history').insert(data).execute()
    return bool(result.data)


def get_instance(instance_id: str) -> Optional[Dict[str, Any]]:
    """Get agent instance by ID."""
    supabase = get_supabase()
    if not supabase:
        return None
    
    result = supabase.table('agent_instances').select('*').eq('instance_id', instance_id).execute()
    return result.data[0] if result.data else None


def list_instances(team_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all running instances."""
    supabase = get_supabase()
    if not supabase:
        return []
    
    query = supabase.table('agent_instances').select('*').is_('stopped_at', 'null')
    
    if team_id:
        query = query.eq('team_id', team_id)
    
    result = query.order('started_at', desc=True).execute()
    return result.data if result.data else []

