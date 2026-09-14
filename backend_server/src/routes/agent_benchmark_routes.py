"""
Agent Benchmark & Feedback REST API Routes

Thin route layer that delegates to shared/src/lib/database/agent_benchmarks_db.py
"""

from flask import Blueprint, request, jsonify
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.routes.server_system_socket_routes import emit_system_update

from shared.src.lib.database.agent_benchmarks_db import (
    list_benchmark_tests,
    get_benchmark_test,
    create_benchmark_run,
    get_benchmark_run,
    list_benchmark_runs,
    delete_benchmark_run,
    execute_benchmark_run,
    get_benchmark_results,
    submit_feedback,
    list_feedback,
    delete_feedback,
    get_agent_scores,
    get_leaderboard,
    compare_agents
)

# Create blueprint
server_agent_benchmark_bp = Blueprint('server_agent_benchmark', __name__, url_prefix='/server/benchmarks')


def get_team_id() -> str:
    """Get team ID from request"""
    return request.args.get('team_id', request.headers.get('X-Team-ID', 'default'))


# =====================================================
# Benchmark Tests
# =====================================================

@server_agent_benchmark_bp.route('/tests', methods=['GET'])
@handle_route_exceptions('agent_benchmark:route_list_benchmark_tests')
def route_list_benchmark_tests():
    """List all available benchmark tests"""
    category = request.args.get('category')
    tests = list_benchmark_tests(category=category)
    return jsonify({'tests': tests, 'count': len(tests)}), 200
# =====================================================
# Benchmark Runs
# =====================================================

@server_agent_benchmark_bp.route('/run', methods=['POST'])
@handle_route_exceptions('agent_benchmark:route_create_benchmark_run')
def route_create_benchmark_run():
    """Create a new benchmark run"""
    data = request.get_json()
    
    if not data or 'agent_id' not in data:
        return jsonify({'error': 'agent_id required'}), 400
    
    agent_id = data['agent_id']
    version = data.get('version', '1.0.0')
    team_id = get_team_id()
    
    run = create_benchmark_run(agent_id, version, team_id)
    
    if not run:
        return jsonify({'error': 'Failed to create benchmark run'}), 500

    emit_system_update('agent_benchmark_changed', {
        'domain': 'agent_benchmark',
        'action': 'run_created',
        'run_id': run.get('id')
    })
    
    return jsonify({
        'run_id': run['id'],
        'agent_id': run['agent_id'],
        'version': run['agent_version'],
        'total_tests': run['total_tests'],
        'status': run['status'],
        'message': 'Benchmark run created. Execute /server/benchmarks/run/{run_id}/execute to start.'
    }), 201
    
@server_agent_benchmark_bp.route('/run/<run_id>/execute', methods=['POST'])
@handle_route_exceptions('agent_benchmark:route_execute_benchmark_run')
def route_execute_benchmark_run(run_id: str):
    """Execute a pending benchmark run"""
    result = execute_benchmark_run(run_id)
    
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Unknown error')}), 400

    emit_system_update('agent_benchmark_changed', {
        'domain': 'agent_benchmark',
        'action': 'run_completed',
        'run_id': run_id
    })
    
    return jsonify({
        'run_id': run_id,
        'status': 'completed',
        'passed': result['passed'],
        'failed': result['failed'],
        'score_percent': result['score_percent']
    }), 200
    
@server_agent_benchmark_bp.route('/runs', methods=['GET'])
@handle_route_exceptions('agent_benchmark:route_list_benchmark_runs')
def route_list_benchmark_runs():
    """List benchmark runs"""
    agent_id = request.args.get('agent_id')
    team_id = get_team_id()
    limit = int(request.args.get('limit', 20))
    
    runs = list_benchmark_runs(team_id=team_id, agent_id=agent_id, limit=limit)
    
    return jsonify({'runs': runs, 'count': len(runs)}), 200
    
@server_agent_benchmark_bp.route('/runs/<run_id>', methods=['GET'])
@handle_route_exceptions('agent_benchmark:route_get_benchmark_run')
def route_get_benchmark_run(run_id: str):
    """Get benchmark run details with results"""
    run = get_benchmark_run(run_id)
    
    if not run:
        return jsonify({'error': 'Run not found'}), 404
    
    results = get_benchmark_results(run_id)
    
    return jsonify({
        'run': run,
        'results': results
    }), 200


@server_agent_benchmark_bp.route('/runs/<run_id>', methods=['DELETE'])
@handle_route_exceptions('agent_benchmark:route_delete_benchmark_run')
def route_delete_benchmark_run(run_id: str):
    """Delete a benchmark run.

    Only safe for runs that never reached 'completed' status (see
    delete_benchmark_run's docstring — no AFTER DELETE trigger rebalances
    agent_scores), so this refuses to delete a completed run rather than
    silently leaving scores skewed.
    """
    run = get_benchmark_run(run_id)
    if not run:
        return jsonify({'error': 'Run not found'}), 404
    if run.get('status') == 'completed':
        return jsonify({'error': 'Cannot delete a completed run — it already affected agent_scores and deleting it would not roll that back'}), 409

    if not delete_benchmark_run(run_id):
        return jsonify({'error': 'Failed to delete run'}), 500

    return jsonify({'message': 'Run deleted successfully'}), 200

# =====================================================
# Feedback
# =====================================================

@server_agent_benchmark_bp.route('/feedback', methods=['POST'])
@handle_route_exceptions('agent_benchmark:route_submit_feedback')
def route_submit_feedback():
    """Submit user feedback for an agent"""
    data = request.get_json()
    
    if not data or 'agent_id' not in data or 'rating' not in data:
        return jsonify({'error': 'agent_id and rating required'}), 400
    
    rating = int(data['rating'])
    if rating < 1 or rating > 5:
        return jsonify({'error': 'rating must be 1-5'}), 400
    
    team_id = get_team_id()
    
    feedback_id = submit_feedback(
        agent_id=data['agent_id'],
        agent_version=data.get('version', '1.0.0'),
        rating=rating,
        team_id=team_id,
        comment=data.get('comment'),
        execution_id=data.get('execution_id'),
        task_description=data.get('task_description')
    )
    
    if not feedback_id:
        return jsonify({'error': 'Failed to submit feedback'}), 500

    emit_system_update('agent_benchmark_changed', {
        'domain': 'agent_benchmark',
        'action': 'feedback_submitted',
        'feedback_id': feedback_id,
        'agent_id': data.get('agent_id')
    })
    
    return jsonify({
        'feedback_id': feedback_id,
        'message': 'Feedback submitted successfully'
    }), 201


@server_agent_benchmark_bp.route('/feedback/<feedback_id>', methods=['DELETE'])
@handle_route_exceptions('agent_benchmark:route_delete_feedback')
def route_delete_feedback(feedback_id: str):
    """Delete a feedback row and rebalance the agent's aggregate score
    (see delete_feedback's docstring — there's no AFTER DELETE trigger, so
    the DB layer recalculates explicitly after the delete)."""
    if not delete_feedback(feedback_id):
        return jsonify({'error': 'Feedback not found or failed to delete'}), 404

    return jsonify({'message': 'Feedback deleted successfully'}), 200


@server_agent_benchmark_bp.route('/feedback', methods=['GET'])
@handle_route_exceptions('agent_benchmark:route_list_feedback')
def route_list_feedback():
    """List feedback for agents"""
    agent_id = request.args.get('agent_id')
    team_id = get_team_id()
    limit = int(request.args.get('limit', 50))
    
    feedback = list_feedback(team_id=team_id, agent_id=agent_id, limit=limit)
    
    return jsonify({'feedback': feedback, 'count': len(feedback)}), 200
    
# =====================================================
# Scores & Leaderboard
# =====================================================

@server_agent_benchmark_bp.route('/scores', methods=['GET'])
@handle_route_exceptions('agent_benchmark:route_get_agent_scores')
def route_get_agent_scores():
    """Get aggregated scores for agents"""
    agent_id = request.args.get('agent_id')
    team_id = get_team_id()
    
    scores = get_agent_scores(team_id=team_id, agent_id=agent_id)
    
    return jsonify({'scores': scores, 'count': len(scores)}), 200
    
@server_agent_benchmark_bp.route('/leaderboard', methods=['GET'])
@handle_route_exceptions('agent_benchmark:route_get_leaderboard')
def route_get_leaderboard():
    """Get agent leaderboard with rankings"""
    team_id = get_team_id()
    limit = int(request.args.get('limit', 20))
    
    leaderboard = get_leaderboard(team_id=team_id, limit=limit)
    
    return jsonify({'leaderboard': leaderboard, 'count': len(leaderboard)}), 200
    
# =====================================================
# Comparison
# =====================================================

@server_agent_benchmark_bp.route('/compare', methods=['GET'])
@handle_route_exceptions('agent_benchmark:route_compare_agents')
def route_compare_agents():
    """Compare two or more agents"""
    agents_param = request.args.get('agents', '')
    if not agents_param:
        return jsonify({'error': 'agents parameter required'}), 400
    
    team_id = get_team_id()
    
    # Parse agent:version pairs
    agent_pairs = []
    for pair in agents_param.split(','):
        parts = pair.strip().split(':')
        if len(parts) == 2:
            agent_pairs.append({'agent_id': parts[0], 'version': parts[1]})
        elif len(parts) == 1:
            agent_pairs.append({'agent_id': parts[0], 'version': '1.0.0'})
    
    if not agent_pairs:
        return jsonify({'error': 'No valid agent:version pairs found'}), 400
    
    result = compare_agents(agent_pairs, team_id)
    
    return jsonify(result), 200
    
