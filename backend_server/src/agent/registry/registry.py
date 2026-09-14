"""
Agent Registry Service

System agents are loaded from YAML templates on startup (source of truth).
Database is only used for user-created custom agents.
"""

import logging
from pathlib import Path
from typing import List, Optional, Dict, Any

from agent.registry.config_schema import AgentDefinition
from agent.registry.validator import validate_agent_yaml, validate_agent_dict, AgentValidationError

logger = logging.getLogger(__name__)


class AgentRegistry:
    """
    Agent Registry Service
    
    System agents: Loaded from YAML templates on startup, cached in memory.
    Custom agents: Stored in database (future feature).
    
    NOTE: Agents are global system resources, NOT team-scoped.
    """
    
    # Class-level cache for system agents (loaded from YAML)
    _system_agents: Dict[str, AgentDefinition] = {}
    _loaded: bool = False
    
    def __init__(self):
        # Auto-load YAML templates on first instantiation
        if not AgentRegistry._loaded:
            self.load_system_agents()
    
    @classmethod
    def load_system_agents(cls) -> None:
        """
        Load all system agents from YAML templates into memory.
        Called once on server startup.
        """
        templates_dir = Path(__file__).parent / 'templates'
        
        if not templates_dir.exists():
            logger.warning(f"[@registry] Templates directory not found: {templates_dir}")
            cls._loaded = True
            return
        
        # Only load YAML files from root templates dir (exclude _deprecated)
        yaml_files = [f for f in templates_dir.glob('*.yaml') if f.is_file()]
        logger.info(f"[@registry] ═══════════════════════════════════════════════")
        logger.info(f"[@registry] Loading {len(yaml_files)} agent templates...")
        logger.info(f"[@registry] ═══════════════════════════════════════════════")
        
        loaded = 0
        selectable = []
        internal = []
        errors = []
        
        for yaml_file in sorted(yaml_files):
            try:
                with open(yaml_file, 'r', encoding='utf-8') as f:
                    yaml_content = f.read()
                
                agent = validate_agent_yaml(yaml_content)
                cls._system_agents[agent.metadata.id] = agent
                
                # Categorize for summary
                meta = agent.metadata
                platform = agent.config.platform_filter if agent.config else 'all'
                
                if meta.selectable:
                    selectable.append(f"  {meta.icon} {meta.nickname:12} ({meta.id}) - {platform}")
                else:
                    internal.append(f"  {meta.icon} {meta.nickname:12} ({meta.id})")
                
                loaded += 1
                
            except AgentValidationError as e:
                errors.append(f"  ❌ {yaml_file.name}: {e}")
            except Exception as e:
                errors.append(f"  ❌ {yaml_file.name}: {e}")
        
        cls._loaded = True
        
        # Print summary
        logger.info(f"[@registry] ")
        logger.info(f"[@registry] ✅ User-Selectable Agents ({len(selectable)}):")
        for line in selectable:
            logger.info(f"[@registry] {line}")
        
        if internal:
            logger.info(f"[@registry] ")
            logger.info(f"[@registry] 🔧 Internal Sub-Agents ({len(internal)}):")
            for line in internal:
                logger.info(f"[@registry] {line}")
        
        if errors:
            logger.info(f"[@registry] ")
            logger.error(f"[@registry] ⚠️ Failed to Load ({len(errors)}):")
            for line in errors:
                logger.error(f"[@registry] {line}")
        
        logger.info(f"[@registry] ")
        logger.info(f"[@registry] ═══════════════════════════════════════════════")
        logger.info(f"[@registry] Total: {loaded}/{len(yaml_files)} agents loaded")
        logger.info(f"[@registry] ═══════════════════════════════════════════════")
    
    @classmethod
    def reload(cls) -> None:
        """Reload all system agents from YAML (for development)"""
        cls._system_agents.clear()
        cls._loaded = False
        cls.load_system_agents()
    
    def list_agents(self) -> List[AgentDefinition]:
        """
        List all system agents.
        
        NOTE: No team_id - agents are global system resources.
        
        Returns:
            List of AgentDefinition objects
        """
        return list(self._system_agents.values())
    
    def get(self, agent_id: str) -> Optional[AgentDefinition]:
        """
        Get agent by ID.
        
        Args:
            agent_id: Agent identifier (e.g., 'qa-web-manager')
            
        Returns:
            AgentDefinition or None if not found
        """
        return self._system_agents.get(agent_id)
    
    def get_selectable_agents(self) -> List[AgentDefinition]:
        """
        Get only agents that can be selected by users in the UI.
        
        Returns:
            List of AgentDefinition objects where selectable=True
        """
        return [
            agent for agent in self._system_agents.values()
            if agent.metadata.selectable
        ]
    
    def get_internal_agents(self) -> List[AgentDefinition]:
        """
        Get only internal sub-agents (not user-selectable).
        
        Returns:
            List of AgentDefinition objects where selectable=False
        """
        return [
            agent for agent in self._system_agents.values()
            if not agent.metadata.selectable
        ]
    
    def get_agents_by_platform(self, platform: str) -> List[AgentDefinition]:
        """
        Get agents filtered by platform.
        
        Args:
            platform: 'web', 'mobile', 'stb', or 'all'
            
        Returns:
            List of matching AgentDefinition objects
        """
        result = []
        for agent in self._system_agents.values():
            agent_platform = agent.config.platform_filter if agent.config else None
            if agent_platform is None or agent_platform == platform or platform == 'all':
                result.append(agent)
        return result
    
    def get_agents_for_event(self, event_type: str) -> List[AgentDefinition]:
        """
        Get all agents that should handle a specific event type.
        
        Args:
            event_type: Event type (e.g., 'alert.blackscreen')
            
        Returns:
            List of AgentDefinition objects with matching triggers
        """
        result = []
        for agent in self._system_agents.values():
            if agent.triggers:
                for trigger in agent.triggers:
                    if trigger.type == event_type:
                        result.append(agent)
                        break
        return result
    
    def exists(self, agent_id: str) -> bool:
        """Check if an agent exists"""
        return agent_id in self._system_agents


# Global instance
_agent_registry: Optional[AgentRegistry] = None


def get_agent_registry() -> AgentRegistry:
    """Get or create global agent registry instance"""
    global _agent_registry
    if _agent_registry is None:
        _agent_registry = AgentRegistry()
    return _agent_registry


def reload_agents() -> None:
    """Reload all agents from YAML (for development/hot-reload)"""
    AgentRegistry.reload()
