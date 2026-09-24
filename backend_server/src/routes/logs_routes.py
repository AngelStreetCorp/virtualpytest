"""
Logs Routes - System logs and service monitoring

Provides access to systemd service logs via journalctl and host log files.
"""

from flask import Blueprint, request, jsonify
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.auth_middleware import require_user_auth, require_role
import subprocess

# Create blueprint
logs_bp = Blueprint('logs', __name__, url_prefix='/server/logs')

# Allowed services (whitelist for security)
ALLOWED_SERVICES = [
    'vpt-server',
    'vpt-server-host',
    'vpt-host',
    'vpt-frontend',
    'vpt-heatmap',
    'vpt-discard-scripts',
    'vpt-discard-incidents',
    'vpt-stream',
    'vpt-monitor',
    'vpt-archiver',
    'vpt-kpi',
    'vpt-transcript',
    'vpt-subtitle',
    'vpt-vnc',
    'vpt-websockify',
    'vpt-emulator',
    'vpt-emulator-fifo',
]

# Log files that live on backend_host machines (served via /host/system/logs/file)
HOST_FILE_LOGS = {
    'deployments',
}


@logs_bp.route('/view', methods=['POST'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('logs:view_logs')
def view_logs():
    """
    View systemd service logs via journalctl
    
    Request body:
    {
        "service": "vpt-server",
        "lines": 50,
        "follow": false,
        "since": "1h",
        "level": "info",
        "grep": "error"
    }
    """
    data = request.get_json() or {}

    service = data.get('service')
    try:
        lines = max(1, min(500, int(data.get('lines', 50))))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'lines must be an integer between 1 and 500'}), 400
    follow = data.get('follow', False)
    since = data.get('since')
    level = data.get('level')
    grep_pattern = data.get('grep')
    host_name = data.get('host_name')
    device_id = data.get('device_id')

    # Validate service
    if not service:
        return jsonify({
            'success': False,
            'error': 'service is required',
            'available_services': ALLOWED_SERVICES + list(HOST_FILE_LOGS)
        }), 400

    # vpt-stream logs are per-device ffmpeg files, not journald. When a
    # device_id is supplied, fetch that device's ffmpeg log from the host.
    if service == 'vpt-stream' and device_id:
        if not host_name:
            return jsonify({
                'success': False,
                'error': 'host_name is required for vpt-stream device logs',
            }), 400
        try:
            from backend_server.src.lib.utils.server_utils import get_host_manager
            from shared.src.lib.utils.build_url_utils import call_host
            host_info = get_host_manager().get_host(host_name)
            if not host_info:
                return jsonify({'success': False, 'error': f'Host not found: {host_name}'}), 404
            resp_data, status_code = call_host(
                host_info,
                '/host/system/logs/stream',
                method='POST',
                data={'device_id': device_id, 'lines': lines},
                timeout=10,
            )
            if resp_data.get('success'):
                logs = resp_data.get('logs', '')
                if grep_pattern and logs:
                    filtered = [l for l in logs.split('\n') if grep_pattern.lower() in l.lower()]
                    logs = '\n'.join(filtered)
                return jsonify({
                    'success': True,
                    'service': service,
                    'host_name': host_name,
                    'device_id': device_id,
                    'logs': logs,
                    'lines_count': resp_data.get('lines_count', 0),
                })
            return jsonify(resp_data), status_code
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    # Host file-based logs: proxy to the backend_host
    if service in HOST_FILE_LOGS:
        if not host_name:
            return jsonify({
                'success': False,
                'error': 'host_name is required for host file logs',
            }), 400
        try:
            from backend_server.src.lib.utils.server_utils import get_host_manager
            from shared.src.lib.utils.build_url_utils import call_host
            host_info = get_host_manager().get_host(host_name)
            if not host_info:
                return jsonify({'success': False, 'error': f'Host not found: {host_name}'}), 404
            resp_data, status_code = call_host(
                host_info,
                '/host/system/logs/file',
                method='POST',
                data={'name': service, 'lines': lines},
                timeout=10,
            )
            if resp_data.get('success'):
                logs = resp_data.get('logs', '')
                if grep_pattern and logs:
                    filtered = [l for l in logs.split('\n') if grep_pattern.lower() in l.lower()]
                    logs = '\n'.join(filtered)
                return jsonify({
                    'success': True,
                    'service': service,
                    'host_name': host_name,
                    'logs': logs,
                    'lines_count': resp_data.get('lines_count', 0),
                })
            return jsonify(resp_data), status_code
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    # Security: only allow whitelisted services
    if service not in ALLOWED_SERVICES:
        return jsonify({
            'success': False,
            'error': f'Service {service} not allowed',
            'available_services': ALLOWED_SERVICES + list(HOST_FILE_LOGS)
        }), 400

    # If host_name provided, proxy journalctl request to the host
    if host_name:
        try:
            from backend_server.src.lib.utils.server_utils import get_host_manager
            from shared.src.lib.utils.build_url_utils import call_host
            host_info = get_host_manager().get_host(host_name)
            if not host_info:
                return jsonify({'success': False, 'error': f'Host not found: {host_name}'}), 404
            resp_data, status_code = call_host(
                host_info,
                '/host/system/logs/journal',
                method='POST',
                data={'service': service, 'lines': lines, 'since': since, 'grep': grep_pattern, 'level': level},
                timeout=10,
            )
            return jsonify(resp_data), status_code
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    # Local journalctl (for server-side services)
    if follow:
        return jsonify({
            'success': False,
            'error': 'Follow mode not supported via API.'
        }), 400

    from shared.src.lib.utils.system_utils import read_journal_logs
    result = read_journal_logs(
        service, lines=lines, since=since, grep=grep_pattern, level=level
    )
    return jsonify(result), 200 if result.get('success') else 500
    
@logs_bp.route('/services', methods=['GET'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('logs:list_services')
def list_services():
    """List available VirtualPyTest services"""
    # Check which services exist
    available = []
    
    for service in ALLOWED_SERVICES:
        try:
            result = subprocess.run(
                ['systemctl', 'is-active', f'{service}.service'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            status = result.stdout.strip()
            available.append({
                'name': service,
                'status': status,
                'active': status == 'active'
            })
        except Exception:
            continue
    
    return jsonify({
        'success': True,
        'services': available,
        'count': len(available)
    })


@logs_bp.route('/agent', methods=['GET'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('logs:agent_history')
def agent_history():
    """Return bounded, structured agent execution history for this server team.

    GET /server/logs/agent?days=30&limit=100&offset=0
    """
    from datetime import datetime, timedelta, timezone
    from shared.src.lib.utils.app_utils import get_team_id
    from shared.src.lib.utils.supabase_utils import get_supabase_client

    try:
        days = max(1, min(90, int(request.args.get('days', 30))))
        limit = max(1, min(200, int(request.args.get('limit', 100))))
        offset = max(0, min(10000, int(request.args.get('offset', 0))))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'days, limit, and offset must be integers'}), 400
    team_id = get_team_id()
    if not team_id:
        return jsonify({'success': True, 'events': [], 'count': 0, 'days': days}), 200
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    sb = get_supabase_client()
    if not sb:
        return jsonify({'success': False, 'error': 'Agent history is unavailable'}), 503
    result = (sb.table('agent_execution_history')
              .select('id,instance_id,agent_id,task_id,event_type,started_at,completed_at,duration_seconds,status,tool_calls,error_message,team_id')
              .eq('team_id', team_id).gte('started_at', since)
              .order('started_at', desc=True).range(offset, offset + limit - 1).execute())
    events = []
    for row in (result.data or []):
        # Error summaries can contain credentials or user supplied content. Keep
        # this endpoint limited to a generic failure indicator; raw details stay server side.
        events.append({
            'id': str(row.get('id') or ''), 'session_id': row.get('instance_id'),
            'agent_id': row.get('agent_id'), 'task_id': row.get('task_id'),
            'event_type': row.get('event_type') or 'agent_execution',
            'timestamp': row.get('started_at'), 'completed_at': row.get('completed_at'),
            'duration_seconds': row.get('duration_seconds'), 'status': row.get('status'),
            'tool_calls': row.get('tool_calls') or 0,
            'error_summary': 'Execution failed' if row.get('error_message') else None,
        })
    return jsonify({'success': True, 'events': events, 'count': len(events), 'days': days,
                    'limit': limit, 'offset': offset}), 200
