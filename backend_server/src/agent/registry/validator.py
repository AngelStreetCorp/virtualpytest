"""
Agent Configuration Validator

Validates agent YAML files. Includes skill validation against available MCP tools.
"""

import yaml
from typing import Dict, Any, List, Tuple
from pydantic import ValidationError

from .config_schema import AgentDefinition

# Try to import skill registry, fallback gracefully if not available
try:
    from agent.skills import get_skill_registry, AVAILABLE_SKILLS
    SKILL_VALIDATION_ENABLED = True
except ImportError:
    SKILL_VALIDATION_ENABLED = False
    AVAILABLE_SKILLS = set()


class AgentValidationError(Exception):
    """Raised when agent configuration is invalid"""
    pass


def validate_skills(skills: List[str]) -> Tuple[List[str], List[str]]:
    """
    Validate skills against available MCP tools

    Returns:
        (valid_skills, invalid_skills)
    """
    if not SKILL_VALIDATION_ENABLED:
        return skills, []

    registry = get_skill_registry()
    return registry.validate_skills(skills)


def validate_agent_yaml(yaml_content: str, strict_skills: bool = False) -> AgentDefinition:
    """
    Validate agent YAML and return AgentDefinition

    Args:
        yaml_content: YAML string content

    Returns:
        Validated AgentDefinition object

    Raises:
        AgentValidationError: If YAML is invalid
    """
    try:
        # Parse YAML
        data = yaml.safe_load(yaml_content)

        if not isinstance(data, dict):
            raise AgentValidationError("YAML must contain a dictionary")

        # Validate against schema
        agent = AgentDefinition(**data)

        # Validate skills against available MCP tools
        if agent.skills:
            valid_skills, invalid_skills = validate_skills(agent.skills)
            if invalid_skills:
                warning = f"Unknown skills: {', '.join(invalid_skills)}"
                if strict_skills:
                    raise AgentValidationError(warning)
                else:
                    print(f"[@agent_validator] ⚠️ {warning}")

        return agent

    except yaml.YAMLError as e:
        raise AgentValidationError(f"Invalid YAML syntax: {str(e)}")
    except ValidationError as e:
        errors = []
        for error in e.errors():
            field = " -> ".join(str(loc) for loc in error['loc'])
            errors.append(f"{field}: {error['msg']}")
        raise AgentValidationError(f"Validation errors:\n" + "\n".join(errors))
    except AgentValidationError:
        raise
    except Exception as e:
        raise AgentValidationError(f"Unexpected error: {str(e)}")


def validate_agent_dict(data: Dict[str, Any]) -> AgentDefinition:
    """
    Validate agent dictionary (from JSON/API)

    Args:
        data: Dictionary containing agent configuration

    Returns:
        Validated AgentDefinition object

    Raises:
        AgentValidationError: If configuration is invalid
    """
    try:
        return AgentDefinition(**data)
    except ValidationError as e:
        errors = []
        for error in e.errors():
            field = " -> ".join(str(loc) for loc in error['loc'])
            errors.append(f"{field}: {error['msg']}")
        raise AgentValidationError(f"Validation errors:\n" + "\n".join(errors))

