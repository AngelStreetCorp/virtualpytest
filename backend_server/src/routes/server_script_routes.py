"""
Server Script Routes - Script management and execution proxy
"""
import os
import re
import time
import threading
import uuid
from flask import Blueprint, request, jsonify, session
import requests
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from  backend_server.src.lib.utils.server_utils import get_host_manager
from backend_server.src.routes.server_system_socket_routes import emit_system_update
from backend_server.src.lib.utils.completion_notifier import notify_completion
from backend_server.src.lib.utils.webhook_utils import resolve_callback_url
from backend_server.src.lib.utils.lock_utils import (
    abort_and_force_unlock,
    acquire_device_lock,
    clear_device_active_script,
    get_client_ip,
    get_device_lock_info,
    release_device_lock,
)
from shared.src.lib.config.constants import CACHE_CONFIG
from shared.src.lib.database.library_visibility_db import list_hidden_library_keys
from shared.src.lib.utils.supabase_utils import get_supabase_client
from backend_server.src.lib.utils.adhoc_execution import create_adhoc_execution, complete_adhoc_execution

server_script_bp = Blueprint('server_script', __name__, url_prefix='/server')

# ============================================================================
# IN-MEMORY CACHE FOR SCRIPT LIST
# ============================================================================
_script_cache = {}  # {cache_key: {'data': {...}, 'timestamp': time.time()}}
_cache_lock = threading.Lock()


def invalidate_script_list_cache() -> None:
    with _cache_lock:
        _script_cache.clear()


def _build_server_failure_log(*, script_name, host_name, device_id, parameters,
                              error, status_code=None, traceback_text=None) -> str:
    """Human-readable server-side log explaining why the host never ran the script.

    Produced by the BACKEND SERVER (not the host) for failures where the host is
    unreachable / errored before the script started, so the run still has a log
    to show instead of an empty 'No Logs' chip.
    """
    from datetime import datetime, timezone
    lines = [
        "=== VirtualPyTest — Server-Side Execution Failure ===",
        f"Timestamp:   {datetime.now(timezone.utc).isoformat()}",
        f"Script:      {script_name}",
        f"Target:      {host_name}:{device_id}",
        f"Parameters:  {parameters or '(none)'}",
        "",
        "The backend server could not start this script on the host, so the host",
        "produced no log or report (the script never ran). This log is generated",
        "by the backend SERVER to record why the execution failed.",
        "",
        f"Error: {error}",
    ]
    if status_code is not None:
        lines.append(f"Host HTTP status: {status_code}")
    if traceback_text:
        lines += ["", "--- Server traceback ---", traceback_text.rstrip()]
    return "\n".join(lines) + "\n"


def _persist_server_failure_artifacts(*, team_id, host_info, host_name, device_id,
                                      script_name, parameters, error,
                                      status_code=None, traceback_text=None) -> dict:
    """Generate a server-side log+report for a failure where the host never ran
    the script, persist a script_results row, and return its id + urls so the
    caller can link it to the deployment_execution (script_result_id) and put
    the urls on the task result.

    Best-effort: any failure here is swallowed and returns empty artifacts so it
    never masks the original execution error.
    """
    try:
        from shared.src.lib.utils.report_generation_utils import generate_and_upload_script_report
        from shared.src.lib.database.script_results_db import (
            record_script_execution_start,
            update_script_execution_result,
        )

        # Resolve a device_model for the R2 artifact folder (falls back to id/host).
        device_model = device_id or 'host'
        try:
            for d in (host_info.get('devices') or []) if isinstance(host_info, dict) else []:
                if d.get('device_id') == device_id:
                    device_model = d.get('device_model') or device_model
                    break
        except Exception:
            pass

        log_text = _build_server_failure_log(
            script_name=script_name, host_name=host_name, device_id=device_id,
            parameters=parameters, error=error, status_code=status_code,
            traceback_text=traceback_text,
        )

        report_result = generate_and_upload_script_report(
            script_name=script_name,
            device_info={'device_name': device_id, 'device_model': device_model, 'device_id': device_id},
            host_info={'host_name': host_name},
            execution_time=0,
            success=False,
            error_message=error,
            stdout=log_text,
            exit_code=1,
            parameters=parameters or '',
            trigger={'type': 'api'},
        ) or {}

        report_url = report_result.get('report_url') or ''
        logs_url = report_result.get('logs_url') or ''

        # Persist a script_results row so the failure (with its server log/report)
        # survives a page refresh — /executions/recent joins it via script_result_id.
        script_result_id = record_script_execution_start(
            team_id=team_id,
            script_name=script_name,
            script_type=script_name,
            host_name=host_name,
            device_name=device_id,
        )
        if script_result_id:
            update_script_execution_result(
                script_result_id=script_result_id,
                success=False,
                execution_time_ms=0,
                html_report_r2_path=report_result.get('report_path') or None,
                html_report_r2_url=report_url or None,
                logs_r2_path=report_result.get('logs_path') or None,
                logs_r2_url=logs_url or None,
                error_msg=error,
            )

        return {
            'script_result_id': script_result_id,
            'report_url': report_url,
            'logs_url': logs_url,
        }
    except Exception as artifact_err:
        print(f"[@server_script:execute_script] Failed to persist server failure artifacts (non-fatal): {artifact_err}")
        return {}


def _build_lock_conflict_payload(host_name: str, device_id: str, lock_info: dict) -> dict:
    return {
        'success': False,
        'error': f'Device {host_name}:{device_id} is locked',
        'errorType': 'device_locked',
        'owner_type': lock_info.get('owner_type'),
        'owner_user_id': lock_info.get('owner_user_id'),
        'owner_session_id': lock_info.get('owner_session_id'),
        'owner_job_id': lock_info.get('owner_job_id'),
        'can_wait': True,
        'can_force_takeover': bool(lock_info.get('can_force_takeover', False)),
        'message': lock_info.get('lock_reason') or 'Device is currently in use by another execution',
        'lock_info': lock_info,
    }

def analyze_script_source(source_text, script_name='virtual_script'):
    """
    Analyze Python *source text* to extract parameter information (argparse /
    _script_args). Shared by disk-script analysis (analyze_script_parameters)
    and DB-stored virtual scripts.
    """
    original_source = source_text or ''

    # Read first 300 lines to analyze parameters (some scripts have args later in file)
    lines = [line.strip() for line in original_source.splitlines()[:300]]
    script_content = '\n'.join(lines)

    # Look for both argparse patterns AND _script_args decorator patterns
    parameters = []
        
    # FIRST: Check for _script_args pattern (used by @script decorator framework)
    # Format: main._script_args = ['--param:type:default', ...]
    script_args_pattern = r"_script_args\s*=\s*\[(.*?)\]"
    script_args_match = re.search(script_args_pattern, script_content, re.DOTALL)
        
    if script_args_match:
        args_content = script_args_match.group(1)
        # Parse each argument: '--param:type:default' or '--param:type'
        # Extract strings between quotes, but ignore Python comments after them
        arg_items = re.findall(r"['\"]([^'\"]+)['\"]", args_content)
        print(f"[@analyze_script] Found _script_args raw: {arg_items}")
        
        for arg_item in arg_items:
            # Strip any Python comments that somehow got included (after # character)
            if '#' in arg_item:
                arg_item = arg_item.split('#')[0].strip()
            
            # Strip any commas or whitespace that got included
            arg_item = arg_item.strip().rstrip(',').strip()
            
            # Parse format: --param-name:type:default or --param-name:type
            # Extended: --param-name:type:default:choice1|choice2|choice3
            # NOTE: defaults may contain colons (e.g. URLs like https://192.168.1.1),
            # so we identify the choices part by the presence of '|' and rejoin the rest as default.
            all_parts = arg_item.split(':')
            if len(all_parts) >= 2:
                # Keep dashes in parameter names - they're used for command-line arguments
                param_name = all_parts[0].replace('--', '')
                param_type = all_parts[1] if len(all_parts) > 1 else 'str'

                # Remaining parts after name:type — find choices (contains '|')
                remaining = all_parts[2:]
                choices_raw = None
                default_parts = remaining
                for ri in range(len(remaining) - 1, -1, -1):
                    if '|' in remaining[ri]:
                        choices_raw = remaining[ri]
                        default_parts = remaining[:ri]
                        break
                default_value = ':'.join(default_parts) if default_parts else None

                # Convert default values
                if default_value == 'None':
                    default_value = None
                elif default_value == 'true' or default_value == 'True':
                    default_value = 'true'
                elif default_value == 'false' or default_value == 'False':
                    default_value = 'false'

                # Parse pipe-separated choices
                choices = [c.strip() for c in choices_raw.split('|') if c.strip()] if choices_raw else None

                param = {
                    'name': param_name,
                    'type': 'optional',
                    'required': False,
                    'help': '',
                    'default': default_value,
                    'dataType': param_type,
                }
                if choices:
                    param['choices'] = choices
                print(f"[@analyze_script] Parsed parameter from _script_args: {param}")
                parameters.append(param)
        
    # SECOND: Look for argparse patterns (fallback for scripts not using @script decorator)
    parser_patterns = [
        r"parser\.add_argument\(['\"]([^'\"]+)['\"][^)]*\)",
        r"parser\.add_argument\(['\"]--([^'\"]+)['\"][^)]*\)",
        r"parser\.add_argument\(['\"]([^'\"]+)['\"].*help=['\"]([^'\"]*)['\"]",
    ]
        
    # Extract positional arguments (required) - only if not already found in _script_args
    positional_pattern = r"parser\.add_argument\(['\"]([^-][^'\"]*)['\"](?:[^)]*help=['\"]([^'\"]*)['\"])?[^)]*\)"
    positional_matches = re.findall(positional_pattern, script_content, re.MULTILINE)
        
    for match in positional_matches:
        param_name = match[0]
        help_text = match[1] if len(match) > 1 else ''
        
        # Skip if already added from _script_args
        if not any(p['name'] == param_name for p in parameters):
            parameters.append({
                'name': param_name,
                'type': 'positional',
                'required': True,
                'help': help_text,
                'default': None
            })
        
    # Extract optional arguments with better multi-line handling
    # Look for parser.add_argument('--param_name', ... ) patterns that can span multiple lines
    optional_pattern = r"parser\.add_argument\(['\"]--([^'\"]+)['\"]([^)]*?)\)"
        
    # Find all add_argument calls for optional parameters - only if not already found in _script_args
    for match in re.finditer(optional_pattern, script_content, re.MULTILINE | re.DOTALL):
        param_name = match.group(1)
        
        # Skip if already added from _script_args
        if any(p['name'] == param_name for p in parameters):
            continue
        
        args_content = match.group(2)  # Everything between the parameter name and closing )
        
        # Extract help text
        help_match = re.search(r"help=['\"]([^'\"]*)['\"]", args_content)
        help_text = help_match.group(1) if help_match else ''
        
        # Extract default value
        default_match = re.search(r"default=([^,)]+)", args_content)
        default_value = None
        if default_match:
            default_raw = default_match.group(1).strip()
            # Handle different types of defaults
            if default_raw == 'True':
                default_value = 'true'
            elif default_raw == 'False':
                default_value = 'false'
            elif default_raw.startswith("'") and default_raw.endswith("'"):
                default_value = default_raw[1:-1]
            elif default_raw.startswith('"') and default_raw.endswith('"'):
                default_value = default_raw[1:-1]
            elif default_raw.isdigit():
                default_value = default_raw
            else:
                # For complex expressions like lambda, just take the value before comma/parenthesis
                default_value = default_raw.split(',')[0].split(')')[0].strip()
        
        parameters.append({
            'name': param_name,
            'type': 'optional',
            'required': False,
            'help': help_text,
            'default': default_value
        })
        
    # NO MORE INJECTION - Scripts explicitly define all their parameters
    # Framework parameters (userinterface_name, host, device) should be
    # explicitly defined in script's _script_args if the script needs them
        
    # Special handling for common patterns
    if 'userinterface_name' in [p['name'] for p in parameters]:
        # Add suggestions for userinterface_name based on common patterns
        ui_param = next(p for p in parameters if p['name'] == 'userinterface_name')
        ui_param['suggestions'] = [
            'example_mobile',
            'example_androidtv'
        ]
        
    # Enrich parameters with _arg_descriptions if available (from source)
    try:
        from shared.src.lib.utils.script_target_rules_utils import extract_arg_descriptions_from_source
        arg_descs = extract_arg_descriptions_from_source(original_source)
        if arg_descs:
            for param in parameters:
                desc = arg_descs.get(param['name'])
                if desc:
                    param['description'] = desc
    except Exception:
        pass

    return {
        'success': True,
        'parameters': parameters,
        'script_name': script_name,
        'has_parameters': len(parameters) > 0
    }


def analyze_script_parameters(script_path):
    """Analyze a Python script file (disk) — thin wrapper over analyze_script_source."""
    if not os.path.exists(script_path):
        return {'success': False, 'error': f'Script not found: {script_path}'}

    with open(script_path, 'r', encoding='utf-8') as f:
        source_text = f.read()

    return analyze_script_source(source_text, os.path.basename(script_path))

@server_script_bp.route('/script/identity-map', methods=['GET'])
@handle_route_exceptions('script:identity_map')
def get_script_identity_map():
    """Serve the effective script identity map: legacy JSON with the DB rows on top.

    The editable source of truth is the executable_identity table
    (/server/script-identity/*); test_scripts/script_identity_map.json is the
    legacy fallback kept for one release. Always 200 — an empty map is a valid
    answer, and the old 404 forced every caller to special-case it.
    """
    from shared.src.lib.utils.script_identity_utils import load_effective_identity_map
    return jsonify({
        'version': 1,
        'scripts': load_effective_identity_map(request.args.get('team_id')),
    })


@server_script_bp.route('/script/analyze', methods=['POST'])
def analyze_script():
    """Analyze script parameters (disk script or DB-stored virtual script)."""
    data = request.get_json()
    script_name = data.get('script_name')

    # Virtual scripts: analyze the DB source instead of a disk file.
    virtual_script_id = data.get('virtual_script_id')
    if virtual_script_id:
        from shared.src.lib.database.virtual_scripts_db import get_virtual_script
        team_id = request.args.get('team_id')
        row = get_virtual_script(virtual_script_id, team_id) if team_id else get_virtual_script(virtual_script_id)
        if not row:
            return jsonify({'success': False, 'error': 'Virtual script not found'}), 404
        return jsonify(analyze_script_source(row.get('source', ''), script_name or row.get('name')))

    if not script_name:
        return jsonify({
            'success': False,
            'error': 'script_name is required'
        }), 400
        
    # Use centralized script path logic
    from  backend_server.src.lib.utils.script_utils import get_script_path
        
    try:
        script_path = get_script_path(script_name)
    except ValueError as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 404
        
    print(f"[@analyze_script] Looking for script at: {script_path}")
    print(f"[@analyze_script] Script exists: {os.path.exists(script_path)}")
        
    # Analyze parameters
    analysis = analyze_script_parameters(script_path)
        
    if not analysis['success']:
        return jsonify(analysis), 404
        

        
    return jsonify(analysis)
        
@server_script_bp.route('/script/get_edge_options', methods=['POST'])
def get_edge_options():
    """Get available edge action_set labels for KPI measurement script"""
    data = request.get_json()
    userinterface_name = data.get('userinterface_name')
    team_id = data.get('team_id')
    host_name = data.get('host_name')
        
    if not all([userinterface_name, team_id, host_name]):
        return jsonify({
            'success': False,
            'error': 'userinterface_name, team_id, and host_name are required'
        }), 400
        
    print(f"[@get_edge_options] Loading edges for {userinterface_name} on {host_name}")
        
    # Get host info
    host_manager = get_host_manager()
    host_info = host_manager.get_host(host_name)
        
    if not host_info:
        return jsonify({
            'success': False,
            'error': f'Host not found: {host_name}'
        }), 404
        
    # Call host to get edges
    from shared.src.lib.utils.build_url_utils import call_host
        
    response_data, status_code = call_host(
        host_info,
        '/host/script/get_edge_options',
        method='POST',
        data={
            'userinterface_name': userinterface_name,
            'team_id': team_id
        },
        timeout=30
    )
        
    if status_code != 200:
        return jsonify({
            'success': False,
            'error': f'Host request failed: {response_data.get("error", "Unknown error")}'
        }), status_code
        
    if not response_data.get('success'):
        return jsonify(response_data), 400
        
    print(f"[@get_edge_options] Found {len(response_data.get('edge_options', []))} edge options")
        
    return jsonify(response_data)
        
@server_script_bp.route('/script/list', methods=['GET'])
@handle_route_exceptions('script:list_scripts')
def list_scripts():
    """List all available Python scripts AND AI test cases"""
    # Get team_id from request args (GET request)
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'error': 'team_id is required'
        }), 400
        
    include_hidden = request.args.get('include_hidden', 'false').lower() == 'true'
    cache_key = f'{team_id}:{int(include_hidden)}'

    # Check cache first
    with _cache_lock:
        if cache_key in _script_cache:
            cached = _script_cache[cache_key]
            age = time.time() - cached['timestamp']
            if age < CACHE_CONFIG['SHORT_TTL']:
                print(f"[@cache] HIT: Script list for team {team_id} include_hidden={include_hidden} (age: {age:.1f}s)")
                return jsonify(cached['data'])
            else:
                del _script_cache[cache_key]
        
    # Get regular Python scripts
    from  backend_server.src.lib.utils.script_utils import list_available_scripts, get_scripts_directory
        
    regular_scripts = list_available_scripts()
    if not include_hidden:
        hidden_script_keys = list_hidden_library_keys(team_id, 'script')
        regular_scripts = [
            script_name for script_name in regular_scripts
            if f'{script_name}.py' not in hidden_script_keys
        ]
    scripts_dir = get_scripts_directory()
        
    # NOTE: AI test cases are loaded separately via /server/testcase/list endpoint
    # No need to mix them with scripts here
    ai_scripts = []
    ai_test_cases_info = []
        
    # Combine both types
    all_scripts = regular_scripts + ai_scripts
        
    if not all_scripts:
        return jsonify({
            'success': False,
            'error': f'No scripts found in directory: {scripts_dir} and no AI test cases'
        }), 404
        
    response_data = {
        'success': True,
        'scripts': all_scripts,
        'count': len(all_scripts),
        'scripts_directory': scripts_dir,
        'regular_scripts': regular_scripts,
        'ai_scripts': ai_scripts,
        'ai_test_cases_info': ai_test_cases_info  # Metadata for frontend
    }
        
    # Store in cache
    with _cache_lock:
        _script_cache[cache_key] = {
            'data': response_data,
            'timestamp': time.time()
        }
        print(f"[@cache] SET: Script list for team {team_id} include_hidden={include_hidden}")
        
    return jsonify(response_data)
        
@server_script_bp.route('/script/upload', methods=['POST'])
@handle_route_exceptions('script:upload')
def upload_script():
    """Upload a Python test script: save it to the server's test_scripts/ directory and
    fan it out to every registered host so it's immediately runnable everywhere.

    Multipart form fields:
      - file: the .py script
      - overwrite: 'true' to replace an existing script (on server + all hosts)

    When the script already exists and overwrite was not requested, returns
    409 {success: false, exists: true, filename} so the frontend can confirm first.
    """
    from werkzeug.utils import secure_filename
    from backend_server.src.lib.utils.script_utils import get_scripts_directory
    from backend_server.src.lib.utils.route_utils import proxy_to_host_direct

    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file provided'}), 400

    file = request.files['file']
    safe_name = secure_filename(file.filename or '')
    if not safe_name or not safe_name.endswith('.py'):
        return jsonify({'success': False, 'error': 'File must be a .py script'}), 400

    overwrite = request.form.get('overwrite', 'false').lower() == 'true'

    scripts_dir = get_scripts_directory()
    os.makedirs(scripts_dir, exist_ok=True)
    target_path = os.path.join(scripts_dir, safe_name)

    if os.path.exists(target_path) and not overwrite:
        return jsonify({'success': False, 'exists': True, 'filename': safe_name}), 409

    # Save on the server
    file.save(target_path)

    # Read the saved content (scripts are text) to fan out to hosts as JSON
    with open(target_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Push to every registered host so the script is runnable on all of them
    host_results = []
    hosts = list(get_host_manager().get_all_hosts().values())
    for host in hosts:
        host_name = host.get('host_name', 'unknown')
        try:
            resp, status = proxy_to_host_direct(
                host,
                '/host/script/upload',
                method='POST',
                data={'filename': safe_name, 'content': content, 'overwrite': True},
                timeout=15,
            )
            ok = status == 200 and isinstance(resp, dict) and resp.get('success')
            host_results.append({
                'host_name': host_name,
                'ok': bool(ok),
                'error': None if ok else (resp.get('error') if isinstance(resp, dict) else f'HTTP {status}'),
            })
        except Exception as e:
            host_results.append({'host_name': host_name, 'ok': False, 'error': str(e)})

    # Refresh the cached script list so the upload shows up immediately
    invalidate_script_list_cache()

    return jsonify({
        'success': True,
        'filename': safe_name,
        'scripts_directory': scripts_dir,
        'hosts': host_results,
    })


@server_script_bp.route('/script/abortRunning', methods=['POST'])
def abort_running_script():
    """Abort currently running script on a host device."""
    data = request.get_json() or {}
    host_name = data.get('host_name')
    device_id = data.get('device_id')

    if not host_name or not device_id:
        return jsonify({
            'success': False,
            'error': 'host_name and device_id required'
        }), 400

    host_manager = get_host_manager()
    host_info = host_manager.get_host(host_name)
    if not host_info:
        return jsonify({
            'success': False,
            'error': f'Host not found: {host_name}'
        }), 404

    from shared.src.lib.utils.build_url_utils import call_host
    response_data, status_code = call_host(
        host_info,
        '/host/script/abort',
        method='POST',
        data={'device_id': device_id},
        timeout=30
    )

    if status_code != 200:
        return jsonify({
            'success': False,
            'error': response_data.get('error', 'Failed to abort running script'),
            'host_result': response_data
        }), status_code

    return jsonify(response_data), 200
@server_script_bp.route('/script/execute', methods=['POST'])
def execute_script():
    """Execute script asynchronously to prevent timeouts"""
    data = request.get_json() or {}
        
    # Get team_id from query params (standardized pattern)
    team_id = request.args.get('team_id')
    print(f"[@server_script:execute_script] Team ID: {team_id or 'N/A'}")
        
    host_name = data.get('host_name')
    device_id = data.get('device_id')
    script_name = data.get('script_name')
    # Virtual scripts: DB-stored source. The host fetches + materializes it to a
    # temp .py file before launch (no rsync deploy). script_name is still required
    # (used as the report/result name); virtual_script_id selects the DB source.
    virtual_script_id = data.get('virtual_script_id')
    parameters = data.get('parameters', '')
    callback_url = data.get('callback_url')
    if callback_url and not resolve_callback_url(callback_url):
        return jsonify({
            'success': False,
            'error': 'Invalid callback_url. Use absolute http/https URL or configure WEBHOOK_BASE_URL for relative paths.'
        }), 400

    if not all([host_name, device_id, script_name]):
        return jsonify({
            'success': False,
            'error': 'host_name, device_id, and script_name required'
        }), 400

    # Named-variant resolution (see docs/agent/navigation/VARIANT.md "Composition"):
    # Optional top-level `variant` field. May name a single variant OR a
    # composition — a list of names, or a '+'/','-separated string. Each
    # component is validated against userinterface_variants for the supplied
    # userinterface_name BEFORE spawning, then collapsed to one canonical
    # ('+'-joined, sorted) scope appended as `--variant <canonical>`.
    from shared.src.lib.utils.navigation_graph import (
        parse_variant_list,
        canonical_variant_name,
    )
    raw_variant = data.get('variant')
    if raw_variant is not None and not isinstance(raw_variant, (str, list)):
        return jsonify({'success': False, 'error': "'variant' must be a string or list of strings"}), 400

    variant_components = parse_variant_list(raw_variant)
    variant_name = canonical_variant_name(raw_variant)  # canonical composite, or None

    if variant_components:
        userinterface_name = data.get('userinterface_name')
        if not userinterface_name and parameters:
            # Best-effort extraction from the parameters string.
            m = re.search(r'--userinterface(?:[ =])([^\s]+)', parameters)
            if m:
                userinterface_name = m.group(1).strip().strip('"').strip("'")
        if not userinterface_name:
            return jsonify({
                'success': False,
                'error': "'variant' requires 'userinterface_name' (top-level field or --userinterface in parameters)"
            }), 400

        from shared.src.lib.database.userinterface_db import list_variant_names
        available = list_variant_names(team_id, userinterface_name)
        missing = [c for c in variant_components if c not in available]
        if missing:
            return jsonify({
                'error': f"unknown variant(s) {missing} for userinterface '{userinterface_name}'; available: {available}"
            }), 400

    # Get host info from registry
    host_manager = get_host_manager()
    host_info = host_manager.get_host(host_name)
        
    if not host_info:
        return jsonify({
            'success': False,
            'error': f'Host not found: {host_name}'
        }), 404
        
    # Generate session ID if not exists
    requested_session_id = data.get('session_id')
    if requested_session_id:
        session['session_id'] = requested_session_id
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())

    session_id = session['session_id']
    user_id = data.get('user_id') or request.headers.get('X-User-ID')
    # Display name of whoever launched the run — stored on the lock so viewers see
    # both who started the script and which script is running.
    user_name = data.get('user_name')
    client_ip = get_client_ip()

    # Create task for async execution
    from  backend_server.src.lib.utils.task_manager import task_manager
    task_id = task_manager.create_task('script_execute', {
        'script_name': script_name,
        'host_name': host_name,
        'device_id': device_id,
        'parameters': parameters,
        'team_id': team_id,
        'callback_url': callback_url,
        'session_id': session_id,
        'user_id': user_id,
    })

    # Handle force_unlock: abort running execution and release existing lock
    force_unlock = bool(data.get('force_unlock', False))
    if force_unlock:
        # strict=True: a new script is about to start on this device, so a failed abort
        # must block rather than risk two runs driving the same device.
        force_result = abort_and_force_unlock(host_name, device_id, strict=True)
        if not force_result.get('success'):
            task_manager.complete_task(task_id, {}, error=force_result.get('errorType') or 'force_unlock_failed')
            return jsonify({
                'success': False,
                'error': force_result.get('error') or 'Failed to force unlock device',
                'errorType': force_result.get('errorType') or 'force_unlock_failed',
                'details': force_result.get('details'),
            }), 409
        emit_system_update('lock_changed', {
            'host_name': host_name,
            'device_id': device_id,
            'is_locked': False,
            'lock_info': force_result.get('lock_info'),
        })
        print(
            f"[@server_script:execute_script] Force unlocked {host_name}:{device_id} "
            f"(aborted={force_result.get('aborted')})"
        )

    # Acquire execution lock before dispatching to host
    lock_result = acquire_device_lock(
        host_name=host_name,
        device_id=device_id,
        owner_type='script_execution',
        owner_session_id=session_id,
        owner_user_id=user_id,
        owner_user_name=user_name,
        owner_job_id=task_id,
        lock_reason=f'script_execute:{script_name}',
        can_force_takeover=True,
        client_ip=client_ip,
        allow_same_user_takeover=True,
    )
    if not lock_result.get('success'):
        conflict = lock_result.get('conflict') or get_device_lock_info(host_name, device_id)
        task_manager.complete_task(task_id, {}, error='device_locked')
        if conflict:
            return jsonify(_build_lock_conflict_payload(host_name, device_id, conflict)), 423
        return jsonify({
            'success': False,
            'error': f'Failed to lock device {host_name}:{device_id} for script execution',
        }), 500

    # If lock is subordinate to manual_control, don't release on completion
    is_subordinate_lock = lock_result.get('subordinate', False)

    # Announce the new lock so viewers' lock badges update immediately — every
    # other acquire path (takeControl, acquireExecutionLock, campaign execute)
    # emits this; without it the badge waits for the 15s fallback poll and a
    # short script can finish before anyone ever sees the device as locked.
    emit_system_update('lock_changed', {
        'host_name': host_name,
        'device_id': device_id,
        'is_locked': True,
        'lock_info': lock_result.get('lock_info'),
    })

    # Resolve script identity (prefix / display_name) to forward to the host.
    # Priority 1: explicit fields on the request (frontend already has the map).
    # Priority 2: server-side resolve_script_identity — executable_identity rows
    #             for this team, then the legacy test_scripts/script_identity_map.json.
    # Whatever we forward wins on the host (VPT_SCRIPT_PREFIX env var), so a host
    # needs no identity map of its own.
    identity_prefix = (data.get('prefix') or '').strip() or None
    identity_display = (data.get('display_name') or '').strip() or None
    if not identity_prefix or not identity_display:
        try:
            from shared.src.lib.utils.script_identity_utils import resolve_script_identity
            resolved = resolve_script_identity(script_name, team_id=team_id) or {}
            identity_prefix = identity_prefix or resolved.get('prefix')
            identity_display = identity_display or resolved.get('display_name')
        except Exception as identity_err:
            print(f"[@server_script:execute_script] script identity fallback failed (non-fatal): {identity_err}")

    # Prepare request payload with callback
    payload = {
        'script_name': script_name,
        'device_id': device_id,
        'task_id': task_id
    }
    if virtual_script_id:
        payload['virtual_script_id'] = virtual_script_id
        # Scope virtual-script + shared-lib (_script_libs) resolution to this team.
        if team_id:
            payload['team_id'] = team_id
    if identity_prefix:
        payload['prefix'] = identity_prefix
    if identity_display:
        payload['display_name'] = identity_display

    # Add parameters if provided
    parameters_normalized = parameters.strip() if isinstance(parameters, str) else ''

    # Append --variant <name> to argv if a top-level variant was supplied and
    # it's not already present in the parameters string. The script-side
    # argparser receives the same argument (validation script & friends declare
    # --variant in _script_args).
    if variant_name and '--variant' not in (parameters_normalized or ''):
        if parameters_normalized:
            parameters_normalized = f"{parameters_normalized} --variant {variant_name}"
        else:
            parameters_normalized = f"--variant {variant_name}"

    if parameters_normalized:
        payload['parameters'] = parameters_normalized

    # Trigger provenance: where did this request come from? Trust the caller's
    # explicit trigger.type if it sent one (MCP / scheduler proxies do), otherwise
    # default to "api" since we're in an HTTP route.
    incoming_trigger = data.get('trigger') if isinstance(data.get('trigger'), dict) else {}
    payload['trigger'] = {
        'type': (incoming_trigger.get('type') or 'api'),
        'caller_ip': incoming_trigger.get('caller_ip') or client_ip,
        'caller_user': incoming_trigger.get('caller_user') or user_id,
    }

    # Execution environment (dev/test/prod): what capacity this run counts as,
    # distinct from trigger.type (who/what triggered it). Untagged runs default
    # to 'prod' so nothing silently drops out of prod KPIs/dashboards.
    incoming_environment = data.get('environment')
    payload['environment'] = incoming_environment if incoming_environment in ('dev', 'test', 'prod') else 'prod'

    # Code versions for the run metadata: the server fills its own version (read
    # from its VERSION.txt) and forwards the frontend version the caller sent
    # (the browser knows its own build). The host version is read locally on the
    # host. Server is the source of truth; mismatches surface in reporting.
    from routes.server_system_routes import _read_local_deployed_version
    incoming_versions = data.get('versions') if isinstance(data.get('versions'), dict) else {}
    payload['versions'] = {
        'server': _read_local_deployed_version('/opt/virtualpytest'),
        'frontend': incoming_versions.get('frontend'),
    }

    # Optional manual device info merged into the run's metadata.info.
    incoming_device_info = data.get('device_info')
    if isinstance(incoming_device_info, dict) and incoming_device_info:
        payload['device_info'] = incoming_device_info
        
    # Host will build callback URL directly, no need to pass it
        
    # Persist a running execution row so it survives page refresh
    adhoc_exec_id = None
    try:
        supabase = get_supabase_client()
        _dep, adhoc_exec = create_adhoc_execution(
            supabase,
            team_id=team_id,
            host_name=host_name,
            device_id=device_id,
            script_name=script_name,
            parameters=parameters,
            # Persist the full launch-time config so "Last Executions" can
            # rerun this row in one click after a page reload. For direct
            # script runs the relaunch shape is straightforward.
            rerun_payload={
                'type': 'script',
                'scriptName': script_name,
                'hostName': host_name,
                'deviceId': device_id,
                'parameters': parameters or '',
            },
        )
        adhoc_exec_id = adhoc_exec['id']
        # Store in task params so task_complete can update it
        task_manager.get_task(task_id)['params']['adhoc_exec_id'] = adhoc_exec_id
        emit_system_update('deployment_changed', {
            'domain': 'deployment',
            'action': 'execution_started',
            'execution_id': adhoc_exec_id,
        })
        print(f"[@route:server_script:execute_script] Created adhoc execution {adhoc_exec_id}")
    except Exception as adhoc_err:
        print(f"[@route:server_script:execute_script] Adhoc execution row failed (non-fatal): {adhoc_err}")

    # Execute in background thread. Completion is emitted via socket events.
    import threading
    def execute_async():
        try:
            from shared.src.lib.utils.build_url_utils import call_host
            
            print(f"[@route:server_script:execute_script] Starting background execution for task {task_id}")
            print(f"[@route:server_script:execute_script] Payload: {payload}")
            
            # Use centralized call_host() which automatically adds API key
            response_data, status_code = call_host(
                host_info,
                '/host/script/execute',
                method='POST',
                data=payload,
                timeout=120  # 2 minutes timeout for immediate response
            )
            
            if status_code not in [200, 202]:
                # Host execution failed, complete task with error and unlock device
                print(f"[@route:server_script:execute_script] Host execution failed for task {task_id}")
                error_msg = (response_data.get('error') if isinstance(response_data, dict) else None) \
                    or 'Host execution failed'
                # The host never ran the script, so it produced no log/report.
                # Generate a server-side log+report explaining the failure and
                # persist a script_results row so the run shows clickable
                # Logs/Report instead of "No Logs"/"No Report".
                artifacts = _persist_server_failure_artifacts(
                    team_id=team_id, host_info=host_info, host_name=host_name,
                    device_id=device_id, script_name=script_name, parameters=parameters,
                    error=error_msg, status_code=status_code,
                )
                if adhoc_exec_id:
                    try:
                        complete_adhoc_execution(
                            get_supabase_client(), adhoc_exec_id, success=False,
                            script_result_id=artifacts.get('script_result_id'),
                        )
                        emit_system_update('deployment_changed', {
                            'domain': 'deployment', 'action': 'execution_completed',
                            'execution_id': adhoc_exec_id,
                        })
                    except Exception:
                        pass
                if not is_subordinate_lock:
                    release_result = release_device_lock(
                        host_name=host_name,
                        device_id=device_id,
                        owner_session_id=session_id,
                        owner_type='script_execution',
                        owner_job_id=task_id,
                        force=False,
                    )
                    if release_result.get('success'):
                        emit_system_update('lock_changed', {
                            'host_name': host_name,
                            'device_id': device_id,
                            'is_locked': False,
                            'lock_info': release_result.get('lock_info'),
                        })
                else:
                    _clear_subordinate_script(host_name, device_id, task_id)
                task_manager.complete_task(task_id, {
                    'success': False,
                    'exit_code': 1,
                    'error': error_msg,
                    'stderr': error_msg,
                    'report_url': artifacts.get('report_url', ''),
                    'logs_url': artifacts.get('logs_url', ''),
                    'script_result_id': artifacts.get('script_result_id'),
                }, error=error_msg)
            else:
                print(f"[@route:server_script:execute_script] Host execution started for task {task_id}")
                # Task will be completed by the host's callback (which will unlock device)

        except Exception as e:
            print(f"[@route:server_script:execute_script] Background execution error for task {task_id}: {e}")
            print(f"[@route:server_script:execute_script] Exception type: {type(e).__name__}")
            import traceback
            tb_text = traceback.format_exc()
            print(f"[@route:server_script:execute_script] Traceback: {tb_text}")
            error_msg = str(e)
            # The script never ran — generate a server-side log+report (incl. the
            # traceback) and persist a script_results row so the run surfaces
            # clickable Logs/Report instead of "No Logs"/"No Report".
            artifacts = _persist_server_failure_artifacts(
                team_id=team_id, host_info=host_info, host_name=host_name,
                device_id=device_id, script_name=script_name, parameters=parameters,
                error=error_msg, traceback_text=tb_text,
            )
            if adhoc_exec_id:
                try:
                    complete_adhoc_execution(
                        get_supabase_client(), adhoc_exec_id, success=False,
                        script_result_id=artifacts.get('script_result_id'),
                    )
                    emit_system_update('deployment_changed', {
                        'domain': 'deployment', 'action': 'execution_completed',
                        'execution_id': adhoc_exec_id,
                    })
                except Exception:
                    pass
            # Unlock device on error (skip if subordinate to manual_control)
            if not is_subordinate_lock:
                release_result = release_device_lock(
                    host_name=host_name,
                    device_id=device_id,
                    owner_session_id=session_id,
                    owner_type='script_execution',
                    owner_job_id=task_id,
                    force=False,
                )
                if release_result.get('success'):
                    emit_system_update('lock_changed', {
                        'host_name': host_name,
                        'device_id': device_id,
                        'is_locked': False,
                        'lock_info': release_result.get('lock_info'),
                    })
            else:
                _clear_subordinate_script(host_name, device_id, task_id)
            task_manager.complete_task(task_id, {
                'success': False,
                'exit_code': 1,
                'error': error_msg,
                'stderr': error_msg,
                'report_url': artifacts.get('report_url', ''),
                'logs_url': artifacts.get('logs_url', ''),
                'script_result_id': artifacts.get('script_result_id'),
            }, error=error_msg)
        
    threading.Thread(target=execute_async, daemon=True).start()
        
    return jsonify({
        'success': True,
        'task_id': task_id,
        'status': 'started',
        'message': f'Script "{script_name}" started in background',
        'lock_info': lock_result.get('lock_info'),
        'deployment_execution_id': adhoc_exec_id,
    }), 202
        
def _clear_subordinate_script(host_name, device_id, task_id):
    """Drop the subordinate-script annotation from a manual_control lock and tell viewers.

    Used when a script that ran under a user's lock ends: the lock survives (the user
    still holds the device), only the running-script label goes away.
    """
    if not host_name or not device_id:
        return
    clear_result = clear_device_active_script(
        host_name=host_name, device_id=device_id, owner_job_id=task_id
    )
    if clear_result.get('cleared'):
        emit_system_update('lock_changed', {
            'host_name': host_name,
            'device_id': device_id,
            'is_locked': True,
            'lock_info': clear_result.get('lock_info'),
        })


def _derive_run_success(result: dict, error) -> bool:
    """Did this run actually pass?

    `script_success` comes from the SCRIPT_SUCCESS: marker the @script decorator
    prints. It is None both when a script ran without emitting the marker AND
    when the script never ran at all, so it cannot be the only signal.

    The old rule was `script_success if not None else not bool(error)`, which
    read "the host reported no error" as "the run passed". A host that failed
    before launching the subprocess — virtual-script materialization denied by
    filesystem permissions, say — returns {'success': False, 'exit_code': 1} and
    sends it as a normal (non-error) callback, so a run that never executed was
    recorded green with no report (BUG-0089).

    Order matters: the marker is the test outcome and wins; everything below it
    is evidence about whether the run happened at all.
    """
    if not isinstance(result, dict):
        result = {}

    script_success = result.get('script_success')
    if script_success is not None:
        return bool(script_success)

    if error:
        return False

    # The executor's own verdict, set on every early-return failure path.
    if result.get('success') is False:
        return False

    # A non-zero exit code is a failure even with no marker (hard crash, kill).
    exit_code = result.get('exit_code')
    if exit_code is not None and exit_code != 0:
        return False

    # Nothing at all came back: no marker, no exit code, no error. The host never
    # ran anything — absence of evidence is not evidence of a pass.
    if exit_code is None and not result.get('script_result_id'):
        return False

    return True


@server_script_bp.route('/script/taskComplete', methods=['POST'])
def task_complete():
    """Receive script execution completion callback from host"""
    print("[@route:server_script:task_complete] Received script completion callback")
        
    # Get callback data
    callback_data = request.get_json() or {}
    task_id = callback_data.get('task_id')
    result = callback_data.get('result') or {}
    error = callback_data.get('error')
        
    if not task_id:
        return jsonify({
            'success': False,
            'error': 'task_id required'
        }), 400
        
    # Convert report URL to signed URL
    if result.get('report_url'):
        from shared.src.lib.utils.cloudflare_utils import convert_to_signed_url
        result['report_url'] = convert_to_signed_url(result['report_url'])
        
    # Update task in manager
    from  backend_server.src.lib.utils.task_manager import task_manager
        
    # Get task info to unlock device and enrich completion payload
    task_info = task_manager.get_task(task_id)
    host_name = None
    device_id = None
    team_id = None
    callback_url = None
    task_params = task_info.get('params', {}) if task_info else {}
    if task_params:
        host_name = task_params.get('host_name')
        device_id = task_params.get('device_id')
        team_id = task_params.get('team_id')
        callback_url = task_params.get('callback_url')
        if host_name and device_id:
            # Check if lock is still manual_control (script ran under umbrella)
            current_lock_info = get_device_lock_info(host_name, device_id)
            if current_lock_info and current_lock_info.get('owner_type') == 'manual_control':
                # Script ran under manual_control umbrella — don't release the lock,
                # just drop the "script running" annotation so the badge falls back
                # to the lock owner alone.
                print(f"[@route:server_script:task_complete] Device {host_name}:{device_id} under manual_control umbrella, skipping unlock")
                _clear_subordinate_script(host_name, device_id, task_id)
            else:
                unlock_result = release_device_lock(
                    host_name=host_name,
                    device_id=device_id,
                    owner_session_id=task_params.get('session_id'),
                    owner_type='script_execution',
                    owner_job_id=task_id,
                    force=False,
                )
                if unlock_result.get('success'):
                    emit_system_update('lock_changed', {
                        'host_name': host_name,
                        'device_id': device_id,
                        'is_locked': False,
                        'lock_info': unlock_result.get('lock_info'),
                    })
                    print(f"[@route:server_script:task_complete] Device unlock for {host_name}:{device_id}: success")
                else:
                    print(
                        f"[@route:server_script:task_complete] Device unlock for {host_name}:{device_id} failed: "
                        f"{unlock_result.get('error')}"
                    )
        
    # Update adhoc deployment_execution row if present
    adhoc_exec_id = task_params.get('adhoc_exec_id')
    if adhoc_exec_id:
        try:
            script_result_id = result.get('script_result_id')
            adhoc_success = _derive_run_success(result, error)
            complete_adhoc_execution(
                get_supabase_client(), adhoc_exec_id,
                success=adhoc_success,
                script_result_id=script_result_id,
            )
            emit_system_update('deployment_changed', {
                'domain': 'deployment', 'action': 'execution_completed',
                'execution_id': adhoc_exec_id,
            })
            print(f"[@route:server_script:task_complete] Updated adhoc execution {adhoc_exec_id}")
        except Exception as adhoc_err:
            print(f"[@route:server_script:task_complete] Adhoc execution update failed (non-fatal): {adhoc_err}")

    task_manager.complete_task(task_id, result, error)
    notify_result = notify_completion(
        {
            'task_id': task_id,
            'execution_type': 'script',
            'status': 'failed' if error else 'completed',
            'host_name': host_name,
            'device_id': device_id,
            'team_id': team_id,
            'result': result,
            'error': error,
            'action': 'script_task_complete',
        },
        callback_url=callback_url,
    )
    if notify_result.get('webhook_error'):
        print(f"[@route:server_script:task_complete] Callback webhook error for task {task_id}: {notify_result['webhook_error']}")
    elif notify_result.get('webhook_sent'):
        print(f"[@route:server_script:task_complete] Callback webhook sent for task {task_id}")
        
    print(f"[@route:server_script:task_complete] Task {task_id} marked as {'failed' if error else 'completed'}")
        
    return jsonify({
        'success': True,
        'message': 'Script completion processed'
    }), 200
        
@server_script_bp.route('/script/status/<task_id>', methods=['GET'])
def get_task_status(task_id):
    """Get status of an async script execution task"""
    from  backend_server.src.lib.utils.task_manager import task_manager
    task = task_manager.get_task(task_id)
        
    if not task:
        return jsonify({
            'success': False,
            'error': 'Task not found'
        }), 404

    task_response = dict(task)
    if task_response.get('result'):
        result = dict(task_response['result'])
        result.pop('stdout', None)
        result.pop('stderr', None)
        task_response['result'] = result
        
    return jsonify({
        'success': True,
        'task': task_response
    }), 200


@server_script_bp.route('/script/progress', methods=['POST'])
def script_progress():
    """
    Receive a live progress event from a running script subprocess and fan it
    out as an `execution_update` (status="running") on the /system Socket.io
    namespace. This is best-effort plumbing — failures must not bubble back
    into the script.
    """
    data = request.get_json(silent=True) or {}
    task_id = data.get('task_id')
    if not task_id:
        return jsonify({'success': False, 'error': 'task_id required'}), 400

    payload = {
        'domain': 'execution',
        'execution_type': 'script',
        'execution_id': task_id,
        'status': 'running',
        'progress': data.get('progress'),
        'message': data.get('message'),
        'result': {
            'step': data.get('step'),
            'step_number': data.get('step_number'),
            'total_steps': data.get('total_steps'),
        },
        'timestamp': time.time(),
    }
    emit_system_update('execution_update', payload)
    return jsonify({'success': True}), 200


@server_script_bp.route('/script/releaseDevice', methods=['POST'])
def release_device_early():
    """Release a device's lock mid-run, when the script subprocess reports it no
    longer needs control (before report/video/upload).

    Mirrors the manual_control guard in /script/taskComplete: if a user holds the
    lock (manual_control umbrella) the script is subordinate to it, so we must NOT
    release it. Otherwise release the script_execution / deployment_execution lock
    so the next user/job can take control immediately. The normal completion
    callback releases idempotently afterwards (no-op), so the end state is
    unchanged — only the timing moves earlier.

    Race-safe: we read the current owner_type and release with force=False scoped
    to that type, so if the lock was taken over (e.g. became manual_control)
    between the read and the release it is left untouched.
    """
    data = request.get_json(silent=True) or {}
    host_name = data.get('host_name')
    device_id = data.get('device_id')
    if not host_name or not device_id:
        return jsonify({'success': False, 'error': 'host_name and device_id required'}), 400

    current_lock_info = get_device_lock_info(host_name, device_id)
    if not current_lock_info:
        return jsonify({'success': True, 'released': False, 'message': 'not_locked'}), 200

    owner_type = current_lock_info.get('owner_type')
    if owner_type == 'manual_control':
        print(f"[@route:server_script:release_device_early] {host_name}:{device_id} under manual_control umbrella, skipping early release")
        return jsonify({'success': True, 'released': False, 'message': 'manual_control'}), 200

    release_result = release_device_lock(
        host_name=host_name,
        device_id=device_id,
        owner_type=owner_type,
        force=False,
    )
    if release_result.get('success') and release_result.get('released'):
        emit_system_update('lock_changed', {
            'host_name': host_name,
            'device_id': device_id,
            'is_locked': False,
            'lock_info': release_result.get('lock_info'),
        })
        print(f"[@route:server_script:release_device_early] Early released {host_name}:{device_id} (owner_type={owner_type})")
    elif not release_result.get('success'):
        print(f"[@route:server_script:release_device_early] Early release failed for {host_name}:{device_id}: {release_result.get('error')}")
    return jsonify({
        'success': bool(release_result.get('success')),
        'released': bool(release_result.get('released')),
    }), 200

