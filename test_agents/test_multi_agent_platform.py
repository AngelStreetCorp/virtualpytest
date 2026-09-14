#!/usr/bin/env python3
"""
Comprehensive Test for Multi-Agent Platform
Tests all Phase 1 components end-to-end
"""

import asyncio
import sys
import os

# Add all required paths
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
backend_src = os.path.join(project_root, 'backend_server', 'src')

sys.path.insert(0, backend_src)
sys.path.insert(0, project_root)

# Set PYTHONPATH for subprocesses
os.environ['PYTHONPATH'] = f"{backend_src}:{project_root}:" + os.environ.get('PYTHONPATH', '')

# Now import - these will work because we're in the right directory context
from events.event_bus import get_event_bus, Event, EventPriority
from resources.lock_manager import get_lock_manager
from agent.registry.registry import get_agent_registry
from agent.registry.validator import validate_agent_yaml, export_agent_yaml
from agent.registry.config_schema import (
    AgentDefinition,
    AgentMetadata,
    AgentGoal,
    AgentGoalType,
    EventTrigger
)
from agent.runtime.runtime import get_agent_runtime
from events.event_router import get_event_router


async def test_1_event_bus():
    """Test 1: Event Bus - Pub/Sub functionality"""
    print("\n" + "="*60)
    print("TEST 1: Event Bus")
    print("="*60)
    
    bus = get_event_bus()
    await bus.connect()
    
    # Test subscription
    received_events = []
    
    async def handler(event):
        received_events.append(event)
        print(f"  ✓ Received event: {event.type}")
    
    await bus.subscribe("test.event", handler)
    await bus.start()
    
    # Test publishing
    event = Event(
        type="test.event",
        payload={"message": "Test message"},
        priority=EventPriority.HIGH
    )
    
    await bus.publish(event)
    await asyncio.sleep(0.5)  # Wait for processing
    
    assert len(received_events) == 1, "Should receive 1 event"
    assert received_events[0].id == event.id, "Event ID should match"
    
    print("✅ Event Bus test PASSED")
    return True


async def test_2_lock_manager():
    """Test 2: Resource Lock Manager - Lock acquisition and queuing"""
    print("\n" + "="*60)
    print("TEST 2: Resource Lock Manager")
    print("="*60)
    
    lock_mgr = get_lock_manager()
    await lock_mgr.start()
    
    # Test lock acquisition
    acquired = await lock_mgr.acquire(
        resource_id="test-device-1",
        resource_type="device",
        owner_id="test-agent-1",
        timeout_seconds=60
    )
    
    assert acquired == True, "First lock should be acquired"
    print("  ✓ Lock acquired successfully")
    
    # Test lock conflict (same resource)
    acquired2 = await lock_mgr.acquire(
        resource_id="test-device-1",
        resource_type="device",
        owner_id="test-agent-2",
        timeout_seconds=60
    )
    
    assert acquired2 == False, "Second lock should be queued"
    print("  ✓ Lock conflict detected, request queued")
    
    # Test status
    status = await lock_mgr.get_status("test-device-1")
    assert status['status'] == 'locked', "Resource should be locked"
    assert status['owner_id'] == "test-agent-1", "Owner should match"
    assert status['queue_length'] == 1, "Should have 1 in queue"
    print("  ✓ Lock status correct")
    
    # Test release
    released = await lock_mgr.release("test-device-1", "test-agent-1")
    assert released == True, "Lock should be released"
    print("  ✓ Lock released successfully")
    
    await lock_mgr.stop()
    print("✅ Lock Manager test PASSED")
    return True


async def test_3_agent_registry():
    """Test 3: Agent Registry - CRUD and versioning"""
    print("\n" + "="*60)
    print("TEST 3: Agent Registry")
    print("="*60)
    
    registry = get_agent_registry()
    
    # Create test agent
    agent = AgentDefinition(
        metadata=AgentMetadata(
            id="test-agent",
            name="Test Agent",
            version="1.0.0",
            author="test-suite",
            description="Test agent for validation"
        ),
        goal=AgentGoal(
            type=AgentGoalType.ON_DEMAND,
            description="Test agent goal for validation purposes"
        ),
        triggers=[
            EventTrigger(type="test.trigger", priority="high")
        ],
        skills=["test_skill_1", "test_skill_2"]
    )
    
    # Test registration
    agent_id = await registry.register(agent, team_id='test-team')
    assert agent_id is not None, "Agent should be registered"
    print("  ✓ Agent registered successfully")
    
    # Test retrieval
    retrieved = await registry.get("test-agent", "1.0.0", team_id='test-team')
    assert retrieved is not None, "Agent should be retrievable"
    assert retrieved.metadata.name == "Test Agent", "Agent data should match"
    print("  ✓ Agent retrieved successfully")
    
    # Test listing
    agents = await registry.list_agents(team_id='test-team')
    assert len(agents) > 0, "Should have at least one agent"
    print("  ✓ Agent listing works")
    
    # Test publish
    success = await registry.publish("test-agent", "1.0.0", team_id='test-team')
    assert success == True, "Agent should be published"
    print("  ✓ Agent published successfully")
    
    # Test event-based lookup
    agents_for_event = await registry.get_agents_for_event("test.trigger", team_id='test-team')
    assert len(agents_for_event) > 0, "Should find agents for event"
    print("  ✓ Event-based agent lookup works")
    
    # Cleanup
    await registry.delete("test-agent", "1.0.0", team_id='test-team')
    print("  ✓ Cleanup completed")
    
    print("✅ Agent Registry test PASSED")
    return True


async def test_4_yaml_import_export():
    """Test 4: YAML Import/Export"""
    print("\n" + "="*60)
    print("TEST 4: YAML Import/Export")
    print("="*60)
    
    # Load template
    template_path = os.path.join(
        os.path.dirname(__file__), 
        '..', 
        'backend_server', 
        'src', 
        'agent', 
        'registry', 
        'templates', 
        'qa-manager.yaml'
    )
    
    with open(template_path, 'r') as f:
        yaml_content = f.read()
    
    # Test validation
    agent = validate_agent_yaml(yaml_content)
    assert agent.metadata.id == "qa-manager", "Should parse QA Manager"
    print("  ✓ YAML parsing successful")
    
    # Test export
    exported = export_agent_yaml(agent)
    assert "qa-manager" in exported, "Export should contain agent ID"
    print("  ✓ YAML export successful")
    
    # Re-import exported YAML
    reimported = validate_agent_yaml(exported)
    assert reimported.metadata.id == agent.metadata.id, "Re-import should match"
    print("  ✓ Round-trip validation successful")
    
    print("✅ YAML Import/Export test PASSED")
    return True


async def test_5_agent_runtime():
    """Test 5: Agent Runtime - Instance management"""
    print("\n" + "="*60)
    print("TEST 5: Agent Runtime")
    print("="*60)
    
    runtime = get_agent_runtime()
    registry = get_agent_registry()
    
    # Register a test agent first
    agent = AgentDefinition(
        metadata=AgentMetadata(
            id="runtime-test-agent",
            name="Runtime Test Agent",
            version="1.0.0",
            author="test-suite",
            description="Agent for runtime testing"
        ),
        goal=AgentGoal(
            type=AgentGoalType.ON_DEMAND,
            description="Test runtime instance management"
        ),
        triggers=[
            EventTrigger(type="runtime.test", priority="normal")
        ]
    )
    
    await registry.register(agent, team_id='test-team')
    await registry.publish("runtime-test-agent", "1.0.0", team_id='test-team')
    print("  ✓ Test agent registered")
    
    # Start runtime
    await runtime.start()
    print("  ✓ Runtime started")
    
    # Start agent instance
    instance_id = await runtime.start_agent("runtime-test-agent", team_id='test-team')
    assert instance_id is not None, "Instance should be created"
    print(f"  ✓ Agent instance started: {instance_id}")
    
    # Check status
    status = runtime.get_status(instance_id)
    assert status is not None, "Should get status"
    assert status['agent_id'] == "runtime-test-agent", "Agent ID should match"
    assert status['state'] == 'idle', "Should be idle initially"
    print("  ✓ Instance status retrieved")
    
    # List instances
    instances = runtime.list_instances(team_id='test-team')
    assert len(instances) > 0, "Should have running instances"
    print("  ✓ Instance listing works")
    
    # Stop instance
    stopped = await runtime.stop_agent(instance_id)
    assert stopped == True, "Instance should stop"
    print("  ✓ Instance stopped")
    
    # Cleanup
    await runtime.stop()
    await registry.delete("runtime-test-agent", "1.0.0", team_id='test-team')
    print("  ✓ Cleanup completed")
    
    print("✅ Agent Runtime test PASSED")
    return True


async def test_6_event_router():
    """Test 6: Event Router - Event routing to agents"""
    print("\n" + "="*60)
    print("TEST 6: Event Router")
    print("="*60)
    
    router = get_event_router()
    registry = get_agent_registry()
    
    # Register test agent with event trigger
    agent = AgentDefinition(
        metadata=AgentMetadata(
            id="router-test-agent",
            name="Router Test Agent",
            version="1.0.0",
            author="test-suite",
            description="Agent for router testing"
        ),
        goal=AgentGoal(
            type=AgentGoalType.ON_DEMAND,
            description="Test event routing"
        ),
        triggers=[
            EventTrigger(type="router.test.event", priority="high")
        ]
    )
    
    await registry.register(agent, team_id='test-team')
    await registry.publish("router-test-agent", "1.0.0", team_id='test-team')
    print("  ✓ Test agent registered with trigger")
    
    # Route event
    event = Event(
        type="router.test.event",
        payload={"test": "data"},
        priority=EventPriority.HIGH,
        team_id='test-team'
    )
    
    routed = await router.route_event(event)
    assert routed == True, "Event should be routed"
    print("  ✓ Event routed successfully")
    
    # Test unhandled event
    unhandled_event = Event(
        type="nonexistent.event.type",
        payload={},
        priority=EventPriority.NORMAL,
        team_id='test-team'
    )
    
    routed_unhandled = await router.route_event(unhandled_event)
    assert routed_unhandled == False, "Unhandled event should return False"
    print("  ✓ Unhandled event detected correctly")
    
    # Cleanup
    await registry.delete("router-test-agent", "1.0.0", team_id='test-team')
    print("  ✓ Cleanup completed")
    
    print("✅ Event Router test PASSED")
    return True


async def run_all_tests():
    """Run all tests in sequence"""
    print("\n" + "🚀"*30)
    print("MULTI-AGENT PLATFORM - COMPREHENSIVE TEST SUITE")
    print("🚀"*30)
    
    tests = [
        ("Event Bus", test_1_event_bus),
        ("Lock Manager", test_2_lock_manager),
        ("Agent Registry", test_3_agent_registry),
        ("YAML Import/Export", test_4_yaml_import_export),
        ("Agent Runtime", test_5_agent_runtime),
        ("Event Router", test_6_event_router),
    ]
    
    results = []
    
    for name, test_func in tests:
        try:
            result = await test_func()
            results.append((name, True, None))
        except Exception as e:
            print(f"\n❌ {name} test FAILED: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False, str(e)))
    
    # Print summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, success, _ in results if success)
    total = len(results)
    
    for name, success, error in results:
        status = "✅ PASSED" if success else f"❌ FAILED: {error}"
        print(f"{name:.<40} {status}")
    
    print("="*60)
    print(f"TOTAL: {passed}/{total} tests passed")
    print("="*60)
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED! Multi-Agent Platform is working! 🎉\n")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed\n")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(run_all_tests())
    sys.exit(exit_code)

