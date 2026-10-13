"""Explore -> testcase keeps every step (regression guard, 2026-10-04).

"Live: zap 3 times" on stb3 passed in Explore (home, live, live_chup x3, verify_node(live)
after each zap) and was saved as home, live, live_chup once: repeated navigations were
collapsed, and the AI builder then filled in the missing zaps with CHANNEL_UP presses,
DetectZapping without a key timestamp and a play-icon wait the box never shows.
"""
import importlib

import pytest

routes = importlib.import_module("features.ai-test.backend_server.server_testprompt_routes")  # noqa: E402

pytestmark = pytest.mark.unit

LIVE_CHECKS = {'live': ([{'command': 'waitForImageToDisappear', 'params': {'image_path': 'blackscreen'},
                          'verification_type': 'image'}], 'all')}


def _nav(label):
    return {'tool': 'navigate_to_node', 'params': {'target_node_label': label}}


def _steps(graph):
    return routes._graph_step_lines(graph)


def test_repeated_action_node_navigations_are_all_kept():
    trace = [_nav('home'), _nav('live'), _nav('live_chup'), _nav('live_chup'), _nav('live_chup')]
    assert _steps(routes._trace_to_graph(trace)) == [
        'Navigate to: home', 'Navigate to: live',
        'Navigate to: live_chup', 'Navigate to: live_chup', 'Navigate to: live_chup']


def test_verify_node_becomes_the_screens_saved_checks():
    trace = [_nav('live'), _nav('live_chup'), {'tool': 'verify_node', 'params': {'node_label': 'live'}}]
    graph = routes._trace_to_graph(trace, LIVE_CHECKS)
    block = next(n for n in graph['nodes'] if n['type'] == 'verification')
    assert block['data']['verifications'] == LIVE_CHECKS['live'][0]
    assert block['data']['verification_pass_condition'] == 'all'
    assert _steps(graph)[-1] == 'Verify: live (its saved checks)'


def test_verify_node_without_saved_checks_is_dropped():
    trace = [_nav('live'), {'tool': 'verify_node', 'params': {'node_label': 'unknown'}}]
    assert _steps(routes._trace_to_graph(trace, LIVE_CHECKS)) == ['Navigate to: live']


@pytest.mark.parametrize('trace', [
    [_nav('home'), _nav('live')],
    [_nav('home'), {'tool': 'verify_node', 'params': {'node_label': 'live'}}],
])
def test_graph_is_one_linear_success_chain(trace):
    graph = routes._trace_to_graph(trace, LIVE_CHECKS)
    chain = ['start'] + [n['id'] for n in graph['nodes'] if n['type'] not in ('start', 'success', 'failure')] + ['success']
    assert [(e['source'], e['target']) for e in graph['edges']] == list(zip(chain, chain[1:]))
