"""
tests/backend_host/test_trust_just_verified_position.py — BUG-0195: the one-step-away position
probe no longer re-checks a position the previous hop verified a moment ago, and where it still
runs it checks the CURRENT node before the target.

Before, `NavigationExecutor.execute_navigation` probed the TARGET's verifications before every
hop after the first, whatever had just happened. The target is not showing yet, so each leg
waited out its 5 s cap (347 s of 597 s over 16 TodoMVC testcases). And a target verified by text
the current screen also shows "passed": no hop ran, the action under test never happened and the
testcase passed (TodoMVC 04_toggle_all_back_to_active: `with-two-todos` is verified by 'Walk dog',
which the `all-completed` screen shows too).

Now:
  * a position is marked verified (`last_verified_node_id` + `last_verified_timestamp`) only when
    its own verifications ran and passed; the probe is skipped while that mark is younger than
    VPT_POSITION_TRUST_SECONDS (default 10 s);
  * a testcase action block (or any standard block that can send commands) and an ad-hoc
    /host/action/executeBatch call forget the mark;
  * where the probe runs: current node first → showing: take the edge; not showing → target;
    neither → the tracked position is cleared.

These tests fail on the code before the fix (the probe awaited the target first, every time,
and a passing target check skipped the hop).
"""
import asyncio
import importlib
import os
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tests.backend_host.test_testcase_fresh_start import _load_executor_module  # noqa: E402

testcase_executor = _load_executor_module()
Executor = testcase_executor.TestCaseExecutor  # not `TestCaseExecutor`: pytest would collect it
ScriptExecutionContext = testcase_executor.ScriptExecutionContext

nav_mod = importlib.import_module('backend_host.src.services.navigation.navigation_executor')
navigation_pathfinding = importlib.import_module('backend_host.src.services.navigation.navigation_pathfinding')
navigation_cache = importlib.import_module('shared.src.lib.utils.navigation_cache')
NavigationExecutor = nav_mod.NavigationExecutor

MARKER = '⏱'
CAP = nav_mod.POSITION_PROBE_TIMEOUT_MS

# TodoMVC-shaped tree: with-todo -> with-two-todos -> all-completed -> with-two-todos
EDGES = {('with-todo', 'with-two-todos'): 'e-add-second',
         ('with-two-todos', 'all-completed'): 'e-toggle-all',
         ('all-completed', 'with-two-todos'): 'e-toggle-all-back',
         ('with-two-todos', 'no-checks'): 'e-to-no-checks',
         ('no-checks', 'with-two-todos'): 'e-from-no-checks'}
VERIFIED = [{'verification_type': 'web', 'command': 'waitForElementToAppear',
             'params': {'search_term': 'Walk dog'}}]


class _Graph:
    def __init__(self):
        self.nodes = {n: {'label': n} for pair in EDGES for n in pair}

    def has_edge(self, a, b):
        return (a, b) in EDGES

    def predecessors(self, _):
        return iter(())


def _step(src, dst, verifications=VERIFIED):
    return {'transition_number': 1, 'step_number': 1, 'from_node_id': src, 'to_node_id': dst,
            'from_node_label': src, 'to_node_label': dst, 'actions': [],
            'verifications': list(verifications), 'edge_id': EDGES[(src, dst)],
            'action_set_id': 'as-1', 'final_wait_time': 0}


@pytest.fixture
def tree(monkeypatch):
    graph = _Graph()
    monkeypatch.setattr(navigation_cache, 'get_cached_unified_graph', lambda *a, **k: graph)

    def one_hop_path(tree_id, target_node_id, team_id, start_node_id=None, variant=None):
        for (src, dst) in EDGES:
            if src == start_node_id and dst == target_node_id:
                return [_step(src, dst)]
        return []
    monkeypatch.setattr(navigation_pathfinding, 'find_shortest_path', one_hop_path)
    monkeypatch.setattr(nav_mod, 'find_shortest_path', one_hop_path)
    return graph


class _Screen:
    """verify_node stand-in: which nodes' verifications pass on the live screen."""

    def __init__(self, showing=(), without_verifications=()):
        self.showing = set(showing)
        self.without_verifications = set(without_verifications)
        self.calls = []  # (node_id, probe_timeout_ms)

    async def verify_node(self, node_id, **kw):
        self.calls.append((node_id, kw.get('probe_timeout_ms')))
        if node_id in self.without_verifications:
            return {'success': False, 'has_verifications': False, 'results': []}
        ok = node_id in self.showing
        return {'success': ok, 'has_verifications': True, 'passed_count': int(ok), 'total_count': 1,
                'results': []}

    def probes(self):
        return [c for c in self.calls if c[1] is not None]


def _executor(screen, nav_context):
    ex = NavigationExecutor.__new__(NavigationExecutor)
    ex.host_name, ex.device_id, ex.device_name, ex.device_model = 'host-1', 'host', 'web', 'host_vnc'
    ex.unified_graph = None
    ex.device = SimpleNamespace(navigation_context=nav_context,
                                verification_executor=SimpleNamespace(verify_node=screen.verify_node),
                                action_executor=SimpleNamespace())
    ex._sync_unified_graph = lambda *a, **k: None
    ex.get_node_label = lambda node_id, *a, **k: node_id
    ex.get_node_id = lambda label, *a, **k: (_ for _ in ()).throw(ValueError(label))  # no 'home'
    ex._record_training_samples = lambda *a, **k: None
    ex._record_failed_verification_sample = lambda *a, **k: None
    ex._resolve_kpi_references = lambda step: None
    ex.edges_run = []
    ex._record_step_execution_results = lambda **k: ex.edges_run.append(k['step']['edge_id']) or 'exec-1'
    return ex


def _at(node, verified_age_s=None, verified_node=None):
    ctx = {'current_node_id': node, 'current_node_label': node, 'current_tree_id': 't',
           'position_timestamp': time.time()}
    if verified_age_s is not None:
        ctx['last_verified_node_id'] = verified_node or node
        ctx['last_verified_timestamp'] = time.time() - verified_age_s
    return ctx


def _goto(ex, target):
    return asyncio.run(ex.execute_navigation(tree_id='t', userinterface_name='ui',
                                             target_node_id=target, team_id='team'))


def _goto_path(ex, src, dst, verifications=VERIFIED):
    return asyncio.run(ex.execute_navigation(tree_id='t', userinterface_name='ui',
                                             navigation_path=[_step(src, dst, verifications)],
                                             team_id='team', verification_mode='each'))


# --------------------------------------------------------------------------------------------
# 1. The skip
# --------------------------------------------------------------------------------------------

def test_a_position_verified_a_moment_ago_is_not_probed(tree, capsys, monkeypatch):
    monkeypatch.delenv('VPT_POSITION_TRUST_SECONDS', raising=False)
    screen = _Screen(showing={'with-two-todos'})
    ex = _executor(screen, _at('with-todo', verified_age_s=0.05))

    result = _goto(ex, 'with-two-todos')

    assert result['success'] is True
    assert screen.probes() == []                          # no capped "where am I?" check at all
    assert screen.calls == [('with-two-todos', None)]     # only the hop's own destination check
    assert ex.edges_run == ['e-add-second']
    skipped = [ln for ln in capsys.readouterr().out.splitlines()
               if ln.startswith(f'{MARKER} nav.probe_skipped_recently_verified ')]
    assert len(skipped) == 1 and 'from=with-todo target=with-two-todos' in skipped[0], skipped


def test_the_false_pass_hop_now_runs(tree, monkeypatch):
    """04_toggle_all_back_to_active: 'Walk dog' is on all-completed too, so the target check
    passes on the wrong screen. The hop under test (toggle-all back) must still run."""
    monkeypatch.delenv('VPT_POSITION_TRUST_SECONDS', raising=False)
    screen = _Screen(showing={'all-completed', 'with-two-todos'})
    ex = _executor(screen, _at('all-completed', verified_age_s=0.02))

    result = _goto(ex, 'with-two-todos')

    assert not result.get('position_tracking_bug_corrected')
    assert not result.get('already_at_target')
    assert ex.edges_run == ['e-toggle-all-back']


def test_a_mark_older_than_the_window_is_probed_current_node_first(tree, monkeypatch):
    monkeypatch.delenv('VPT_POSITION_TRUST_SECONDS', raising=False)
    screen = _Screen(showing={'with-todo', 'with-two-todos'})
    ex = _executor(screen, _at('with-todo', verified_age_s=11))

    _goto(ex, 'with-two-todos')

    assert screen.probes() == [('with-todo', CAP)]        # current showing: target never probed
    assert ex.edges_run == ['e-add-second']


def test_a_mark_for_another_node_is_probed(tree, monkeypatch):
    monkeypatch.delenv('VPT_POSITION_TRUST_SECONDS', raising=False)
    screen = _Screen(showing={'with-todo', 'with-two-todos'})
    ex = _executor(screen, _at('with-todo', verified_age_s=0.05, verified_node='all-completed'))

    _goto(ex, 'with-two-todos')

    assert screen.probes() == [('with-todo', CAP)]


@pytest.mark.parametrize('env, age_s, probed', [
    ('30', 11, False),     # a longer window trusts an 11 s old mark
    ('0', 0.05, True),     # 0 turns the skip off
    ('soon', 11, True),    # unusable -> default 10 s
    ('soon', 5, False),
])
def test_the_window_comes_from_the_environment(tree, monkeypatch, env, age_s, probed):
    monkeypatch.setenv('VPT_POSITION_TRUST_SECONDS', env)
    screen = _Screen(showing={'with-todo', 'with-two-todos'})
    ex = _executor(screen, _at('with-todo', verified_age_s=age_s))

    _goto(ex, 'with-two-todos')

    assert bool(screen.probes()) is probed


# --------------------------------------------------------------------------------------------
# 2. What marks a position verified
# --------------------------------------------------------------------------------------------

def test_a_hop_whose_verifications_pass_marks_its_destination(tree):
    screen = _Screen(showing={'with-two-todos'})
    ex = _executor(screen, _at('with-todo'))
    before = time.time()

    assert _goto_path(ex, 'with-todo', 'with-two-todos')['success'] is True

    ctx = ex.device.navigation_context
    assert ctx['current_node_id'] == 'with-two-todos'
    assert ctx['last_verified_node_id'] == 'with-two-todos'
    assert ctx['last_verified_timestamp'] >= before


def test_a_destination_without_verifications_is_not_marked(tree):
    """The hop's check is skipped (nothing to verify): the position is claimed, not verified.
    Before the fix the end of every navigation stamped last_verified_timestamp = now."""
    screen = _Screen()
    ex = _executor(screen, _at('with-two-todos', verified_age_s=0.01))

    assert _goto_path(ex, 'with-two-todos', 'no-checks', verifications=[])['success'] is True

    ctx = ex.device.navigation_context
    assert ctx['current_node_id'] == 'no-checks'
    assert ctx['last_verified_timestamp'] == 0
    assert ctx.get('last_verified_node_id') is None


def test_after_a_destination_without_verifications_the_next_hop_is_probed(tree, monkeypatch):
    monkeypatch.delenv('VPT_POSITION_TRUST_SECONDS', raising=False)
    screen = _Screen(showing=set(), without_verifications={'no-checks'})
    ex = _executor(screen, _at('with-two-todos'))
    assert _goto_path(ex, 'with-two-todos', 'no-checks', verifications=[])['success'] is True
    screen.calls.clear()

    _goto(ex, 'with-two-todos')                            # a moment later, one edge away

    # probed (current first; it has nothing to check, so the target too), then the hop runs
    assert screen.probes() == [('no-checks', CAP), ('with-two-todos', CAP)]
    assert ex.edges_run[-1] == 'e-from-no-checks'


def test_setting_a_position_is_not_verifying_it(tree):
    ex = _executor(_Screen(), _at('with-todo', verified_age_s=0.01))
    ex.update_current_position('with-todo', 't', 'with-todo')      # same node, a claim
    assert ex.device.navigation_context['last_verified_node_id'] is None

    ctx = _at('with-todo', verified_age_s=0.01)
    ex.device.navigation_context = ctx
    ex.clear_current_position()
    assert ctx['last_verified_node_id'] is None and ctx['last_verified_timestamp'] == 0


# --------------------------------------------------------------------------------------------
# 3. Out-of-band commands forget the mark
# --------------------------------------------------------------------------------------------

@pytest.fixture
def testcase(monkeypatch):
    ex = Executor()
    ctx = _at('with-todo', verified_age_s=0.01)
    ex.device = SimpleNamespace(navigation_context=ctx)
    ex._execute_action_block = AsyncMock(return_value={'success': True, 'execution_time_ms': 0})
    ex._execute_verification_block = AsyncMock(return_value={'success': True, 'execution_time_ms': 0})
    ex._execute_standard_block = AsyncMock(return_value={'success': True, 'execution_time_ms': 0})
    return ex, ctx, ScriptExecutionContext('trust-position')


def _run_block(ex, context, node_type, data):
    return asyncio.run(ex._execute_block({'id': 'b1', 'type': node_type, 'data': data}, context))


def test_an_action_block_forgets_the_mark(testcase):
    ex, ctx, context = testcase
    _run_block(ex, context, 'action', {'actions': [{'command': 'click_element'}]})
    assert ctx['last_verified_timestamp'] == 0
    assert ctx['last_verified_node_id'] is None
    assert ctx['current_node_id'] == 'with-todo'           # the position itself is kept


def test_an_action_block_that_raises_still_forgets_the_mark(testcase):
    ex, ctx, context = testcase
    ex._execute_action_block = AsyncMock(side_effect=RuntimeError('driver gone'))
    with pytest.raises(RuntimeError):
        _run_block(ex, context, 'action', {'actions': [{'command': 'click_element'}]})
    assert ctx['last_verified_timestamp'] == 0


@pytest.mark.parametrize('command, forgets', [
    ('custom_code', True), ('api_call', True), ('some_future_block', True),
    ('sleep', False), ('evaluate_condition', False), ('get_current_time', False),
    ('common_operation', False),
])
def test_standard_blocks_that_can_send_commands_forget_the_mark(testcase, command, forgets):
    ex, ctx, context = testcase
    _run_block(ex, context, command, {'command': command, 'params': {}})
    assert (ctx['last_verified_timestamp'] == 0) is forgets


def test_a_verification_block_keeps_the_mark(testcase):
    ex, ctx, context = testcase
    _run_block(ex, context, 'verification', {'verifications': [{'command': 'waitForElementToAppear'}]})
    assert ctx['last_verified_timestamp'] > 0 and ctx['last_verified_node_id'] == 'with-todo'


def test_after_an_action_block_the_next_one_step_hop_is_probed(tree, testcase, monkeypatch):
    monkeypatch.delenv('VPT_POSITION_TRUST_SECONDS', raising=False)
    tc, ctx, context = testcase
    _run_block(tc, context, 'action', {'actions': [{'command': 'click_element'}]})
    screen = _Screen(showing={'with-todo', 'with-two-todos'})
    ex = _executor(screen, ctx)

    _goto(ex, 'with-two-todos')

    assert screen.probes() == [('with-todo', CAP)]


def test_forget_position_verification_tolerates_a_missing_context():
    nav_mod.forget_position_verification(None)
    ctx = {}
    nav_mod.forget_position_verification(ctx, 'test')
    assert ctx == {'last_verified_timestamp': 0, 'last_verified_node_id': None}


# --------------------------------------------------------------------------------------------
# 4. Where the probe runs: current first, then target, else clear
# --------------------------------------------------------------------------------------------

def test_current_not_showing_but_target_is_corrects_the_position(tree):
    """The tracking-bug case the probe exists for is still caught."""
    screen = _Screen(showing={'with-two-todos'})
    ex = _executor(screen, _at('with-todo'))

    result = _goto(ex, 'with-two-todos')

    assert screen.probes() == [('with-todo', CAP), ('with-two-todos', CAP)]
    assert result.get('position_tracking_bug_corrected') is True
    assert ex.edges_run == []
    ctx = ex.device.navigation_context
    assert ctx['current_node_id'] == 'with-two-todos'
    assert ctx['last_verified_node_id'] == 'with-two-todos'


def test_neither_showing_clears_the_position_instead_of_taking_its_edge(tree):
    """Before the fix: 'position tracking is correct, proceeding' and the edge ran from a
    screen the device was not on."""
    screen = _Screen(showing=set())
    ex = _executor(screen, _at('with-todo'))

    result = _goto(ex, 'with-two-todos')

    # current, then target — and the no-position flow reuses that target answer, no third check
    assert screen.probes() == [('with-todo', CAP), ('with-two-todos', CAP)]
    assert ex.edges_run == []                              # no path from entry in this stub tree
    assert result['success'] is False
    ctx = ex.device.navigation_context
    assert ctx['current_node_id'] is None
    assert ctx.get('last_verified_node_id') is None


def test_a_current_node_without_verifications_is_not_disproved(tree):
    """Nothing can disprove it: keep the old behaviour (take the edge from it)."""
    screen = _Screen(showing=set(), without_verifications={'with-todo'})
    ex = _executor(screen, _at('with-todo'))

    _goto(ex, 'with-two-todos')

    assert screen.probes() == [('with-todo', CAP), ('with-two-todos', CAP)]
    assert ex.edges_run == ['e-add-second']


def test_the_current_check_reports_its_own_duration(tree, capsys):
    screen = _Screen(showing={'with-todo'})
    ex = _executor(screen, _at('with-todo'))

    _goto(ex, 'with-two-todos')

    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith(MARKER)]
    current = [ln for ln in lines if ln.startswith(f'{MARKER} nav.probe_current_one_step_away ')]
    assert len(current) == 1, lines
    assert f'node=with-todo target=with-two-todos cap_ms={CAP} success=True legs=1/1' in current[0]
    assert not [ln for ln in lines if ln.startswith(f'{MARKER} nav.probe_target_one_step_away ')]
