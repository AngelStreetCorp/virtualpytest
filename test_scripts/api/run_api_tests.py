#!/usr/bin/env python3
"""
Standalone API test runner for CI.

No VPT framework dependencies — only requires `requests` and `pyyaml`.
Reads the same api_profiles.json as api_test.py.

Usage:
    python test_scripts/api/run_api_tests.py --profile smoke
    python test_scripts/api/run_api_tests.py --profile full
    python test_scripts/api/run_api_tests.py --endpoints "/server/system/health,/server/script/list"
    python test_scripts/api/run_api_tests.py --discover   # every GET route the server registers

Environment variables:
    SERVER_URL   Base URL of the backend server (default: http://localhost:5109)
    API_KEY      API key sent as X-API-Key and Authorization: Bearer headers
    TEAM_ID      Team ID appended as ?team_id= for endpoints that need it
"""

import argparse
import html as html_module
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests
import urllib3
import yaml

# Self-signed certs are common in VPT deployments — suppress the noise
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CURRENT_DIR = Path(__file__).parent
PROJECT_ROOT = CURRENT_DIR.parent.parent

_script_description = "Standalone API test runner for CI and local use."


# ---------------------------------------------------------------------------
# Minimal execution context (replaces ScriptExecutionContext from VPT)
# ---------------------------------------------------------------------------

@dataclass
class SimpleContext:
    step_results: list = field(default_factory=list)
    overall_success: bool = False
    error_message: str = ''
    team_id: str = ''
    start_time: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Shared helpers (kept in sync with api_test.py)
# ---------------------------------------------------------------------------

def load_profile(profile_name: str) -> dict:
    """Load a predefined test profile from api_profiles.json."""
    profiles_path = CURRENT_DIR / 'api_profiles.json'

    if not profiles_path.exists():
        print(f'ERROR: Profiles file not found: {profiles_path}')
        return None

    try:
        with open(profiles_path) as f:
            profiles = json.load(f)
        return profiles.get(profile_name)
    except Exception as e:
        print(f'ERROR: Could not load profiles: {e}')
        return None


def load_spec_endpoints(spec_name: str) -> dict:
    """Load endpoints from an OpenAPI spec YAML file."""
    spec_path = PROJECT_ROOT / 'docs' / 'openapi' / 'specs' / f'{spec_name}.yaml'

    if not spec_path.exists():
        print(f'ERROR: Spec file not found: {spec_path}')
        return None

    try:
        with open(spec_path) as f:
            spec = yaml.safe_load(f)

        endpoints = []
        for path, methods in spec.get('paths', {}).items():
            for method, details in methods.items():
                if method.upper() in ('GET', 'POST', 'PUT', 'DELETE', 'PATCH'):
                    endpoints.append({
                        'path': path,
                        'method': method.upper(),
                        'expected_status': 200,
                        'description': details.get('summary', ''),
                    })

        return {
            'name': f'OpenAPI Spec: {spec_name}',
            'description': spec.get('info', {}).get('description', ''),
            'endpoints': endpoints,
        }
    except Exception as e:
        print(f'ERROR: Could not load spec: {e}')
        return None


def parse_custom_endpoints(endpoints_str: str) -> dict:
    """Parse a comma-separated list of endpoint paths."""
    if not endpoints_str or not endpoints_str.strip():
        return None

    paths = [p.strip() for p in endpoints_str.split(',') if p.strip()]
    return {
        'name': 'Custom Endpoint List',
        'description': f'Testing {len(paths)} custom endpoints',
        'endpoints': [{'path': p, 'method': 'GET', 'expected_status': 200} for p in paths],
    }


def build_headers() -> dict:
    """Auth headers (mirrors _helpers.js:apiHeaders()): API_KEY as X-API-Key + Bearer."""
    headers = {'Content-Type': 'application/json'}
    api_key = os.getenv('API_KEY', '')
    if api_key:
        headers['X-API-Key'] = api_key
        headers['Authorization'] = f'Bearer {api_key}'
    return headers


def test_endpoint(endpoint: dict, server_url: str, context: SimpleContext) -> dict:
    """Test a single API endpoint and return a step result dict."""
    path = endpoint['path']
    method = endpoint.get('method', 'GET')
    expected_status = endpoint.get('expected_status', 200)
    description = endpoint.get('description', '')

    url = f'{server_url}{path}'

    step_data = {
        'action': f'{method} {path}',
        'description': description or f'Test {method} {path}',
        'timestamp': time.time(),
        'success': False,
        'skipped': False,
        'error': None,
        'response_time_ms': 0,
        'status_code': None,
    }

    if endpoint.get('skip_reason'):
        step_data['skipped'] = True
        step_data['error'] = endpoint['skip_reason']
        print(f'  SKIP  {method} {path}  —  {endpoint["skip_reason"]}')
        return step_data

    try:
        # Add team_id query param where needed (always for discovered routes: most
        # list routes 400 without it and the extra param is ignored by the rest)
        params = dict(endpoint.get('params') or {})
        if endpoint.get('policy') == 'discover' or 'team_id' in path or any(
            x in path for x in ('devices', 'campaigns', 'testcase', 'requirements', 'script', 'deployment')
        ):
            if context.team_id:
                params.setdefault('team_id', context.team_id)

        headers = build_headers()

        start = time.time()
        response = requests.request(
            method=method,
            url=url,
            params=params,
            headers=headers,
            timeout=10,
            verify=False,
        )
        elapsed = (time.time() - start) * 1000

        step_data['response_time_ms'] = round(elapsed, 2)
        step_data['status_code'] = response.status_code
        step_data['request_headers'] = {k: v for k, v in headers.items() if k.lower() not in ('authorization', 'x-api-key')}
        step_data['request_params'] = params
        # Capture response body (truncated to 4KB)
        try:
            body = response.json()
            import json as _json
            step_data['response_body'] = _json.dumps(body, indent=2)[:4096]
        except Exception:
            step_data['response_body'] = response.text[:4096]

        if endpoint.get('policy') == 'discover':
            ok, error = discover_verdict(endpoint, response.status_code)
        else:
            ok = response.status_code == expected_status
            error = None if ok else f'Expected {expected_status}, got {response.status_code}'
        step_data['success'] = ok
        step_data['error'] = error
        if ok:
            print(f'  PASS  {method} {path}  →  {response.status_code}  ({elapsed:.0f}ms)')
        else:
            print(f'  FAIL  {method} {path}  →  {response.status_code}  ({error})')

    except requests.exceptions.Timeout:
        step_data['error'] = 'Request timeout (10s)'
        print(f'  FAIL  {method} {path}  →  timeout')
    except requests.exceptions.ConnectionError:
        step_data['error'] = 'Connection error'
        print(f'  FAIL  {method} {path}  →  connection error')
    except Exception as e:
        step_data['error'] = str(e)
        print(f'  FAIL  {method} {path}  →  {e}')

    return step_data



# ---------------------------------------------------------------------------
# Route discovery (--discover): every GET route the running server registers
# ---------------------------------------------------------------------------
#
# The server lists its own url_map at GET /server/api-testing/config, including
# parametrized rules with their placeholder names. We hit every GET rule once:
#   - static rules as-is
#   - parametrized rules with ids resolved from the matching list endpoint
#     (RESOLVERS); a rule whose id cannot be resolved is reported as SKIP.
# Pass/fail for discovered routes is a liveness contract, not an exact-status one
# (that lives in tests/backend_server): 2xx passes, 401/403 pass (the API key is
# not an admin JWT), 404 fails unless the route is in ALLOW_404, 5xx/timeout fail.

#: Rules that cannot be exercised with a plain GET. Reason shown in the report.
SKIP_ROUTES = {
    '/server/<path:endpoint>': 'auto_proxy catch-all — forwards to a host, needs host_name',
    '/server/monitoring/proxyImage/<filename>': 'binary proxy to a host capture file',
    '/server/cicd/report/<run>/<path:filename>': 'static file serving of an uploaded report',
    '/server/api-testing/config': 'the discovery endpoint itself (fetched to build this list)',
    # These GETs forward to a host: they measure host availability, not server health.
    '/server/system/diskUsage': 'proxies to a host (host_name) — host availability, not server health',
    '/server/system/getDeviceActions': 'proxies to a host (host_name) — host availability, not server health',
    '/server/system/getStreamQuality': 'proxies to a host (host_name) — host availability, not server health',
    '/server/postman/environments': 'needs a Postman workspaceId from a user-linked Postman account',
    '/server/validation/preview/<tree_id>': 'proxies to a host (host_name) — host availability, not server health',
    '/server/testcase/<testcase_id>/history': 'proxies to a host (host_name) — host availability, not server health',
    '/server/navigation/preview/<tree_id>/<node_id>': 'proxies to a host (host_name) — host availability, not server health',
    '/server/postman/workspaces/<workspace_id>/collections': 'workspace_id here is a Postman workspace (user-linked account), not a VPT one',
    '/server/postman/workspaces/<workspace_id>/environments': 'workspace_id here is a Postman workspace (user-linked account), not a VPT one',
}

#: Query params a route requires beyond team_id. ``{name}`` tokens go through RESOLVERS.
EXTRA_PARAMS = {
    '/server/benchmarks/compare': {'agents': '{agent_id}'},
    '/server/cicd/branches': {'project': '{project}'},
    '/server/monitoring/avq': {'device_id': '{device_id}'},
    '/server/monitoring/zaps': {'device_name': '{device_name}'},
    '/server/navigationTrees/kpi-action-sets': {'userinterface_name': '{interface_name}'},
    '/server/navigationTrees/lockStatus': {'userinterface_id': '{userinterface_id}'},
    '/server/navigationTrees/nodes': {'userinterface_name': '{interface_name}'},
    '/server/userinterface/domReport': {'userinterface': '{interface_name}'},
    '/server/userinterface/getCompatibleInterfaces': {'device_model': '{device_model}'},
}

#: Routes where 404 is the healthy answer when the underlying artifact was never generated.
ALLOW_404 = {
    '/server/security/dashboard': 'docs/security dashboard not generated on this server',
    '/server/security/reports/<report_name>': 'security report not generated on this server',
    '/server/script/identity-map': 'script_identity_map.json is an optional generated file',
    '/server/agents/<agent_id>/export': 'agent registry may hold no exportable agent',
    '/server/pathfinding/stats/<tree_id>': 'unified graph is built on first navigation; 404 until a host loads the tree',
}

#: Some list rows are unusable as ids for a given placeholder; the first row passing wins.
PICK_FILTERS = {
    'script_name': lambda value: '/' not in value,   # 'android/app_install' breaks a <script_name> segment
}

#: How to turn a Flask placeholder into a real id.
#: (param, path_filter, list_path, id_keys) — path_filter narrows a param name that
#: means different things on different routes (jira instance vs runtime instance).
#: list_path may reference an already-resolved param, e.g. {tree_id}.
RESOLVERS = [
    ('team_id',          None,             '$TEAM_ID',                                     ()),
    ('report_id',        None,             '$CONST:smoke',                                 ()),
    ('report_name',      None,             '$CONST:server-report',                         ()),
    ('testcase_id',      None,             '/server/testcase/list',                        ('testcase_id', 'id')),
    ('requirement_id',   None,             '/server/requirements/list',                    ('id', 'requirement_id')),
    ('requirement_code', None,             '/server/requirements/list',                    ('code', 'requirement_code')),
    ('campaign_id',      None,             '/server/campaigns/getAllCampaigns',            ('campaign_id', 'id')),
    ('deployment_id',    None,             '/server/deployment/list',                      ('id', 'deployment_id')),
    ('device_id',        None,             '/server/devices/getAllDevices',                ('device_id', 'id')),
    ('device_name',      None,             '/server/devices/getAllDevices',                ('device_name', 'name')),
    ('device_model',     None,             '/server/devicemodel/getAllModels',             ('name', 'model_name')),
    ('host_name',        None,             '/server/system/getAllHosts',                   ('host_name', 'name')),
    ('model_id',         None,             '/server/devicemodel/getAllModels',             ('id', 'model_id')),
    ('user_id',          None,             '/server/users',                                ('id', 'user_id')),
    ('workspace_id',     None,             '/server/workspaces/user/{user_id}',            ('id', 'workspace_id')),
    ('tree_id',          None,             '/server/navigationTrees',                      ('id', 'tree_id')),
    ('node_id',          None,             '/server/navigationTrees/{tree_id}/nodes',      ('node_id', 'id')),
    ('edge_id',          None,             '/server/navigationTrees/{tree_id}/edges',      ('edge_id', 'id')),
    ('userinterface_id', None,             '/server/userinterface/getAllUserInterfaces',   ('id', 'userinterface_id')),
    ('interface_id',     None,             '/server/userinterface/getAllUserInterfaces',   ('id', 'userinterface_id')),
    ('ui_id',            None,             '/server/ai_userinterface/list',                ('id', 'ai_userinterface_id')),
    ('ai_userinterface_id', None,          '/server/ai_userinterface/list',                ('id', 'ai_userinterface_id')),
    ('campaign_result_id', None,           '/server/campaign-results/getAllCampaignResults', ('campaign_execution_id', 'id')),
    ('run_id',           '/benchmarks/',   '/server/benchmarks/runs',                      ('id', 'run_id')),
    ('interface_name',   None,             '/server/userinterface/getAllUserInterfaces',   ('name', 'userinterface_name')),
    ('script_result_id', None,             '/server/script-results/getAllScriptResults',   ('id', 'script_result_id')),
    ('script_id',        None,             '/server/virtual-script/list',                  ('id', 'script_id')),
    ('script_name',      None,             '/server/script/list',                          ('name', 'script_name')),
    ('prompt_id',        None,             '/server/testprompt/list',                      ('id', 'prompt_id')),
    ('agent_id',         None,             '/server/agents/',                              ('metadata.id', 'agent_id', 'id')),
    ('instance_id',      '/integrations/jira/', '/server/integrations/jira/instances',     ('id', 'instance_id')),
    ('instance_id',      '/runtime/',      '/server/runtime/instances',                    ('instance_id', 'id')),
    ('project',          None,             '/server/cicd/runs',                            ('project',)),
    ('run',              None,             '/server/cicd/runs',                            ('run',)),
]


def _rows_of(body):
    """Find the list of rows in a list-endpoint response (bare list, or first list value)."""
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for value in body.values():
            if isinstance(value, list) and value:
                return value
    return []


def _pick_id(row, id_keys):
    if isinstance(row, str):
        return row
    if not isinstance(row, dict):
        return None
    for key in id_keys:
        value = row
        for part in key.split('.'):          # 'metadata.id' walks nested dicts
            value = value.get(part) if isinstance(value, dict) else None
        if value not in (None, ''):
            return str(value)
    return None


def _pick_first(rows, id_keys, accept=None):
    for row in rows:
        value = _pick_id(row, id_keys)
        if value and (accept is None or accept(value)):
            return value
    return None


class ParamResolver:
    """Resolves Flask placeholders to real ids, one list call per placeholder (cached)."""

    def __init__(self, server_url: str, headers: dict, team_id: str):
        self.server_url = server_url
        self.headers = headers
        self.team_id = team_id
        self.cache: dict = {}

    def _rule_for(self, param: str, route: str):
        for name, path_filter, list_path, id_keys in RESOLVERS:
            if name == param and (path_filter is None or path_filter in route):
                return list_path, id_keys
        return None

    def resolve(self, param: str, route: str, resolved: dict):
        rule = self._rule_for(param, route)
        if rule is None:
            return None, f'no resolver for <{param}>'
        list_path, id_keys = rule
        if list_path == '$TEAM_ID':
            return (self.team_id, None) if self.team_id else (None, 'TEAM_ID not set')
        if list_path.startswith('$CONST:'):
            return list_path.split(':', 1)[1], None
        # A list path may depend on another placeholder ({tree_id}, {user_id}); resolve it
        # first, whatever order the placeholders appear in the rule.
        while True:
            try:
                list_path = list_path.format(**resolved)
                break
            except KeyError as missing:
                dep = missing.args[0]
                if dep == param:
                    return None, f'resolver for <{param}> depends on itself'
                value, why = self.resolve(dep, route, resolved)
                if value is None:
                    return None, f'needs <{dep}>: {why}'
                resolved[dep] = value
        cache_key = (list_path, id_keys, param)
        if cache_key in self.cache:
            return self.cache[cache_key]
        try:
            resp = requests.get(
                f'{self.server_url}{list_path}', headers=self.headers,
                params={'team_id': self.team_id} if self.team_id else {},
                timeout=15, verify=False,
            )
            if resp.status_code != 200:
                result = (None, f'{list_path} -> {resp.status_code}')
            else:
                rows = _rows_of(resp.json())
                value = _pick_first(rows, id_keys, PICK_FILTERS.get(param))
                result = (value, None) if value else (None, f'{list_path} returned no usable rows')
        except Exception as exc:  # noqa: BLE001 - resolution failure is a SKIP, not a crash
            result = (None, f'{list_path} -> {exc}')
        self.cache[cache_key] = result
        return result


def load_discovered_endpoints(server_url: str, headers: dict, team_id: str) -> dict:
    """Build the endpoint list from the server's own route table (GET only)."""
    url = f'{server_url}/server/api-testing/config'
    try:
        resp = requests.get(url, headers=headers, timeout=15, verify=False)
    except Exception as exc:  # noqa: BLE001
        print(f'ERROR: Could not reach {url}: {exc}')
        return None
    if resp.status_code != 200:
        print(f'ERROR: {url} -> {resp.status_code}: {resp.text[:200]}')
        return None
    body = resp.json()
    if body.get('fallback'):
        print(f'ERROR: Server route discovery failed: {body.get("error")}')
        return None

    rules = {}
    for entry in body.get('config', {}).get('endpoints', []):
        # Only url_map rules. The server also prepends its hand-written CRITICAL_ROUTES,
        # several of which name paths that no longer exist (they fall into the auto_proxy
        # catch-all and answer 400) — a fixed list is exactly what this mode replaces.
        if entry.get('category') != 'auto':
            continue
        if entry.get('method') != 'GET' or not entry.get('url'):
            continue
        rules.setdefault(entry['url'], entry.get('path_params') or [])
    if not rules:
        print('ERROR: Server returned no GET routes')
        return None

    resolver = ParamResolver(server_url, headers, team_id)
    endpoints = []
    for rule in sorted(rules):
        path_params = rules[rule]
        endpoint = {'path': rule, 'rule': rule, 'method': 'GET', 'policy': 'discover',
                    'description': f'discovered: {rule}'}
        if rule in SKIP_ROUTES:
            endpoint['skip_reason'] = SKIP_ROUTES[rule]
            endpoints.append(endpoint)
            continue
        extra = EXTRA_PARAMS.get(rule, {})
        wanted = list(path_params) + [v.strip('{}') for v in extra.values() if v.startswith('{')]
        resolved = {}
        for param in wanted:
            if param in resolved:
                continue
            value, why = resolver.resolve(param, rule, resolved)
            if value is None:
                endpoint['skip_reason'] = f'<{param}> unresolved: {why}'
                break
            resolved[param] = value
        if not endpoint.get('skip_reason'):
            path = rule
            for param in path_params:
                path = re.sub(rf'<(?:[a-z]+:)?{param}>', resolved[param], path)
            endpoint['path'] = path
            endpoint['params'] = {k: (resolved[v.strip('{}')] if v.startswith('{') else v)
                                  for k, v in extra.items()}
        endpoints.append(endpoint)

    unresolved = sum(1 for e in endpoints if e.get('skip_reason'))
    return {
        'name': 'Discovered GET routes',
        'description': f'{len(endpoints)} GET rules from {server_url} url_map ({unresolved} skipped)',
        'endpoints': endpoints,
    }


def discover_verdict(endpoint: dict, status_code: int):
    """(success, error) for a discovered route — liveness contract, see block comment above."""
    if 200 <= status_code < 300 or status_code in (401, 403):
        return True, None
    if status_code == 404 and endpoint.get('rule') in ALLOW_404:
        return True, None
    if status_code == 404:
        return False, '404 — route or resolved id not found'
    if status_code >= 500:
        return False, f'{status_code} — server error'
    return False, f'{status_code} — request rejected (missing param?)'


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description='Standalone API test runner')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--profile', help='Test profile name from api_profiles.json')
    group.add_argument('--endpoints', help='Comma-separated endpoint paths to test')
    group.add_argument('--spec', help='OpenAPI spec name (without .yaml extension)')
    group.add_argument('--discover', action='store_true',
                       help='Test every GET route the server registers (from /server/api-testing/config)')
    args = parser.parse_args()

    server_url = os.getenv('SERVER_URL', 'http://localhost:5109').rstrip('/')
    context = SimpleContext(team_id=os.getenv('TEAM_ID', ''))

    # Resolve test configuration
    if args.discover:
        print('Discovering GET routes from the server')
        test_config = load_discovered_endpoints(server_url, build_headers(), context.team_id)
    elif args.spec:
        print(f'Loading endpoints from OpenAPI spec: {args.spec}')
        test_config = load_spec_endpoints(args.spec)
    elif args.endpoints:
        print('Testing custom endpoints')
        test_config = parse_custom_endpoints(args.endpoints)
    elif args.profile:
        print(f'Loading profile: {args.profile}')
        test_config = load_profile(args.profile)
    else:
        print('No profile/endpoints/spec specified — defaulting to smoke')
        test_config = load_profile('smoke')

    if not test_config:
        print('ERROR: No valid test configuration found')
        return 1

    endpoints_to_test = test_config.get('endpoints', [])
    if not endpoints_to_test:
        print('ERROR: No endpoints to test')
        return 1

    print()
    print(f'Profile  : {test_config["name"]}')
    print(f'Server   : {server_url}')
    print(f'Endpoints: {len(endpoints_to_test)}')
    print()

    for i, endpoint in enumerate(endpoints_to_test, 1):
        print(f'[{i}/{len(endpoints_to_test)}] {endpoint.get("method", "GET")} {endpoint["path"]}')
        step = test_endpoint(endpoint, server_url, context)
        context.step_results.append(step)

    # Summary
    total = len(context.step_results)
    skipped = sum(1 for s in context.step_results if s.get('skipped'))
    passed = sum(1 for s in context.step_results if s['success'])
    failed = total - passed - skipped
    elapsed = time.time() - context.start_time

    print()
    print('-' * 50)
    print(f'Results  : {passed} passed, {failed} failed, {skipped} skipped of {total}  ({elapsed:.1f}s)')
    if failed:
        print('Failed endpoints:')
        for s in context.step_results:
            if not s['success'] and not s.get('skipped'):
                print(f'  • {s["action"]}  —  {s["error"]}  (status: {s["status_code"]})')
    if skipped:
        print('Skipped endpoints:')
        for s in context.step_results:
            if s.get('skipped'):
                print(f'  • {s["action"]}  —  {s["error"]}')
    print('-' * 50)

    profile_name = 'discover' if args.discover else (args.profile or args.spec or 'custom')
    write_html_report(
        context.step_results,
        profile_name,
        server_url,
        Path('api-report/index.html'),
    )
    print('HTML report written to api-report/index.html')

    return 0 if failed == 0 else 1


def write_html_report(results: list, profile_name: str, server_url: str, output_path: Path) -> None:
    """Write a self-contained HTML report of API test results."""
    total = len(results)
    skipped = sum(1 for r in results if r.get('skipped'))
    passed = sum(1 for r in results if r['success'])
    failed = total - passed - skipped
    elapsed = sum(r.get('response_time_ms', 0) for r in results)
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    overall_color = '#2e7d32' if failed == 0 else '#c62828'
    overall_label = 'PASSED' if failed == 0 else 'FAILED'

    rows = []
    for i, r in enumerate(results):
        status = r.get('status_code', '—')
        rt = r.get('response_time_ms', 0)
        ok = r['success']
        skip = r.get('skipped', False)
        row_color = '#f5f5f5' if skip else ('#e8f5e9' if ok else '#ffebee')
        detail_color = '#eeeeee' if skip else ('#f1f8e9' if ok else '#fff3e0')
        icon = '–' if skip else ('✔' if ok else '✘')
        icon_color = '#9e9e9e' if skip else ('#2e7d32' if ok else '#c62828')
        err = html_module.escape(r.get('error') or '')
        action = html_module.escape(r.get('action', ''))
        desc = html_module.escape(r.get('description', ''))
        req_params = html_module.escape(str(r.get('request_params') or {}))
        req_headers = html_module.escape(str(r.get('request_headers') or {}))
        resp_body = html_module.escape((r.get('response_body') or '—')[:3000])
        detail_id = f'detail-{i}'
        rows.append(f'''
        <tr style="background:{row_color};cursor:pointer" onclick="toggleDetail('{detail_id}')">
          <td style="color:{icon_color};font-size:1.1em;text-align:center">{icon}</td>
          <td style="font-family:monospace">{action} <span style="color:#aaa;font-size:.75em">▼</span></td>
          <td>{desc}</td>
          <td style="text-align:center">{status}</td>
          <td style="text-align:right">{rt:.0f}ms</td>
          <td style="color:{'#757575' if skip else '#c62828'};font-size:.85em">{err}</td>
        </tr>
        <tr id="{detail_id}" style="display:none;background:{detail_color}">
          <td></td>
          <td colspan="5" style="padding:12px 8px">
            <div style="display:flex;gap:16px;flex-wrap:wrap">
              <div style="flex:1;min-width:200px">
                <div style="font-size:.75rem;text-transform:uppercase;color:#888;margin-bottom:4px">Request</div>
                <pre style="margin:0;background:#263238;color:#eceff1;padding:10px;border-radius:6px;font-size:.78rem;overflow-x:auto;white-space:pre-wrap">Params: {req_params}
Headers: {req_headers}</pre>
              </div>
              <div style="flex:2;min-width:300px">
                <div style="font-size:.75rem;text-transform:uppercase;color:#888;margin-bottom:4px">Response Body</div>
                <pre style="margin:0;background:#263238;color:#eceff1;padding:10px;border-radius:6px;font-size:.78rem;overflow-x:auto;white-space:pre-wrap;max-height:300px">{resp_body}</pre>
              </div>
            </div>
          </td>
        </tr>''')

    rows_html = '\n'.join(rows)
    html = f'''<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>API Smoke Report</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 0; padding: 24px; background: #fafafa; color: #212121; }}
  h1 {{ margin: 0 0 4px; font-size: 1.5rem; }}
  .meta {{ color: #666; font-size: .85rem; margin-bottom: 20px; }}
  .summary {{ display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }}
  .kpi {{ background: #fff; border: 1px solid #e0e0e0; border-radius: 8px; padding: 12px 20px; min-width: 100px; }}
  .kpi-label {{ font-size: .75rem; color: #888; text-transform: uppercase; }}
  .kpi-value {{ font-size: 1.8rem; font-weight: 700; line-height: 1.1; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.1); }}
  th {{ background: #37474f; color: #fff; padding: 10px 12px; text-align: left; font-size: .8rem; text-transform: uppercase; }}
  td {{ padding: 8px 12px; font-size: .88rem; border-bottom: 1px solid #f0f0f0; }}
  tr:last-child td {{ border-bottom: none; }}
  tr[id^="detail-"] td {{ border-bottom: 1px solid #e0e0e0; }}
</style>
<script>function toggleDetail(id){{var el=document.getElementById(id);el.style.display=el.style.display==='none'?'table-row':'none';}}</script>
</head>
<body>
<h1>API Smoke Report</h1>
<div class="meta">Profile: {html_module.escape(profile_name)} &nbsp;|&nbsp; Server: {html_module.escape(server_url)} &nbsp;|&nbsp; {ts}</div>
<div class="summary">
  <div class="kpi"><div class="kpi-label">Overall</div><div class="kpi-value" style="color:{overall_color}">{overall_label}</div></div>
  <div class="kpi"><div class="kpi-label">Passed</div><div class="kpi-value" style="color:#2e7d32">{passed}</div></div>
  <div class="kpi"><div class="kpi-label">Failed</div><div class="kpi-value" style="color:#c62828">{failed}</div></div>
  <div class="kpi"><div class="kpi-label">Skipped</div><div class="kpi-value" style="color:#9e9e9e">{skipped}</div></div>
  <div class="kpi"><div class="kpi-label">Total</div><div class="kpi-value">{total}</div></div>
  <div class="kpi"><div class="kpi-label">Duration</div><div class="kpi-value" style="font-size:1.2rem">{elapsed/1000:.1f}s</div></div>
</div>
<table>
  <thead><tr><th></th><th>Endpoint</th><th>Description</th><th>Status</th><th>Time</th><th>Error</th></tr></thead>
  <tbody>{rows_html}</tbody>
</table>
</body></html>'''

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding='utf-8')


if __name__ == '__main__':
    sys.exit(main())
