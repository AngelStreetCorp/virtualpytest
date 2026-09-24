"""
tests/backend_host/test_navigation_block_id_label_fallback.py — which of target_node_id /
target_node_label a testcase navigation block hands to ExecutionOrchestrator.execute_navigation.

812ce5119 flipped TestCaseExecutor._execute_navigation_block from label-first to id-first.
Sound in itself (labels duplicate and drift), but stored graphs exist whose target_node_id
matches no node in the navigation tree while their label is still right. Under id-first
every hop of such a graph failed in ~0.1 s with zero execution rows.

The rule now: the id wins when it is a node of the unified graph the navigation will use;
a stale id falls back to the label with one warning; a stale id with no label fails before
any navigation attempt, naming the id and the tree. execute_navigation must still receive
EXACTLY ONE of id/label — the backend validates that.

The executor's package chain (backend_host.src → controllers → cv2, and shared → psutil,
flask, boto3, supabase...) is not importable on a bare box, so the module is loaded with
hollow parent packages and MagicMock stand-ins for whichever third-party modules are absent.
Nothing the navigation block touches lives in those modules.
"""
import asyncio
import importlib
import importlib.util
import os
import sys
import types
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
    # Hollow parents: the real backend_host/src/__init__ imports every controller (cv2...).
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
    # execution_event_utils pulls host_utils → controller_manager → cv2; the navigation
    # block never emits an event, so a stand-in is enough.
    if _EVENT_UTILS not in sys.modules and not _importable('cv2'):
        sys.modules[_EVENT_UTILS] = MagicMock(name=_EVENT_UTILS)
    return importlib.import_module(_EXECUTOR)


testcase_executor = _load_executor_module()
Executor = testcase_executor.TestCaseExecutor  # not `TestCaseExecutor`: pytest would try to collect it
ScriptExecutionContext = testcase_executor.ScriptExecutionContext

TREE_ID = 'tree-abc'
TEAM_ID = 'team-1'
UI_NAME = 'sauce_demo_web'


class FakeGraph:
    """Only what the pre-check reads: `node_id in graph.nodes`."""
    def __init__(self, node_ids):
        self.nodes = set(node_ids)


def _executor_with_graph(graph):
    ex = Executor()
    ex.device = MagicMock()
    ex.device.navigation_context = {}
    ex.device.navigation_executor._sync_unified_graph.return_value = graph
    return ex


def _context():
    ctx = ScriptExecutionContext('nav-block-test')
    ctx.tree_id = TREE_ID
    ctx.team_id = TEAM_ID
    ctx.userinterface_name = UI_NAME
    return ctx


@pytest.fixture
def execute_navigation(monkeypatch):
    """Stand-in ExecutionOrchestrator, installed where the block imports it from."""
    orchestrator_mod = types.ModuleType(_ORCHESTRATOR)
    orchestrator_cls = MagicMock(name='ExecutionOrchestrator')
    orchestrator_cls.execute_navigation = AsyncMock(return_value={'success': True})
    orchestrator_mod.ExecutionOrchestrator = orchestrator_cls
    monkeypatch.setitem(sys.modules, _ORCHESTRATOR, orchestrator_mod)
    return orchestrator_cls.execute_navigation


def _run(ex, data):
    return asyncio.run(ex._execute_navigation_block(data, _context()))


def _nav_kwargs(execute_navigation):
    execute_navigation.assert_awaited_once()
    return execute_navigation.await_args.kwargs


def test_id_that_is_a_node_of_the_graph_is_used_and_label_is_dropped(execute_navigation):
    ex = _executor_with_graph(FakeGraph({'uuid-home', 'uuid-cart'}))
    result = _run(ex, {'target_node_id': 'uuid-cart', 'target_node_label': 'Cart'})

    kwargs = _nav_kwargs(execute_navigation)
    assert kwargs['target_node_id'] == 'uuid-cart'
    assert kwargs['target_node_label'] is None
    assert kwargs['tree_id'] == TREE_ID
    assert result['success'] is True


def test_stale_id_with_label_navigates_by_label_and_warns_once(execute_navigation, capsys):
    ex = _executor_with_graph(FakeGraph({'uuid-home', 'uuid-cart'}))
    result = _run(ex, {'target_node_id': 'uuid-stale', 'target_node_label': 'Cart'})

    kwargs = _nav_kwargs(execute_navigation)
    assert kwargs['target_node_label'] == 'Cart'
    assert kwargs['target_node_id'] is None
    assert result['success'] is True

    warnings = [line for line in capsys.readouterr().out.splitlines()
                if 'is not a node of tree' in line]
    assert len(warnings) == 1
    assert 'uuid-stale' in warnings[0]
    assert 'Cart' in warnings[0]
    assert TREE_ID in warnings[0]


def test_stale_id_with_target_node_alias_falls_back_the_same_way(execute_navigation):
    ex = _executor_with_graph(FakeGraph({'uuid-home'}))
    _run(ex, {'target_node_id': 'uuid-stale', 'target_node': 'Home'})

    kwargs = _nav_kwargs(execute_navigation)
    assert kwargs['target_node_label'] == 'Home'
    assert kwargs['target_node_id'] is None


def test_label_only_navigates_by_label_without_a_pre_check(execute_navigation):
    ex = _executor_with_graph(FakeGraph({'uuid-home'}))
    result = _run(ex, {'target_node_label': 'Home'})

    kwargs = _nav_kwargs(execute_navigation)
    assert kwargs['target_node_label'] == 'Home'
    assert kwargs['target_node_id'] is None
    assert result['success'] is True
    ex.device.navigation_executor._sync_unified_graph.assert_not_called()


def test_stale_id_without_label_fails_before_any_navigation_naming_id_and_tree(execute_navigation):
    ex = _executor_with_graph(FakeGraph({'uuid-home'}))
    result = _run(ex, {'target_node_id': 'uuid-stale'})

    execute_navigation.assert_not_awaited()
    assert result['success'] is False
    assert 'uuid-stale' in result['error']
    assert TREE_ID in result['error']


def test_no_graph_to_check_against_keeps_id_first_behaviour(execute_navigation):
    """Cache miss and populate failed: nothing to pre-check, so the id goes through as before."""
    ex = _executor_with_graph(None)
    _run(ex, {'target_node_id': 'uuid-maybe-stale', 'target_node_label': 'Cart'})

    kwargs = _nav_kwargs(execute_navigation)
    assert kwargs['target_node_id'] == 'uuid-maybe-stale'
    assert kwargs['target_node_label'] is None


def test_pre_check_uses_the_navigation_executor_graph_for_this_tree_team_and_ui(execute_navigation):
    ex = _executor_with_graph(FakeGraph({'uuid-home'}))
    _run(ex, {'target_node_id': 'uuid-home', 'target_node_label': 'Home'})

    ex.device.navigation_executor._sync_unified_graph.assert_called_once_with(TREE_ID, TEAM_ID, UI_NAME)
