import re
from flask import Blueprint, jsonify, request
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
import os
import json
import requests
import threading
import time
from pathlib import Path
from shared.src.lib.config.constants import CACHE_CONFIG
from backend_server.src.lib.auth_middleware import require_permission
from backend_server.src.integrations.testrail_client import TestRailConnectionError, test_connection as test_testrail_connection
from backend_server.src.integrations import testrail_service

server_integrations_bp = Blueprint('server_integrations_bp', __name__, url_prefix='/server/integrations')

# Add CORS headers for all responses in this blueprint
@server_integrations_bp.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, Pragma, Cache-Control'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS, DELETE'
    return response

# Path to integrations config
BACKEND_SERVER_ROOT = Path(__file__).parent.parent.parent
JIRA_CONFIG_PATH = BACKEND_SERVER_ROOT / 'config' / 'integrations' / 'jira_instances.json'

def load_jira_instances():
    """Load JIRA instances configuration from JSON file"""
    try:
        if not JIRA_CONFIG_PATH.exists():
            print(f"[@integrations_routes] JIRA config not found: {JIRA_CONFIG_PATH}")
            return []
        
        with open(JIRA_CONFIG_PATH, 'r') as f:
            instances = json.load(f)
        
        print(f"[@integrations_routes] Loaded {len(instances)} JIRA instance(s)")
        return instances
    except Exception as e:
        print(f"[@integrations_routes] Error loading JIRA config: {e}")
        return []

def save_jira_instances(instances):
    """Save JIRA instances configuration to JSON file"""
    try:
        JIRA_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(JIRA_CONFIG_PATH, 'w') as f:
            json.dump(instances, f, indent=2)
        print(f"[@integrations_routes] Saved {len(instances)} JIRA instance(s)")
        return True
    except Exception as e:
        print(f"[@integrations_routes] Error saving JIRA config: {e}")
        return False

def get_jira_instance_by_id(instance_id):
    """Get JIRA instance config by ID"""
    instances = load_jira_instances()
    for instance in instances:
        if instance['id'] == instance_id:
            return instance
    return None

# A JIRA domain is a public DNS name ('acme.atlassian.net', 'jira.example.com').
# Rejects schemes, ports, paths, credentials, IP literals and 'localhost' so the
# server never makes an authenticated request to an arbitrary/internal target.
_JIRA_DOMAIN_RE = re.compile(r'^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$')


def validate_jira_domain(domain) -> str:
    candidate = (domain or '').strip().lower()
    if not _JIRA_DOMAIN_RE.match(candidate) or candidate.endswith('.localhost'):
        raise ValueError(f'Invalid JIRA domain: {domain!r} (expected a hostname like acme.atlassian.net)')
    return candidate


def call_jira_api(domain, endpoint, email, api_token, method='GET', data=None):
    """Call JIRA API (security layer - API tokens never exposed to frontend)"""
    try:
        from requests.auth import HTTPBasicAuth

        from urllib.parse import quote
        domain = quote(validate_jira_domain(domain), safe='.-')
        if not str(endpoint).startswith('/'):
            raise ValueError(f'JIRA endpoint must be a path: {endpoint!r}')
        url = f"https://{domain}/rest/api/3{quote(str(endpoint), safe='/?=&%+,:@')}"
        auth = HTTPBasicAuth(email, api_token)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        
        print(f"[@integrations_routes] Calling JIRA API: {url}")
        
        if method == 'GET':
            response = requests.get(url, headers=headers, auth=auth, timeout=10)
        elif method == 'POST':
            response = requests.post(url, headers=headers, auth=auth, json=data, timeout=10)
        else:
            raise ValueError(f"Unsupported method: {method}")
        
        # Log response details for debugging
        print(f"[@integrations_routes] Response status: {response.status_code}")
        if response.status_code >= 400:
            print(f"[@integrations_routes] Error response body: {response.text}")
        
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"[@integrations_routes] JIRA API error: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"[@integrations_routes] Error response: {e.response.text}")
        raise


# ============================================================================
# JIRA INSTANCES MANAGEMENT
# ============================================================================

@server_integrations_bp.route('/jira/instances', methods=['GET'])
@handle_route_exceptions('server_integrations:get_jira_instances')
def get_jira_instances():
    """Get list of configured JIRA instances"""
    try:
        instances = load_jira_instances()
        
        # Return sanitized data (no API tokens!)
        result = []
        for instance in instances:
            result.append({
                'id': instance['id'],
                'name': instance['name'],
                'domain': instance['domain'],
                'email': instance['email'],
                'projectKey': instance.get('projectKey', ''),
            })
        
        return jsonify({
            'success': True,
            'instances': result
        })
    except Exception as e:
        print(f"[@integrations_routes:get_jira_instances] Error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@server_integrations_bp.route('/jira/instances', methods=['POST'])
@handle_route_exceptions('server_integrations:create_jira_instance')
def create_jira_instance():
    """Create or update JIRA instance configuration"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['name', 'domain', 'email', 'apiToken', 'projectKey']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'success': False,
                    'error': f'Missing required field: {field}'
                }), 400
        
        instances = load_jira_instances()
        
        # Generate new ID or use existing
        instance_id = data.get('id', f"jira-{len(instances) + 1}")
        
        # Check if updating existing instance
        existing_index = None
        for i, instance in enumerate(instances):
            if instance['id'] == instance_id:
                existing_index = i
                break
        
        new_instance = {
            'id': instance_id,
            'name': data['name'],
            'domain': data['domain'],
            'email': data['email'],
            'apiToken': data['apiToken'],
            'projectKey': data['projectKey']
        }
        
        if existing_index is not None:
            instances[existing_index] = new_instance
        else:
            instances.append(new_instance)
        
        if not save_jira_instances(instances):
            return jsonify({
                'success': False,
                'error': 'Failed to save configuration'
            }), 500
        
        return jsonify({
            'success': True,
            'instance': {
                'id': instance_id,
                'name': new_instance['name'],
                'domain': new_instance['domain'],
                'email': new_instance['email'],
                'projectKey': new_instance['projectKey']
            }
        })
    except Exception as e:
        print(f"[@integrations_routes:create_jira_instance] Error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@server_integrations_bp.route('/jira/instances/<instance_id>', methods=['DELETE'])
@handle_route_exceptions('server_integrations:delete_jira_instance')
def delete_jira_instance(instance_id):
    """Delete JIRA instance configuration"""
    try:
        instances = load_jira_instances()
        instances = [i for i in instances if i['id'] != instance_id]
        
        if not save_jira_instances(instances):
            return jsonify({
                'success': False,
                'error': 'Failed to save configuration'
            }), 500
        
        return jsonify({
            'success': True
        })
    except Exception as e:
        print(f"[@integrations_routes:delete_jira_instance] Error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# JIRA TICKETS/ISSUES
# ============================================================================

@server_integrations_bp.route('/jira/<instance_id>/tickets', methods=['GET'])
@handle_route_exceptions('server_integrations:get_jira_tickets')
def get_jira_tickets(instance_id):
    """Get tickets/issues from JIRA instance"""
    try:
        instance = get_jira_instance_by_id(instance_id)
        if not instance:
            return jsonify({
                'success': False,
                'error': 'JIRA instance not found'
            }), 404
        
        # Get query parameters
        status_filter = request.args.get('status', '')
        max_results = int(request.args.get('maxResults', 100))
        
        # Build JQL query
        jql = f"project={instance['projectKey']}"
        if status_filter:
            jql += f" AND status='{status_filter}'"
        jql += " ORDER BY created DESC"
        
        # Call JIRA API - use new /search/jql endpoint (v3)
        import urllib.parse
        encoded_jql = urllib.parse.quote(jql)
        endpoint = f"/search/jql?jql={encoded_jql}&maxResults={max_results}&fields=summary,status,priority,assignee,created,updated,issuetype"
        
        result = call_jira_api(
            instance['domain'],
            endpoint,
            instance['email'],
            instance['apiToken']
        )
        
        # Extract and format tickets
        tickets = []
        for issue in result.get('issues', []):
            fields = issue.get('fields', {})
            tickets.append({
                'id': issue.get('id'),
                'key': issue.get('key'),
                'summary': fields.get('summary', ''),
                'status': fields.get('status', {}).get('name', '') if fields.get('status') else 'Unknown',
                'priority': fields.get('priority', {}).get('name', 'None') if fields.get('priority') else 'None',
                'assignee': fields.get('assignee', {}).get('displayName', 'Unassigned') if fields.get('assignee') else 'Unassigned',
                'created': fields.get('created', ''),
                'updated': fields.get('updated', ''),
                'issueType': fields.get('issuetype', {}).get('name', '') if fields.get('issuetype') else 'Unknown',
                'url': f"https://{instance['domain']}/browse/{issue.get('key')}"
            })
        
        # Get statistics - new API returns isLast instead of total
        total = len(tickets)
        if not result.get('isLast', True):
            # If there are more pages, get accurate count
            count_result = call_jira_api(
                instance['domain'],
                f"/search/jql?jql={encoded_jql}&maxResults=1000",
                instance['email'],
                instance['apiToken']
            )
            total = len(count_result.get('issues', []))
        
        return jsonify({
            'success': True,
            'total': total,
            'tickets': tickets
        })
    except requests.exceptions.HTTPError as e:
        error_msg = f"JIRA API error: {e.response.status_code}"
        if e.response.status_code == 401:
            error_msg = "Authentication failed. Check email and API token."
        elif e.response.status_code == 404:
            error_msg = "Project not found. Check project key."
        
        print(f"[@integrations_routes:get_jira_tickets] {error_msg}")
        return jsonify({
            'success': False,
            'error': error_msg
        }), e.response.status_code
    except Exception as e:
        print(f"[@integrations_routes:get_jira_tickets] Error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@server_integrations_bp.route('/jira/<instance_id>/stats', methods=['GET'])
@handle_route_exceptions('server_integrations:get_jira_stats')
def get_jira_stats(instance_id):
    """Get ticket statistics from JIRA instance"""
    try:
        instance = get_jira_instance_by_id(instance_id)
        if not instance:
            return jsonify({
                'success': False,
                'error': 'JIRA instance not found'
            }), 404
        
        project_key = instance['projectKey']
        import urllib.parse
        
        # Helper function to get count using new /search/jql endpoint
        def get_jira_count(jql):
            encoded_jql = urllib.parse.quote(jql)
            # Use new /search/jql endpoint
            result = call_jira_api(
                instance['domain'],
                f"/search/jql?jql={encoded_jql}&maxResults=1",
                instance['email'],
                instance['apiToken']
            )
            # Count total by checking if there are more issues
            total = len(result.get('issues', []))
            if not result.get('isLast', True):
                # If not last page, we need to get actual count
                # Make another call with higher maxResults to get total
                result_full = call_jira_api(
                    instance['domain'],
                    f"/search/jql?jql={encoded_jql}&maxResults=1000",
                    instance['email'],
                    instance['apiToken']
                )
                total = len(result_full.get('issues', []))
            return total
        
        # Get counts by status
        statuses = ['Open', 'In Progress', 'Done', 'To Do', 'Closed']
        stats = {
            'total': 0,
            'byStatus': {}
        }
        
        # Get total count
        stats['total'] = get_jira_count(f"project={project_key}")
        
        # Get counts by status
        for status in statuses:
            count = get_jira_count(f"project={project_key} AND status='{status}'")
            if count > 0:
                stats['byStatus'][status] = count
        
        return jsonify({
            'success': True,
            'stats': stats
        })
    except Exception as e:
        print(f"[@integrations_routes:get_jira_stats] Error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@server_integrations_bp.route('/jira/<instance_id>/test', methods=['POST'])
@handle_route_exceptions('server_integrations:test_jira_connection')
def test_jira_connection(instance_id):
    """Test JIRA connection with provided credentials"""
    try:
        data = request.get_json()
        
        # Use provided credentials or existing instance
        if 'domain' in data and 'email' in data and 'apiToken' in data:
            domain = data['domain']
            email = data['email']
            api_token = data['apiToken']
            project_key = data.get('projectKey', '')
        else:
            instance = get_jira_instance_by_id(instance_id)
            if not instance:
                return jsonify({
                    'success': False,
                    'error': 'JIRA instance not found'
                }), 404
            domain = instance['domain']
            email = instance['email']
            api_token = instance['apiToken']
            project_key = instance.get('projectKey', '')
        
        # Test connection by getting myself
        result = call_jira_api(domain, '/myself', email, api_token)
        
        # If project key provided, verify it exists
        if project_key:
            call_jira_api(domain, f"/project/{project_key}", email, api_token)
        
        return jsonify({
            'success': True,
            'user': result.get('displayName', 'Unknown'),
            'email': result.get('emailAddress', email)
        })
    except requests.exceptions.HTTPError as e:
        error_msg = "Connection failed"
        if e.response.status_code == 401:
            error_msg = "Authentication failed. Check email and API token."
        elif e.response.status_code == 404:
            error_msg = "Project not found. Check project key."
        
        return jsonify({
            'success': False,
            'error': error_msg
        }), 400
    except Exception as e:
        print(f"[@integrations_routes:test_jira_connection] Error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# SLACK CONFIGURATION
# ============================================================================

SLACK_CONFIG_PATH = BACKEND_SERVER_ROOT / 'config' / 'integrations' / 'slack_config.json'
THREADS_PATH = BACKEND_SERVER_ROOT / 'config' / 'integrations' / 'slack_threads.json'

# TestRail credentials are kept on the backend and omitted from every read response.
TESTRAIL_CONFIG_PATH = BACKEND_SERVER_ROOT / 'config' / 'integrations' / 'testrail.json'


def _testrail_team_id():
    return (request.args.get('team_id') or '').strip()


def _load_testrail_config(team_id=None):
    return testrail_service.load_config(team_id or _testrail_team_id())


@server_integrations_bp.route('/testrail/config', methods=['GET'])
@require_permission('plugins.testrail:view')
@handle_route_exceptions('server_integrations:get_testrail_config')
def get_testrail_config():
    config = _load_testrail_config(_testrail_team_id())
    return jsonify({'success': True, 'config': {
        'base_url': config.get('base_url', ''),
        'username': config.get('username', ''),
        'project_id': config.get('project_id'),
        'has_credentials': bool(config.get('api_key')),
        'auto_publish': bool(config.get('auto_publish', False)),
    }})


@server_integrations_bp.route('/testrail/cases', methods=['GET'])
@require_permission('plugins.testrail:view')
@handle_route_exceptions('server_integrations:list_testrail_cases')
def list_testrail_cases_route():
    config = _load_testrail_config()
    if not config.get('api_key'):
        return jsonify({'success': False, 'error': 'Connect TestRail before linking cases.'}), 400
    try:
        cases = testrail_service.list_cases(config, request.args.get('search', '').strip())
        return jsonify({'success': True, 'cases': cases})
    except TestRailConnectionError as exc:
        return jsonify({'success': False, 'category': exc.category, 'error': str(exc)}), 400


@server_integrations_bp.route('/testrail/automation', methods=['POST'])
@require_permission('plugins.testrail:manage')
@handle_route_exceptions('server_integrations:update_testrail_automation')
def update_testrail_automation_route():
    team_id = _testrail_team_id()
    config = _load_testrail_config(team_id)
    if not team_id or not config.get('api_key'):
        return jsonify({'success': False, 'error': 'Connect TestRail before enabling automatic publishing.'}), 400
    data = request.get_json(silent=True) or {}
    config['auto_publish'] = bool(data.get('enabled'))
    try:
        testrail_service.save_config(team_id, config)
    except (OSError, ValueError):
        return jsonify({'success': False, 'error': 'Could not save TestRail publishing settings.'}), 500
    return jsonify({'success': True, 'auto_publish': config['auto_publish']})


@server_integrations_bp.route('/testrail/mappings', methods=['GET', 'POST', 'DELETE'])
@require_permission('plugins.testrail:manage')
@handle_route_exceptions('server_integrations:manage_testrail_mappings')
def manage_testrail_mappings_route():
    team_id = _testrail_team_id()
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required.'}), 400
    config = _load_testrail_config(team_id)
    if request.method == 'GET':
        return jsonify({'success': True, 'mappings': config.get('case_mappings', {})})
    data = request.get_json(silent=True) or {}
    if request.method == 'POST' and isinstance(data.get('mappings'), list):
        try:
            saved = testrail_service.save_mappings(team_id, data['mappings'])
            return jsonify({'success': True, 'mappings': saved})
        except (TypeError, ValueError, TestRailConnectionError) as exc:
            return jsonify({'success': False, 'error': str(exc), 'category': getattr(exc, 'category', 'invalid_mapping')}), 400
    vpt_key = str((request.args.get('vpt_key') if request.method == 'DELETE' else data.get('vpt_key')) or '').strip()
    if not vpt_key:
        return jsonify({'success': False, 'error': 'VirtualPyTest case name is required.'}), 400
    try:
        if request.method == 'DELETE':
            removed = testrail_service.remove_mapping(team_id, vpt_key)
            return jsonify({'success': True, 'removed': removed})
        case_id = int(data.get('case_id'))
        mapping = testrail_service.save_mapping(team_id, vpt_key, case_id)
        return jsonify({'success': True, 'mapping': mapping})
    except (TypeError, ValueError, TestRailConnectionError) as exc:
        return jsonify({'success': False, 'error': str(exc), 'category': getattr(exc, 'category', 'invalid_mapping')}), 400


@server_integrations_bp.route('/testrail/test', methods=['POST'])
@require_permission('plugins.testrail:manage')
@handle_route_exceptions('server_integrations:test_testrail_connection')
def test_testrail_connection_route():
    data = request.get_json(silent=True) or {}
    base_url = data.get('base_url', '')
    username = data.get('username', '')
    api_key = data.get('api_key', '')
    if not api_key:
        saved = _load_testrail_config(_testrail_team_id())
        if (saved.get('base_url', '').rstrip('/').lower() == str(base_url).rstrip('/').lower()
                and saved.get('username', '').lower() == str(username).lower()):
            api_key = saved.get('api_key', '')
    try:
        result = test_testrail_connection(
            base_url, username, api_key
        )
        return jsonify({'success': True, **result})
    except TestRailConnectionError as exc:
        return jsonify({'success': False, 'category': exc.category, 'error': str(exc)}), 400


@server_integrations_bp.route('/testrail/config', methods=['POST', 'DELETE'])
@require_permission('plugins.testrail:manage')
@handle_route_exceptions('server_integrations:save_testrail_config')
def save_testrail_config():
    if request.method == 'DELETE':
        try:
            team_id = _testrail_team_id()
            if not team_id:
                return jsonify({'success': False, 'error': 'team_id is required.'}), 400
            try:
                with open(TESTRAIL_CONFIG_PATH, 'r') as config_file:
                    stored = json.load(config_file)
            except FileNotFoundError:
                stored = {'teams': {}}
            teams = stored.get('teams', {}) if isinstance(stored, dict) else {}
            teams.pop(team_id, None)
            if teams:
                stored = {'teams': teams}
                temp_path = TESTRAIL_CONFIG_PATH.with_suffix('.tmp')
                with open(temp_path, 'w') as config_file:
                    json.dump(stored, config_file)
                os.chmod(temp_path, 0o600)
                os.replace(temp_path, TESTRAIL_CONFIG_PATH)
            else:
                TESTRAIL_CONFIG_PATH.unlink(missing_ok=True)
            return jsonify({'success': True})
        except OSError:
            return jsonify({'success': False, 'error': 'Could not remove TestRail configuration.'}), 500

    data = request.get_json(silent=True) or {}
    team_id = _testrail_team_id()
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required.'}), 400
    current = _load_testrail_config(team_id)
    base_url = (data.get('base_url') or '').strip()
    username = (data.get('username') or '').strip()
    api_key = (data.get('api_key') or '').strip() or current.get('api_key', '')
    if not base_url or not username or not api_key:
        return jsonify({'success': False, 'error': 'Instance URL, username/email, and API key are required.'}), 400
    try:
        validated = test_testrail_connection(base_url, username, api_key)
    except TestRailConnectionError as exc:
        return jsonify({'success': False, 'category': exc.category, 'error': str(exc)}), 400

    project_id = data.get('project_id')
    project_ids = {str(project.get('id')) for project in validated['projects']}
    if project_id is None or str(project_id) not in project_ids:
        return jsonify({'success': False, 'error': 'Selected project is not available to this TestRail account.'}), 400
    config = {
        **current,
        'base_url': validated['base_url'],
        'username': username,
        'api_key': api_key,
        'project_id': int(project_id),
    }
    if 'auto_publish' in data:
        config['auto_publish'] = bool(data.get('auto_publish'))
    try:
        testrail_service.save_config(team_id, config)
    except (OSError, ValueError):
        return jsonify({'success': False, 'error': 'Could not securely save TestRail configuration.'}), 500
    return jsonify({'success': True, 'config': {
        'base_url': config['base_url'], 'username': username,
        'project_id': config['project_id'], 'has_credentials': True,
        'auto_publish': bool(config.get('auto_publish', False)),
    }})

# Simple in-memory cache for Slack config to avoid re-reading from disk on every request
_slack_config_cache = {'data': None, 'timestamp': 0.0}
_slack_cache_lock = threading.Lock()
SLACK_CONFIG_TTL = CACHE_CONFIG['MEDIUM_TTL']

def load_slack_config():
    """Load Slack configuration from JSON file"""
    try:
        if not SLACK_CONFIG_PATH.exists():
            print(f"[@integrations_routes] Slack config not found: {SLACK_CONFIG_PATH}")
            return {
                'enabled': False,
                'bot_token': '',
                'channel_id': '',
                'sync_tool_calls': False,
                'sync_thinking': False
            }
        
        with open(SLACK_CONFIG_PATH, 'r') as f:
            config = json.load(f)
        
        print(f"[@integrations_routes] Loaded Slack config (enabled={config.get('enabled')})")
        return config
    except Exception as e:
        print(f"[@integrations_routes] Error loading Slack config: {e}")
        return {'enabled': False}

def save_slack_config(config):
    """Save Slack configuration to JSON file"""
    try:
        SLACK_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SLACK_CONFIG_PATH, 'w') as f:
            json.dump(config, f, indent=2)
        print(f"[@integrations_routes] Saved Slack config")
        return True
    except Exception as e:
        print(f"[@integrations_routes] Error saving Slack config: {e}")
        return False


# ============================================================================
# SLACK ROUTES
# ============================================================================

@server_integrations_bp.route('/slack/config', methods=['GET'])
@handle_route_exceptions('server_integrations:get_slack_config')
def get_slack_config():
    """Get Slack configuration (without token for security)"""
    try:
        with _slack_cache_lock:
            age = time.time() - _slack_config_cache['timestamp']
            if _slack_config_cache['data'] and age < SLACK_CONFIG_TTL:
                response = jsonify(_slack_config_cache['data'])
                response.headers['Cache-Control'] = f"public, max-age={int(SLACK_CONFIG_TTL)}"
                return response

        config = load_slack_config()

        # Build Slack URL if workspace_id and channel_id are available
        workspace_id = config.get('workspace_id', '')
        channel_id = config.get('channel_id', '')
        slack_url = f"https://app.slack.com/client/{workspace_id}/{channel_id}" if workspace_id and channel_id else None

        payload = {
            'success': True,
            'config': {
                'enabled': config.get('enabled', False),
                'workspace_id': workspace_id,
                'channel_id': channel_id,
                'url': slack_url,
                'sync_tool_calls': config.get('sync_tool_calls', False),
                'sync_thinking': config.get('sync_thinking', False),
                'has_token': bool(config.get('bot_token'))
            }
        }

        with _slack_cache_lock:
            _slack_config_cache['data'] = payload
            _slack_config_cache['timestamp'] = time.time()

        response = jsonify(payload)
        response.headers['Cache-Control'] = f"public, max-age={int(SLACK_CONFIG_TTL)}"
        return response
    except Exception as e:
        print(f"[@integrations_routes:get_slack_config] Error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@server_integrations_bp.route('/slack/config', methods=['POST'])
@handle_route_exceptions('server_integrations:update_slack_config')
def update_slack_config():
    """Update Slack configuration"""
    try:
        data = request.get_json()
        config = load_slack_config()
        
        # Update fields
        if 'bot_token' in data:
            config['bot_token'] = data['bot_token']
        if 'channel_id' in data:
            config['channel_id'] = data['channel_id']
        if 'enabled' in data:
            config['enabled'] = data['enabled']
        if 'sync_tool_calls' in data:
            config['sync_tool_calls'] = data['sync_tool_calls']
        if 'sync_thinking' in data:
            config['sync_thinking'] = data['sync_thinking']
        
        if not save_slack_config(config):
            return jsonify({
                'success': False,
                'error': 'Failed to save configuration'
            }), 500

        # Update cache with new values so next GET is immediate
        with _slack_cache_lock:
            _slack_config_cache['data'] = None
            _slack_config_cache['timestamp'] = 0.0
        
        # Reload the sync service if it exists
        try:
            from integrations.slack_sync import reload_slack_config
            reload_slack_config()
        except ImportError:
            pass  # Service not running or not imported yet
        
        return jsonify({
            'success': True,
            'config': {
                'enabled': config.get('enabled', False),
                'channel_id': config.get('channel_id', ''),
                'has_token': bool(config.get('bot_token'))
            }
        })
    except Exception as e:
        print(f"[@integrations_routes:update_slack_config] Error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@server_integrations_bp.route('/slack/test', methods=['POST'])
@handle_route_exceptions('server_integrations:test_slack_connection')
def test_slack_connection():
    """Test Slack connection with provided or saved credentials"""
    try:
        data = request.get_json()
        token = data.get('bot_token')
        
        # If no token provided, use saved config
        if not token:
            config = load_slack_config()
            token = config.get('bot_token')
        
        if not token:
            return jsonify({
                'success': False,
                'error': 'No bot token provided'
            }), 400
        
        # Test connection using slack-sdk
        from slack_sdk import WebClient
        from slack_sdk.errors import SlackApiError
        
        client = WebClient(token=token)
        response = client.auth_test()
        
        return jsonify({
            'success': True,
            'team': response.get('team', 'Unknown'),
            'user': response.get('user', 'Unknown'),
            'bot_id': response.get('bot_id', 'Unknown')
        })
    except Exception as e:
        error_msg = str(e)
        if 'invalid_auth' in error_msg:
            error_msg = 'Invalid bot token. Please check your credentials.'
        elif 'not_authed' in error_msg:
            error_msg = 'Authentication failed. Token may be expired.'
        
        print(f"[@integrations_routes:test_slack_connection] Error: {error_msg}")
        return jsonify({
            'success': False,
            'error': error_msg
        }), 400


@server_integrations_bp.route('/slack/status', methods=['GET'])
@handle_route_exceptions('server_integrations:get_slack_status')
def get_slack_status():
    """Get Slack sync status and statistics"""
    try:
        config = load_slack_config()
        
        # Load thread statistics
        threads_path = BACKEND_SERVER_ROOT / 'config' / 'integrations' / 'slack_threads.json'
        thread_count = 0
        last_sync = None
        
        if threads_path.exists():
            with open(threads_path, 'r') as f:
                threads = json.load(f)
                thread_count = len(threads)
                # Get most recent sync time if available
                if threads:
                    last_sync = threads.get('_last_sync')
        
        status = {
            'enabled': config.get('enabled', False),
            'configured': bool(config.get('bot_token') and config.get('channel_id')),
            'channel_id': config.get('channel_id', ''),
            'conversations_synced': thread_count,
            'last_sync': last_sync,
            'sync_tool_calls': config.get('sync_tool_calls', False),
            'sync_thinking': config.get('sync_thinking', False)
        }
        
        return jsonify({
            'success': True,
            'status': status
        })
    except Exception as e:
        print(f"[@integrations_routes:get_slack_status] Error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@server_integrations_bp.route('/slack/send-test', methods=['POST'])
@handle_route_exceptions('server_integrations:send_test_message')
def send_test_message():
    """Send a test message to Slack channel"""
    try:
        config = load_slack_config()
        
        if not config.get('enabled'):
            return jsonify({
                'success': False,
                'error': 'Slack integration is disabled'
            }), 400
        
        if not config.get('bot_token') or not config.get('channel_id'):
            return jsonify({
                'success': False,
                'error': 'Slack not configured. Please set bot token and channel ID.'
            }), 400
        
        from slack_sdk import WebClient
        from slack_sdk.errors import SlackApiError
        
        client = WebClient(token=config['bot_token'])
        
        # Send test message
        response = client.chat_postMessage(
            channel=config['channel_id'],
            text="🤖 VirtualPyTest - Test Message",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*VirtualPyTest AI Integration*\n\nThis is a test message to verify Slack connectivity. ✅"
                    }
                }
            ]
        )
        
        return jsonify({
            'success': True,
            'message': 'Test message sent successfully',
            'timestamp': response.get('ts')
        })
    except Exception as e:
        error_msg = str(e)
        if 'channel_not_found' in error_msg:
            error_msg = 'Channel not found. Please check the channel ID.'
        elif 'not_in_channel' in error_msg:
            error_msg = 'Bot is not a member of this channel. Please invite the bot first.'
        
        print(f"[@integrations_routes:send_test_message] Error: {error_msg}")
        return jsonify({
            'success': False,
            'error': error_msg
        }), 400


# =========================================
# SLACK EVENTS API - Bidirectional Chat
# =========================================

@server_integrations_bp.route('/slack/events', methods=['POST'])
@handle_route_exceptions('server_integrations:slack_events')
def slack_events():
    """
    Slack Events API webhook endpoint for bidirectional chat
    
    When users reply in a Slack thread, this forwards the message
    to the corresponding Agent Chat session via Socket.IO

    Unauthenticated by the global guard (Slack carries no JWT and no API key), so the
    signature is this route's only credential — it is checked before the body is parsed,
    and a request without a valid one is refused outright.
    """
    from backend_server.src.integrations.slack_sync import verify_slack_signature

    ok, reason = verify_slack_signature(
        request.get_data(),
        request.headers.get('X-Slack-Request-Timestamp', ''),
        request.headers.get('X-Slack-Signature', ''),
    )
    if not ok:
        # The reason goes to the log, not the response: which half of the check failed is
        # information an attacker would otherwise get for free.
        print(f"[@integrations_routes:slack_events] ⛔ rejected unsigned/invalid request: {reason}")
        return jsonify({'error': 'unauthorized'}), 401

    try:
        data = request.json
        print(f"[@integrations_routes:slack_events] 📥 Received: type={data.get('type')}")
        
        # Handle Slack URL verification challenge
        if data.get('type') == 'url_verification':
            print(f"[@integrations_routes:slack_events] ✅ URL verification challenge")
            return jsonify({'challenge': data.get('challenge')})
        
        # Handle event callbacks
        if data.get('type') == 'event_callback':
            event = data.get('event', {})
            event_type = event.get('type')
            event_subtype = event.get('subtype')
            has_thread_ts = bool(event.get('thread_ts'))
            has_bot_id = bool(event.get('bot_id'))
            
            print(f"[@integrations_routes:slack_events] 📨 Event: type={event_type}, subtype={event_subtype}, thread_ts={has_thread_ts}, bot={has_bot_id}")
            print(f"[@integrations_routes:slack_events] 📝 Text: {event.get('text', '')[:100]}")
            
            # Only process message events
            if event_type == 'message':
                # Ignore bot messages to prevent loops
                if event.get('bot_id') or event.get('subtype') == 'bot_message':
                    print(f"[@integrations_routes:slack_events] ⏭️ Skipping bot message")
                    return jsonify({'ok': True})
                
                # Get thread_ts - for threaded replies, or ts for regular messages being replied to
                thread_ts = event.get('thread_ts')  # Thread parent timestamp
                message_ts = event.get('ts')  # This message's timestamp
                user_message = event.get('text', '')
                slack_user_id = event.get('user', '')
                
                # Load threads mapping to find session_id
                if THREADS_PATH.exists():
                    with open(THREADS_PATH, 'r') as f:
                        threads = json.load(f)
                    
                    print(f"[@integrations_routes:slack_events] 🔍 Searching for thread_ts={thread_ts} in {len(threads)} threads")
                    
                    # Find session_id by thread_ts (reverse lookup)
                    session_id = None
                    lookup_ts = thread_ts if thread_ts else message_ts
                    
                    for sid, ts in threads.items():
                        if ts == lookup_ts and not sid.startswith('_'):
                            session_id = sid
                            break
                    
                    if session_id:
                        print(f"[@integrations_routes:slack_events] ✅ Found session {session_id[:8]} for thread")
                        
                        # Process directly on backend (no frontend involved)
                        # This avoids any UI navigation/redirection
                        import threading
                        
                        def process_slack_message_async():
                            try:
                                import asyncio
                                from agent.session_manager import get_session_manager
                                from agent.manager import get_manager
                                
                                # Get or create event loop for this thread
                                try:
                                    loop = asyncio.get_event_loop()
                                except RuntimeError:
                                    loop = asyncio.new_event_loop()
                                    asyncio.set_event_loop(loop)
                                
                                session_mgr = get_session_manager()
                                session = session_mgr.get_session(session_id)
                                
                                if not session:
                                    print(f"[@integrations_routes:slack_events] ❌ Session {session_id[:8]} not found")
                                    return
                                
                                # Get team_id from session context
                                team_id = session.get_context('team_id')
                                agent_id = session.get_context('agent_id') or 'assistant'
                                
                                # Post user message to Slack first
                                try:
                                    from integrations.slack_sync import get_slack_sync
                                    slack = get_slack_sync()
                                    if slack.enabled:
                                        slack.post_user_message(
                                            conversation_id=session_id,
                                            user_name=f'Slack User ({slack_user_id})',
                                            content=user_message,
                                            conversation_title=f"Chat Session {session_id[:8]}"
                                        )
                                except Exception as slack_err:
                                    print(f"[@integrations_routes:slack_events] ⚠️ Failed to post user message: {slack_err}")
                                
                                # Process with AI manager
                                manager = get_manager(team_id=team_id, agent_id=agent_id)
                                
                                async def run_processing():
                                    try:
                                        async for event in manager.process_message(user_message, session):
                                            # Post AI responses to Slack (messages/results only)
                                            if event.type in ['message', 'result'] and event.content:
                                                try:
                                                    from integrations.slack_sync import get_slack_sync
                                                    slack = get_slack_sync()
                                                    if slack.enabled:
                                                        slack.post_message(
                                                            conversation_id=session_id,
                                                            agent=event.agent or 'AI Agent',
                                                            content=event.content,
                                                            conversation_title=f"Chat Session {session_id[:8]}"
                                                        )
                                                except Exception as slack_err:
                                                    print(f"[@integrations_routes:slack_events] ⚠️ Failed to post response: {slack_err}")
                                    except Exception as proc_err:
                                        print(f"[@integrations_routes:slack_events] ❌ Processing error: {proc_err}")
                                
                                loop.run_until_complete(run_processing())
                                print(f"[@integrations_routes:slack_events] ✅ Processed Slack message for session {session_id[:8]}")
                                
                            except Exception as e:
                                print(f"[@integrations_routes:slack_events] ❌ Async processing error: {e}")
                        
                        # Run in background thread to not block Slack's 3-second timeout
                        thread = threading.Thread(target=process_slack_message_async)
                        thread.daemon = True
                        thread.start()
                        
                        print(f"[@integrations_routes:slack_events] 🚀 Started background processing for session {session_id[:8]}")
                    else:
                        print(f"[@integrations_routes:slack_events] ⚠️ No session found for ts={lookup_ts}")
                        print(f"[@integrations_routes:slack_events] 📋 Available threads: {list(threads.keys())[:5]}...")
                else:
                    print(f"[@integrations_routes:slack_events] ⚠️ No threads mapping file found at {THREADS_PATH}")
        
        return jsonify({'ok': True})
        
    except Exception as e:
        print(f"[@integrations_routes:slack_events] Error: {e}")
        return jsonify({'ok': True})  # Always return 200 to Slack
