"""
Agent Benchmarks & Feedback Database Operations

Manages:
- Benchmark test definitions (from YAML files)
- Benchmark runs and results (in database)
- User feedback collection (in database)
- Agent scores and leaderboard (in database)

Test definitions are file-based for easy editing and version control.
Execution data stays in database for runtime tracking.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
from shared.src.lib.utils.supabase_utils import get_supabase_client

# Import file-based benchmark loader
from backend_server.src.agent.benchmarks import (
    load_all_benchmarks,
    get_benchmarks_by_category,
    get_benchmark_by_id,
    get_benchmarks_for_agent,
    count_benchmarks
)

DEFAULT_TEAM_ID = 'default'


def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()


# =====================================================
# Benchmark Tests (FILE-BASED)
# =====================================================

def list_benchmark_tests(category: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    List all available benchmark tests from YAML files.
    
    Args:
        category: Optional category filter (navigation, detection, execution, analysis, recovery)
        
    Returns:
        List of benchmark test definitions
    """
    if category:
        return get_benchmarks_by_category(category)
    return load_all_benchmarks()


def get_benchmark_test(test_id: str) -> Optional[Dict[str, Any]]:
    """Get a specific benchmark test by test_id from YAML files."""
    return get_benchmark_by_id(test_id)


# =====================================================
# Score Calculation
# =====================================================

def recalculate_agent_score(
    agent_id: str,
    agent_version: str,
    team_id: str = DEFAULT_TEAM_ID
) -> bool:
    """
    Call the PostgreSQL function to recalculate agent scores.
    
    This should be called after:
    - Benchmark run completes
    - User feedback is submitted
    
    Args:
        agent_id: Agent identifier
        agent_version: Agent version  
        team_id: Team ID
        
    Returns:
        True if successful, False otherwise
    """
    supabase = get_supabase()
    if not supabase:
        return False
    
    try:
        # Call the PostgreSQL stored function
        supabase.rpc('recalculate_agent_score', {
            'p_agent_id': agent_id,
            'p_agent_version': agent_version,
            'p_team_id': team_id
        }).execute()
        return True
    except Exception as e:
        print(f"[@db:agent_benchmarks:recalculate_agent_score] Error: {e}")
        return False


# =====================================================
# Benchmark Runs
# =====================================================

def create_benchmark_run(
    agent_id: str,
    agent_version: str,
    team_id: str = DEFAULT_TEAM_ID
) -> Optional[Dict[str, Any]]:
    """
    Create a new benchmark run for an agent.
    
    Args:
        agent_id: Agent identifier (e.g., 'qa-web-manager')
        agent_version: Agent version (e.g., '1.0.0')
        team_id: Team ID
        
    Returns:
        Created run record or None on error
    """
    supabase = get_supabase()
    if not supabase:
        return None
    
    # Count applicable tests from YAML files
    tests = get_benchmarks_for_agent(agent_id)
    test_count = len(tests)
    
    run_data = {
        'agent_id': agent_id,
        'agent_version': agent_version,
        'team_id': team_id,
        'status': 'pending',
        'total_tests': test_count,
        'completed_tests': 0,
        'passed_tests': 0,
        'failed_tests': 0
    }
    
    result = supabase.table('agent_benchmark_runs').insert(run_data).execute()
    return result.data[0] if result.data else None


def get_benchmark_run(run_id: str) -> Optional[Dict[str, Any]]:
    """Get a benchmark run by ID."""
    supabase = get_supabase()
    if not supabase:
        return None
    
    result = supabase.table('agent_benchmark_runs').select('*').eq('id', run_id).execute()
    return result.data[0] if result.data else None


def update_benchmark_run(run_id: str, updates: Dict[str, Any]) -> bool:
    """
    Update a benchmark run.

    Args:
        run_id: Run UUID
        updates: Fields to update

    Returns:
        True if successful
    """
    supabase = get_supabase()
    if not supabase:
        return False

    supabase.table('agent_benchmark_runs').update(updates).eq('id', run_id).execute()
    return True


def delete_benchmark_run(run_id: str) -> bool:
    """
    Delete a benchmark run.

    Safe to call regardless of status: trigger_agent_score_on_benchmark only
    recalculates agent_scores when a run's status transitions to 'completed'
    (setup/db/schema/023_agent_scores_triggers.sql), so deleting a run that
    never completed (e.g. a 'pending' run created for a test) needs no score
    fixup. Deleting a completed run does NOT retroactively rebalance
    agent_scores — there's no AFTER DELETE trigger for that — so only delete
    runs whose completion never affected real scores.

    Returns:
        True if successful
    """
    supabase = get_supabase()
    if not supabase:
        return False

    supabase.table('agent_benchmark_runs').delete().eq('id', run_id).execute()
    return True


def list_benchmark_runs(
    team_id: str = DEFAULT_TEAM_ID,
    agent_id: Optional[str] = None,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """
    List benchmark runs.
    
    Args:
        team_id: Team ID filter
        agent_id: Optional agent ID filter
        limit: Max results
        
    Returns:
        List of benchmark runs
    """
    supabase = get_supabase()
    if not supabase:
        return []
    
    query = supabase.table('agent_benchmark_runs').select('*').eq('team_id', team_id)
    
    if agent_id:
        query = query.eq('agent_id', agent_id)
    
    result = query.order('created_at', desc=True).limit(limit).execute()
    return result.data if result.data else []


def execute_benchmark_run(run_id: str) -> Dict[str, Any]:
    """
    Execute a pending benchmark run.
    
    Args:
        run_id: Run UUID
        
    Returns:
        {success: bool, passed: int, failed: int, score_percent: float, error: str}
    """
    supabase = get_supabase()
    if not supabase:
        return {'success': False, 'error': 'Database not available'}
    
    # Get run
    run = get_benchmark_run(run_id)
    if not run:
        return {'success': False, 'error': 'Run not found'}
    
    if run['status'] != 'pending':
        return {'success': False, 'error': f"Run is {run['status']}, cannot execute"}
    
    # Update to running
    update_benchmark_run(run_id, {
        'status': 'running',
        'started_at': datetime.now().isoformat()
    })
    
    # Get tests from YAML files (filtered by agent)
    agent_id = run['agent_id']
    tests = get_benchmarks_for_agent(agent_id)
    
    passed = 0
    failed = 0
    total_points = 0.0
    earned_points = 0.0
    
    for test in tests:
        # Simulate test execution (placeholder - real implementation would call agent)
        test_passed = True
        points = test.get('points', 1.0)
        total_points += points
        
        # Record result (benchmark_id is nullable for file-based tests)
        result_data = {
            'run_id': run_id,
            'test_id': test['test_id'],
            'passed': test_passed,
            'points_earned': points if test_passed else 0.0,
            'points_possible': points,
            'duration_seconds': 1.5
        }
        supabase.table('agent_benchmark_results').insert(result_data).execute()
        
        if test_passed:
            passed += 1
            earned_points += points
        else:
            failed += 1
        
        # Update progress
        update_benchmark_run(run_id, {
            'completed_tests': passed + failed,
            'passed_tests': passed,
            'failed_tests': failed
        })
    
    # Calculate score based on points
    score = (earned_points / total_points * 100) if total_points > 0 else 0
    
    # Complete run
    # Note: Database trigger automatically recalculates agent_scores on status = 'completed'
    update_benchmark_run(run_id, {
        'status': 'completed',
        'completed_at': datetime.now().isoformat(),
        'score_percent': round(score, 2)
    })
    
    return {
        'success': True,
        'passed': passed,
        'failed': failed,
        'score_percent': round(score, 2)
    }


def get_benchmark_results(run_id: str) -> List[Dict[str, Any]]:
    """Get results for a benchmark run."""
    supabase = get_supabase()
    if not supabase:
        return []
    
    result = supabase.table('agent_benchmark_results').select('*').eq('run_id', run_id).order('executed_at').execute()
    return result.data if result.data else []


# =====================================================
# User Feedback
# =====================================================

def submit_feedback(
    agent_id: str,
    agent_version: str,
    rating: int,
    team_id: str = DEFAULT_TEAM_ID,
    comment: Optional[str] = None,
    execution_id: Optional[str] = None,
    task_description: Optional[str] = None
) -> Optional[str]:
    """
    Submit user feedback for an agent.
    
    Args:
        agent_id: Agent identifier
        agent_version: Agent version
        rating: 1-5 stars
        team_id: Team ID
        comment: Optional feedback text
        execution_id: Optional task/execution reference
        task_description: Optional task description
        
    Returns:
        Feedback ID or None on error
    """
    if rating < 1 or rating > 5:
        return None
    
    supabase = get_supabase()
    if not supabase:
        return None
    
    feedback_data = {
        'agent_id': agent_id,
        'agent_version': agent_version,
        'rating': rating,
        'comment': comment,
        'execution_id': execution_id,
        'task_description': task_description,
        'team_id': team_id
    }
    
    # Note: Database trigger automatically recalculates agent_scores on INSERT
    result = supabase.table('agent_feedback').insert(feedback_data).execute()
    return result.data[0]['id'] if result.data else None


def delete_feedback(feedback_id: str) -> bool:
    """
    Delete a feedback row and rebalance the agent's aggregate score.

    trigger_agent_score_on_feedback only fires AFTER INSERT (see
    setup/db/schema/023_agent_scores_triggers.sql) — there's no AFTER DELETE
    counterpart, so a plain delete would leave agent_scores permanently
    skewed by the deleted row's rating. Look the row up first so
    recalculate_agent_score() can be called with its (agent_id,
    agent_version, team_id) after the delete, which recomputes the
    aggregate from whatever feedback rows actually remain.

    Returns:
        True if successful
    """
    supabase = get_supabase()
    if not supabase:
        return False

    existing = supabase.table('agent_feedback').select('agent_id, agent_version, team_id').eq('id', feedback_id).execute()
    if not existing.data:
        return False
    row = existing.data[0]

    supabase.table('agent_feedback').delete().eq('id', feedback_id).execute()
    recalculate_agent_score(row['agent_id'], row['agent_version'], row['team_id'])
    return True


def list_feedback(
    team_id: str = DEFAULT_TEAM_ID,
    agent_id: Optional[str] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """List feedback for agents."""
    supabase = get_supabase()
    if not supabase:
        return []
    
    query = supabase.table('agent_feedback').select('*').eq('team_id', team_id)
    
    if agent_id:
        query = query.eq('agent_id', agent_id)
    
    result = query.order('created_at', desc=True).limit(limit).execute()
    return result.data if result.data else []


# =====================================================
# Scores & Leaderboard
# =====================================================

def get_agent_scores(
    team_id: str = None,  # Deprecated - kept for API compatibility
    agent_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get aggregated scores for agents (global, not per-team)."""
    supabase = get_supabase()
    if not supabase:
        return []
    
    query = supabase.table('agent_scores').select('*')
    
    if agent_id:
        query = query.eq('agent_id', agent_id)
    
    result = query.order('overall_score', desc=True).execute()
    return result.data if result.data else []


def get_leaderboard(team_id: str = None, limit: int = 20) -> List[Dict[str, Any]]:
    """Get agent leaderboard with rankings (global, not per-team)."""
    supabase = get_supabase()
    if not supabase:
        return []
    
    result = supabase.table('agent_scores').select('*').order('overall_score', desc=True).limit(limit).execute()
    
    leaderboard = []
    for idx, entry in enumerate(result.data or []):
        entry['rank'] = idx + 1
        leaderboard.append(entry)
    
    return leaderboard


def get_agent_score(
    agent_id: str,
    agent_version: str,
    team_id: str = None  # Deprecated - kept for API compatibility
) -> Optional[Dict[str, Any]]:
    """Get score for a specific agent version (global, not per-team)."""
    supabase = get_supabase()
    if not supabase:
        return None
    
    result = supabase.table('agent_scores').select('*').eq('agent_id', agent_id).eq('agent_version', agent_version).execute()
    return result.data[0] if result.data else None


def compare_agents(
    agent_pairs: List[Dict[str, str]],
    team_id: str = DEFAULT_TEAM_ID
) -> Dict[str, Any]:
    """
    Compare multiple agents.
    
    Args:
        agent_pairs: List of {'agent_id': str, 'version': str}
        team_id: Team ID
        
    Returns:
        {comparison: [...], winner: str or None}
    """
    comparison = []
    
    for pair in agent_pairs:
        score = get_agent_score(pair['agent_id'], pair.get('version', '1.0.0'), team_id)
        
        if score:
            comparison.append(score)
        else:
            comparison.append({
                'agent_id': pair['agent_id'],
                'agent_version': pair.get('version', '1.0.0'),
                'overall_score': 0,
                'benchmark_score': 0,
                'user_rating_score': 0,
                'success_rate_score': 0
            })
    
    winner = max(comparison, key=lambda x: x.get('overall_score', 0)) if comparison else None
    
    return {
        'comparison': comparison,
        'winner': winner['agent_id'] if winner and winner.get('overall_score', 0) > 0 else None
    }

