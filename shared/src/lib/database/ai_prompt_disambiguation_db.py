"""
AI Prompt Disambiguation Database Operations

Stores learned user preferences for disambiguating ambiguous navigation prompts.
Follows the same pattern as ai_analysis_cache_db.py for consistency.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from shared.src.lib.utils.supabase_utils import get_supabase_client


def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()


def get_learned_mapping(team_id: str, userinterface_name: str, user_phrase: str) -> Optional[str]:
    """
    Get learned node mapping for a specific phrase.
    
    Args:
        team_id: Team ID
        userinterface_name: UI context (e.g., "example_mobile")
        user_phrase: The ambiguous phrase (e.g., "live fullscreen")
    
    Returns:
        Resolved node name or None if not found
    """
    supabase = get_supabase()
    
    try:
        result = supabase.table('ai_prompt_disambiguation').select('resolved_node').eq(
            'team_id', team_id
        ).eq('userinterface_name', userinterface_name).eq('user_phrase', user_phrase).execute()
        
        if result.data:
            return result.data[0]['resolved_node']
    except Exception as e:
        print(f"[@ai_prompt_disambiguation_db:get_learned_mapping] Error: {e}")
    
    return None


def get_learned_mappings_batch(team_id: str, userinterface_name: str, 
                               user_phrases: List[str]) -> Dict[str, str]:
    """
    Get multiple learned mappings in one query for efficiency.
    
    Args:
        team_id: Team ID
        userinterface_name: UI context
        user_phrases: List of ambiguous phrases to lookup
    
    Returns:
        Dictionary mapping phrases to resolved nodes
        Example: {"live fullscreen": "live_fullscreen", "channel+": "channel_up"}
    """
    if not user_phrases:
        return {}
    
    supabase = get_supabase()
    
    try:
        result = supabase.table('ai_prompt_disambiguation').select(
            'user_phrase', 'resolved_node'
        ).eq('team_id', team_id).eq('userinterface_name', userinterface_name).in_(
            'user_phrase', user_phrases
        ).execute()
        
        # Return as dict for easy lookup
        return {row['user_phrase']: row['resolved_node'] for row in result.data}
    except Exception as e:
        print(f"[@ai_prompt_disambiguation_db:get_learned_mappings_batch] Error: {e}")
        return {}


def save_disambiguation(team_id: str, userinterface_name: str, 
                       user_phrase: str, resolved_node: str) -> Dict:
    """
    Save or update disambiguation mapping.
    
    If mapping already exists, increments usage_count and updates last_used_at.
    If new, creates entry with usage_count = 1.
    
    Args:
        team_id: Team ID
        userinterface_name: UI context
        user_phrase: The ambiguous phrase
        resolved_node: The node the user selected
    
    Returns:
        {'success': True/False, 'updated': True/False, 'usage_count': int}
    """
    supabase = get_supabase()
    
    try:
        # Try to find existing mapping
        existing = supabase.table('ai_prompt_disambiguation').select('id', 'usage_count').eq(
            'team_id', team_id
        ).eq('userinterface_name', userinterface_name).eq('user_phrase', user_phrase).execute()
        
        if existing.data:
            # Update existing: increment usage count, update timestamp
            mapping_id = existing.data[0]['id']
            new_count = existing.data[0]['usage_count'] + 1
            
            result = supabase.table('ai_prompt_disambiguation').update({
                'resolved_node': resolved_node,
                'usage_count': new_count,
                'last_used_at': datetime.now(timezone.utc).isoformat()
            }).eq('id', mapping_id).execute()
            
            print(f"[@ai_prompt_disambiguation_db:save] Updated: '{user_phrase}' → '{resolved_node}' (usage: {new_count})")
            return {'success': True, 'updated': True, 'usage_count': new_count}
        
        # Insert new mapping
        result = supabase.table('ai_prompt_disambiguation').insert({
            'team_id': team_id,
            'userinterface_name': userinterface_name,
            'user_phrase': user_phrase,
            'resolved_node': resolved_node,
            'usage_count': 1,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'last_used_at': datetime.now(timezone.utc).isoformat()
        }).execute()
        
        print(f"[@ai_prompt_disambiguation_db:save] Created: '{user_phrase}' → '{resolved_node}'")
        return {'success': True, 'updated': False, 'usage_count': 1}
        
    except Exception as e:
        print(f"[@ai_prompt_disambiguation_db:save] Error: {e}")
        return {'success': False, 'error': str(e)}


def delete_disambiguation(team_id: str, mapping_id: str) -> bool:
    """
    Delete a disambiguation mapping.
    
    Args:
        team_id: Team ID (for security)
        mapping_id: UUID of mapping to delete
    
    Returns:
        True if deleted, False otherwise
    """
    supabase = get_supabase()
    
    try:
        result = supabase.table('ai_prompt_disambiguation').delete().eq(
            'id', mapping_id
        ).eq('team_id', team_id).execute()
        
        if result.data:
            print(f"[@ai_prompt_disambiguation_db:delete] Deleted mapping: {mapping_id}")
            return True
        return False
    except Exception as e:
        print(f"[@ai_prompt_disambiguation_db:delete] Error: {e}")
        return False


def get_all_disambiguations(team_id: str, userinterface_name: str = None, 
                            limit: int = 100) -> List[Dict]:
    """
    Get all learned disambiguations for management UI.
    
    Args:
        team_id: Team ID
        userinterface_name: Optional filter by UI
        limit: Max number of results
    
    Returns:
        List of disambiguation records
    """
    supabase = get_supabase()
    
    try:
        query = supabase.table('ai_prompt_disambiguation').select('*').eq('team_id', team_id)
        
        if userinterface_name:
            query = query.eq('userinterface_name', userinterface_name)
        
        result = query.order('usage_count', desc=True).order(
            'last_used_at', desc=True
        ).limit(limit).execute()
        
        return [dict(row) for row in result.data]
    except Exception as e:
        print(f"[@ai_prompt_disambiguation_db:get_all] Error: {e}")
        return []


def get_disambiguation_stats(team_id: str, userinterface_name: str = None) -> Dict:
    """
    Get statistics about learned disambiguations.
    
    Args:
        team_id: Team ID
        userinterface_name: Optional filter by UI
    
    Returns:
        Dictionary with stats (total_mappings, most_used, etc.)
    """
    supabase = get_supabase()
    
    try:
        query = supabase.table('ai_prompt_disambiguation').select('id', count='exact').eq('team_id', team_id)
        
        if userinterface_name:
            query = query.eq('userinterface_name', userinterface_name)
        
        result = query.execute()
        total_mappings = result.count or 0
        
        return {
            'total_mappings': total_mappings,
            'team_id': team_id,
            'userinterface_name': userinterface_name or 'all'
        }
    except Exception as e:
        print(f"[@ai_prompt_disambiguation_db:get_stats] Error: {e}")
        return {
            'total_mappings': 0,
            'team_id': team_id,
            'userinterface_name': userinterface_name or 'all'
        }
