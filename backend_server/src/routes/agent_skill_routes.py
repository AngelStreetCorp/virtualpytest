"""
Agent Skills Management REST API Routes

Provides HTTP endpoints for skill management, reloading, and testing.
"""

from flask import Blueprint, request, jsonify
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from typing import Dict, Any, List
import json

from agent.skills.skill_loader import SkillLoader
from agent.skills.skill_registry import SkillRegistry
from shared.src.lib.config.constants import APP_CONFIG

# Create blueprint
server_agent_skill_bp = Blueprint('server_agent_skill', __name__, url_prefix='/server/skills')


@server_agent_skill_bp.route('/reload', methods=['POST'])
@handle_route_exceptions('agent_skill:reload_skills')
def reload_skills():
    """
    Reload all skill definitions from YAML files.

    Useful for development when skill YAML files are modified.

    Returns:
        JSON response with reload status
    """
    # Reload skills from disk
    SkillLoader.reload()

    # Get updated skill list
    all_skills = SkillLoader.get_all_skills()

    skill_info = []
    for name, skill in all_skills.items():
        skill_info.append({
            'name': skill.name,
            'description': skill.description,
            'platform': skill.platform,
            'requires_device': skill.requires_device,
            'tool_count': len(skill.tools),
            'trigger_count': len(skill.triggers)
        })

    return jsonify({
        'message': 'Skills reloaded successfully',
        'count': len(all_skills),
        'skills': skill_info
    }), 200

@server_agent_skill_bp.route('', methods=['GET'])
@handle_route_exceptions('agent_skill:list_skills')
def list_skills():
    """
    List all loaded skills with their details.

    Query params:
        - platform: Filter by platform (optional)
        - requires_device: Filter by device requirement (optional)
    """
    all_skills = SkillLoader.get_all_skills()

    # Apply filters
    platform_filter = request.args.get('platform')
    device_filter = request.args.get('requires_device')

    filtered_skills = []
    for name, skill in all_skills.items():
        # Platform filter
        if platform_filter and skill.platform != platform_filter:
            continue

        # Device filter
        if device_filter is not None:
            requires_device = device_filter.lower() in ('true', '1', 'yes')
            if skill.requires_device != requires_device:
                continue

        filtered_skills.append({
            'name': skill.name,
            'description': skill.description,
            'version': skill.version,
            'platform': skill.platform,
            'requires_device': skill.requires_device,
            'timeout_seconds': skill.timeout_seconds,
            'triggers': skill.triggers[:5],  # Limit triggers for brevity
            'tools': skill.tools,
            'trigger_count': len(skill.triggers)
        })

    return jsonify({
        'skills': filtered_skills,
        'count': len(filtered_skills),
        'total': len(all_skills)
    }), 200

@server_agent_skill_bp.route('/<skill_name>', methods=['GET'])
@handle_route_exceptions('agent_skill:get_skill')
def get_skill(skill_name: str):
    """Get detailed information about a specific skill"""
    skill = SkillLoader.get_skill(skill_name)

    if not skill:
        return jsonify({
            'error': f'Skill "{skill_name}" not found'
        }), 404

    return jsonify({
        'name': skill.name,
        'description': skill.description,
        'version': skill.version,
        'platform': skill.platform,
        'requires_device': skill.requires_device,
        'timeout_seconds': skill.timeout_seconds,
        'triggers': skill.triggers,
        'tools': skill.tools,
        'system_prompt': skill.system_prompt
    }), 200

@server_agent_skill_bp.route('/match', methods=['POST'])
@handle_route_exceptions('agent_skill:match_skill')
def match_skill():
    """
    Test skill matching against a message.

    Body:
        - message: User message to test (required)
        - available_skills: List of skill names to consider (optional)
        - device_platform: Optional device platform for filtering ('mobile', 'stb', 'web')
    """
    data = request.get_json()

    if not data or 'message' not in data:
        return jsonify({
            'error': 'message is required'
        }), 400

    message = data['message']
    available_skills = data.get('available_skills', [])
    device_platform = data.get('device_platform')

    # If no skills specified, use all skills
    if not available_skills:
        all_skills = SkillLoader.get_all_skills()
        available_skills = list(all_skills.keys())

    matched_skill = SkillLoader.match_skill(message, available_skills, device_platform)

    if matched_skill:
        return jsonify({
            'matched': True,
            'skill': {
                'name': matched_skill.name,
                'description': matched_skill.description,
                'triggers': matched_skill.triggers
            }
        }), 200
    else:
        return jsonify({
            'matched': False,
            'message': 'No skill matched the message'
        }), 200

@server_agent_skill_bp.route('/test/<skill_name>', methods=['POST'])
@handle_route_exceptions('agent_skill:test_skill')
def test_skill(skill_name: str):
    """
    Test a skill definition for validity.

    This endpoint validates that the skill YAML is well-formed
    and all required fields are present.
    """
    skill = SkillLoader.get_skill(skill_name)

    if not skill:
        return jsonify({
            'error': f'Skill "{skill_name}" not found'
        }), 404

    # Basic validation
    issues = []

    if not skill.name:
        issues.append('Missing name')
    if not skill.description:
        issues.append('Missing description')
    if not skill.triggers:
        issues.append('No triggers defined')
    if not skill.tools:
        issues.append('No tools defined')

    # Check tool validity (basic check)
    for tool in skill.tools:
        if not isinstance(tool, str):
            issues.append(f'Invalid tool format: {tool}')

    if issues:
        return jsonify({
            'valid': False,
            'issues': issues,
            'skill': skill_name
        }), 200
    else:
        return jsonify({
            'valid': True,
            'message': f'Skill "{skill_name}" is valid',
            'skill': {
                'name': skill.name,
                'triggers': len(skill.triggers),
                'tools': len(skill.tools)
            }
        }), 200
