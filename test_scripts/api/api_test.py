#!/usr/bin/env python3
"""
API Testing Script for VirtualPyTest

This script tests API endpoints and validates responses.

Usage:
    python test_scripts/api/api_test.py --profile sanity
    python test_scripts/api/api_test.py --profile full
    python test_scripts/api/api_test.py --endpoints "/health,/devices/getAllDevices"
    python test_scripts/api/api_test.py --spec server-device-management
    
Examples:
    Quick health check:
        python test_scripts/api/api_test.py --profile sanity
    
    Full API validation:
        python test_scripts/api/api_test.py --profile full
    
    Custom endpoints:
        python test_scripts/api/api_test.py --endpoints "/server/health,/server/devices/getAllDevices"
    
    Test specific OpenAPI spec:
        python test_scripts/api/api_test.py --spec server-device-management
"""

import sys
import os
import time
import json
import requests
import yaml
from pathlib import Path

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_args, get_context


def load_profile(profile_name: str) -> dict:
    """Load predefined test profile from JSON file"""
    profiles_path = Path(current_dir) / "api_profiles.json"
    
    if not profiles_path.exists():
        print(f"❌ [load_profile] Profiles file not found: {profiles_path}")
        return None
    
    try:
        with open(profiles_path, 'r') as f:
            profiles = json.load(f)
        return profiles.get(profile_name)
    except Exception as e:
        print(f"❌ [load_profile] Error loading profiles: {e}")
        return None


def load_spec_endpoints(spec_name: str, server_url: str) -> dict:
    """Load endpoints from OpenAPI spec file"""
    spec_path = Path(project_root) / "docs" / "openapi" / "specs" / f"{spec_name}.yaml"
    
    if not spec_path.exists():
        print(f"❌ [load_spec] Spec file not found: {spec_path}")
        return None
    
    try:
        with open(spec_path, 'r') as f:
            spec = yaml.safe_load(f)
        
        endpoints = []
        paths = spec.get('paths', {})
        
        for path, methods in paths.items():
            for method, details in methods.items():
                if method.upper() in ['GET', 'POST', 'PUT', 'DELETE', 'PATCH']:
                    endpoints.append({
                        "path": path,
                        "method": method.upper(),
                        "expected_status": 200,
                        "description": details.get('summary', '')
                    })
        
        return {
            "name": f"OpenAPI Spec: {spec_name}",
            "description": spec.get('info', {}).get('description', ''),
            "endpoints": endpoints
        }
    except Exception as e:
        print(f"❌ [load_spec] Error loading spec: {e}")
        return None


def parse_custom_endpoints(endpoints_str: str) -> dict:
    """Parse custom endpoint list from command line"""
    if not endpoints_str or not endpoints_str.strip():
        return None
    
    endpoint_paths = [e.strip() for e in endpoints_str.split(',') if e.strip()]
    
    endpoints = []
    for path in endpoint_paths:
        endpoints.append({
            "path": path,
            "method": "GET",  # Default to GET
            "expected_status": 200
        })
    
    return {
        "name": "Custom Endpoint List",
        "description": f"Testing {len(endpoints)} custom endpoints",
        "endpoints": endpoints
    }


def test_endpoint(endpoint: dict, server_url: str, context) -> dict:
    """Test a single API endpoint and record as step"""
    path = endpoint['path']
    method = endpoint.get('method', 'GET')
    expected_status = endpoint.get('expected_status', 200)
    description = endpoint.get('description', '')
    
    url = f"{server_url}{path}"
    
    step_data = {
        "action": f"{method} {path}",
        "description": description or f"Test {method} {path}",
        "timestamp": time.time(),
        "success": False,
        "error": None,
        "response_time_ms": 0,
        "status_code": None,
    }
    
    try:
        start_time = time.time()

        # Add team_id query param if needed (for endpoints that require it)
        params = {}
        if 'team_id' in path or any(x in path for x in ['devices', 'campaigns', 'testcase', 'requirements']):
            params['team_id'] = context.team_id

        # Build headers with API key auth (mirrors _helpers.js:apiHeaders())
        headers = {'Content-Type': 'application/json'}
        api_key = os.getenv('API_KEY', '')
        if api_key:
            headers['X-API-Key'] = api_key
            headers['Authorization'] = f'Bearer {api_key}'

        # Make request
        response = requests.request(
            method=method,
            url=url,
            params=params,
            headers=headers,
            timeout=10
        )
        
        response_time = (time.time() - start_time) * 1000  # ms
        
        step_data['response_time_ms'] = round(response_time, 2)
        step_data['status_code'] = response.status_code
        
        # Check if status matches expected
        if response.status_code == expected_status:
            step_data['success'] = True
            print(f"✅ {method} {path}: {response.status_code} ({response_time:.0f}ms)")
        else:
            step_data['success'] = False
            step_data['error'] = f"Expected status {expected_status}, got {response.status_code}"
            print(f"❌ {method} {path}: {response.status_code} (expected {expected_status})")
        
    except requests.exceptions.Timeout:
        step_data['error'] = "Request timeout (10s)"
        print(f"❌ {method} {path}: Timeout")
    except requests.exceptions.ConnectionError:
        step_data['error'] = "Connection error"
        print(f"❌ {method} {path}: Connection error")
    except Exception as e:
        step_data['error'] = str(e)
        print(f"❌ {method} {path}: {e}")
    
    return step_data


def capture_execution_summary(context, test_config: dict, server_url: str) -> str:
    """Capture execution summary as text for report - matches validation.py format"""
    
    # Get actual step counts from context.step_results
    total_steps = len(context.step_results)
    successful_steps = sum(1 for step in context.step_results if step.get('success', False))
    failed_steps = total_steps - successful_steps
    
    # Calculate average response time
    response_times = [step.get('response_time_ms', 0) for step in context.step_results if step.get('response_time_ms')]
    avg_response_time = sum(response_times) / len(response_times) if response_times else 0
    
    lines = []
    lines.append("-"*60)
    lines.append("🎯 [API TEST] EXECUTION SUMMARY")
    lines.append("-"*60)
    lines.append(f"📋 Test Profile: {test_config['name']}")
    lines.append(f"📝 Description: {test_config['description']}")
    lines.append(f"🌐 Server URL: {server_url}")
    lines.append(f"⏱️ Total Time: {context.get_execution_time_ms()/1000:.1f}s")
    lines.append(f"⚡ Avg Response Time: {avg_response_time:.0f}ms")
    lines.append(f"📊 Endpoints Tested: {total_steps}")
    lines.append(f"✅ Successful: {successful_steps}")
    lines.append(f"❌ Failed: {failed_steps}")
    
    # Calculate success rate
    if total_steps > 0:
        success_rate = (successful_steps / total_steps * 100)
        lines.append(f"🎯 Success Rate: {success_rate:.1f}%")
    else:
        lines.append(f"🎯 Success Rate: 0.0% (no endpoints tested)")
    
    lines.append(f"🎯 Result: {'SUCCESS' if context.overall_success else 'FAILED'}")
    
    if context.error_message:
        lines.append(f"\n❌ Error: {context.error_message}")
    
    # Show failed endpoints if any
    if failed_steps > 0:
        lines.append(f"\n❌ Failed Endpoints:")
        for step in context.step_results:
            if not step.get('success', False):
                action = step.get('action', 'unknown')
                error = step.get('error', 'unknown error')
                status = step.get('status_code', 'N/A')
                lines.append(f"   • {action} - {error} (status: {status})")
    
    lines.append("-"*60)
    
    return "\n".join(lines)


def execute_api_tests(profile: str = None, endpoints: str = None, spec: str = None) -> bool:
    """Execute API tests based on profile, custom endpoints, or OpenAPI spec"""
    context = get_context()
    args = get_args()
    
    # Get server URL from environment or use default
    server_url = os.getenv('SERVER_URL', 'http://localhost:5109')
    
    # Determine test configuration
    test_config = None
    
    if spec:
        # Mode 3: Load from OpenAPI spec
        print(f"📋 [api_test] Loading endpoints from OpenAPI spec: {spec}")
        test_config = load_spec_endpoints(spec, server_url)
    elif endpoints:
        # Mode 2: Custom endpoint list
        print(f"📋 [api_test] Testing custom endpoints")
        test_config = parse_custom_endpoints(endpoints)
    elif profile:
        # Mode 1: Predefined profile
        print(f"📋 [api_test] Loading profile: {profile}")
        test_config = load_profile(profile)
    else:
        # Default to sanity check
        print(f"📋 [api_test] No mode specified, using default 'sanity' profile")
        test_config = load_profile('sanity')
    
    if not test_config:
        context.error_message = "No valid test configuration found"
        print(f"❌ [api_test] {context.error_message}")
        return False
    
    endpoints_to_test = test_config.get('endpoints', [])
    
    if not endpoints_to_test:
        context.error_message = "No endpoints to test"
        print(f"❌ [api_test] {context.error_message}")
        return False
    
    print(f"✅ [api_test] Found {len(endpoints_to_test)} endpoints to test")
    print(f"🌐 [api_test] Server URL: {server_url}")
    
    # Test each endpoint
    for i, endpoint in enumerate(endpoints_to_test, 1):
        print(f"\n⚡ [api_test] Testing {i}/{len(endpoints_to_test)}: {endpoint.get('method', 'GET')} {endpoint['path']}")
        
        # Test endpoint and record as step
        step_result = test_endpoint(endpoint, server_url, context)
        
        # Record step in context (like validation.py does)
        context.step_results.append(step_result)
    
    # Calculate success from context.step_results (matches validation.py logic)
    total_steps = len(context.step_results)
    successful_steps = sum(1 for step in context.step_results if step.get('success', False))
    
    # Set overall success
    context.overall_success = (successful_steps == total_steps and total_steps > 0)
    
    success_rate = (successful_steps / total_steps * 100) if total_steps else 0
    print(f"\n🎉 [api_test] Results: {successful_steps}/{total_steps} endpoints successful ({success_rate:.1f}%)")
    
    # Capture summary for report
    summary_text = capture_execution_summary(context, test_config, server_url)
    context.execution_summary = summary_text
    
    return context.overall_success


@script("api_test", "Test API endpoints and validate responses")
def main():
    """Main API test function - matches validation.py pattern"""
    context = get_context()
    args = get_args()

    # Execute API tests based on provided arguments
    result = execute_api_tests(
        profile=args.profile,
        endpoints=args.endpoints,
        spec=args.spec
    )
    
    return result


# Script arguments (matches validation.py pattern)
main._script_args = [
    '--profile:str::sanity|full|devices|campaigns',
    '--endpoints:str:',    # Custom comma-separated endpoint list
    '--spec:str:',         # OpenAPI spec name (e.g., server-device-management)
]
main._script_description = "Test API endpoints and validate responses."
main._arg_descriptions = {
    'profile': 'Test profile (smoke, sanity, full, etc.)',
    'endpoints': 'Comma-separated endpoint paths',
    'spec': 'OpenAPI spec name without .yaml',
}

if __name__ == "__main__":
    main()
