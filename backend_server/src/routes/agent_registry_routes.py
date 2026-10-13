"""
Agent Registry REST API Routes

System agents are loaded from YAML on startup.
No team_id - agents are global system resources.
"""


from flask import Blueprint, request, jsonify
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from typing import Optional

from agent.registry import (
    get_agent_registry,
    AgentDefinition,
)
from shared.src.lib.ai import router as ai_router, usages as ai_usages


def _resolve_agent_model(agent_id: str) -> Optional[str]:
    """The model serving this agent's usage (server default routing, TASK-30)."""
    try:
        return ai_router.resolve(ai_usages.agent_usage(agent_id)).primary.model
    except Exception:
        return None


def _agent_to_dict_with_model(agent: AgentDefinition) -> dict:
    data = agent.to_dict()
    data['model'] = _resolve_agent_model(agent.metadata.id)
    return data

# Create blueprint
server_agent_registry_bp = Blueprint('server_agent_registry', __name__, url_prefix='/server/agents')


# strict_slashes=False: the frontend calls /server/agents (no slash). Flask would answer with a
# 308 to '/server/agents/' built as http:// behind the reverse proxy, which the browser blocks as
# mixed content on the https site -> Agent Dashboard 'Failed to fetch' (BUG-0045).
@server_agent_registry_bp.route('/', methods=['GET'], strict_slashes=False)
@handle_route_exceptions('agent_registry:list_agents')
def list_agents():
    """
    List all system agents (loaded from YAML templates).
    
    Query params:
        - selectable: Filter by selectable (true/false)
        - platform: Filter by platform (web/mobile/stb)
    
    NOTE: No team_id - agents are global system resources.
    """
    registry = get_agent_registry()
    
    # Check for filters
    selectable_filter = request.args.get('selectable')
    platform_filter = request.args.get('platform')
    
    if selectable_filter == 'true':
        agents = registry.get_selectable_agents()
    elif selectable_filter == 'false':
        agents = registry.get_internal_agents()
    elif platform_filter:
        agents = registry.get_agents_by_platform(platform_filter)
    else:
        agents = registry.list_agents()
    
    return jsonify({
        'agents': [_agent_to_dict_with_model(agent) for agent in agents],
        'count': len(agents)
    }), 200

@server_agent_registry_bp.route('/<agent_id>', methods=['GET'])
@handle_route_exceptions('agent_registry:get_agent')
def get_agent(agent_id: str):
    """
    Get specific agent by ID.

    NOTE: No team_id or version - returns system agent from YAML.
    """
    registry = get_agent_registry()
    agent = registry.get(agent_id)

    if not agent:
        return jsonify({'error': f'Agent not found: {agent_id}'}), 404

    return jsonify(_agent_to_dict_with_model(agent)), 200
    
@server_agent_registry_bp.route('/events/<event_type>', methods=['GET'])
@handle_route_exceptions('agent_registry:get_agents_for_event')
def get_agents_for_event(event_type: str):
    """
    Get all agents that handle a specific event type.
    """
    registry = get_agent_registry()
    agents = registry.get_agents_for_event(event_type)

    return jsonify({
        'event_type': event_type,
        'agents': [_agent_to_dict_with_model(agent) for agent in agents],
        'count': len(agents)
    }), 200

@server_agent_registry_bp.route('/selectable', methods=['GET'])
@handle_route_exceptions('agent_registry:list_selectable_agents')
def list_selectable_agents():
    """
    List only agents that can be selected by users in the UI dropdown.
    Convenience endpoint - same as ?selectable=true
    """
    registry = get_agent_registry()
    agents = registry.get_selectable_agents()

    return jsonify({
        'agents': [_agent_to_dict_with_model(agent) for agent in agents],
        'count': len(agents)
    }), 200
    
