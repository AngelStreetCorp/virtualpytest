"""
tests/backend_host/test_position_probe_timeout.py — the cap applied to a node's verifications
when NavigationExecutor asks "where am I?".

Both pre-flight probes (am I at the target? am I at home?) used to honour the node's own
verification timeouts, which are sized for "wait for this screen to appear after we acted on
it" rather than "is it showing right now". On youtube-android-mobile that was 60s for the
target plus 20s+20s for home — 101 seconds of a 139-second run before the first command
reached the phone.

`timeout` is MILLISECONDS for every verification type (web and video included), so the cap is
applied uniformly in milliseconds.
"""
import importlib

import pytest

verification_executor = importlib.import_module(
    'backend_host.src.services.verifications.verification_executor')
VerificationExecutor = verification_executor.VerificationExecutor
cap = VerificationExecutor._capped_verifications

CAP_MS = 5000


def test_timeouts_are_capped_in_milliseconds():
    out = cap([{'verification_type': 'adb', 'command': 'waitForElementToAppear',
                'params': {'search_term': 'Subscriptions', 'timeout': 20000}}], CAP_MS)
    assert out[0]['params']['timeout'] == 5000


@pytest.mark.parametrize('verification_type', ['video', 'web'])
def test_video_and_web_are_capped_in_milliseconds_too(verification_type):
    out = cap([{'verification_type': verification_type, 'command': 'WaitForVideoToAppear',
                'params': {'motion_threshold': 3.0, 'duration': 3.0, 'timeout': 60000}}], CAP_MS)
    assert out[0]['params']['timeout'] == 5000


def test_a_timeout_already_shorter_than_the_cap_is_left_alone():
    out = cap([{'verification_type': 'adb', 'params': {'timeout': 1500}}], CAP_MS)
    assert out[0]['params']['timeout'] == 1500
    out = cap([{'verification_type': 'video', 'params': {'timeout': 2000}}], CAP_MS)
    assert out[0]['params']['timeout'] == 2000


@pytest.mark.parametrize('params', [{}, {'timeout': None}, {'timeout': 'soon'}])
def test_a_missing_or_unusable_timeout_gets_the_cap(params):
    """No timeout at all means each controller's own default, which can be longer than the cap."""
    out = cap([{'verification_type': 'adb', 'params': dict(params)}], CAP_MS)
    assert out[0]['params']['timeout'] == 5000


def test_a_verification_with_no_params_key_still_gets_one():
    out = cap([{'verification_type': 'text', 'command': 'waitForTextToAppear'}], CAP_MS)
    assert out[0]['params']['timeout'] == 5000


def test_the_nodes_own_verifications_are_never_mutated():
    """These dicts come out of the cached unified graph. Writing to them would shorten the
    node's real verifications for the rest of the run — and for every later run that reads the
    same cache entry."""
    original = [{'verification_type': 'video', 'params': {'timeout': 60000, 'duration': 3.0}}]
    out = cap(original, CAP_MS)
    assert original[0]['params']['timeout'] == 60000, 'the source was modified in place'
    assert out[0]['params']['timeout'] == 5000
    assert out[0]['params'] is not original[0]['params']


def test_several_verifications_are_capped_independently():
    out = cap([
        {'verification_type': 'adb', 'params': {'timeout': 20000}},
        {'verification_type': 'video', 'params': {'timeout': 60000}},
        {'verification_type': 'image', 'params': {'timeout': 800}},
    ], CAP_MS)
    assert [v['params']['timeout'] for v in out] == [5000, 5000, 800]


# ---------------------------------------------------------------------------
# Every "where am I?" call site passes the cap (2026-09-29: three of five did not)
#
# The one-step-away probe waited out each leg of the next node's 10 s web verifications before
# every hop after the first: 60 s of a 108 s TodoMVC testcase. The stale-position and
# already-at-target probes had the same gap.
# ---------------------------------------------------------------------------

import asyncio  # noqa: E402
import time  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from unittest.mock import AsyncMock  # noqa: E402

nav_mod = importlib.import_module('backend_host.src.services.navigation.navigation_executor')
navigation_pathfinding = importlib.import_module('backend_host.src.services.navigation.navigation_pathfinding')
navigation_cache = importlib.import_module('shared.src.lib.utils.navigation_cache')


class _OneEdgeGraph:
    """home -> with-todo is one edge; nothing is an action node."""

    def __init__(self):
        self.nodes = {'home': {'label': 'home'}, 'with-todo': {'label': 'with-todo'}}

    def has_edge(self, a, b):
        return (a, b) == ('home', 'with-todo')

    def predecessors(self, _):
        return iter(())


def _navigator(monkeypatch, nav_context, verdict=False):
    graph = _OneEdgeGraph()
    monkeypatch.setattr(navigation_cache, 'get_cached_unified_graph', lambda *a, **k: graph)
    monkeypatch.setattr(navigation_pathfinding, 'find_shortest_path', lambda *a, **k: [])
    ex = nav_mod.NavigationExecutor.__new__(nav_mod.NavigationExecutor)
    ex.host_name, ex.device_id, ex.device_name, ex.device_model = 'host-1', 'host', 'web', 'host_vnc'
    ex.unified_graph = None
    verify_node = AsyncMock(return_value={'success': verdict, 'has_verifications': True,
                                          'passed_count': 0, 'total_count': 2})
    ex.device = SimpleNamespace(navigation_context=nav_context,
                                verification_executor=SimpleNamespace(verify_node=verify_node))
    ex._sync_unified_graph = lambda *a, **k: None
    ex.get_node_label = lambda node_id, *a, **k: node_id
    ex.get_node_id = lambda label, *a, **k: label
    ex._record_training_samples = lambda *a, **k: None
    ex._record_failed_verification_sample = lambda *a, **k: None
    ex.update_current_position = lambda *a, **k: None
    return ex, verify_node


def _probe_caps(verify_node):
    return [(c.kwargs['node_id'], c.kwargs.get('probe_timeout_ms')) for c in verify_node.await_args_list]


def test_one_step_away_probe_is_capped(monkeypatch):
    """No verified mark on 'home' (BUG-0195), so the probe runs: the current node first, then —
    as neither is showing here — the target. Both capped."""
    ex, verify_node = _navigator(monkeypatch, {'current_node_id': 'home', 'current_node_label': 'home',
                                               'position_timestamp': time.time()})
    asyncio.run(ex.execute_navigation(tree_id='t', userinterface_name='ui',
                                      target_node_id='with-todo', team_id='team'))
    assert _probe_caps(verify_node)[:2] == [('home', nav_mod.POSITION_PROBE_TIMEOUT_MS),
                                            ('with-todo', nav_mod.POSITION_PROBE_TIMEOUT_MS)]


def test_stale_position_probe_is_capped(monkeypatch):
    ex, verify_node = _navigator(monkeypatch, {'current_node_id': 'home', 'current_node_label': 'home',
                                               'position_timestamp': time.time() - 120})
    asyncio.run(ex.execute_navigation(tree_id='t', userinterface_name='ui',
                                      target_node_id='with-todo', team_id='team'))
    calls = _probe_caps(verify_node)
    assert calls[0] == ('home', nav_mod.POSITION_PROBE_TIMEOUT_MS), calls
    # The stale position failed, so the no-position probes followed; capped as before.
    assert all(cap_ms == nav_mod.POSITION_PROBE_TIMEOUT_MS for _, cap_ms in calls), calls


def test_already_at_target_probe_is_capped(monkeypatch):
    ex, verify_node = _navigator(monkeypatch, {'current_node_id': 'with-todo', 'current_node_label': 'with-todo',
                                               'position_timestamp': time.time()}, verdict=True)
    result = asyncio.run(ex.execute_navigation(tree_id='t', userinterface_name='ui',
                                               target_node_id='with-todo', team_id='team'))
    assert _probe_caps(verify_node) == [('with-todo', nav_mod.POSITION_PROBE_TIMEOUT_MS)]
    assert result.get('already_at_target') is True
