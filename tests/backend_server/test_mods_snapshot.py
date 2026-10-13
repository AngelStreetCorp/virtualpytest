"""The mods snapshot (features/mods/lib/snapshot.py, TASK-77).

Offline: pure functions. The snapshot must be shaped exactly like the live /system updates,
because the browser maps both with the same code (frontend/src/mods/core/mappers.ts).
"""

import pytest

from features.mods.lib.snapshot import build_snapshot

pytestmark = pytest.mark.unit


def test_snapshot_replays_runs_locks_and_presence_as_system_updates():
    tasks = [{
        'id': 'task-1',
        'created_at': 100.0,
        'params': {'team_id': 'team', 'host_name': 'vpt-pi1', 'device_id': 'device1', 'script_name': 'goto'},
        'progress': {'step': 'zap', 'step_number': 2, 'total_steps': 5},
    }]
    locks = {
        'vpt-pi1:device1': {'host_name': 'vpt-pi1', 'device_id': 'device1', 'owner_user_name': 'Paul'},
        'broken': {'device_id': 'x'},
    }
    presence = {'team_id': 'team', 'online': 1, 'users': [{'user_id': 'u', 'name': 'Paul'}], 'shared_sessions': 0}

    events = build_snapshot(tasks, locks, presence)

    assert [e['type'] for e in events] == ['execution_update', 'lock_changed', 'presence_changed']
    run = events[0]
    assert run['execution_id'] == 'task-1' and run['status'] == 'running' and run['team_id'] == 'team'
    assert run['result'] == {'step': 'zap', 'step_number': 2, 'total_steps': 5}
    assert run['message'] == 'goto'
    assert events[1]['is_locked'] is True and events[1]['lock_info']['owner_user_name'] == 'Paul'
    assert events[2]['online'] == 1


def test_running_tasks_are_filtered_by_team_and_status():
    from backend_server.src.lib.utils.task_manager import TaskManager

    tm = TaskManager()
    mine = tm.create_task('script_execute', {'team_id': 'team'})
    tm.create_task('script_execute', {'team_id': 'other'})
    done = tm.create_task('script_execute', {'team_id': 'team'})
    tm.complete_task(done, {}, success=True)
    tm.create_task('web_command', {'team_id': 'team'})

    assert [t['id'] for t in tm.running_tasks('script_execute', 'team')] == [mine]
