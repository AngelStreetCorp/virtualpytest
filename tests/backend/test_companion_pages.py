"""Atlas Companion catalogue (TASK-126 G1): paths are real routes, params are really read by the page."""
import re
from pathlib import Path

import pytest

from backend_server.src.agent.tools import page_interaction as pi

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'frontend' / 'src'
ROUTES = set(re.findall(r'<Route\s+path="([^"]+)"', (SRC / 'App.tsx').read_text()))
ROUTES |= set(re.findall(r'^\s+path="([^"]+)"', (SRC / 'App.tsx').read_text(), re.M))


def _route(path: str) -> str:
    return re.sub(r'\{(\w+)\}', r':\1', path)


@pytest.mark.parametrize('key', list(pi.COMPANION_PAGES))
def test_path_is_an_app_route(key):
    assert _route(pi.COMPANION_PAGES[key]['path']) in ROUTES


@pytest.mark.parametrize('key', list(pi.COMPANION_PAGES))
def test_params_are_read_by_the_page(key):
    entry = pi.COMPANION_PAGES[key]
    if not entry['params']:
        return
    text = (SRC / entry['file']).read_text()
    for param in entry['params']:
        assert re.search(r"""\.get\(\s*['"]%s['"]\s*\)""" % re.escape(param), text), \
            f"{entry['file']} does not read ?{param}="


def test_navigation_aliases_point_at_known_pages():
    for alias, path in pi.NAVIGATION_ALIASES.items():
        assert path in pi.PAGE_SCHEMAS, alias
        assert path in ROUTES, path
    for path in pi.PAGE_SCHEMAS:
        assert path in ROUTES, path


def test_show_page_validates_and_targets_one_session(monkeypatch):
    sent = []
    monkeypatch.setattr(pi.socket_manager, 'socketio', object())
    monkeypatch.setattr(pi.socket_manager, 'emit_to_room',
                        lambda room, ev, data, namespace='/agent': sent.append((room, ev, data)))
    assert 'no param' in pi.show_page('test_reports', {'nope': '1'}, session_id='s1')
    assert 'takes passed, failed' in pi.show_page('test_reports', {'status': 'x'}, session_id='s1')
    assert 'Unknown page' in pi.show_page('nope', session_id='s1')
    assert 'needs path_args' in pi.show_page('run_summary', session_id='s1')
    assert not sent
    pi.show_page('test_reports', {'host': 'h', 'status': 'failed'}, session_id='s1')
    pi.show_page('run_summary', path_args={'kind': 'script', 'id': '7'}, open_now=True, session_id='s1')
    assert [s[0] for s in sent] == ['s1', 's1']
    assert sent[0][2]['action'] == 'companion_offer'
    assert sent[1][2]['action'] == 'companion_open' and sent[1][2]['payload']['path'] == '/test-results/runs/script/7'
    assert 'No chat session' in pi.show_page('dashboard')


KNOWN = {
    'host': ['host-clone-1', 'vpt-pi4'],
    'device': {'vpt-pi4': ['web_tv', 'device1'], 'host-clone-1': ['phone1']},
    'script': ['test_scripts/goto_live.py'],
}


def _show(monkeypatch, page, params=None, **kw):
    sent = []
    monkeypatch.setattr(pi.socket_manager, 'socketio', object())
    monkeypatch.setattr(pi.socket_manager, 'emit_to_room',
                        lambda room, ev, data, namespace='/agent': sent.append(data))
    out = pi.show_page(page, params, session_id='s1', known=KNOWN, **kw)
    return out, sent


def test_inexact_host_is_refused_with_closest_matches(monkeypatch):
    out, sent = _show(monkeypatch, 'test_reports', {'host': 'pi4'})
    assert out.startswith('❌') and "host 'pi4'" in out and 'vpt-pi4' in out and not sent


def test_exact_host_and_device_pass(monkeypatch):
    out, sent = _show(monkeypatch, 'test_reports', {'host': 'vpt-pi4', 'device': 'web_tv'})
    assert out.startswith('✅') and sent[0]['payload']['params'] == {'host': 'vpt-pi4', 'device': 'web_tv'}


def test_device_must_belong_to_the_host(monkeypatch):
    out, sent = _show(monkeypatch, 'test_reports', {'host': 'host-clone-1', 'device': 'web_tv'})
    assert out.startswith('❌') and "device 'web_tv'" in out and 'phone1' in out and not sent


def test_unknown_script_is_refused_with_closest(monkeypatch):
    out, sent = _show(monkeypatch, 'test_reports', {'script': 'goto_live'})
    assert out.startswith('❌') and 'test_scripts/goto_live.py' in out and not sent


def test_no_known_hosts_refuses_every_guess(monkeypatch):
    sent = []
    monkeypatch.setattr(pi.socket_manager, 'socketio', object())
    monkeypatch.setattr(pi.socket_manager, 'emit_to_room', lambda *a, **k: sent.append(a))
    out = pi.show_page('incidents', {'host': 'x'}, session_id='s1', known={'host': [], 'device': {}})
    assert out.startswith('❌') and not sent


def test_run_summary_needs_a_real_run_id(monkeypatch):
    bad, sent = _show(monkeypatch, 'run_summary', path_args={'kind': 'script', 'id': 'nope'},
                      run_exists=lambda k, i: False)
    assert bad.startswith('❌') and 'get_execution_results' in bad and not sent
    nokind, _ = _show(monkeypatch, 'run_summary', path_args={'kind': 'x', 'id': '1'}, run_exists=lambda k, i: True)
    assert nokind.startswith('❌')
    ok, sent = _show(monkeypatch, 'run_summary', path_args={'kind': 'script', 'id': '7'}, run_exists=lambda k, i: True)
    assert ok.startswith('✅') and sent[0]['payload']['path'] == '/test-results/runs/script/7'


def test_answers_route_each_question_to_one_page():
    a = {k: e['answers'].lower() for k, e in pi.COMPANION_PAGES.items()}
    assert 'why' in a['run_summary'] and 'not for why' in a['test_reports']
    assert 'not covered' in a['coverage'] and 'not coverage gaps' in a['requirements']


def _bridge(monkeypatch, calls):
    from types import SimpleNamespace
    from backend_server.src.agent.core import tool_bridge as tb
    sent = []
    monkeypatch.setattr(pi.socket_manager, 'socketio', object())
    monkeypatch.setattr(pi.socket_manager, 'emit_to_room',
                        lambda room, ev, data, namespace='/agent': sent.append((room, data)))
    session = SimpleNamespace(id='s9', context={'_turn_tools': calls, 'team_id': 't'}, messages=[])
    bridge = object.__new__(tb.ToolBridge)
    bridge.session = session
    bridge.logger = __import__('logging').getLogger('t')
    monkeypatch.setattr(bridge, '_companion_known', lambda: KNOWN, raising=False)
    return bridge, sent


def test_turn_end_offers_the_page_of_the_data_tool(monkeypatch):
    bridge, sent = _bridge(monkeypatch, [('get_execution_results',
                                          {'host_name': 'vpt-pi4', 'device_name': 'web_tv', 'success': False, 'limit': 5})])
    assert bridge.companion_fallback().startswith('✅')
    room, data = sent[0]
    assert room == 's9' and data['action'] == 'companion_offer' and data['payload']['page'] == 'test_reports'
    assert data['payload']['params'] == {'host': 'vpt-pi4', 'device': 'web_tv', 'status': 'failed'}


def test_turn_end_sends_nothing_when_show_page_was_called_or_args_do_not_validate(monkeypatch):
    bridge, sent = _bridge(monkeypatch, [('get_execution_results', {}), ('show_page', {})])
    assert bridge.companion_fallback() is None and not sent
    bridge, sent = _bridge(monkeypatch, [('get_execution_results', {'host_name': 'pi4'})])
    assert bridge.companion_fallback() is None and not sent
    bridge, sent = _bridge(monkeypatch, [('list_hosts', {}), ('get_weather', {})])
    assert bridge.companion_fallback() is None and not sent


def test_turn_end_offers_the_run_summary_for_a_single_run(monkeypatch):
    bridge, sent = _bridge(monkeypatch, [('get_execution_results', {'limit': 1, 'success': False, '_ids': ['r1']})])
    monkeypatch.setattr(bridge, '_companion_run_exists', lambda kind, rid: rid == 'r1', raising=False)
    assert bridge.companion_fallback().startswith('✅')
    assert sent[0][1]['payload']['path'] == '/test-results/runs/script/r1'


def test_show_page_retries_send_only_the_last_valid_offer_at_turn_end(monkeypatch):
    bridge, sent = _bridge(monkeypatch, [('show_page', {})])
    offers = bridge.session.context.setdefault('_turn_offers', [])
    for params in ({'host': 'pi4'}, {'host': 'vpt-pi4'}, {'host': 'vpt-pi4', 'device': 'web_tv'}):
        pi.show_page('test_reports', params, session_id='s9', known=KNOWN, defer=offers)
    assert not sent and len(offers) == 2          # the refused one never gets collected
    assert bridge.companion_fallback() == 'sent'
    assert len(sent) == 1 and sent[0][1]['payload']['params'] == {'host': 'vpt-pi4', 'device': 'web_tv'}
    assert bridge.companion_fallback() is None    # nothing left to send


def test_turn_end_offers_the_live_page_of_a_started_script(monkeypatch):
    bridge, sent = _bridge(monkeypatch, [('execute_script', {'script_name': 'goto_live', '_task': 'task-42'})])
    assert bridge.companion_fallback().startswith('✅')
    assert sent[0][1]['payload']['path'] == '/test-results/live/task-42'


def test_companion_echo_is_stripped_from_answers():
    _COMPANION_ECHO = pi.COMPANION_ECHO
    text = "Done. Connected to host-clone-1.\nCompanion: test_reports — host_name=host-clone-1"
    assert _COMPANION_ECHO.sub('', text).rstrip() == "Done. Connected to host-clone-1."


def test_companion_echo_keeps_real_text():
    text = "The TV companion: a small box.\nCompanion: x"
    assert pi.COMPANION_ECHO.sub('', text).rstrip() == "The TV companion: a small box."


def test_show_page_path_args_are_restricted(monkeypatch):
    monkeypatch.setattr(pi.socket_manager, 'socketio', object(), raising=False)
    out = pi.show_page('run_live', path_args={'taskId': '../x?y'}, defer=[])
    assert out.startswith('❌')


def _followup(monkeypatch, text, shown='Test Reports — host=vpt-pi4, device=web_tv', calls=()):
    bridge, sent = _bridge(monkeypatch, list(calls))
    bridge.session.context['companion'] = shown
    bridge.session.messages = [{'role': 'user', 'content': text}]
    return bridge, sent


def test_followup_only_failed_offers_the_shown_page_with_status(monkeypatch):
    bridge, sent = _followup(monkeypatch, 'only failed')
    assert bridge.companion_fallback().startswith('✅')
    p = sent[0][1]['payload']
    assert p['page'] == 'test_reports'
    assert p['params'] == {'host': 'vpt-pi4', 'device': 'web_tv', 'status': 'failed'}


def test_followup_this_month_sets_range_30d(monkeypatch):
    bridge, sent = _followup(monkeypatch, 'and this month?', calls=[('list_hosts', {})])
    bridge.companion_fallback()
    assert sent[0][1]['payload']['params']['range'] == '30d'


def test_followup_same_for_another_known_host(monkeypatch):
    bridge, sent = _followup(monkeypatch, 'same for host-clone-1?')
    bridge.companion_fallback()
    assert sent[0][1]['payload']['params'] == {'host': 'host-clone-1'}


def test_followup_without_filter_words_offers_nothing(monkeypatch):
    bridge, sent = _followup(monkeypatch, "what's in there?")
    assert bridge.companion_fallback() is None and not sent


def test_followup_skipped_when_a_data_tool_ran_or_nothing_is_shown(monkeypatch):
    bridge, sent = _followup(monkeypatch, 'only failed', calls=[('get_weather', {})])
    assert bridge.companion_fallback() is None and not sent
    bridge, sent = _followup(monkeypatch, 'only failed', shown='')
    assert bridge.companion_fallback() is None and not sent
