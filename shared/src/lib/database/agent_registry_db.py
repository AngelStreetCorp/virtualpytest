"""
Agent Registry Database Operations

Sync database layer for agent registry using Supabase client.
"""

import json
from typing import Dict, List, Optional, Any
from shared.src.lib.utils.supabase_utils import get_supabase_client

DEFAULT_TEAM_ID = 'default'


def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()


def register_agent(
    agent_id: str,
    name: str,
    version: str,
    author: str,
    description: str,
    goal_type: str,
    goal_description: str,
    definition: Dict[str, Any],
    team_id: str = DEFAULT_TEAM_ID,
    created_by: Optional[str] = None,
    tags: Optional[List[str]] = None
) -> Optional[str]:
    """
    Register new agent or update existing version.
    
    Returns:
        UUID of registered agent or None on error
    """
    supabase = get_supabase()
    if not supabase:
        return None
    
    data = {
        'agent_id': agent_id,
        'name': name,
        'version': version,
        'author': author,
        'description': description,
        'goal_type': goal_type,
        'goal_description': goal_description,
        'definition': definition,
        'status': 'draft',
        'team_id': team_id,
        'created_by': created_by,
        'tags': tags or []
    }
    
    result = supabase.table('agent_registry').upsert(
        data,
        on_conflict='agent_id,version'
    ).execute()
    
    if result.data:
        print(f"[@agent_registry_db] ✅ Registered: {agent_id} v{version}")
        return result.data[0].get('id')
    return None


def get_agent(
    agent_id: str,
    version: Optional[str] = None,
    team_id: str = DEFAULT_TEAM_ID
) -> Optional[Dict[str, Any]]:
    """
    Get agent definition by ID and version.
    If version is None, returns latest published version.
    
    Returns:
        Definition dict or None if not found
    """
    supabase = get_supabase()
    if not supabase:
        return None
    
    query = supabase.table('agent_registry').select('definition')
    
    if version:
        result = query.eq('agent_id', agent_id).eq('version', version).eq('team_id', team_id).execute()
    else:
        # Get latest published version
        result = query.eq('agent_id', agent_id).eq('team_id', team_id).eq('status', 'published').order('created_at', desc=True).limit(1).execute()
    
    if result.data:
        definition = result.data[0]['definition']
        # Handle JSON string from database
        if isinstance(definition, str):
            return json.loads(definition)
        return definition
    return None


def list_agents(
    team_id: str = DEFAULT_TEAM_ID,
    status: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    List all agents (latest versions).
    
    Returns:
        List of definition dicts
    """
    supabase = get_supabase()
    if not supabase:
        return []
    
    # Use RPC for DISTINCT ON query (Supabase doesn't support it directly)
    # Fallback: get all and dedupe in Python
    query = supabase.table('agent_registry').select('agent_id, definition, created_at').eq('team_id', team_id)
    
    if status:
        query = query.eq('status', status)
    
    result = query.order('created_at', desc=True).execute()
    
    if not result.data:
        return []
    
    # Dedupe by agent_id (keep latest)
    seen = set()
    definitions = []
    for row in result.data:
        if row['agent_id'] not in seen:
            seen.add(row['agent_id'])
            definition = row['definition']
            # Handle JSON string from database
            if isinstance(definition, str):
                definition = json.loads(definition)
            definitions.append(definition)
    
    return definitions


def list_agent_versions(
    agent_id: str,
    team_id: str = DEFAULT_TEAM_ID
) -> List[Dict[str, Any]]:
    """List all versions of an agent."""
    supabase = get_supabase()
    if not supabase:
        return []
    
    result = supabase.table('agent_registry').select(
        'version, status, created_at, updated_at, author'
    ).eq('agent_id', agent_id).eq('team_id', team_id).order('created_at', desc=True).execute()
    
    return result.data if result.data else []


def get_agents_for_event(
    event_type: str,
    team_id: str = DEFAULT_TEAM_ID
) -> List[Dict[str, Any]]:
    """Get all agents that should handle a specific event type."""
    supabase = get_supabase()
    if not supabase:
        return []
    
    # Query the triggers table and join with registry
    triggers_result = supabase.table('agent_event_triggers').select(
        'agent_id'
    ).eq('event_type', event_type).eq('team_id', team_id).execute()
    
    if not triggers_result.data:
        return []
    
    # Get definitions for matched agents
    agent_ids = [t['agent_id'] for t in triggers_result.data]
    definitions = []
    
    for aid in agent_ids:
        definition = get_agent(aid, team_id=team_id)
        if definition:
            definitions.append(definition)
    
    return definitions


def publish_agent(
    agent_id: str,
    version: str,
    team_id: str = DEFAULT_TEAM_ID
) -> bool:
    """Publish an agent version (make it active)."""
    supabase = get_supabase()
    if not supabase:
        return False
    
    result = supabase.table('agent_registry').update({
        'status': 'published'
    }).eq('agent_id', agent_id).eq('version', version).eq('team_id', team_id).execute()
    
    if result.data:
        print(f"[@agent_registry_db] 📢 Published: {agent_id} v{version}")
        return True
    return False


def deprecate_agent(
    agent_id: str,
    version: str,
    team_id: str = DEFAULT_TEAM_ID
) -> bool:
    """Deprecate an agent version."""
    supabase = get_supabase()
    if not supabase:
        return False
    
    result = supabase.table('agent_registry').update({
        'status': 'deprecated'
    }).eq('agent_id', agent_id).eq('version', version).eq('team_id', team_id).execute()
    
    if result.data:
        print(f"[@agent_registry_db] 🗑️ Deprecated: {agent_id} v{version}")
        return True
    return False


def delete_agent(
    agent_id: str,
    version: str,
    team_id: str = DEFAULT_TEAM_ID
) -> bool:
    """Delete an agent version."""
    supabase = get_supabase()
    if not supabase:
        return False
    
    result = supabase.table('agent_registry').delete().eq(
        'agent_id', agent_id
    ).eq('version', version).eq('team_id', team_id).execute()
    
    if result.data:
        print(f"[@agent_registry_db] 🗑️ Deleted: {agent_id} v{version}")
        return True
    return False


def register_triggers(
    agent_id: str,
    triggers: List[Dict[str, Any]],
    team_id: str = DEFAULT_TEAM_ID
) -> bool:
    """Register event triggers for agent."""
    supabase = get_supabase()
    if not supabase:
        return False
    
    # Delete existing triggers
    supabase.table('agent_event_triggers').delete().eq(
        'agent_id', agent_id
    ).eq('team_id', team_id).execute()
    
    # Insert new triggers
    if triggers:
        trigger_data = [
            {
                'agent_id': agent_id,
                'event_type': t.get('type'),
                'priority': t.get('priority', 3),
                'filters': t.get('filters', {}),
                'team_id': team_id
            }
            for t in triggers
        ]
        supabase.table('agent_event_triggers').insert(trigger_data).execute()
    
    return True


def search_agents(
    query: str,
    team_id: str = DEFAULT_TEAM_ID
) -> List[Dict[str, Any]]:
    """Search agents by name, description, or tags."""
    supabase = get_supabase()
    if not supabase:
        return []
    
    # Use ilike for case-insensitive search
    result = supabase.table('agent_registry').select(
        'agent_id, definition, created_at'
    ).eq('team_id', team_id).or_(
        f"name.ilike.%{query}%,description.ilike.%{query}%"
    ).order('created_at', desc=True).execute()
    
    if not result.data:
        return []
    
    # Dedupe by agent_id
    seen = set()
    definitions = []
    for row in result.data:
        if row['agent_id'] not in seen:
            seen.add(row['agent_id'])
            definition = row['definition']
            if isinstance(definition, str):
                definition = json.loads(definition)
            definitions.append(definition)
    
    return definitions


def get_enabled_agents(
    team_id: str = DEFAULT_TEAM_ID
) -> List[Dict[str, Any]]:
    """
    Get all enabled published agents for auto-start on backend boot.
    
    Returns:
        List of agent definitions that should auto-start
    """
    supabase = get_supabase()
    if not supabase:
        return []
    
    result = supabase.table('agent_registry').select(
        'agent_id, version, definition, created_at'
    ).eq('team_id', team_id).eq('status', 'published').eq('enabled', True).order('created_at', desc=True).execute()
    
    if not result.data:
        return []
    
    # Dedupe by agent_id (keep latest version)
    seen = set()
    definitions = []
    for row in result.data:
        if row['agent_id'] not in seen:
            seen.add(row['agent_id'])
            definition = row['definition']
            if isinstance(definition, str):
                definition = json.loads(definition)
            definitions.append(definition)
    
    print(f"[@agent_registry_db] 🚀 Found {len(definitions)} enabled agents for auto-start")
    return definitions


def set_agent_enabled(
    agent_id: str,
    enabled: bool,
    team_id: str = DEFAULT_TEAM_ID
) -> bool:
    """
    Enable or disable an agent's auto-start.
    
    Args:
        agent_id: Agent identifier
        enabled: True to enable, False to disable
        team_id: Team namespace
        
    Returns:
        True if updated successfully
    """
    supabase = get_supabase()
    if not supabase:
        return False
    
    result = supabase.table('agent_registry').update({
        'enabled': enabled
    }).eq('agent_id', agent_id).eq('team_id', team_id).execute()
    
    if result.data:
        status = "enabled" if enabled else "disabled"
        print(f"[@agent_registry_db] ⚡ Agent {agent_id} {status}")
        return True
    return False


def get_agent_status(
    agent_id: str,
    team_id: str = DEFAULT_TEAM_ID
) -> Optional[Dict[str, Any]]:
    """
    Get agent status including enabled state.
    
    Returns:
        Dict with agent_id, version, status, enabled, or None
    """
    supabase = get_supabase()
    if not supabase:
        return None
    
    result = supabase.table('agent_registry').select(
        'agent_id, version, status, enabled, definition'
    ).eq('agent_id', agent_id).eq('team_id', team_id).order('created_at', desc=True).limit(1).execute()
    
    if result.data:
        return result.data[0]
    return None

