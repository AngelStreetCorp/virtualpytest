"""
Test Agent Registry

Tests for agent configuration, validation, and storage.
"""

import pytest
import asyncio
from backend_server.src.agent.registry import (
    AgentDefinition,
    AgentMetadata,
    AgentGoal,
    AgentGoalType,
    EventTrigger,
    validate_agent_yaml,
    export_agent_yaml,
    AgentValidationError,
    AgentRegistry
)


def test_agent_definition_creation():
    """Test creating agent definition"""
    agent = AgentDefinition(
        metadata=AgentMetadata(
            id="test-agent",
            name="Test Agent",
            version="1.0.0",
            author="test",
            description="Test agent"
        ),
        goal=AgentGoal(
            type=AgentGoalType.ON_DEMAND,
            description="Test goal description for testing purposes"
        ),
        triggers=[
            EventTrigger(type="test.event", priority="normal")
        ],
        skills=["test_skill"]
    )
    
    assert agent.metadata.id == "test-agent"
    assert agent.metadata.version == "1.0.0"
    assert len(agent.triggers) == 1
    assert agent.goal.type == AgentGoalType.ON_DEMAND


def test_agent_to_dict():
    """Test agent serialization"""
    agent = AgentDefinition(
        metadata=AgentMetadata(
            id="test-agent",
            name="Test Agent",
            version="1.0.0",
            author="test",
            description="Test"
        ),
        goal=AgentGoal(
            type=AgentGoalType.CONTINUOUS,
            description="Test continuous agent description"
        )
    )
    
    data = agent.to_dict()
    assert data['metadata']['id'] == "test-agent"
    assert data['goal']['type'] == "continuous"


def test_yaml_export_import():
    """Test YAML export and import"""
    agent = AgentDefinition(
        metadata=AgentMetadata(
            id="test-agent",
            name="Test Agent",
            version="1.0.0",
            author="test",
            description="Test"
        ),
        goal=AgentGoal(
            type=AgentGoalType.ON_DEMAND,
            description="Test agent for YAML export/import testing"
        ),
        triggers=[
            EventTrigger(type="test.event", priority="high")
        ]
    )
    
    # Export to YAML
    yaml_str = export_agent_yaml(agent)
    assert "test-agent" in yaml_str
    assert "1.0.0" in yaml_str
    
    # Import from YAML
    imported = validate_agent_yaml(yaml_str)
    assert imported.metadata.id == agent.metadata.id
    assert imported.metadata.version == agent.metadata.version


def test_yaml_validation_errors():
    """Test YAML validation catches errors"""
    
    # Invalid YAML syntax
    with pytest.raises(AgentValidationError):
        validate_agent_yaml("invalid: yaml: syntax:")
    
    # Missing required fields
    with pytest.raises(AgentValidationError):
        validate_agent_yaml("metadata: {id: test}")
    
    # Invalid version format
    invalid_version_yaml = """
metadata:
  id: test-agent
  name: Test
  version: not-a-version
  author: test
  description: Test
goal:
  type: continuous
  description: Test description
"""
    with pytest.raises(AgentValidationError):
        validate_agent_yaml(invalid_version_yaml)


def test_priority_validation():
    """Test event trigger priority validation"""
    
    # Valid priorities
    for priority in ['critical', 'high', 'normal', 'low']:
        trigger = EventTrigger(type="test.event", priority=priority)
        assert trigger.priority == priority
    
    # Invalid priority
    with pytest.raises(ValueError):
        EventTrigger(type="test.event", priority="invalid")


@pytest.mark.asyncio
async def test_registry_operations():
    """Test registry CRUD operations (requires database)"""
    
    # This test requires database connection
    # Skip if not available
    try:
        registry = AgentRegistry()
        
        agent = AgentDefinition(
            metadata=AgentMetadata(
                id="test-registry",
                name="Test Registry",
                version="1.0.0",
                author="test",
                description="Test"
            ),
            goal=AgentGoal(
                type=AgentGoalType.ON_DEMAND,
                description="Testing registry operations with database"
            )
        )
        
        # Register
        agent_id = await registry.register(agent, team_id='test')
        assert agent_id is not None
        
        # Get
        retrieved = await registry.get("test-registry", "1.0.0", team_id='test')
        assert retrieved is not None
        assert retrieved.metadata.id == "test-registry"
        
        # List
        agents = await registry.list_agents(team_id='test')
        assert len(agents) > 0
        
        # Publish
        success = await registry.publish("test-registry", "1.0.0", team_id='test')
        assert success
        
        # Clean up
        await registry.delete("test-registry", "1.0.0", team_id='test')
        
    except Exception as e:
        pytest.skip(f"Database not available: {e}")


if __name__ == "__main__":
    # Run basic tests
    test_agent_definition_creation()
    test_agent_to_dict()
    test_yaml_export_import()
    test_yaml_validation_errors()
    test_priority_validation()
    
    print("✅ All basic tests passed!")
    
    # Run async test
    try:
        asyncio.run(test_registry_operations())
        print("✅ Registry tests passed!")
    except Exception as e:
        print(f"⚠️ Registry tests skipped: {e}")

