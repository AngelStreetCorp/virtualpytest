"""
Resource Locks Database Operations

Sync database layer for resource locking using Supabase client.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from shared.src.lib.utils.supabase_utils import get_supabase_client

DEFAULT_TEAM_ID = 'default'


def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()


def is_resource_available(resource_id: str) -> bool:
    """Check if resource is currently available (not locked)."""
    supabase = get_supabase()
    if not supabase:
        return True  # Assume available if DB not connected
    
    now = datetime.utcnow().isoformat()
    result = supabase.table('resource_locks').select('id').eq(
        'resource_id', resource_id
    ).gt('expires_at', now).execute()
    
    return len(result.data or []) == 0


def acquire_lock(
    resource_id: str,
    resource_type: str,
    owner_id: str,
    owner_type: str = 'agent',
    timeout_seconds: int = 3600,
    priority: int = 3,
    team_id: str = DEFAULT_TEAM_ID
) -> Optional[str]:
    """
    Try to acquire lock on resource.
    
    Returns:
        Lock ID if acquired, None if resource is locked
    """
    supabase = get_supabase()
    if not supabase:
        return None
    
    # Check availability first
    if not is_resource_available(resource_id):
        return None
    
    now = datetime.utcnow()
    expires_at = now + timedelta(seconds=timeout_seconds)
    
    data = {
        'resource_id': resource_id,
        'resource_type': resource_type,
        'owner_id': owner_id,
        'owner_type': owner_type,
        'acquired_at': now.isoformat(),
        'expires_at': expires_at.isoformat(),
        'priority': priority,
        'team_id': team_id
    }
    
    try:
        result = supabase.table('resource_locks').insert(data).execute()
        if result.data:
            print(f"[@resource_locks_db] 🔒 Acquired: {resource_id} by {owner_id}")
            return result.data[0].get('id')
    except Exception as e:
        print(f"[@resource_locks_db] ❌ Failed to acquire lock: {e}")
    
    return None


def release_lock(
    resource_id: str,
    owner_id: str,
    team_id: str = DEFAULT_TEAM_ID
) -> bool:
    """Release lock on resource."""
    supabase = get_supabase()
    if not supabase:
        return False
    
    now = datetime.utcnow().isoformat()
    result = supabase.table('resource_locks').delete().eq(
        'resource_id', resource_id
    ).eq('owner_id', owner_id).eq('team_id', team_id).gt('expires_at', now).execute()
    
    if result.data:
        print(f"[@resource_locks_db] 🔓 Released: {resource_id} by {owner_id}")
        return True
    
    print(f"[@resource_locks_db] ⚠️ Cannot release: {resource_id} (not locked by {owner_id})")
    return False


def get_lock_status(
    resource_id: str,
    team_id: str = DEFAULT_TEAM_ID
) -> Dict[str, Any]:
    """Get current status of resource lock."""
    supabase = get_supabase()
    if not supabase:
        return {'status': 'available', 'owner_id': None, 'expires_at': None, 'queue_length': 0}
    
    now = datetime.utcnow().isoformat()
    
    # Check active lock
    lock_result = supabase.table('resource_locks').select(
        'owner_id, expires_at, resource_type'
    ).eq('resource_id', resource_id).gt('expires_at', now).execute()
    
    # Get queue length
    queue_result = supabase.table('resource_lock_queue').select(
        '*', count='exact'
    ).eq('resource_id', resource_id).eq('team_id', team_id).execute()
    queue_length = queue_result.count or 0
    
    if lock_result.data:
        lock = lock_result.data[0]
        return {
            'status': 'locked',
            'owner_id': lock['owner_id'],
            'expires_at': lock['expires_at'],
            'queue_length': queue_length
        }
    
    return {
        'status': 'available',
        'owner_id': None,
        'expires_at': None,
        'queue_length': queue_length
    }


def add_to_queue(
    resource_id: str,
    owner_id: str,
    priority: int,
    timeout_seconds: int,
    team_id: str = DEFAULT_TEAM_ID
) -> bool:
    """Add lock request to queue."""
    supabase = get_supabase()
    if not supabase:
        return False
    
    data = {
        'resource_id': resource_id,
        'owner_id': owner_id,
        'priority': priority,
        'timeout_seconds': timeout_seconds,
        'team_id': team_id
    }
    
    result = supabase.table('resource_lock_queue').insert(data).execute()
    
    if result.data:
        print(f"[@resource_locks_db] 📝 Queued: {resource_id} for {owner_id}")
        return True
    return False


def get_next_in_queue(
    resource_id: str,
    team_id: str = DEFAULT_TEAM_ID
) -> Optional[Dict[str, Any]]:
    """Get and remove next request from queue (highest priority, earliest)."""
    supabase = get_supabase()
    if not supabase:
        return None
    
    # Get next in queue
    result = supabase.table('resource_lock_queue').select('*').eq(
        'resource_id', resource_id
    ).eq('team_id', team_id).order('priority').order('queued_at').limit(1).execute()
    
    if not result.data:
        return None
    
    request = result.data[0]
    
    # Delete from queue
    supabase.table('resource_lock_queue').delete().eq('id', request['id']).execute()
    
    return request


def cleanup_expired_locks() -> List[Dict[str, Any]]:
    """Remove expired locks and return their info."""
    supabase = get_supabase()
    if not supabase:
        return []
    
    now = datetime.utcnow().isoformat()
    
    # Get expired locks
    result = supabase.table('resource_locks').select(
        'resource_id, owner_id'
    ).lt('expires_at', now).execute()
    
    expired = result.data or []
    
    if expired:
        # Delete expired locks
        supabase.table('resource_locks').delete().lt('expires_at', now).execute()
        print(f"[@resource_locks_db] 🧹 Cleaned up {len(expired)} expired locks")
    
    return expired

