"""
AI Graph Cache Database Operations

Clean database operations for AI graph caching.
Stores generated graphs to avoid repeated AI calls for identical prompts.

NO legacy code, NO backward compatibility.
"""

import json
import hashlib
from typing import Dict, List, Optional, Any
from datetime import datetime


def _generate_fingerprint(prompt: str, context: Dict) -> str:
    """
    Generate unique fingerprint for prompt + context combination
    
    Args:
        prompt: User prompt (normalized)
        context: Execution context (device, interface, nodes)
        
    Returns:
        SHA-256 fingerprint (hex string)
    """
    # Normalize prompt
    prompt_normalized = prompt.lower().strip()
    
    # Create context signature
    context_signature = {
        'device_model': context.get('device_model'),
        'userinterface_name': context.get('userinterface_name'),
        'available_nodes': sorted(context.get('available_nodes', []))
    }
    
    # Generate fingerprint using SHA-256 (secure hash, prevents collision attacks)
    fingerprint_data = f"{prompt_normalized}:{json.dumps(context_signature, sort_keys=True)}"
    return hashlib.sha256(fingerprint_data.encode()).hexdigest()


def store_graph(fingerprint: str, 
                original_prompt: str,
                device_model: str,
                userinterface_name: str,
                available_nodes: List[str],
                graph: Dict,
                analysis: str,
                team_id: str) -> bool:
    """
    Store a generated graph in cache
    
    Args:
        fingerprint: Unique graph fingerprint
        original_prompt: Original user prompt
        device_model: Device model
        userinterface_name: Interface name
        available_nodes: Available navigation nodes
        graph: Generated graph dict (nodes + edges)
        analysis: AI analysis text
        team_id: Team ID
        
    Returns:
        True if stored successfully
    """
    try:
        from shared.src.lib.utils.supabase_utils import get_supabase_client
        supabase = get_supabase_client()
        
        # Normalize prompt for consistent lookups
        normalized_prompt = original_prompt.lower().strip()
        
        data = {
            'fingerprint': fingerprint,
            'original_prompt': original_prompt,
            'normalized_prompt': normalized_prompt,
            'device_model': device_model,
            'userinterface_name': userinterface_name,
            'available_nodes': json.dumps(available_nodes),
            'graph': json.dumps(graph),
            'analysis': analysis,
            'team_id': team_id,
            'use_count': 1,
            'created_at': datetime.now().isoformat(),
            'last_used': datetime.now().isoformat()
        }
        
        result = supabase.table('ai_graph_cache').insert(data).execute()
        
        if result.data:
            print(f"[@ai_graph_cache_db] ✅ Stored graph: {fingerprint[:8]}...")
            return True
        else:
            print(f"[@ai_graph_cache_db] ❌ Failed to store graph")
            return False
            
    except Exception as e:
        print(f"[@ai_graph_cache_db] ❌ Error storing graph: {e}")
        return False


def get_graph_by_fingerprint(fingerprint: str, team_id: str) -> Optional[Dict]:
    """
    Get cached graph by fingerprint
    
    Args:
        fingerprint: Graph fingerprint
        team_id: Team ID
        
    Returns:
        Graph data dict or None
    """
    try:
        from shared.src.lib.utils.supabase_utils import get_supabase_client
        supabase = get_supabase_client()
        
        result = supabase.table('ai_graph_cache')\
            .select('*')\
            .eq('fingerprint', fingerprint)\
            .eq('team_id', team_id)\
            .single()\
            .execute()
        
        if result.data:
            data = result.data
            # Parse JSON fields
            data['available_nodes'] = json.loads(data['available_nodes'])
            data['graph'] = json.loads(data['graph'])
            
            # Update use count and last_used
            _increment_use_count(fingerprint, team_id)
            
            print(f"[@ai_graph_cache_db] ✅ Cache HIT: {fingerprint[:8]}...")
            return data
        else:
            return None
            
    except Exception as e:
        error_str = str(e)
        return None


def _increment_use_count(fingerprint: str, team_id: str) -> None:
    """Increment use count for cached graph"""
    try:
        from shared.src.lib.utils.supabase_utils import get_supabase_client
        supabase = get_supabase_client()
        
        # Get current count
        current = supabase.table('ai_graph_cache')\
            .select('use_count')\
            .eq('fingerprint', fingerprint)\
            .eq('team_id', team_id)\
            .single()\
            .execute()
        
        if current.data:
            new_count = current.data['use_count'] + 1
            
            supabase.table('ai_graph_cache')\
                .update({
                    'use_count': new_count,
                    'last_used': datetime.now().isoformat()
                })\
                .eq('fingerprint', fingerprint)\
                .eq('team_id', team_id)\
                .execute()
                
    except Exception as e:
        # Non-critical, don't fail the request
        print(f"[@ai_graph_cache_db] Warning: Could not increment use count: {e}")


def delete_graph(fingerprint: str, team_id: str) -> bool:
    """
    Delete cached graph
    
    Args:
        fingerprint: Graph fingerprint
        team_id: Team ID
        
    Returns:
        True if deleted
    """
    try:
        from shared.src.lib.utils.supabase_utils import get_supabase_client
        supabase = get_supabase_client()
        
        supabase.table('ai_graph_cache')\
            .delete()\
            .eq('fingerprint', fingerprint)\
            .eq('team_id', team_id)\
            .execute()
        
        print(f"[@ai_graph_cache_db] Deleted graph: {fingerprint[:8]}...")
        return True
            
    except Exception as e:
        print(f"[@ai_graph_cache_db] Error deleting graph: {e}")
        return False


def cleanup_old_graphs(team_id: str, days_old: int = 90) -> int:
    """
    Clean up old cached graphs
    
    Args:
        team_id: Team ID
        days_old: Remove graphs older than this
        
    Returns:
        Number of graphs removed
    """
    try:
        from shared.src.lib.utils.supabase_utils import get_supabase_client
        supabase = get_supabase_client()
        
        # Calculate cutoff date
        cutoff_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff_date = cutoff_date.replace(day=cutoff_date.day - days_old)
        
        result = supabase.table('ai_graph_cache')\
            .delete()\
            .eq('team_id', team_id)\
            .lt('last_used', cutoff_date.isoformat())\
            .execute()
        
        removed_count = len(result.data) if result.data else 0
        print(f"[@ai_graph_cache_db] Cleaned up {removed_count} old graphs")
        return removed_count
        
    except Exception as e:
        print(f"[@ai_graph_cache_db] Error cleaning up: {e}")
        return 0

