"""Host Deployment Routes - Manage scheduled script executions"""
from flask import Blueprint, request, jsonify
from backend_host.src.lib.utils.route_decorators import route_exception_handler

host_deployment_bp = Blueprint('host_deployment', __name__, url_prefix='/host/deployment')

@route_exception_handler()
def get_deployment_scheduler():
    from backend_host.src.services.deployment_scheduler import get_deployment_scheduler as _get_scheduler
    return _get_scheduler()
@host_deployment_bp.route('/add', methods=['POST'])
def add_deployment():
    """Add new deployment to scheduler"""
    scheduler = get_deployment_scheduler()
    if not scheduler:
        return jsonify({'success': False, 'error': 'Scheduler not available'}), 503
    
    data = request.get_json()
    try:
        scheduler.add_deployment(data)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@host_deployment_bp.route('/pause/<deployment_id>', methods=['POST'])
def pause_deployment(deployment_id):
    """Pause deployment"""
    scheduler = get_deployment_scheduler()
    if not scheduler:
        return jsonify({'success': False, 'error': 'Scheduler not available'}), 503
    
    try:
        scheduler.pause_deployment(deployment_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@host_deployment_bp.route('/resume/<deployment_id>', methods=['POST'])
def resume_deployment(deployment_id):
    """Resume deployment"""
    scheduler = get_deployment_scheduler()
    if not scheduler:
        return jsonify({'success': False, 'error': 'Scheduler not available'}), 503
    
    try:
        scheduler.resume_deployment(deployment_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@host_deployment_bp.route('/remove/<deployment_id>', methods=['DELETE'])
def remove_deployment(deployment_id):
    """Remove deployment"""
    scheduler = get_deployment_scheduler()
    if not scheduler:
        return jsonify({'success': False, 'error': 'Scheduler not available'}), 503

    try:
        scheduler.remove_deployment(deployment_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@host_deployment_bp.route('/update/<deployment_id>', methods=['PUT'])
def update_deployment(deployment_id):
    """Update an existing deployment schedule"""
    scheduler = get_deployment_scheduler()
    if not scheduler:
        return jsonify({'success': False, 'error': 'Scheduler not available'}), 503

    data = request.get_json() or {}
    if data.get('id') and data.get('id') != deployment_id:
        return jsonify({'success': False, 'error': 'Deployment ID mismatch'}), 400

    try:
        scheduler.update_deployment({**data, 'id': deployment_id})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@host_deployment_bp.route('/run/<deployment_id>', methods=['POST'])
@route_exception_handler()
def run_deployment_now(deployment_id):
    """Trigger a deployment immediately"""
    scheduler = get_deployment_scheduler()
    if not scheduler:
        return jsonify({'success': False, 'error': 'Scheduler not available'}), 503

    scheduler.run_deployment_now(deployment_id)
    return jsonify({'success': True})

@host_deployment_bp.route('/status', methods=['GET'])
def deployment_status():
    """Check if deployment scheduler is available"""
    scheduler = get_deployment_scheduler()
    return jsonify({
        'available': scheduler is not None,
        'message': 'Deployment scheduler ready' if scheduler else 'APScheduler dependency missing'
    })


@host_deployment_bp.route('/jobs', methods=['GET'])
@route_exception_handler()
def deployment_jobs():
    """Inspect APScheduler jobs and deployment queue state for this host."""
    scheduler = get_deployment_scheduler()
    if not scheduler:
        return jsonify({'success': False, 'error': 'Scheduler not available'}), 503

    return jsonify({
        'success': True,
        'snapshot': scheduler.get_scheduler_snapshot(),
    })


@host_deployment_bp.route('/abortRunning', methods=['POST'])
@route_exception_handler()
def abort_running_deployment():
    """Abort any currently running deployment script process for a device."""
    data = request.get_json() or {}
    device_id = data.get('device_id')
    if not device_id:
        return jsonify({'success': False, 'error': 'device_id is required'}), 400

    from shared.src.lib.executors.script_executor import abort_running_script
    result = abort_running_script(device_id)
    status_code = 200 if result.get('success') else 500
    return jsonify(result), status_code
