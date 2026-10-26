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
from backend_server.src.lib.utils.trigger_utils import resolve_caller_user
from backend_server.src.lib.utils.lock_utils import (
    resolve_lock_owner,
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
from shared.src.lib.utils.script_params_utils import analyze_script_source
from shared.src.lib.utils.script_target_rules_utils import target_incompatibility
from backend_server.src.lib.utils.script_utils import extract_script_target_rules
from backend_server.src.lib.utils.adhoc_execution import create_adhoc_execution, complete_adhoc_execution
from backend_server.src.lib.auth_middleware import require_permission

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


def _lock_held_by_browser_isolated_run(lock_info) -> bool:
    """True when the device lock belongs to a browser-isolated script run.

    Such a run drives its OWN Chrome (its own debug port, its own profile), so it does
    not hold the device to itself: another browser-isolated run may go beside it
    (TASK-146). Any other owner - a Take Control, a script that drives the host's own
    browser - still blocks the device.
    """
    if not lock_info:
        return False
    if lock_info.get('owner_type') != 'script_execution':
        return False
    reason = lock_info.get('lock_reason') or ''
    return reason.endswith('#browser_isolated')


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


def _queue_run_until_free(*, task_id, team_id, script_name, host_name, device_id, parameters,
                          virtual_script_id, data, conflict, reason, message):
    """Park this run until the device frees up.

    This is exactly what the Run Tests page does when it gets a 423: a one-shot
    deployment the host scheduler runs once the device frees up, done server-side so an
    API caller firing a batch (BUG-0118) gets the same queue as a browser tab. The
    task_id stays open and is completed by /server/deployments/executionComplete with the
    run's real result.

    (A browser-isolated run does not come here: it runs beside the other one, and the
    host's browser pool waits for a slot on its own - see TASK-150.)

    Returns the (response, 202) pair for the caller to return, or None when the queue
    could not be created - the caller then refuses with the 423 it already knows how to
    handle.
    """
    from backend_server.src.lib.utils.task_manager import task_manager
    try:
        from routes.server_deployment_routes import create_deployment_record
        ui_match = re.search(r'--userinterface(?:[ =])([^\s]+)', parameters or '')
        queued_deployment = create_deployment_record(team_id, {
            'name': f"{script_name}_{host_name}_{device_id}_{int(time.time() * 1000)}",
            'host_name': host_name,
            'device_id': device_id,
            'script_name': script_name,
            'userinterface_name': data.get('userinterface_name') or (ui_match.group(1) if ui_match else ''),
            'parameters': parameters or '',
            'cron_expression': '0 0 1 1 *',
            'max_executions': 1,
            'virtual_script_id': virtual_script_id,
            'environment': data.get('environment'),
            'device_info': data.get('device_info'),
            'rerun_payload': {
                'type': 'script',
                'scriptName': script_name,
                'hostName': host_name,
            },
            'deviceId': device_id,
            'parameters': parameters or '',
            'queued_task_id': task_id,
        })
        task_manager.get_task(task_id)['params']['queued_deployment_id'] = queued_deployment.get('id')
        print(f"[@server_script:execute_script] {host_name}:{device_id} {reason} - queued "
              f"{script_name} as deployment {queued_deployment.get('id')} (task {task_id})")
        return jsonify({
            'success': True,
            'queued': True,
            'task_id': task_id,
            'deployment_id': queued_deployment.get('id'),
            'message': message,
            'lock_info': conflict,
        }), 202
    except Exception as queue_err:
        # Fall back to the refusal the caller already knows how to handle.
        print(f"[@server_script:execute_script] Queue fallback failed ({queue_err}); returning device_locked")
        return None

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
        
def _build_script_items(script_names, team_id):
    """Resolve each script name to {script_ref, prefix, display_name, label}.

    The `scripts` array (bare names) is what every caller used to get, which
    forced each one to fetch /server/script/identity-map separately and
    re-implement the normalize + basename-fallback merge — the browser does that
    in identityMapCache.ts, and an external caller (idp, MCP) could not do it
    at all. `items` carries the server-rendered label so every consumer shows
    the same string.

    `script_ref` — not `label` — is what goes back to /server/script/execute.

    The map is loaded ONCE for the whole list (it is itself TTL-cached), so this
    adds no per-script query.
    """
    from shared.src.lib.utils.script_identity_utils import (
        format_script_label,
        load_effective_identity_map,
        lookup_identity_entry,
        normalize_script_ref,
    )

    try:
        identity_map = load_effective_identity_map(team_id)
    except Exception as e:
        # A missing identity map must never break the script list: items simply
        # fall back to the bare script name, which is the documented behaviour
        # for an unmapped script anyway.
        print(f"[@list_scripts] identity map unavailable, labels fall back to script names: {e}")
        identity_map = {}

    items = []
    for script_name in script_names:
        entry = lookup_identity_entry(identity_map, script_name)
        prefix = entry.get('prefix') or None
        display_name = entry.get('display_name') or None
        items.append({
            'script_ref': normalize_script_ref(script_name),
            'prefix': prefix,
            'display_name': display_name,
            'label': format_script_label(script_name, prefix, display_name),
        })
    return items


@server_script_bp.route('/script/list', methods=['GET'])
@handle_route_exceptions('script:list_scripts')
def list_scripts():
    """List all available Python scripts AND AI test cases.

    Returns both `scripts` (bare names, unchanged for back-compat) and `items`
    (the same scripts with prefix / display_name / label resolved — see
    _build_script_items). Prefer `items`.
    """
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
        'items': _build_script_items(all_scripts, team_id),
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
    # The run to stop, when the caller knows it: a device can carry several runs, and
    # the abort must hit the one that overran (E50).
    task_id = data.get('task_id')

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
        data={'device_id': device_id, 'task_id': task_id},
        timeout=30
    )

    if status_code != 200:
        return jsonify({
            'success': False,
            'error': response_data.get('error', 'Failed to abort running script'),
            'host_result': response_data
        }), status_code

    return jsonify(response_data), 200
# Launching a script on a device is `execution.run:run_test`, the same permission
# /server/testcase/execute has carried all along. This route had no gate at all, so any
# authenticated user — a viewer included — could start a run on a shared device. The test
# that says otherwise (test_permissions.py::test_viewer_cannot_run_test) existed but had
# skipped itself since the day it was written: its host_name fixture read a route that does
# not exist, so it never ran. Admin and the shared service key bypass the check inside the
# decorator, so host callbacks, idp and MCP are unaffected.
@server_script_bp.route('/script/execute', methods=['POST'])
@require_permission('execution.run:run_test')
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

    # Same target rules the frontend applies before offering a target
    # (frontend/src/utils/targetCompatibility.ts). Only for scripts that declare
    # _target_rules; virtual scripts keep their source in the DB.
    target_rules = None
    if not virtual_script_id:
        target_rules = extract_script_target_rules(script_name)
        if target_rules is not None:
            problem = target_incompatibility(target_rules, {'host_name': host_name, **host_info}, device_id)
            if problem:
                return jsonify({
                    'success': False,
                    'error': f'Target not allowed for {script_name}: {problem}',
                    'target_rules': target_rules,
                }), 400

    # A browser-isolated web script drives its OWN Chrome - its own debug port, its own
    # profile - so it does not need the device to itself: two of them can share one host
    # at the same time instead of queueing behind each other (TASK-146). Every other
    # script keeps the exclusive device lock.
    browser_isolated = bool((target_rules or {}).get('browser_isolated'))
    lock_reason = f'script_execute:{script_name}'
    if browser_isolated:
        lock_reason = f'{lock_reason}#browser_isolated'

    # Generate session ID if not exists
    requested_session_id = data.get('session_id')
    if requested_session_id:
        session['session_id'] = requested_session_id
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())

    session_id = session['session_id']
    # Verified login first; display name of whoever launched the run — stored on
    # the lock so viewers see both who started the script and which script runs.
    user_id, user_name = resolve_lock_owner(data)
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
        force_result = abort_and_force_unlock(
            host_name, device_id, strict=True, protect_others=True,
            caller_sessions=[session_id] if session_id else None, caller_user_id=user_id,
        )
        if not force_result.get('success'):
            task_manager.complete_task(task_id, {}, error=force_result.get('errorType') or 'force_unlock_failed')
            return jsonify({
                'success': False,
                'error': force_result.get('error') or 'Failed to force unlock device',
                'errorType': force_result.get('errorType') or 'force_unlock_failed',
                'details': force_result.get('details'),
                'lock_info': force_result.get('lock_info'),
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
        lock_reason=lock_reason,
        can_force_takeover=True,
        client_ip=client_ip,
        allow_same_user_takeover=True,
    )
    # True when this run holds the device lock. A parallel browser-isolated run does
    # not (it runs beside the one that does), and must not release the other's lock.
    lock_acquired = bool(lock_result.get('success'))
    if not lock_result.get('success'):
        conflict = lock_result.get('conflict') or get_device_lock_info(host_name, device_id)

        # The device is taken by another BROWSER-ISOLATED run: that run drives its own
        # Chrome, so this one can run beside it (TASK-146). Two web scripts no longer
        # queue behind each other on one host.
        if browser_isolated and _lock_held_by_browser_isolated_run(conflict):
            print(
                f"[@server_script:execute_script] {host_name}:{device_id} is used by another "
                f"browser-isolated run ({conflict.get('lock_reason')}) - running beside it "
                f"(TASK-146)"
            )
            lock_acquired = False
        else:
            # The device is busy: queue this run rather than refuse it. This is exactly
            # what the Run Tests page does when it gets a 423 - a one-shot deployment the
            # host scheduler runs once the device frees up - done server-side so an API
            # caller firing a batch (BUG-0118) gets the same queue as a browser tab. The
            # task_id stays open and is completed by /server/deployments/executionComplete
            # with the run's real result. Callers that would rather fail than wait (the
            # UI's rerun button) send queue_if_locked=false and get the 423 as before.
            queue_if_locked = data.get('queue_if_locked', True) is not False
            if conflict and queue_if_locked:
                queued = _queue_run_until_free(
                    task_id=task_id, team_id=team_id, script_name=script_name,
                    host_name=host_name, device_id=device_id, parameters=parameters,
                    virtual_script_id=virtual_script_id, data=data, conflict=conflict,
                    reason=f"locked by {conflict.get('owner_type')}",
                    message=f'Device {host_name}:{device_id} is busy; run queued and will start when it frees up',
                )
                if queued is not None:
                    return queued

            task_manager.complete_task(task_id, {}, error='device_locked')
            if conflict:
                return jsonify(_build_lock_conflict_payload(host_name, device_id, conflict)), 423
            return jsonify({
                'success': False,
                'error': f'Failed to lock device {host_name}:{device_id} for script execution',
            }), 500

    # Subordinate = the script runs under its user's Take Control (manual_control).
    # A failed launch keeps that lock; a run that ends releases it
    # (/script/taskComplete → _release_subordinate_lock).
    is_subordinate_lock = lock_result.get('subordinate', False)

    # Remember whether this run holds the lock: a parallel browser-isolated run does
    # NOT, and must never release the lock of the run it runs beside.
    try:
        task_manager.get_task(task_id)['params']['lock_acquired'] = lock_acquired
        task_manager.get_task(task_id)['params']['browser_isolated'] = browser_isolated
    except Exception as lock_flag_err:
        print(f"[@server_script:execute_script] Could not record the lock state ({lock_flag_err}) - non-fatal")

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
    # The budget the caller declared for this run (the game dispatcher knows a run must
    # not outlive its slot). The host enforces it as the run's hard ceiling instead of
    # the flat default hour (E50).
    try:
        declared_timeout = float(data['timeout_seconds']) if data.get('timeout_seconds') is not None else None
    except (TypeError, ValueError):
        declared_timeout = None
    if declared_timeout and declared_timeout > 0:
        payload['timeout_seconds'] = declared_timeout
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
    #
    # A supplied variant that canonicalises to nothing ('', 'base', []) is still
    # an explicit choice — "run base" — and must reach argv as `--variant base`.
    # ScriptExecutor treats a literal --variant flag as the caller's decision and
    # only falls back to the device's DEVICE{i}_VARIANT default when the flag is
    # absent; without this the .env default silently overrides the base the user
    # picked in Run Tests (BUG-0152).
    variant_flag = variant_name or ('base' if raw_variant is not None else None)
    if variant_flag and '--variant' not in (parameters_normalized or ''):
        if parameters_normalized:
            parameters_normalized = f"{parameters_normalized} --variant {variant_flag}"
        else:
            parameters_normalized = f"--variant {variant_flag}"

    # Append --device <device_id> to argv unless the caller already spelled it out.
    # payload['device_id'] only drives the device lock and the report path; the
    # script itself picks its device from --device, which ScriptExecutor defaults
    # to 'device1' (shared/src/lib/executors/script_executor.py). Without this an
    # API caller that omits the flag silently runs on device1 — or, when that id
    # does not exist on the host, falls back to the host's own VNC device. The
    # scheduler already appends the flag itself (backend_host deployment_scheduler).
    if device_id and '--device' not in (parameters_normalized or ''):
        if parameters_normalized:
            parameters_normalized = f"{parameters_normalized} --device {device_id}"
        else:
            parameters_normalized = f"--device {device_id}"

    if parameters_normalized:
        payload['parameters'] = parameters_normalized

    # Trigger provenance: where did this request come from? Trust the caller's
    # explicit trigger.type if it sent one (MCP / scheduler proxies do), otherwise
    # default to "api" since we're in an HTTP route.
    incoming_trigger = data.get('trigger') if isinstance(data.get('trigger'), dict) else {}
    payload['trigger'] = {
        'type': (incoming_trigger.get('type') or 'api'),
        'caller_ip': incoming_trigger.get('caller_ip') or client_ip,
        'caller_user': incoming_trigger.get('caller_user') or resolve_caller_user(user_id, user_name),
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
        # The host ties the run to this row, so it can answer "is this row still
        # running?" per row instead of "is this device busy?" (E50).
        payload['execution_id'] = adhoc_exec_id
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
                if not is_subordinate_lock and lock_acquired:
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
            # Unlock device on error (skip if subordinate to manual_control: the
            # script never ran, so the user's Take Control stays)
            if not is_subordinate_lock and lock_acquired:
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


def _release_subordinate_lock(host_name, device_id, task_id) -> bool:
    """End the run's user's Take Control when the script that ran under it ends.

    A script only runs under a manual_control lock when its user holds that lock
    (lock_utils: same-user subordinate). Leaving the device locked after the run
    meant it stayed "in control" until that user remembered to release it, and
    every queued or API run behind it waited. So a finished run releases it —
    but only the lock it ran under: still manual_control AND still annotated
    with this task (active_script_job_id). The release is scoped to
    owner_job_id=task_id, so a Take Control taken afresh in between is kept.

    Returns True if released; otherwise just clears the script annotation.
    """
    if not host_name or not device_id or not task_id:
        _clear_subordinate_script(host_name, device_id, task_id)
        return False
    lock_info = get_device_lock_info(host_name, device_id) or {}
    if (lock_info.get('owner_type') != 'manual_control'
            or lock_info.get('active_script_job_id') != task_id):
        _clear_subordinate_script(host_name, device_id, task_id)
        return False
    release_result = release_device_lock(
        host_name=host_name,
        device_id=device_id,
        owner_type='manual_control',
        owner_job_id=task_id,
        force=False,
    )
    if release_result.get('success') and release_result.get('released'):
        emit_system_update('lock_changed', {
            'host_name': host_name,
            'device_id': device_id,
            'is_locked': False,
            'lock_info': release_result.get('lock_info'),
        })
        print(f"[@route:server_script:_release_subordinate_lock] Released {host_name}:{device_id} "
              f"(user's Take Control the run {task_id} ran under)")
        return True
    _clear_subordinate_script(host_name, device_id, task_id)
    return False


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


def _describe_failed_run(result: dict) -> str:
    """Why this run failed, in words that name what actually happened (BUG-0759).

    A script that ran and reported `SCRIPT_SUCCESS:false` DID report — the test failed,
    which is the outcome the run exists to produce. Calling that "host reported no
    script result" told every consumer the host had gone quiet, which sends people
    hunting an infrastructure fault that does not exist (it cost this repo a whole
    debugging detour on 2026-10-22 before the two were told apart).

    So the message is chosen by what the callback carries:
      - stderr: the host phrased the failure, and its sentence is the reason;
      - a failed marker: the test ran and failed, and here is its report;
      - otherwise the host genuinely said nothing, which is the only case the old
        wording ever described.
    """
    if not isinstance(result, dict):
        result = {}

    # Whatever the host actually said comes first: if it phrased the failure, that
    # sentence is the reason.
    stderr = (result.get('stderr') or '').strip()
    if stderr:
        return stderr[:500]

    if result.get('script_success') is False:
        report_url = result.get('report_url')
        reason = 'The test ran and reported a failed result'
        return f"{reason}: {report_url}" if report_url else reason

    return 'host reported no script result'


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
                # Script ran under its user's Take Control: release that lock with
                # the run (only if it is still the lock this run ran under).
                _release_subordinate_lock(host_name, device_id, task_id)
            elif task_params.get('lock_acquired') is False:
                # A parallel browser-isolated run (TASK-146) holds no lock of its own:
                # the device belongs to the run it runs beside, which releases it.
                print(
                    f"[@route:server_script:task_complete] {host_name}:{device_id}: this run held "
                    f"no lock (parallel browser-isolated run) - leaving the device lock alone"
                )
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
        
    # Did this run actually pass? Derived ONCE and used for every record this
    # callback writes. The adhoc row has consulted _derive_run_success since the
    # first half of BUG-0089; the task record and the outbound webhook were still
    # on the old `'failed' if error else 'completed'` rule, so the same run that
    # the adhoc row correctly marked failed was reported to an external consumer
    # as completed. One callback must not produce two verdicts.
    run_success = _derive_run_success(result, error)

    # A failure the host did not phrase as an error still needs a reason on the
    # wire, or the consumer sees status=failed with error=None. Only ever states
    # what the callback actually carried — a test that failed is not a host that
    # said nothing (BUG-0759).
    if not run_success and not error:
        error = _describe_failed_run(result)

    # Update adhoc deployment_execution row if present
    adhoc_exec_id = task_params.get('adhoc_exec_id')
    if adhoc_exec_id:
        try:
            script_result_id = result.get('script_result_id')
            complete_adhoc_execution(
                get_supabase_client(), adhoc_exec_id,
                success=run_success,
                script_result_id=script_result_id,
            )
            emit_system_update('deployment_changed', {
                'domain': 'deployment', 'action': 'execution_completed',
                'execution_id': adhoc_exec_id,
            })
            print(f"[@route:server_script:task_complete] Updated adhoc execution {adhoc_exec_id}")
        except Exception as adhoc_err:
            print(f"[@route:server_script:task_complete] Adhoc execution update failed (non-fatal): {adhoc_err}")

    task_manager.complete_task(task_id, result, error, success=run_success)
    notify_result = notify_completion(
        {
            'task_id': task_id,
            'execution_type': 'script',
            'status': 'completed' if run_success else 'failed',
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
        
    print(f"[@route:server_script:task_complete] Task {task_id} marked as {'completed' if run_success else 'failed'}")
        
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


@server_script_bp.route('/script/liveProgress', methods=['GET'])
def script_live_progress():
    """Recorded progress of the script now running on a device, for the Run Tests "Live run"
    dialog opened by a browser that did not launch the run (or opened after it started)."""
    team_id = request.args.get('team_id')
    host_name = request.args.get('host_name')
    device_id = request.args.get('device_id')
    if not team_id or not host_name:
        return jsonify({'success': False, 'error': 'team_id and host_name required'}), 400

    from backend_server.src.lib.utils.task_manager import task_manager
    tasks = [
        t for t in task_manager.running_tasks('script_execute', team_id)
        if (t.get('params') or {}).get('host_name') == host_name
        and str((t.get('params') or {}).get('device_id') or '') == str(device_id or '')
    ]
    if not tasks:
        return jsonify({'success': True, 'task': None}), 200
    task = max(tasks, key=lambda t: t.get('created_at') or 0)
    return jsonify({'success': True, 'task': {
        'id': task['id'],
        'progress': task.get('progress'),
        'progress_steps': task.get('progress_steps') or [],
    }}), 200


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

    from backend_server.src.lib.utils.task_manager import task_manager
    task = task_manager.get_task(task_id) or {}
    payload = {
        'domain': 'execution',
        'execution_type': 'script',
        'execution_id': task_id,
        # The task's team routes the update to that team's /system room only.
        'team_id': (task.get('params') or {}).get('team_id'),
        'host_name': (task.get('params') or {}).get('host_name'),
        'device_id': (task.get('params') or {}).get('device_id'),
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
    task_manager.record_progress(task_id, {
        'step': data.get('step'),
        'step_number': data.get('step_number'),
        'total_steps': data.get('total_steps'),
        'progress': data.get('progress'),
        'message': data.get('message'),
    })
    emit_system_update('execution_update', payload)
    return jsonify({'success': True}), 200


@server_script_bp.route('/script/releaseDevice', methods=['POST'])
def release_device_early():
    """Release a device's lock mid-run, when the script subprocess reports it no
    longer needs control (before report/video/upload).

    A run under its user's Take Control (manual_control umbrella) releases that
    lock too, scoped to this task (_release_subordinate_lock) — same rule as
    /script/taskComplete. Otherwise release the script_execution / deployment_execution lock
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
        released = _release_subordinate_lock(host_name, device_id, data.get('task_id'))
        return jsonify({'success': True, 'released': released,
                        'message': None if released else 'manual_control'}), 200

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

