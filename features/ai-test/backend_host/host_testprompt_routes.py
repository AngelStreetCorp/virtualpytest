"""
Host Test Prompt Routes

A test prompt is orchestrated by the server (features/ai-test/backend_server): an
exploration drives the device through the agent's MCP tools, a graph run through the
testcase executor. The host only keeps the device's running.log in step with an
exploration, so the step overlay shows it like any other run.
"""

from flask import Blueprint, request, jsonify

host_testprompt_bp = Blueprint('host_testprompt', __name__, url_prefix='/host/testprompt')


@host_testprompt_bp.route('/runningLog', methods=['POST'])
def testprompt_running_log():
    """Write (``log`` object) or remove (``log`` null) the device's running.log for an
    exploration run, so the step overlay that polls it shows the agent's steps the same
    way it shows a testcase executor run. ``log`` uses the executor's running.log shape
    (script_name, total_steps, current_step_number, start_time, current_step, ...)."""
    import json
    import os
    from shared.src.lib.utils.storage_path_utils import (
        get_capture_folder_from_device_id,
        get_running_log_path,
    )

    data = request.get_json() or {}
    device_id = data.get('device_id')
    if not device_id:
        return jsonify({'success': False, 'error': 'device_id is required'}), 400
    try:
        path = get_running_log_path(get_capture_folder_from_device_id(device_id))
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 404

    log = data.get('log')
    if log is None:
        if os.path.exists(path):
            os.remove(path)
        return jsonify({'success': True, 'removed': True})

    temp_path = path + '.tmp'
    with open(temp_path, 'w') as f:
        json.dump(log, f)
    os.replace(temp_path, path)
    return jsonify({'success': True})

