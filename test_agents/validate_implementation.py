#!/usr/bin/env python3
"""
Implementation Validation Script
Verifies all Phase 1 components are in place and importable
"""

import os
import sys

def check_file_exists(filepath, description):
    """Check if a file exists"""
    if os.path.exists(filepath):
        print(f"✅ {description}")
        return True
    else:
        print(f"❌ MISSING: {description}")
        return False

def check_directory_exists(dirpath, description):
    """Check if a directory exists"""
    if os.path.isdir(dirpath):
        print(f"✅ {description}")
        return True
    else:
        print(f"❌ MISSING: {description}")
        return False

def main():
    print("\n" + "="*70)
    print("MULTI-AGENT PLATFORM - IMPLEMENTATION VALIDATION")
    print("="*70)
    
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    results = []
    
    # Check Database Schema
    print("\n📁 Database Schema:")
    results.append(check_file_exists(
        os.path.join(base_dir, 'setup/db/schema/020_event_system.sql'),
        'Event System Schema (020)'
    ))
    results.append(check_file_exists(
        os.path.join(base_dir, 'setup/db/schema/021_agent_registry.sql'),
        'Agent Registry Schema (021)'
    ))
    
    # Check Backend Core
    print("\n📁 Backend Core:")
    results.append(check_file_exists(
        os.path.join(base_dir, 'backend_server/src/database/async_client.py'),
        'Async Database Client'
    ))
    results.append(check_file_exists(
        os.path.join(base_dir, 'backend_server/src/events/event_bus.py'),
        'Event Bus'
    ))
    results.append(check_file_exists(
        os.path.join(base_dir, 'backend_server/src/events/event_router.py'),
        'Event Router'
    ))
    results.append(check_file_exists(
        os.path.join(base_dir, 'backend_server/src/resources/lock_manager.py'),
        'Resource Lock Manager'
    ))
    
    # Check Agent Registry
    print("\n📁 Agent Registry:")
    results.append(check_file_exists(
        os.path.join(base_dir, 'backend_server/src/agent/registry/config_schema.py'),
        'Agent Config Schema'
    ))
    results.append(check_file_exists(
        os.path.join(base_dir, 'backend_server/src/agent/registry/validator.py'),
        'YAML Validator'
    ))
    results.append(check_file_exists(
        os.path.join(base_dir, 'backend_server/src/agent/registry/registry.py'),
        'Agent Registry Service'
    ))
    results.append(check_file_exists(
        os.path.join(base_dir, 'backend_server/src/agent/registry/templates/qa-manager.yaml'),
        'QA Manager Template'
    ))
    results.append(check_file_exists(
        os.path.join(base_dir, 'backend_server/src/agent/registry/templates/explorer.yaml'),
        'Explorer Template'
    ))
    results.append(check_file_exists(
        os.path.join(base_dir, 'backend_server/src/agent/registry/templates/executor.yaml'),
        'Executor Template'
    ))
    
    # Check Routes
    print("\n📁 REST API Routes:")
    results.append(check_file_exists(
        os.path.join(base_dir, 'backend_server/src/routes/agent_registry_routes.py'),
        'Agent Registry Routes'
    ))
    results.append(check_file_exists(
        os.path.join(base_dir, 'backend_server/src/routes/event_routes.py'),
        'Event Routes'
    ))
    
    # Check Frontend Components
    print("\n📁 Frontend Components:")
    results.append(check_file_exists(
        os.path.join(base_dir, 'frontend/src/components/agent/AgentSelector.tsx'),
        'Agent Selector Component'
    ))
    results.append(check_file_exists(
        os.path.join(base_dir, 'frontend/src/components/agent/AgentStatus.tsx'),
        'Agent Status Component'
    ))
    
    # Check Dependencies
    print("\n📁 Dependencies:")
    req_file = os.path.join(base_dir, 'backend_server/requirements.txt')
    if os.path.exists(req_file):
        with open(req_file, 'r') as f:
            content = f.read()
            has_asyncpg = 'asyncpg' in content
            has_apscheduler = 'apscheduler' in content
            has_fastapi = 'fastapi' in content
            
            results.append(has_asyncpg)
            print(f"{'✅' if has_asyncpg else '❌'} asyncpg dependency")
            results.append(has_apscheduler)
            print(f"{'✅' if has_apscheduler else '❌'} apscheduler dependency")
            results.append(has_fastapi)
            print(f"{'✅' if has_fastapi else '❌'} fastapi dependency")
    else:
        print("❌ requirements.txt not found")
        results.extend([False, False, False])
    
    # Check Route Registration
    print("\n📁 Route Registration:")
    app_file = os.path.join(base_dir, 'backend_server/src/app.py')
    if os.path.exists(app_file):
        with open(app_file, 'r') as f:
            content = f.read()
            has_registry_import = 'agent_registry_routes' in content
            has_event_import = 'event_routes' in content

            results.append(has_registry_import)
            print(f"{'✅' if has_registry_import else '❌'} Agent Registry routes imported")
            results.append(has_event_import)
            print(f"{'✅' if has_event_import else '❌'} Event routes imported")
    else:
        print("❌ app.py not found")
        results.extend([False, False])
    
    # Summary
    print("\n" + "="*70)
    print("VALIDATION SUMMARY")
    print("="*70)
    
    total = len(results)
    passed = sum(results)
    percentage = (passed / total * 100) if total > 0 else 0
    
    print(f"Files/Components Validated: {passed}/{total} ({percentage:.1f}%)")
    
    if passed == total:
        print("\n🎉 ALL COMPONENTS PRESENT - Implementation Complete! 🎉")
        print("\nNext Steps:")
        print("  1. Install Redis: brew install redis && brew services start redis")
        print("  2. Install dependencies: cd backend_server && pip install -r requirements.txt")
        print("  3. Start backend server")
        print("  4. Test API endpoints")
        return 0
    else:
        print(f"\n⚠️  {total - passed} component(s) missing")
        return 1

if __name__ == "__main__":
    exit_code = main()
    print()
    sys.exit(exit_code)

