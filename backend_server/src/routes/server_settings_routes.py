"""
Settings Management Routes

Admin-only API for editing server and frontend .env files and proxying host
configuration changes to a selected registered host. Secrets are returned in
full to an authenticated admin; the frontend masks credential-like fields where
they are displayed.
"""

from flask import Blueprint, request, jsonify
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.auth_middleware import require_user_auth, require_role
import os
import re
import shutil
import subprocess
from datetime import datetime

server_settings_bp = Blueprint('server_settings', __name__, url_prefix='/server/settings')

# =====================================================
# FRONTEND SSH BRIDGE
# =====================================================
#
# The frontend that actually serves the site runs on one specific VM, separate
# from whichever backend_server answers this request (see
# reference_multi_server_registry in the agent memory). Reading/writing
# "frontend/.env" off this process's own local disk edits a copy nobody
# serves. When FRONTEND_SSH_HOST is set (in this server's own root .env), we
# instead SSH to that VM and run the forced command installed at
# setup/scripts/frontend_env_bridge.sh, which only allows "read" and "write"
# of exactly that one file — nothing else is reachable with this key. Without
# FRONTEND_SSH_HOST (or if the target is unreachable, e.g. a server that
# isn't on the same LAN as the frontend VM) we fall back to the local copy.

FRONTEND_SSH_KEY = '/var/lib/vpt_user/.ssh/frontend_settings_ed25519'


def _run_frontend_bridge(ssh_host, action, input_text=None):
    """Run one `read`/`write` command against the frontend .env bridge over SSH."""
    cmd = [
        'ssh',
        '-o', 'BatchMode=yes',
        '-o', 'ConnectTimeout=6',
        '-o', 'StrictHostKeyChecking=accept-new',
        '-i', FRONTEND_SSH_KEY,
        ssh_host,
        action,
    ]
    result = subprocess.run(cmd, input=input_text, capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f'ssh {action} exited {result.returncode}')
    return result.stdout


# =====================================================
# ENV FILE HELPERS
# =====================================================

def get_project_root():
    """Get the project root directory"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))


def get_env_paths():
    """Get local paths to all .env files"""
    project_root = get_project_root()
    return {
        'server': os.path.join(project_root, '.env'),
        'frontend': os.path.join(project_root, 'frontend', '.env'),
        'frontend_local': os.path.join(project_root, 'frontend', '.env.local'),
        'host': os.path.join(project_root, 'backend_host', 'src', '.env'),
    }


def parse_env_text(text):
    """Parse .env file content and return a dict of key-value pairs."""
    env_dict = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        match = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)=(.*)$', line)
        if match:
            key, value = match.group(1), match.group(2)
            if (value.startswith('"') and value.endswith('"')) or \
               (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            env_dict[key] = value
    return env_dict


def parse_env_file(file_path):
    """Parse a local .env file and return a dict of key-value pairs."""
    if not os.path.exists(file_path):
        return {}
    with open(file_path, 'r') as f:
        return parse_env_text(f.read())


def parse_env_files(file_paths):
    """Parse multiple env files in order, with later files overriding earlier ones."""
    merged = {}
    for file_path in file_paths:
        merged.update(parse_env_file(file_path))
    return merged


def merge_env_text(existing_text, updates):
    """Apply key updates onto raw .env text, preserving comments/structure/order."""
    lines = existing_text.splitlines()
    updated_lines = []
    updated_keys = set()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            updated_lines.append(line)
            continue
        match = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)=(.*)$', stripped)
        if match and match.group(1) in updates:
            updated_lines.append(f"{match.group(1)}={updates[match.group(1)]}")
            updated_keys.add(match.group(1))
        else:
            updated_lines.append(line)
    for key, value in updates.items():
        if key not in updated_keys:
            updated_lines.append(f"{key}={value}")
    return '\n'.join(updated_lines) + '\n'


def write_env_file(file_path, updates, backup=True):
    """Update a local .env file in place, preserving structure. Creates it if missing."""
    if not os.path.exists(file_path):
        content = ''.join(f"{k}={v}\n" for k, v in updates.items())
    else:
        if backup:
            backup_path = f"{file_path}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            shutil.copy(file_path, backup_path)
        with open(file_path, 'r') as f:
            existing = f.read()
        content = merge_env_text(existing, updates)
    with open(file_path, 'w') as f:
        f.write(content)
    return True


def is_sensitive_key(key):
    """Name-based heuristic: anything that looks like a credential gets masked client-side."""
    return bool(re.search(r'(KEY|SECRET|TOKEN|PASSWORD|PWD)', key, re.IGNORECASE))


DEVICE_KEY_RE = re.compile(r'^DEVICE(\d+)_(.+)$')


def extract_device_configs(host_env):
    """Pull DEVICE<N>_* keys out of the host env into a per-device dict."""
    devices = {}
    for key, value in host_env.items():
        match = DEVICE_KEY_RE.match(key)
        if not match:
            continue
        device_key = f"DEVICE{match.group(1)}"
        devices.setdefault(device_key, {})[f"DEVICE_{match.group(2)}"] = value
    return devices


def strip_device_keys(host_env):
    """The flat 'host' section excludes DEVICE<N>_* keys — those live under 'devices'."""
    return {k: v for k, v in host_env.items() if not DEVICE_KEY_RE.match(k)}


def get_frontend_env(server_env):
    """
    Read the frontend's real .env. Uses the SSH bridge to the actual frontend VM
    when FRONTEND_SSH_HOST is configured; otherwise reads this process's own
    local copy (dev mode, or a server the bridge isn't wired up on).

    Returns (env_dict, source, warning) where source is 'ssh' or 'local', and
    warning is set whenever we fell back to the local copy despite a bridge
    being configured (so the UI can say "this isn't the live site").
    """
    env_paths = get_env_paths()
    ssh_host = server_env.get('FRONTEND_SSH_HOST', '').strip()
    if not ssh_host:
        return parse_env_files([env_paths['frontend'], env_paths['frontend_local']]), 'local', None
    try:
        return parse_env_text(_run_frontend_bridge(ssh_host, 'read')), 'ssh', None
    except Exception as e:
        local_env = parse_env_files([env_paths['frontend'], env_paths['frontend_local']])
        warning = (
            f"Could not reach the frontend host over SSH ({ssh_host}: {e}). "
            "Showing this server's own local copy, which is not what actually serves the site."
        )
        return local_env, 'local', warning


# =====================================================
# API ENDPOINTS
# =====================================================

@server_settings_bp.route('/config', methods=['GET'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_settings:get_config')
def get_config():
    """Get every key from all .env files. Admin-only — values are returned in full."""
    env_paths = get_env_paths()
    server_env = parse_env_file(env_paths['server'])
    frontend_env, frontend_source, frontend_warning = get_frontend_env(server_env)
    host_env = parse_env_file(env_paths['host'])
    host_flat = strip_device_keys(host_env)

    return jsonify({
        'server': server_env,
        'server_sensitive_keys': sorted(k for k in server_env if is_sensitive_key(k)),
        'frontend': frontend_env,
        'frontend_sensitive_keys': sorted(k for k in frontend_env if is_sensitive_key(k)),
        'frontend_source': frontend_source,
        'frontend_warning': frontend_warning,
        'host': host_flat,
        'host_sensitive_keys': sorted(k for k in host_flat if is_sensitive_key(k)),
        'devices': extract_device_configs(host_env),
    })


@server_settings_bp.route('/config', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_settings:update_config')
def update_config():
    """Update .env keys. Every key sent for a section is written — no whitelist."""
    data = request.get_json() or {}
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    env_paths = get_env_paths()
    updated_files = []

    if data.get('server'):
        server_updates = dict(data['server'])
        # Validate AI provider/model combo before writing. Resolve the effective
        # values by overlaying this update on the current env — covers the case
        # where only one of {provider, model} is being changed.
        if 'AI_AGENT_PROVIDER' in server_updates or 'AI_AGENT_MODEL' in server_updates:
            from shared.src.lib.ai.config import validate_provider_model
            effective_provider = server_updates.get('AI_AGENT_PROVIDER') or os.getenv('AI_AGENT_PROVIDER', '')
            effective_model = server_updates.get('AI_AGENT_MODEL') or os.getenv('AI_AGENT_MODEL', '')
            model_error = validate_provider_model(effective_provider, effective_model)
            if model_error:
                return jsonify({'error': model_error}), 400
        write_env_file(env_paths['server'], server_updates)
        for key, value in server_updates.items():
            os.environ[key] = value
        updated_files.append('server')

    if data.get('frontend'):
        frontend_updates = dict(data['frontend'])
        server_env = parse_env_file(env_paths['server'])
        ssh_host = server_env.get('FRONTEND_SSH_HOST', '').strip()
        if ssh_host:
            # No silent fallback here: writing the local copy on failure would
            # look like it saved while changing nothing the site actually uses.
            current = _run_frontend_bridge(ssh_host, 'read')
            _run_frontend_bridge(ssh_host, 'write', input_text=merge_env_text(current, frontend_updates))
        else:
            write_env_file(env_paths['frontend'], frontend_updates)
        updated_files.append('frontend')

    if data.get('host') or data.get('devices'):
        host_updates = {}
        if data.get('host'):
            host_updates.update(data['host'])
        if data.get('devices'):
            for device_key, device_data in data['devices'].items():
                device_match = re.match(r'^DEVICE(\d+)$', device_key)
                if not device_match:
                    continue
                device_num = device_match.group(1)
                for field_key, field_value in device_data.items():
                    field_match = re.match(r'^DEVICE_(.+)$', field_key)
                    if field_match:
                        host_updates[f"DEVICE{device_num}_{field_match.group(1)}"] = field_value
        if host_updates:
            write_env_file(env_paths['host'], host_updates)
            updated_files.append('host')

    return jsonify({
        'success': True,
        'updated_files': updated_files,
        'message': 'Configuration updated successfully',
    })


@server_settings_bp.route('/host-config', methods=['GET', 'POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_settings:host_config')
def host_config():
    """Read or save configuration on a selected registered host."""
    host_name = request.args.get('host_name') if request.method == 'GET' else (request.get_json() or {}).get('host_name')
    if not host_name:
        return jsonify({'success': False, 'error': 'host_name is required'}), 400
    from backend_server.src.lib.utils.server_utils import get_host_manager
    host_data = get_host_manager().get_host(host_name)
    if not host_data:
        return jsonify({'success': False, 'error': f'Host {host_name} not found'}), 404
    from shared.src.lib.utils.build_url_utils import call_host
    payload = {}
    if request.method == 'POST':
        body = request.get_json() or {}
        payload = {'host': body.get('host', {}), 'devices': body.get('devices', {})}
    response_data, status_code = call_host(
        host_data, '/host/system/config', method=request.method, data=payload if request.method == 'POST' else None,
        timeout=30,
    )
    return jsonify(response_data), status_code


@server_settings_bp.route('/restart-host-service', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_settings:restart_host_service')
def restart_host_settings_service():
    """Restart only the host services exposed by the Host & Devices settings UI."""
    data = request.get_json() or {}
    host_name = data.get('host_name')
    service = data.get('service')
    if service not in {'vpt-host', 'vpt-stream'}:
        return jsonify({'success': False, 'error': 'service must be vpt-host or vpt-stream'}), 400
    from backend_server.src.lib.utils.server_utils import get_host_manager
    host_data = get_host_manager().get_host(host_name) if host_name else None
    if not host_data:
        return jsonify({'success': False, 'error': f'Host {host_name} not found'}), 404
    endpoint = '/host/system/restartHostService' if service == 'vpt-host' else '/host/system/restartHostStreamService'
    from shared.src.lib.utils.build_url_utils import call_host
    response_data, status_code = call_host(host_data, endpoint, method='POST', data={}, timeout=60)
    return jsonify(response_data), status_code


@server_settings_bp.route('/restart-frontend', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_settings:restart_frontend')
def restart_frontend():
    """Restart the real frontend VM's service over the SSH bridge (see CONTRACTS.md #18b).

    Only wired up where FRONTEND_SSH_HOST is configured (Awesomation today) —
    there's no path to the frontend VM from a server that isn't on its LAN.
    Note this restarts the service; it does NOT rebuild, so it won't pick up
    .env changes while the frontend runs in prod mode (npm run build bakes
    VITE_* in at build time) — rebuild isn't implemented yet.
    """
    server_env = parse_env_file(get_env_paths()['server'])
    ssh_host = server_env.get('FRONTEND_SSH_HOST', '').strip()
    if not ssh_host:
        return jsonify({'success': False, 'error': 'FRONTEND_SSH_HOST is not configured on this server'}), 400
    _run_frontend_bridge(ssh_host, 'restart')
    return jsonify({'success': True, 'message': 'Frontend service restart requested'}), 200


@server_settings_bp.route('/backup', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('server_settings:backup')
def backup_config():
    """Create a manual backup of every local .env file this process can see."""
    env_paths = get_env_paths()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backed_up = []
    for service, path in env_paths.items():
        if os.path.exists(path):
            shutil.copy(path, f"{path}.backup.{timestamp}")
            backed_up.append(service)
    return jsonify({
        'success': True,
        'backed_up': backed_up,
        'timestamp': timestamp,
    })
