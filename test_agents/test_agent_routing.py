#!/usr/bin/env python3
"""
Test Agent ID Routing
Validates that frontend agent selection correctly routes to backend agent configurations
"""

import sys
import os

# Add all required paths
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
backend_src = os.path.join(project_root, 'backend_server', 'src')
shared_src = project_root  # shared is at project root

sys.path.insert(0, backend_src)
sys.path.insert(0, shared_src)

# Set PYTHONPATH for subprocesses
os.environ['PYTHONPATH'] = f"{backend_src}:{shared_src}:" + os.environ.get('PYTHONPATH', '')


def test_1_agent_configs_exist():
    """Test 1: All agent configs are defined"""
    print("\n" + "="*60)
    print("TEST 1: Agent Configs Exist")
    print("="*60)
    
    from agent.core.manager import QAManagerAgent
    
    expected_agents = [
        'ai-assistant',
        'qa-web-manager', 
        'qa-mobile-manager',
        'qa-stb-manager',
        'monitoring-manager'
    ]
    
    for agent_id in expected_agents:
        assert agent_id in QAManagerAgent.AGENT_CONFIGS, f"Missing config for {agent_id}"
        config = QAManagerAgent.AGENT_CONFIGS[agent_id]
        assert 'name' in config, f"Missing 'name' in {agent_id}"
        assert 'nickname' in config, f"Missing 'nickname' in {agent_id}"
        assert 'specialty' in config, f"Missing 'specialty' in {agent_id}"
        assert 'platform' in config, f"Missing 'platform' in {agent_id}"
        print(f"  ✓ {agent_id}: {config['nickname']} ({config['platform']})")
    
    print("✅ All agent configs exist")
    return True


def test_2_agent_routing():
    """Test 2: Agent ID routes to correct config"""
    print("\n" + "="*60)
    print("TEST 2: Agent Routing")
    print("="*60)
    
    from agent.core.manager import QAManagerAgent
    
    test_cases = [
        ('ai-assistant', 'Atlas', 'all'),
        ('qa-web-manager', 'Sherlock', 'web'),
        ('qa-mobile-manager', 'Scout', 'mobile'),
        ('qa-stb-manager', 'Watcher', 'stb'),
        ('monitoring-manager', 'Guardian', 'all'),
    ]
    
    for agent_id, expected_nickname, expected_platform in test_cases:
        mgr = QAManagerAgent(agent_id=agent_id)
        
        assert mgr.agent_id == agent_id, f"Expected agent_id={agent_id}, got {mgr.agent_id}"
        assert mgr.agent_config['nickname'] == expected_nickname, \
            f"Expected nickname={expected_nickname}, got {mgr.agent_config['nickname']}"
        assert mgr.agent_config['platform'] == expected_platform, \
            f"Expected platform={expected_platform}, got {mgr.agent_config['platform']}"
        
        print(f"  ✓ {agent_id} → {expected_nickname} ({expected_platform})")
    
    print("✅ Agent routing works correctly")
    return True


def test_3_default_agent():
    """Test 3: Default agent when no ID provided"""
    print("\n" + "="*60)
    print("TEST 3: Default Agent")
    print("="*60)
    
    from agent.core.manager import QAManagerAgent
    
    # Test with None
    mgr1 = QAManagerAgent(agent_id=None)
    assert mgr1.agent_id == 'ai-assistant', f"Expected ai-assistant, got {mgr1.agent_id}"
    print(f"  ✓ agent_id=None → ai-assistant (Atlas)")
    
    # Test with empty string (should fallback)
    mgr2 = QAManagerAgent(agent_id='')
    assert mgr2.agent_id == 'ai-assistant' or mgr2.agent_config['nickname'] == 'Atlas'
    print(f"  ✓ agent_id='' → fallback to Atlas")
    
    # Test with unknown ID (should fallback gracefully)
    mgr3 = QAManagerAgent(agent_id='unknown-agent')
    assert mgr3.agent_config is not None, "Should have fallback config"
    print(f"  ✓ agent_id='unknown-agent' → fallback config")
    
    print("✅ Default agent handling works")
    return True


def test_4_system_prompt_customization():
    """Test 4: System prompt contains agent-specific content"""
    print("\n" + "="*60)
    print("TEST 4: System Prompt Customization")
    print("="*60)
    
    from agent.core.manager import QAManagerAgent
    
    test_cases = [
        ('qa-web-manager', ['Sherlock', 'Web testing', 'web']),
        ('qa-mobile-manager', ['Scout', 'Mobile testing', 'mobile']),
        ('qa-stb-manager', ['Watcher', 'Set-top box', 'stb']),
        ('monitoring-manager', ['Guardian', 'monitoring', 'all']),
    ]
    
    for agent_id, expected_strings in test_cases:
        mgr = QAManagerAgent(agent_id=agent_id)
        prompt = mgr.system_prompt
        
        for expected in expected_strings:
            assert expected.lower() in prompt.lower(), \
                f"Expected '{expected}' in system prompt for {agent_id}"
        
        print(f"  ✓ {agent_id}: prompt contains {expected_strings}")
    
    print("✅ System prompts are customized correctly")
    return True


def test_5_sub_agents_initialized():
    """Test 5: Sub-agents are initialized for all managers"""
    print("\n" + "="*60)
    print("TEST 5: Sub-Agents Initialized")
    print("="*60)
    
    from agent.core.manager import QAManagerAgent
    
    mgr = QAManagerAgent(agent_id='qa-web-manager')
    
    expected_subagents = ['explorer', 'builder', 'executor', 'analyst', 'maintainer']
    
    for subagent in expected_subagents:
        assert subagent in mgr.agents, f"Missing sub-agent: {subagent}"
        assert mgr.agents[subagent] is not None, f"Sub-agent {subagent} is None"
        print(f"  ✓ {subagent}: initialized")
    
    print("✅ All sub-agents initialized")
    return True


def run_all_tests():
    """Run all tests"""
    print("\n" + "🚀"*30)
    print("AGENT ROUTING TEST SUITE")
    print("🚀"*30)
    
    tests = [
        ("Agent Configs Exist", test_1_agent_configs_exist),
        ("Agent Routing", test_2_agent_routing),
        ("Default Agent", test_3_default_agent),
        ("System Prompt Customization", test_4_system_prompt_customization),
        ("Sub-Agents Initialized", test_5_sub_agents_initialized),
    ]
    
    results = []
    
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, True, None))
        except Exception as e:
            print(f"\n❌ {name} FAILED: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False, str(e)))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, success, _ in results if success)
    total = len(results)
    
    for name, success, error in results:
        status = "✅ PASSED" if success else f"❌ FAILED: {error}"
        print(f"{name:.<45} {status}")
    
    print("="*60)
    print(f"TOTAL: {passed}/{total} tests passed")
    print("="*60)
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED! Agent routing is working! 🎉\n")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed\n")
        return 1


if __name__ == "__main__":
    exit_code = run_all_tests()
    sys.exit(exit_code)

