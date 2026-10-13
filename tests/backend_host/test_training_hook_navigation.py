"""
tests/backend_host/test_training_hook_navigation.py — TASK-27 step 3c.

A node verification that passes during navigation is a free `screen-id` training
sample, and a `focus` sample when the focus detector finds a labelled box on the
same frame. The hook lives in `NavigationExecutor._record_training_samples`.

Pure: `record_sample`, `enabled` and `ImageHelpers._focus_signature` are
monkeypatched, the frame is a tiny JPEG written to tmp_path, and the hook's
thread runner is replaced by a synchronous one so nothing races.
"""
import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import cv2
import numpy as np
import pytest

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from shared.src.lib.ai import training_samples  # noqa: E402
from backend_host.src.controllers.verification.image_helpers import ImageHelpers  # noqa: E402
from backend_host.src.services.navigation import navigation_executor as nav_mod  # noqa: E402

NavigationExecutor = nav_mod.NavigationExecutor
_REAL_FAILED_HOOK = NavigationExecutor._record_failed_verification_sample


def _sync(fn):
    fn()


class _Graph:
    def __init__(self, nodes):
        self.nodes = nodes


@pytest.fixture
def frame(tmp_path):
    path = str(tmp_path / 'capture_1.jpg')
    cv2.imwrite(path, np.full((72, 128, 3), 40, np.uint8))
    return path


@pytest.fixture
def executor():
    ex = NavigationExecutor.__new__(NavigationExecutor)
    ex.device = SimpleNamespace(navigation_context={})
    ex.device_model = 'android_tv'
    ex.host_name, ex.device_id, ex.device_name = 'host-1', 'device1', 'tv'
    ex.unified_graph = _Graph({'n-home': {'label': 'home', 'tree_id': 'tree-sub'}})
    return ex


@pytest.fixture
def calls(monkeypatch):
    recorded = []
    monkeypatch.setattr(training_samples, 'enabled', lambda: True)
    monkeypatch.setattr(training_samples, 'record_sample',
                        lambda image, **kw: recorded.append((image, kw)) or 'sid')
    return recorded


def _focus(monkeypatch, result):
    seen = []

    def fake(self, img):
        seen.append(img.shape)
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(ImageHelpers, '_focus_signature', fake)
    return seen


def _verification(frame):
    return {'success': True, 'has_verifications': True,
            'results': [{'success': True, 'screenshot_path': frame}],
            'verification_screenshots': [frame]}


def _run(executor, verification, label='home'):
    executor._record_training_samples(verification, 'n-home', label, 'tree-root', 'team-1',
                                      'example_android_tv', runner=_sync)


def test_screen_id_sample_with_run_label(executor, calls, frame, monkeypatch):
    _focus(monkeypatch, {'kind': 'none'})
    _run(executor, _verification(frame))

    assert len(calls) == 1
    image, kw = calls[0]
    assert image == frame
    assert kw == {
        'family': 'screen-id',
        'ground_truth': {'node_id': 'n-home', 'label': 'home'},
        'team_id': 'team-1', 'device_model': 'android_tv',
        'userinterface': 'example_android_tv', 'node_id': 'n-home',
        'label_source': 'run',
        'source_ref': {'tree_id': 'tree-sub', 'node_id': 'n-home', 'edge_id': None},
    }


def test_label_falls_back_to_the_graph_when_navigating_by_id(executor, calls, frame, monkeypatch):
    _focus(monkeypatch, {'kind': 'none'})
    _run(executor, _verification(frame), label=None)
    assert calls[0][1]['ground_truth'] == {'node_id': 'n-home', 'label': 'home'}


def test_focus_box_with_label_adds_a_focus_sample(executor, calls, frame, monkeypatch):
    seen = _focus(monkeypatch, {'kind': 'box', 'x': 0.42, 'y': 0.61, 'label': 'settings'})
    _run(executor, _verification(frame))

    assert seen == [(72, 128, 3)]          # computed on the verified frame
    assert [kw['family'] for _img, kw in calls] == ['screen-id', 'focus']
    image, kw = calls[1]
    assert image == frame
    # OCR from the detector is a model answer, never run truth.
    assert kw['model_answer'] == {'focused': 'settings'}
    assert kw['ground_truth'] is None
    assert kw['label_source'] == 'none'
    assert kw['focus_label'] == 'settings'
    assert kw['boxes'] == {'focus': {'cx': 0.42, 'cy': 0.61}}
    assert kw['node_id'] == 'n-home' and kw['team_id'] == 'team-1'
    assert kw['device_model'] == 'android_tv' and kw['userinterface'] == 'example_android_tv'
    assert kw['source_ref'] == {'tree_id': 'tree-sub', 'node_id': 'n-home', 'edge_id': None}
    assert calls[0][1]['label_source'] == 'run'     # screen-id stays run truth


@pytest.mark.parametrize('signature', [
    {'kind': 'nav', 'x': 0.3, 'width': 0.1},
    {'kind': 'none'},
    {'kind': 'box', 'x': 0.5, 'y': 0.5, 'label': ''},
])
def test_no_focus_sample_for_nav_none_or_unlabelled_box(executor, calls, frame, monkeypatch, signature):
    _focus(monkeypatch, signature)
    _run(executor, _verification(frame))
    assert [kw['family'] for _img, kw in calls] == ['screen-id']


def test_disabled_does_nothing_not_even_the_focus_signature(executor, frame, monkeypatch):
    monkeypatch.setattr(training_samples, 'enabled', lambda: False)
    record = MagicMock()
    monkeypatch.setattr(training_samples, 'record_sample', record)
    seen = _focus(monkeypatch, {'kind': 'box', 'x': 0.5, 'y': 0.5, 'label': 'settings'})
    runner = MagicMock()

    executor._record_training_samples(_verification(frame), 'n-home', 'home', 'tree-root',
                                      'team-1', 'example_android_tv', runner=runner)

    runner.assert_not_called()
    record.assert_not_called()
    assert seen == []


def test_no_frame_no_sample(executor, calls, frame, monkeypatch):
    seen = _focus(monkeypatch, {'kind': 'box', 'x': 0.5, 'y': 0.5, 'label': 'settings'})
    _run(executor, {'success': True, 'results': [{'success': True, 'screenshot_path': ''}],
                    'verification_screenshots': ['']})
    assert calls == [] and seen == []


def test_frame_prefers_a_passing_leg(frame):
    result = {'results': [{'success': False, 'screenshot_path': '/tmp/fail.jpg'},
                          {'success': True, 'screenshot_path': frame}],
              'verification_screenshots': ['/tmp/fail.jpg', frame]}
    assert NavigationExecutor._verified_frame_path(result) == frame


@pytest.mark.parametrize('where', ['record', 'focus', 'enabled', 'runner'])
def test_errors_never_escape(executor, frame, monkeypatch, where):
    monkeypatch.setattr(training_samples, 'enabled', lambda: True)
    monkeypatch.setattr(training_samples, 'record_sample', lambda *a, **k: 'sid')
    _focus(monkeypatch, {'kind': 'box', 'x': 0.5, 'y': 0.5, 'label': 'settings'})
    runner = _sync
    if where == 'record':
        def boom(*a, **k):
            raise RuntimeError('minio down')
        monkeypatch.setattr(training_samples, 'record_sample', boom)
    elif where == 'focus':
        _focus(monkeypatch, RuntimeError('tesseract missing'))
    elif where == 'enabled':
        def boom():
            raise RuntimeError('env')
        monkeypatch.setattr(training_samples, 'enabled', boom)
    else:
        def runner(fn):
            raise RuntimeError('cannot start thread')

    executor._record_training_samples(_verification(frame), 'n-home', 'home', 'tree-root',
                                      'team-1', 'example_android_tv', runner=runner)


def test_default_runner_is_a_daemon_thread(monkeypatch):
    started = []

    class FakeThread:
        def __init__(self, target, name, daemon):
            started.append(daemon)

        def start(self):
            pass
    monkeypatch.setattr(nav_mod.threading, 'Thread', FakeThread)
    NavigationExecutor._start_training_thread(lambda: None)
    assert started == [True]


def test_goto_already_at_target_records_once_and_a_failing_hook_does_not_fail_it(
        executor, frame, monkeypatch):
    """Through execute_navigation: the 'already at target' success branch records one
    screen-id sample for the verified node, and an upload that blows up changes nothing."""
    verification = _verification(frame)
    executor.device = SimpleNamespace(
        navigation_context={'current_node_id': 'n-home', 'current_node_label': 'home',
                            'position_timestamp': 10 ** 12},
        verification_executor=SimpleNamespace(verify_node=AsyncMock(return_value=verification)),
    )
    monkeypatch.setattr(executor, '_sync_unified_graph', lambda *a, **k: executor.unified_graph)
    monkeypatch.setattr(executor, 'update_current_position', lambda *a, **k: {'success': True})
    monkeypatch.setattr('shared.src.lib.utils.navigation_cache.get_cached_unified_graph',
                        lambda *a, **k: None)
    monkeypatch.setattr(NavigationExecutor, '_start_training_thread', staticmethod(_sync))
    monkeypatch.setattr(training_samples, 'enabled', lambda: True)
    families = []

    def boom(image, **kw):
        families.append(kw['family'])
        raise RuntimeError('minio down')
    monkeypatch.setattr(training_samples, 'record_sample', boom)
    _focus(monkeypatch, {'kind': 'box', 'x': 0.5, 'y': 0.5, 'label': 'settings'})

    result = asyncio.run(executor.execute_navigation(
        tree_id='tree-root', userinterface_name='example_android_tv',
        target_node_id='n-home', team_id='team-1'))

    assert result['success'] is True and result.get('already_at_target') is True
    assert families == ['screen-id']


# ─── Call sites inside execute_navigation ─────────────────────────────────────

def _nav_device(executor, monkeypatch, verify_node, nav_context=None):
    executor.device = SimpleNamespace(
        navigation_context=nav_context if nav_context is not None else {
            'current_node_id': None, 'current_node_label': None, 'current_tree_id': None},
        verification_executor=SimpleNamespace(verify_node=verify_node),
        action_executor=SimpleNamespace(),
    )
    monkeypatch.setattr(executor, '_sync_unified_graph', lambda *a, **k: executor.unified_graph)
    monkeypatch.setattr(executor, 'update_current_position', lambda *a, **k: {'success': True})
    monkeypatch.setattr(executor, '_record_step_execution_results', lambda **k: 'exec-1')
    monkeypatch.setattr(executor, '_resolve_kpi_references', lambda step: None)
    monkeypatch.setattr('shared.src.lib.utils.navigation_cache.get_cached_unified_graph',
                        lambda *a, **k: None)
    hook = []
    monkeypatch.setattr(NavigationExecutor, '_record_training_samples',
                        lambda self, *a, **k: hook.append((a, k)))
    failed = []
    monkeypatch.setattr(NavigationExecutor, '_record_failed_verification_sample',
                        lambda self, *a, **k: failed.append((a, k)))
    executor._failed_hook = failed
    return hook


_STEP = {'transition_number': 1, 'step_number': 1, 'from_node_id': 'n-home',
         'to_node_id': 'n-settings', 'from_node_label': 'home', 'to_node_label': 'settings',
         'actions': [], 'verifications': [{'verification_type': 'image', 'command': 'x'}],
         'edge_id': 'edge-7', 'action_set_id': 'as-1', 'final_wait_time': 0}


def _goto_path(executor):
    return asyncio.run(executor.execute_navigation(
        tree_id='tree-root', userinterface_name='example_android_tv',
        navigation_path=[dict(_STEP)], team_id='team-1', verification_mode='each'))


def test_per_step_verified_destination_records_once_with_the_edge(executor, frame, monkeypatch):
    verification = _verification(frame)
    hook = _nav_device(executor, monkeypatch, AsyncMock(return_value=verification))

    result = _goto_path(executor)

    assert result['success'] is True
    assert hook == [((verification, 'n-settings', 'settings', 'tree-root', 'team-1',
                      'example_android_tv'), {'edge_id': 'edge-7'})]


def test_per_step_failed_verification_records_one_failure_sample(executor, frame, monkeypatch):
    failed = {'success': False, 'has_verifications': True, 'error': 'not on screen',
              'results': [{'success': False, 'screenshot_path': frame}]}
    hook = _nav_device(executor, monkeypatch, AsyncMock(return_value=failed))

    result = _goto_path(executor)

    assert result['success'] is False          # navigation still fails
    assert hook == []                          # no success sample
    assert executor._failed_hook == [((failed, 'n-settings', 'settings', 'tree-root', 'team-1',
                                       'example_android_tv'), {'edge_id': 'edge-7'})]


def test_per_step_success_records_no_failure_sample(executor, frame, monkeypatch):
    _nav_device(executor, monkeypatch, AsyncMock(return_value=_verification(frame)))
    assert _goto_path(executor)['success'] is True
    assert executor._failed_hook == []


def test_per_step_without_verifications_records_nothing(executor, monkeypatch):
    verify = AsyncMock()
    hook = _nav_device(executor, monkeypatch, verify)
    step = dict(_STEP, verifications=[])

    result = asyncio.run(executor.execute_navigation(
        tree_id='tree-root', userinterface_name='example_android_tv',
        navigation_path=[step], team_id='team-1', verification_mode='each'))

    assert result['success'] is True
    verify.assert_not_called()
    assert hook == [] and executor._failed_hook == []


def test_home_probe_success_records_home(executor, frame, monkeypatch):
    """No position, target not on screen, home is: home gets one sample (no edge)."""
    target_fail = {'success': False, 'has_verifications': True, 'results': []}
    home_ok = _verification(frame)

    async def verify_node(node_id, **kw):
        return home_ok if node_id == 'n-home' else target_fail
    hook = _nav_device(executor, monkeypatch, verify_node)
    monkeypatch.setattr(executor, 'get_node_id',
                        lambda label, *a, **k: 'n-home' if label == 'home' else (_ for _ in ()).throw(ValueError()))
    monkeypatch.setattr(nav_mod, 'find_shortest_path', lambda *a, **k: [])   # stop after the probes

    asyncio.run(executor.execute_navigation(
        tree_id='tree-root', userinterface_name='example_android_tv',
        target_node_id='n-settings', team_id='team-1'))

    assert hook == [((home_ok, 'n-home', 'home', 'tree-root', 'team-1', 'example_android_tv'), {})]
    # the no-position target probe failed first: a probe, so no failure sample
    assert executor._failed_hook == []


def test_no_position_and_home_probe_failures_record_nothing(executor, monkeypatch):
    failed = {'success': False, 'has_verifications': True, 'results': []}
    hook = _nav_device(executor, monkeypatch, AsyncMock(return_value=failed))
    monkeypatch.setattr(executor, 'get_node_id',
                        lambda label, *a, **k: 'n-home' if label == 'home' else (_ for _ in ()).throw(ValueError()))
    monkeypatch.setattr(nav_mod, 'find_shortest_path', lambda *a, **k: [])

    asyncio.run(executor.execute_navigation(
        tree_id='tree-root', userinterface_name='example_android_tv',
        target_node_id='n-settings', team_id='team-1'))

    assert hook == []
    assert executor._failed_hook == []       # probes fail routinely off-screen: noise


def test_one_step_probe_failure_records_nothing(executor, monkeypatch):
    """Position says n-home, target n-settings is one edge away: the probe fails because
    the device is (correctly) still on n-home. No failure sample."""
    failed = {'success': False, 'has_verifications': True,
              'results': [{'success': False, 'screenshot_path': '/tmp/f.jpg'}]}
    hook = _nav_device(executor, monkeypatch, AsyncMock(return_value=failed),
                       nav_context={'current_node_id': 'n-home', 'current_node_label': 'home',
                                    'current_tree_id': 'tree-root', 'position_timestamp': 10 ** 12})

    class _OneStep:
        nodes = {'n-home': {}, 'n-settings': {}}

        def has_edge(self, a, b):
            return (a, b) == ('n-home', 'n-settings')
    monkeypatch.setattr('shared.src.lib.utils.navigation_cache.get_cached_unified_graph',
                        lambda *a, **k: _OneStep())
    monkeypatch.setattr(nav_mod, 'find_shortest_path', lambda *a, **k: [])

    asyncio.run(executor.execute_navigation(
        tree_id='tree-root', userinterface_name='example_android_tv',
        target_node_id='n-settings', team_id='team-1'))

    executor.device.verification_executor.verify_node.assert_awaited()
    assert hook == [] and executor._failed_hook == []


def test_conditional_divergence_records_nothing(executor, frame, monkeypatch):
    """A conditional edge landing on a valid sibling is an expected divergence, not a
    wrong screen: no failure sample."""
    failed = {'success': False, 'has_verifications': True, 'error': 'sibling',
              'results': [{'success': False, 'screenshot_path': frame}]}
    hook = _nav_device(executor, monkeypatch, AsyncMock(return_value=failed))
    step = dict(_STEP, is_conditional=True)

    asyncio.run(executor.execute_navigation(
        tree_id='tree-root', userinterface_name='example_android_tv',
        navigation_path=[step], team_id='team-1', verification_mode='each'))

    assert hook == [] and executor._failed_hook == []


def test_already_at_target_failed_check_records_failure_and_navigation_is_unchanged(
        executor, frame, monkeypatch):
    failed = {'success': False, 'has_verifications': True,
              'results': [{'success': False, 'screenshot_path': frame}]}
    hook = _nav_device(executor, monkeypatch, AsyncMock(return_value=failed),
                       nav_context={'current_node_id': 'n-home', 'current_node_label': 'home',
                                    'current_tree_id': 'tree-root', 'position_timestamp': 10 ** 12})
    monkeypatch.setattr(nav_mod, 'find_shortest_path', lambda *a, **k: [])

    result = asyncio.run(executor.execute_navigation(
        tree_id='tree-root', userinterface_name='example_android_tv',
        target_node_id='n-home', team_id='team-1'))

    assert not result.get('already_at_target')
    assert hook == []
    assert executor._failed_hook == [((failed, 'n-home', 'home', 'tree-root', 'team-1',
                                       'example_android_tv'), {})]


# ─── Step 4d: the failed-verification hook itself ─────────────────────────────

def _failed_verification(frame):
    return {'success': False, 'has_verifications': True,
            'results': [{'success': True, 'screenshot_path': '/tmp/ok-leg.jpg'},
                        {'success': False, 'screenshot_path': frame}],
            'verification_screenshots': ['/tmp/ok-leg.jpg', frame]}


def _run_failed(executor, verification, label='home', edge_id=None, runner=_sync):
    executor._record_failed_verification_sample(verification, 'n-home', label, 'tree-root', 'team-1',
                                                'example_android_tv', edge_id=edge_id, runner=runner)


def test_failed_verification_records_once_with_no_label(executor, calls, frame, monkeypatch):
    seen = _focus(monkeypatch, {'kind': 'box', 'x': 0.5, 'y': 0.5, 'label': 'settings'})
    _run_failed(executor, _failed_verification(frame), edge_id='edge-7')

    assert seen == []                     # no focus sample on a failed frame
    assert len(calls) == 1
    image, kw = calls[0]
    assert image == frame                 # the failed leg's frame, not the passing one
    assert kw == {
        'family': 'screen-id', 'team_id': 'team-1', 'device_model': 'android_tv',
        'userinterface': 'example_android_tv', 'node_id': None,
        # step 4k: this bare fake graph (nodes only) has no groups, so expected_group is None
        'model_answer': {'expected_node_id': 'n-home', 'expected_label': 'home', 'expected_group': None,
                         'verified': False},
        'ground_truth': None, 'label_source': 'none',
        'source_ref': {'tree_id': 'tree-sub', 'node_id': 'n-home', 'edge_id': 'edge-7'},
        'force': False, 'skip_cap': True,
    }


def test_failed_verification_label_falls_back_to_the_graph(executor, calls, frame):
    _run_failed(executor, _failed_verification(frame), label=None)
    assert calls[0][1]['model_answer']['expected_label'] == 'home'


def test_failed_verification_without_a_failed_frame_is_skipped(executor, calls):
    _run_failed(executor, {'success': False, 'has_verifications': True,
                           'results': [{'success': False, 'screenshot_path': ''}],
                           'verification_screenshots': ['/tmp/other.jpg']})
    assert calls == []


def test_failed_verification_without_verifications_is_skipped(executor, calls, frame):
    runner = MagicMock()
    _run_failed(executor, {'success': False, 'has_verifications': False,
                           'results': [{'success': False, 'screenshot_path': frame}]}, runner=runner)
    runner.assert_not_called()
    assert calls == []


def test_failed_verification_disabled_starts_nothing(executor, frame, monkeypatch):
    monkeypatch.setattr(training_samples, 'enabled', lambda: False)
    record = MagicMock()
    monkeypatch.setattr(training_samples, 'record_sample', record)
    runner = MagicMock()
    _run_failed(executor, _failed_verification(frame), runner=runner)
    runner.assert_not_called()
    record.assert_not_called()


@pytest.mark.parametrize('where', ['record', 'enabled', 'runner'])
def test_failed_verification_errors_never_escape(executor, frame, monkeypatch, where):
    monkeypatch.setattr(training_samples, 'enabled', lambda: True)
    monkeypatch.setattr(training_samples, 'record_sample', lambda *a, **k: 'sid')
    runner = _sync

    def boom(*a, **k):
        raise RuntimeError('boom')
    if where == 'record':
        monkeypatch.setattr(training_samples, 'record_sample', boom)
    elif where == 'enabled':
        monkeypatch.setattr(training_samples, 'enabled', boom)
    else:
        runner = boom
    _run_failed(executor, _failed_verification(frame), runner=runner)


def test_per_step_failure_hook_blowing_up_leaves_the_result_unchanged(executor, frame, monkeypatch):
    """Real hook, real (sync) runner, record_sample raising: navigation fails exactly as before."""
    failed = {'success': False, 'has_verifications': True, 'error': 'not on screen',
              'results': [{'success': False, 'screenshot_path': frame}]}
    _nav_device(executor, monkeypatch, AsyncMock(return_value=failed))
    monkeypatch.setattr(NavigationExecutor, '_record_failed_verification_sample', _REAL_FAILED_HOOK)
    monkeypatch.setattr(NavigationExecutor, '_start_training_thread', staticmethod(_sync))
    monkeypatch.setattr(training_samples, 'enabled', lambda: True)
    tried = []

    def boom(image, **kw):
        tried.append(kw['family'])
        raise RuntimeError('minio down')
    monkeypatch.setattr(training_samples, 'record_sample', boom)

    result = _goto_path(executor)

    assert result['success'] is False
    assert tried == ['screen-id']


# ─── Step 4k: the screen-id label is the screen group ─────────────────────────

def _stb_graph():
    """A real unified-graph shape: Home and two tabs chained by RIGHT, OK into Apps."""
    import networkx as nx
    g = nx.DiGraph()
    for nid, label in (('n-home', 'home'), ('n-tvguide', 'home_tvguide'), ('n-apps', 'home_apps'),
                       ('n-store', 'apps')):
        g.add_node(nid, label=label, node_type='screen', verifications=[], tree_id='tree-sub')
    g.add_node('entry-node', label='ENTRY', node_type='entry', verifications=[])

    def add(src, tgt, key, **extra):
        g.add_edge(src, tgt, action_sets=[{'id': f'{src}-{tgt}',
                                           'actions': [{'command': 'press_key', 'params': {'key': key}}]}],
                   default_action_set_id=f'{src}-{tgt}', **extra)
    add('entry-node', 'n-home', 'HOME')
    add('n-home', 'n-tvguide', 'RIGHT')
    add('n-tvguide', 'n-apps', 'RIGHT')
    add('n-apps', 'n-store', 'OK')
    add('n-store', 'n-apps', 'BACK', is_reverse_edge=True)
    return g


def test_screen_id_label_is_the_group_and_the_row_keeps_its_node(executor, calls, frame, monkeypatch):
    _focus(monkeypatch, {'kind': 'none'})
    executor.unified_graph = _stb_graph()
    executor._record_training_samples(_verification(frame), 'n-apps', 'home_apps', 'tree-root', 'team-1',
                                      'stb_tv', runner=_sync)
    kw = calls[0][1]
    assert kw['ground_truth'] == {'node_id': 'n-home', 'label': 'home', 'node': 'n-apps',
                                  'node_label': 'home_apps', 'focus': 'apps'}
    assert kw['node_id'] == 'n-apps'           # the stable key stays the original node


def test_the_group_node_itself_has_no_focus(executor, calls, frame, monkeypatch):
    _focus(monkeypatch, {'kind': 'none'})
    executor.unified_graph = _stb_graph()
    executor._record_training_samples(_verification(frame), 'n-store', 'apps', 'tree-root', 'team-1',
                                      'stb_tv', runner=_sync)
    assert calls[0][1]['ground_truth'] == {'node_id': 'n-store', 'label': 'apps', 'node': 'n-store',
                                           'node_label': 'apps', 'focus': None}


def test_no_graph_keeps_the_per_node_label(executor, calls, frame, monkeypatch):
    _focus(monkeypatch, {'kind': 'none'})
    executor.unified_graph = None
    _run(executor, _verification(frame))
    assert calls[0][1]['ground_truth'] == {'node_id': 'n-home', 'label': 'home'}


def test_failed_verification_stores_the_expected_group(executor, calls, frame):
    executor.unified_graph = _stb_graph()
    executor._record_failed_verification_sample(_failed_verification(frame), 'n-tvguide', 'home_tvguide',
                                                'tree-root', 'team-1', 'stb_tv', runner=_sync)
    assert calls[0][1]['model_answer'] == {'expected_node_id': 'n-tvguide', 'expected_label': 'home_tvguide',
                                           'expected_group': 'home', 'verified': False}


def test_grouping_error_never_escapes(executor, calls, frame, monkeypatch):
    from shared.src.lib.ai import screen_groups

    def boom(graph):
        raise RuntimeError('boom')
    _focus(monkeypatch, {'kind': 'none'})
    executor.unified_graph = _stb_graph()
    monkeypatch.setattr(screen_groups, 'from_graph', boom)
    executor._record_training_samples(_verification(frame), 'n-apps', 'home_apps', 'tree-root', 'team-1',
                                      'stb_tv', runner=_sync)
    assert calls[0][1]['ground_truth'] == {'node_id': 'n-apps', 'label': 'home_apps'}


def _stb_apps_graph():
    """The live stb_tv Apps shape: home_apps -OK-> apps, apps -> apps_netflix is DOWN, HOME,
    DOWN (both ways), and the tiles are chained by RIGHT."""
    import networkx as nx
    g = nx.DiGraph()
    g.add_node('entry-node', label='ENTRY', node_type='entry', verifications=[])
    for nid in ('home', 'home_apps', 'apps', 'apps_netflix', 'apps_disney', 'netflix_home'):
        g.add_node(nid, label=nid, node_type='screen', verifications=[], tree_id='t')

    def add(src, tgt, keys, **extra):
        g.add_edge(src, tgt, action_sets=[{'id': f'{src}-{tgt}', 'actions': [
            {'command': 'press_key', 'params': {'key': k}} for k in keys]}],
            default_action_set_id=f'{src}-{tgt}', **extra)
    add('entry-node', 'home', ['BACK', 'TVGUIDE', 'TVGUIDE', 'HOME'])
    add('home', 'home_apps', ['RIGHT'])
    add('home_apps', 'apps', ['OK'])
    add('apps', 'apps_netflix', ['DOWN', 'HOME', 'DOWN'])
    add('apps_netflix', 'apps', ['DOWN', 'HOME', 'DOWN'], is_reverse_edge=True)
    add('apps_netflix', 'apps_disney', ['RIGHT'])
    add('apps_netflix', 'netflix_home', ['OK'])
    add('netflix_home', 'apps_netflix', ['HOME'], is_reverse_edge=True)
    return g


def test_hook_applies_the_core_override_apps_tiles_are_apps(executor, calls, frame, monkeypatch):
    _focus(monkeypatch, {'kind': 'none'})
    executor.unified_graph = _stb_apps_graph()
    executor._record_training_samples(_verification(frame), 'apps_disney', 'apps_disney', 'tree-root', 'team-1',
                                      'stb_tv', runner=_sync)
    assert calls[0][1]['ground_truth'] == {'node_id': 'apps', 'label': 'apps', 'node': 'apps_disney',
                                           'node_label': 'apps_disney', 'focus': 'disney'}


def test_without_the_override_the_tiles_stay_apart(executor, calls, frame, monkeypatch):
    """Another userinterface (no override): DOWN, HOME, DOWN does not join apps."""
    _focus(monkeypatch, {'kind': 'none'})
    executor.unified_graph = _stb_apps_graph()
    executor._record_training_samples(_verification(frame), 'apps_disney', 'apps_disney', 'tree-root', 'team-1',
                                      'other_ui', runner=_sync)
    assert calls[0][1]['ground_truth']['label'] == 'apps_netflix'   # the tiles alone, not apps
