"""
tests/backend_host/test_testcase_step_timing.py -- where a web testcase's time goes, in its log.

Measured 2026-09-29 (TodoMVC on host-clone-2): ~65-70 s per test between VPT's step rows with
nothing recorded, because (a) TestCaseExecutor._execute_block redirects stdout into a per-block
buffer, so nothing printed inside a block reached execution.txt or the journal, and (b) the
"target is one step away" position probe in NavigationExecutor.execute_navigation waits out the
target node's full verification timeouts and writes no row.

Logging only: the block keeps its full log in the step's `logs`; the '⏱' timing lines are also
passed on to the run's stdout, and the probe now reports its own duration.
"""
import asyncio
import io
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tests.backend_host.test_testcase_fresh_start import _load_executor_module  # noqa: E402

testcase_executor = _load_executor_module()
Executor = testcase_executor.TestCaseExecutor
ScriptExecutionContext = testcase_executor.ScriptExecutionContext

import importlib  # noqa: E402

nav_mod = importlib.import_module('backend_host.src.services.navigation.navigation_executor')
navigation_pathfinding = importlib.import_module('backend_host.src.services.navigation.navigation_pathfinding')
navigation_cache = importlib.import_module('shared.src.lib.utils.navigation_cache')
NavigationExecutor = nav_mod.NavigationExecutor

MARKER = '⏱'


def test_block_log_stays_whole_and_timing_lines_reach_the_run_log():
    ex = Executor()

    async def fake_navigation_block(data, context):
        print('[@navigation_executor] 🔍 Target is 1 step away - verifying')
        print(f'{MARKER} nav.probe_target_one_step_away 20012 ms target=with-todo')
        return {'success': True, 'execution_time_ms': 1}

    ex._execute_navigation_block = fake_navigation_block
    ctx = ScriptExecutionContext('timing')
    node = {'id': 'b1', 'type': 'navigation', 'data': {'target_node_label': 'with-todo'}}

    run_log = io.StringIO()
    saved = sys.stdout
    sys.stdout = run_log
    try:
        result = asyncio.run(ex._execute_block(node, ctx))
        restored = sys.stdout
    finally:
        sys.stdout = saved

    assert restored is run_log  # redirect undone
    assert result['success'] is True
    # The step's own logs are unchanged: everything the block printed.
    assert '[@navigation_executor] 🔍 Target is 1 step away - verifying\n' in result['logs']
    assert f'{MARKER} nav.probe_target_one_step_away 20012 ms' in result['logs']
    # The run log (execution.txt / journal) receives only the timing line.
    assert run_log.getvalue() == f'{MARKER} nav.probe_target_one_step_away 20012 ms target=with-todo\n'


class _OneEdgeGraph:
    """Unified-graph stand-in: home -> with-todo is one edge."""

    def __init__(self):
        self.nodes = {'home': {'label': 'home'}, 'with-todo': {'label': 'with-todo'}}

    def has_edge(self, a, b):
        return (a, b) == ('home', 'with-todo')

    def predecessors(self, _):
        return iter(())


@pytest.fixture
def one_edge_tree(monkeypatch):
    graph = _OneEdgeGraph()
    monkeypatch.setattr(navigation_cache, 'get_cached_unified_graph', lambda *a, **k: graph)
    # No path: execution stops right after the position checks.
    monkeypatch.setattr(navigation_pathfinding, 'find_shortest_path', lambda *a, **k: [])
    return graph


def test_one_step_away_probe_reports_its_duration(one_edge_tree, capsys):
    ex = NavigationExecutor.__new__(NavigationExecutor)
    ex.host_name, ex.device_id, ex.device_name, ex.device_model = 'host-1', 'host', 'web', 'host_vnc'
    ex.unified_graph = None
    import time
    verify_node = AsyncMock(return_value={'success': False, 'has_verifications': True,
                                          'passed_count': 0, 'total_count': 2})
    ex.device = SimpleNamespace(
        navigation_context={'current_node_id': 'home', 'current_node_label': 'home',
                            'position_timestamp': time.time()},
        verification_executor=SimpleNamespace(verify_node=verify_node))
    ex._sync_unified_graph = lambda *a, **k: None
    ex.get_node_label = lambda node_id, *a, **k: node_id
    ex._record_training_samples = lambda *a, **k: None
    ex._record_failed_verification_sample = lambda *a, **k: None

    result = asyncio.run(ex.execute_navigation(tree_id='t', userinterface_name='ui',
                                               target_node_id='with-todo', team_id='team'))

    assert result['success'] is False  # no path in this stub; the probe ran before that
    # The probe is capped like the other position probes (it used to wait out every leg). Since
    # BUG-0195 it checks the current node first, then (not showing here) the target.
    current_call, probe_call = verify_node.await_args_list[:2]
    assert current_call.kwargs['node_id'] == 'home'
    assert probe_call.kwargs['node_id'] == 'with-todo'
    assert current_call.kwargs['probe_timeout_ms'] == nav_mod.POSITION_PROBE_TIMEOUT_MS
    assert probe_call.kwargs['probe_timeout_ms'] == nav_mod.POSITION_PROBE_TIMEOUT_MS
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith(MARKER)]
    current = [ln for ln in lines if ln.startswith(f'{MARKER} nav.probe_current_one_step_away ')]
    assert len(current) == 1, lines
    assert (f'node=home target=with-todo cap_ms={nav_mod.POSITION_PROBE_TIMEOUT_MS} '
            'success=False legs=0/2') in current[0]
    probe = [ln for ln in lines if ln.startswith(f'{MARKER} nav.probe_target_one_step_away ')]
    assert len(probe) == 1, lines
    assert (f'from=home target=with-todo cap_ms={nav_mod.POSITION_PROBE_TIMEOUT_MS} '
            'success=False legs=0/2') in probe[0]
    assert any(ln.startswith(f'{MARKER} nav.pathfinding ') for ln in lines)
