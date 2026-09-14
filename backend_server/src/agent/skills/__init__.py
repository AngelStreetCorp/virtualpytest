"""
Skill System - Dynamic Skill Loading for Agents

This module provides:
- SkillDefinition: Pydantic model for skill configurations
- SkillLoader: Loads skills from YAML definitions
- SkillRegistry: Validates tools exist as MCP tools

Skills are loaded from YAML files in skills/definitions/ and provide
focused capabilities that agents can dynamically load.
"""

from .skill_schema import SkillDefinition
from .skill_loader import SkillLoader
from .skill_registry import SkillRegistry, get_skill_registry, AVAILABLE_SKILLS

__all__ = [
    'SkillDefinition',
    'SkillLoader',
    'SkillRegistry',
    'get_skill_registry',
    'AVAILABLE_SKILLS'
]
