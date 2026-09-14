"""
Agent Registry System

This module provides agent configuration, versioning, and storage:
- Config Schema: Pydantic models for agent definitions
- Validator: YAML validation and import/export
- Registry: Database storage and retrieval
- Templates: Predefined agent configurations
"""

from .config_schema import (
    AgentDefinition,
    AgentMetadata,
    EventTrigger,
    SubAgentReference,
    AgentPermissions,
    AgentConfig
)
from .validator import validate_agent_yaml, export_agent_yaml, AgentValidationError
from .registry import AgentRegistry, get_agent_registry, reload_agents

__all__ = [
    'AgentDefinition',
    'AgentMetadata',
    'EventTrigger',
    'SubAgentReference',
    'AgentPermissions',
    'AgentConfig',
    'validate_agent_yaml',
    'export_agent_yaml',
    'AgentValidationError',
    'AgentRegistry',
    'get_agent_registry',
    'reload_agents'
]

