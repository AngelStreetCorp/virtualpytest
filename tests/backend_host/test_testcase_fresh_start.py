"""
tests/backend_host/test_testcase_fresh_start.py — BUG-0190: a web testcase's first navigation
takes the tree's entry edge instead of trusting whatever page it finds.

With no tracked position, NavigationExecutor.execute_navigation first probes "am I already at
the target?" and, if the target's verifications pass, records a 0-action step and skips the
path — entry edge included. On a web device VPT closes the browser at the end of every run, so
a browser that is open at testcase start was left by something else (ad-hoc REST/MCP commands),
and a target verified by text every view shows ("todos" on TodoMVC's #/completed) passes the
probe on a stale page with stale storage.

The fix, in three places:
  * execute_navigation(start_from_entry=True) forgets the tracked position and skips both
    probes (target, then home) — pathfinding starts at entry;
  * TestCaseExecutor arms it at testcase start for a device with a web controller unless
    VPT_KEEP_BROWSER_OPEN=true, and hands it to the FIRST navigation block only;
  * an action block before that first navigation cancels it (the testcase set the device up
    itself).

The testcase executor is loaded with hollow parent packages and MagicMock stand-ins for absent
third-party modules, as in test_navigation_block_id_label_fallback.py.
"""
import asyncio
import importlib
import importlib.util
import os
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

_EXECUTOR = 'backend_host.src.services.testcase.testcase_executor'
_EVENT_UTILS = 'backend_host.src.lib.utils.execution_event_utils'
_ORCHESTRATOR = 'backend_host.src.orchestrator'
_THIRD_PARTY = ['psutil', 'flask', 'flask_cors', 'dotenv', 'boto3', 'botocore', 'botocore.client',
                'boto3.s3', 'boto3.s3.transfer', 'botocore.exceptions', 'supabase', 'httpx',
                'supabase.lib', 'supabase.lib.client_options']


def _importable(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _load_executor_module():
    if _EXECUTOR in sys.modules:
        return sys.modules[_EXECUTOR]
    for name, rel in [('backend_host', 'backend_host'),
                      ('backend_host.src', 'backend_host/src'),
                      ('backend_host.src.services', 'backend_host/src/services'),
                      ('backend_host.src.services.testcase', 'backend_host/src/services/testcase')]:
        if name not in sys.modules:
            pkg = types.ModuleType(name)
            pkg.__path__ = [os.path.join(REPO_ROOT, rel)]
            sys.modules[name] = pkg
    for name in _THIRD_PARTY:
        if name not in sys.modules and not _importable(name):
            stub = MagicMock(name=name)
            stub.__path__ = []
            stub.__spec__ = None
            sys.modules[name] = stub
    if _EVENT_UTILS not in sys.modules and not _importable('cv2'):
        sys.modules[_EVENT_UTILS] = MagicMock(name=_EVENT_UTILS)
    return importlib.import_module(_EXECUTOR)


testcase_executor = _load_executor_module()
Executor = testcase_executor.TestCaseExecutor  # not `TestCaseExecutor`: pytest would try to collect it
ScriptExecutionContext = testcase_executor.ScriptExecutionContext

nav_mod = importlib.import_module('backend_host.src.services.navigation.navigation_executor')
navigation_pathfinding = importlib.import_module('backend_host.src.services.navigation.navigation_pathfinding')
navigation_cache = importlib.import_module('shared.src.lib.utils.navigation_cache')
NavigationExecutor = nav_mod.NavigationExecutor

TREE_ID = 'tree-todomvc'
TEAM_ID = 'team-1'
UI_NAME = 'todomvc_web'
HOME = 'n-home'


# --------------------------------------------------------------------------------------------
# NavigationExecutor.execute_navigation(start_from_entry=...)
# --------------------------------------------------------------------------------------------

@pytest.fixture
def pathfinding(monkeypatch):
    """find_shortest_path returns no path: execution stops right after the start decision,
    before any step runs, with a clean 'No unified path' failure."""
    calls = []

    def fake_find_shortest_path(tree_id, target_node_id, team_id, start_node_id=None, variant=None):
        calls.append({'target': target_node_id, 'start': start_node_id})
        return []

    monkeypatch.setattr(navigation_pathfinding, 'find_shortest_path', fake_find_shortest_path)
    monkeypatch.setattr(navigation_cache, 'get_cached_unified_graph', lambda *a, **k: None)
    return calls


def _navigation_executor(verify_success=True, nav_context=None):
    """A NavigationExecutor whose probe passes (the TodoMVC case: 'todos' is on every view)."""
    ex = NavigationExecutor.__new__(NavigationExecutor)
    ex.host_name, ex.device_id, ex.device_name, ex.device_model = 'host-1', 'host', 'web', 'host_vnc'
    ex.unified_graph = None
    context = {'current_node_id': None, 'current_node_label': None}
    context.update(nav_context or {})
    verify_node = AsyncMock(return_value={'success': verify_success, 'has_verifications': True})
    ex.device = SimpleNamespace(navigation_context=context,
                                verification_executor=SimpleNamespace(verify_node=verify_node))
    ex._sync_unified_graph = lambda *a, **k: None
    ex.get_node_label = lambda node_id, *a, **k: {HOME: 'home'}.get(node_id, node_id)

    def get_node_id(label, *a, **k):
        if label == 'home':
            return HOME
        raise ValueError(label)
    ex.get_node_id = get_node_id
    ex._record_training_samples = lambda *a, **k: None
    ex._record_failed_verification_sample = lambda *a, **k: None
    return ex


def _navigate(ex, target=HOME, **kwargs):
    return asyncio.run(ex.execute_navigation(tree_id=TREE_ID, userinterface_name=UI_NAME,
                                             target_node_id=target, team_id=TEAM_ID, **kwargs))


def test_without_fresh_start_a_passing_probe_skips_the_entry_edge(pathfinding):
    """The bug, as it was: target verified on whatever page is showing, zero actions, no path."""
    ex = _navigation_executor(verify_success=True)
    result = _navigate(ex)

    ex.device.verification_executor.verify_node.assert_awaited_once()
    assert result['success'] is True
    assert result['already_at_target'] is True
    assert result['actions_executed'] == 0
    assert pathfinding == []


def test_fresh_start_skips_the_probe_and_paths_from_entry(pathfinding, capsys):
    ex = _navigation_executor(verify_success=True)
    _navigate(ex, start_from_entry=True)

    ex.device.verification_executor.verify_node.assert_not_awaited()
    assert pathfinding == [{'target': HOME, 'start': None}]
    assert 'Testcase fresh start: navigating from entry (position probes skipped)' in capsys.readouterr().out


def test_fresh_start_also_skips_the_home_fallback_probe(pathfinding):
    """Target is not home: without the flag the target probe fails, then home is probed and, when
    it passes, the path starts from home — which also skips the entry edge."""
    ex = _navigation_executor(verify_success=True)
    ex.device.verification_executor.verify_node.side_effect = [
        {'success': False, 'has_verifications': True},   # target probe
        {'success': True, 'has_verifications': True},    # home probe
    ]
    _navigate(ex, target='n-with-todo')
    assert pathfinding[-1] == {'target': 'n-with-todo', 'start': HOME}

    ex = _navigation_executor(verify_success=True)
    _navigate(ex, target='n-with-todo', start_from_entry=True)
    ex.device.verification_executor.verify_node.assert_not_awaited()
    assert pathfinding[-1] == {'target': 'n-with-todo', 'start': None}


def test_fresh_start_discards_a_tracked_position_without_verifying_it(pathfinding):
    """The by-name (campaign) path never resets position: a >30 s old one would be re-verified
    with the node's full timeouts before anything else. Fresh start drops it outright."""
    ex = _navigation_executor(verify_success=True, nav_context={
        'current_node_id': 'n-completed', 'current_node_label': 'completed',
        'current_tree_id': TREE_ID, 'position_timestamp': 0, 'last_verified_timestamp': 5})
    _navigate(ex, start_from_entry=True)

    ex.device.verification_executor.verify_node.assert_not_awaited()
    assert pathfinding == [{'target': HOME, 'start': None}]
    ctx = ex.device.navigation_context
    assert ctx['current_tree_id'] is None
    assert ctx['position_timestamp'] == 0
    assert ctx['last_verified_timestamp'] == 0
    assert ctx['previous_node_id'] == 'n-completed'


def test_fresh_start_is_ignored_by_a_recovery(pathfinding):
    """Recovery repositions mid-run: it keeps the normal probe."""
    ex = _navigation_executor(verify_success=False)
    _navigate(ex, start_from_entry=True, is_recovery=True)
    ex.device.verification_executor.verify_node.assert_awaited()


# --------------------------------------------------------------------------------------------
# TestCaseExecutor: who gets start_from_entry
# --------------------------------------------------------------------------------------------

class FakeGraph:
    def __init__(self, node_ids):
        self.nodes = set(node_ids)


@pytest.fixture
def execute_navigation(monkeypatch):
    orchestrator_mod = types.ModuleType(_ORCHESTRATOR)
    orchestrator_cls = MagicMock(name='ExecutionOrchestrator')
    orchestrator_cls.execute_navigation = AsyncMock(return_value={'success': True})
    orchestrator_mod.ExecutionOrchestrator = orchestrator_cls
    monkeypatch.setitem(sys.modules, _ORCHESTRATOR, orchestrator_mod)
    return orchestrator_cls.execute_navigation


def _testcase_executor():
    ex = Executor()
    ex.device = MagicMock()
    ex.device.navigation_context = {}
    ex.device.navigation_executor._sync_unified_graph.return_value = FakeGraph({HOME, 'n-with-todo'})
    ex._execute_action_block = AsyncMock(return_value={'success': True, 'execution_time_ms': 0})
    return ex


def _armed_context(pending=True):
    ctx = ScriptExecutionContext('fresh-start-test')
    ctx.tree_id = TREE_ID
    ctx.team_id = TEAM_ID
    ctx.userinterface_name = UI_NAME
    ctx.start_from_entry_pending = pending
    return ctx


def _nav_block(target):
    return {'type': 'navigation', 'data': {'target_node_id': target}}


def _flags(execute_navigation):
    return [c.kwargs['start_from_entry'] for c in execute_navigation.await_args_list]


def test_only_the_first_navigation_of_a_testcase_starts_from_entry(execute_navigation):
    ex, ctx = _testcase_executor(), _armed_context()
    asyncio.run(ex._execute_block(_nav_block(HOME), ctx))
    asyncio.run(ex._execute_block(_nav_block('n-with-todo'), ctx))

    assert _flags(execute_navigation) == [True, False]


def test_an_action_block_before_the_first_navigation_cancels_the_fresh_start(execute_navigation):
    ex, ctx = _testcase_executor(), _armed_context()
    asyncio.run(ex._execute_block({'type': 'action', 'data': {'actions': []}}, ctx))
    asyncio.run(ex._execute_block(_nav_block(HOME), ctx))

    ex._execute_action_block.assert_awaited_once()
    assert _flags(execute_navigation) == [False]


def test_an_unarmed_context_never_starts_from_entry(execute_navigation):
    ex = _testcase_executor()
    ctx = _armed_context()
    del ctx.start_from_entry_pending
    asyncio.run(ex._execute_block(_nav_block(HOME), ctx))

    assert _flags(execute_navigation) == [False]


def _device(controllers):
    return SimpleNamespace(get_controllers=lambda kind: list(controllers.get(kind, [])))


def test_a_web_device_is_armed(monkeypatch):
    monkeypatch.delenv('VPT_KEEP_BROWSER_OPEN', raising=False)
    assert Executor._starts_from_entry(_device({'web': [object()]})) is True


@pytest.mark.parametrize('value', ['true', 'TRUE', '1', 'yes'])
def test_keep_browser_open_disarms_it(monkeypatch, value):
    monkeypatch.setenv('VPT_KEEP_BROWSER_OPEN', value)
    assert Executor._starts_from_entry(_device({'web': [object()]})) is False


@pytest.mark.parametrize('value', ['', 'false', '0'])
def test_keep_browser_open_off_leaves_it_armed(monkeypatch, value):
    monkeypatch.setenv('VPT_KEEP_BROWSER_OPEN', value)
    assert Executor._starts_from_entry(_device({'web': [object()]})) is True


def test_a_device_without_a_web_controller_is_not_armed(monkeypatch):
    """Android / TV / STB keep the position probe."""
    monkeypatch.delenv('VPT_KEEP_BROWSER_OPEN', raising=False)
    assert Executor._starts_from_entry(_device({'remote': [object()]})) is False
