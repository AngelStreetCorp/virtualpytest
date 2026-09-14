"""
Agent Configuration Schema

Pydantic models defining the structure of agent configurations.
Agents can be exported/imported as YAML files.
"""

from pydantic import BaseModel, Field, field_validator
from typing import List, Dict, Optional, Any, Union
from enum import Enum
from datetime import datetime


class EventTrigger(BaseModel):
    """Event that triggers agent activation"""
    type: str = Field(..., description="Event type (e.g., 'alert.blackscreen')")
    priority: str = Field(..., description="Priority: critical, high, normal, low")
    filters: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional filters for event matching"
    )
    
    @field_validator('priority')
    @classmethod
    def validate_priority(cls, v: str) -> str:
        valid = ['critical', 'high', 'normal', 'low']
        if v.lower() not in valid:
            raise ValueError(f"Priority must be one of: {valid}")
        return v.lower()


class SubAgentReference(BaseModel):
    """Reference to a subagent this agent can delegate to"""
    id: str = Field(..., description="Subagent identifier")
    version: str = Field(
        default="latest",
        description="Version requirement (e.g., '>=1.0.0', 'latest')"
    )
    delegate_for: List[str] = Field(
        ...,
        description="Task types this subagent handles"
    )


class AgentPermissions(BaseModel):
    """Agent resource access permissions"""
    devices: List[str] = Field(
        default_factory=list,
        description="Device permissions: read, take_control"
    )
    database: List[str] = Field(
        default_factory=list,
        description="Database permissions: read, write.table_name"
    )
    external: List[str] = Field(
        default_factory=list,
        description="External integrations: jira, slack, etc."
    )


class AgentConfig(BaseModel):
    """Agent runtime configuration"""
    enabled: bool = Field(
        default=True,
        description="Whether agent auto-starts on backend runtime start"
    )
    background_queues: List[str] = Field(
        default_factory=list,
        description="Redis queues for background processing (e.g., ['p1_alerts', 'p2_scripts'])"
    )
    dry_run: bool = Field(
        default=False,
        description="If true, background worker prints events but doesn't process (save tokens)"
    )
    max_parallel_tasks: int = Field(
        default=3,
        ge=1,
        description="Maximum parallel task execution"
    )
    approval_required_for: List[str] = Field(
        default_factory=list,
        description="Actions requiring human approval"
    )
    auto_retry: bool = Field(
        default=True,
        description="Automatically retry failed tasks"
    )
    feedback_collection: bool = Field(
        default=True,
        description="Collect user feedback after tasks"
    )
    timeout_seconds: int = Field(
        default=3600,
        ge=60,
        description="Default task timeout in seconds"
    )
    budget_limit_usd: Optional[float] = Field(
        default=None,
        description="Monthly budget limit in USD"
    )
    platform_filter: Optional[str] = Field(
        default=None,
        description="Platform focus: web, mobile, stb, or None for all"
    )


class AgentMetadata(BaseModel):
    """Agent metadata and versioning"""
    id: str = Field(
        ...,
        pattern="^[a-z0-9-]+$",
        description="Unique agent identifier (lowercase, hyphens)"
    )
    name: str = Field(..., min_length=1, description="Human-readable name")
    nickname: Optional[str] = Field(
        default=None,
        description="Short display name (e.g., 'Sherlock', 'Atlas'). Falls back to name if not set."
    )
    icon: Optional[str] = Field(
        default=None,
        description="Emoji icon for UI display (e.g., '🧪', '🔍')"
    )
    selectable: bool = Field(
        default=True,
        description="If true, agent appears in UI dropdown. If false, agent is internal (sub-agent)."
    )
    default: bool = Field(
        default=False,
        description="If true, this agent is the default selection in UI"
    )
    version: str = Field(
        ...,
        pattern=r"^\d+\.\d+\.\d+(-[a-z0-9]+)?$",
        description="Semantic version (e.g., 1.0.0, 2.1.0-beta)"
    )
    author: str = Field(..., description="Creator/owner of this agent")
    description: str = Field(..., description="What this agent does")
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    tags: List[str] = Field(default_factory=list, description="Tags for categorization")
    suggestions: List[str] = Field(
        default_factory=list,
        description="Example prompts to show in chat UI (e.g., 'Automate login test', 'Run regression suite')"
    )
    prompt_presets: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Categorized prompt presets with variable substitution (e.g., device, host, interface)"
    )


class AgentDefinition(BaseModel):
    """
    Complete agent definition
    
    This is the root model for agent configurations.
    Can be serialized to/from YAML for portability.
    """
    metadata: AgentMetadata
    triggers: List[EventTrigger] = Field(
        default_factory=list,
        description="Events that activate this agent"
    )
    event_pools: List[str] = Field(
        default_factory=list,
        description="Event channels to subscribe to"
    )
    subagents: List[SubAgentReference] = Field(
        default_factory=list,
        description="Subagents this agent can delegate to"
    )
    available_skills: List[str] = Field(
        default_factory=list,
        description="Skills this agent can dynamically load (e.g., 'exploration-mobile')"
    )
    skills: List[str] = Field(
        default_factory=list,
        description="Default tools (before skill loads)"
    )
    permissions: AgentPermissions = Field(
        default_factory=AgentPermissions,
        description="Resource access permissions"
    )
    config: AgentConfig = Field(
        default_factory=AgentConfig,
        description="Runtime configuration"
    )
    
    class Config:
        use_enum_values = True
        json_schema_extra = {
            "example": {
                "metadata": {
                    "id": "qa-manager",
                    "name": "QA Manager",
                    "version": "2.1.0",
                    "author": "team-qa",
                    "description": "Continuous quality validation",
                    "tags": ["qa", "automation", "testing"]
                },
                "triggers": [
                    {
                        "type": "alert.blackscreen",
                        "priority": "critical"
                    }
                ],
                "event_pools": ["shared.alerts", "shared.builds"],
                "subagents": [
                    {
                        "id": "executor",
                        "version": ">=1.0.0",
                        "delegate_for": ["test_execution"]
                    }
                ],
                "skills": ["list_testcases", "execute_testcase"],
                "permissions": {
                    "devices": ["read", "take_control"],
                    "database": ["read", "write.testcases"]
                },
                "config": {
                    "max_parallel_tasks": 3,
                    "auto_retry": True
                }
            }
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (for JSON/YAML export)"""
        return self.model_dump(exclude_none=True)
    
    @classmethod
    def from_dict(cls, data: Union[Dict[str, Any], str]) -> 'AgentDefinition':
        """Create from dictionary or JSON string (for JSON/YAML import)"""
        import json
        # Handle JSON string from database (asyncpg may not auto-decode JSONB)
        if isinstance(data, str):
            data = json.loads(data)
        return cls(**data)

