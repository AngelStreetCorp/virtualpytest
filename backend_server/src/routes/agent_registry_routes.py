"""
Agent Registry REST API Routes

System agents are loaded from YAML on startup.
No team_id - agents are global system resources.
"""

import os

from flask import Blueprint, request, jsonify, Response
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.routes.server_system_socket_routes import emit_system_update
from typing import Optional

from agent.registry import (
    get_agent_registry,
    AgentDefinition,
    validate_agent_yaml,
    export_agent_yaml,
    AgentValidationError,
    reload_agents
)
from shared.src.lib.ai.config import get_active_model


def _resolve_agent_model(agent_id: str) -> str:
    """Resolve the LLM model an agent will use, honoring per-agent env overrides."""
    if agent_id == 'analyzer':
        configured = (os.getenv('ANALYZER_OPENROUTER_MODEL') or '').strip()
        if configured:
            return configured
    return get_active_model()


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
    
@server_agent_registry_bp.route('/<agent_id>/export', methods=['GET'])
@handle_route_exceptions('agent_registry:export_agent')
def export_agent(agent_id: str):
    """
    Export agent as YAML file.
    """
    registry = get_agent_registry()
    agent = registry.get(agent_id)
    
    if not agent:
        return jsonify({'error': f'Agent not found: {agent_id}'}), 404
    
    # Export to YAML
    yaml_content = export_agent_yaml(agent)
    
    # Return as downloadable file
    return Response(
        yaml_content,
        mimetype='text/yaml',
        headers={
            'Content-Disposition': f'attachment; filename={agent_id}-{agent.metadata.version}.yaml'
        }
    )
    
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
    
@server_agent_registry_bp.route('/reload', methods=['POST'])
@handle_route_exceptions('agent_registry:reload_agents_endpoint')
def reload_agents_endpoint():
    """
    Reload all agents from YAML templates.
    Useful for development when YAML files are modified.
    """
    reload_agents()
    
    registry = get_agent_registry()
    agents = registry.list_agents()

    emit_system_update('agent_registry_changed', {
        'domain': 'agent_registry',
        'action': 'reloaded',
        'count': len(agents)
    })
    
    return jsonify({
        'message': 'Agents reloaded from YAML',
        'count': len(agents),
        'agents': [a.metadata.id for a in agents]
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
    
# Keep import endpoint for custom agents (future feature)
@server_agent_registry_bp.route('/import', methods=['POST'])
@handle_route_exceptions('agent_registry:import_agent_yaml')
def import_agent_yaml():
    """
    Import custom agent from YAML.
    
    NOTE: This is for user-created custom agents, not system agents.
    System agents should be modified by editing YAML templates and calling /reload.
    
    Body: YAML string or file upload
    """
    # Check if file upload or raw YAML
    if 'file' in request.files:
        file = request.files['file']
        yaml_content = file.read().decode('utf-8')
    elif request.data:
        yaml_content = request.data.decode('utf-8')
    else:
        return jsonify({'error': 'No YAML content provided'}), 400
    
    # Validate YAML
    try:
        agent = validate_agent_yaml(yaml_content)
    except AgentValidationError as e:
        return jsonify({'error': str(e)}), 400
    
    # For now, just validate and return success
    # In future, this could save to database for custom agents
    emit_system_update('agent_registry_changed', {
        'domain': 'agent_registry',
        'action': 'import_validated',
        'agent_id': agent.metadata.id,
        'version': agent.metadata.version
    })

    return jsonify({
        'agent_id': agent.metadata.id,
        'version': agent.metadata.version,
        'nickname': agent.metadata.nickname,
        'message': 'Agent YAML validated successfully. To add system agents, place YAML in templates/ and call /reload.'
    }), 200
    
