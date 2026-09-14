"""
Skill Definition Schema

Pydantic models defining the structure of skill configurations.
Skills are loaded from YAML files and provide focused capabilities to agents.
"""

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Union


class ToolCacheConfig(BaseModel):
    """Cache configuration for a tool"""
    enabled: bool = Field(default=True, description="Enable result caching")
    ttl_seconds: int = Field(default=300, ge=0, description="Time-to-live in seconds (0 = session-only)")
    prompt_cache: bool = Field(default=True, description="Mark for Anthropic prompt caching")


class SkillDefinition(BaseModel):
    """
    Complete skill definition
    
    Skills are focused capabilities that agents can dynamically load.
    They provide system prompts and tool access for specific tasks.
    """
    name: str = Field(
        ...,
        pattern="^[a-z0-9-]+$",
        description="Unique skill identifier (lowercase, hyphens)"
    )
    version: str = Field(
        default="1.0.0",
        pattern=r"^\d+\.\d+\.\d+(-[a-z0-9]+)?$",
        description="Semantic version"
    )
    description: str = Field(
        ...,
        min_length=10,
        description="Description of what this skill does (used by agents for matching)"
    )
    triggers: List[str] = Field(
        default_factory=list,
        description="Keywords for auto-matching user requests"
    )
    system_prompt: str = Field(
        ...,
        min_length=50,
        description="Workflow instructions for the LLM"
    )
    tools: List[str] = Field(
        ...,
        min_length=1,
        description="MCP tools this skill exposes"
    )
    tool_cache: Optional[Dict[str, Union[bool, ToolCacheConfig]]] = Field(
        default=None,
        description="Tool-specific caching config. Format: {tool_name: true|false|{config}}"
    )
    require_tool_use: bool = Field(
        default=False,
        description="Reject a final answer produced with zero tool calls this turn (the manager nudges the model to research once)"
    )
    platform: Optional[str] = Field(
        default=None,
        description="Platform focus: mobile, web, stb, or null for all"
    )
    requires_device: bool = Field(
        default=False,
        description="Whether this skill needs device control"
    )
    required_context: List[str] = Field(
        default_factory=list,
        description="Context keys this skill requires (e.g., 'tree_id', 'available_testcases', 'campaign_id')"
    )
    timeout_seconds: int = Field(
        default=1800,
        ge=60,
        description="Default timeout for this skill"
    )
    
    @field_validator('platform')
    @classmethod
    def validate_platform(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            valid = ['mobile', 'web', 'stb']
            if v.lower() not in valid:
                raise ValueError(f"Platform must be one of: {valid}")
            return v.lower()
        return v
    
    def get_tool_cache_config(self, tool_name: str) -> Optional[ToolCacheConfig]:
        """Get cache configuration for a specific tool"""
        if not self.tool_cache or tool_name not in self.tool_cache:
            return None
        
        config = self.tool_cache[tool_name]
        
        # Already a ToolCacheConfig (Pydantic auto-converted)
        if isinstance(config, ToolCacheConfig):
            return config if config.enabled else None
        
        # Simple boolean format
        if isinstance(config, bool):
            if config:
                return ToolCacheConfig()  # Use defaults
            return None
        
        # Dict format - convert to ToolCacheConfig (shouldn't reach here if Pydantic works)
        if isinstance(config, dict):
            return ToolCacheConfig(**config)
        
        return None
    
    def get_cacheable_tools(self) -> List[str]:
        """Get list of tools marked for prompt caching"""
        if not self.tool_cache:
            return []
        
        cacheable = []
        for tool_name in self.tools:
            config = self.get_tool_cache_config(tool_name)
            if config and config.prompt_cache:
                cacheable.append(tool_name)
        
        return cacheable
    
    def matches_triggers(self, message: str) -> bool:
        """Check if user message matches any of this skill's triggers"""
        message_lower = message.lower()
        return any(trigger.lower() in message_lower for trigger in self.triggers)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization"""
        return self.model_dump(exclude_none=True)

