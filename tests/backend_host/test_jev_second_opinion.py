"""Jev shadow on localize ties and borderline text checks (TASK-47 G13): background, bounded, never
changes or delays a result. Fakes only: no network, no DB, no device."""
import importlib
import os
import threading
import time

import numpy as np
import pytest

from shared.src.lib.ai import decisions, router

jso = importlib.import_module('backend_host.src.controllers.verification.jev_second_opinion')


class Calls(list):
    done = None


class FakeHelpers:
    """The slice of ImageHelpers the fact builders use."""
    def _region_dhashes(self, g): return {'full': 'a'}
    def _dhash_hex(self, g): return 'a'
    def _focus_signature(self, i): return {'kind': None}
    def _focus_crop_hex(self, i): return None
    def _title_text(self, i): return ''
    @staticmethod
    def _normalize_text(s): return s
    def _region_dists(self, live, regs): return [10]
    @staticmethod
    def _dhash_hamming(a, b): return 4
    @staticmethod
    def _focus_agreement(a, b): return 1.0
    @staticmethod
    def title_score(a, b): return 1.0


NODES = [{'node_id': n, 'label': n.upper(), 'fingerprint': {'dhash': 'a', 'regions': {'full': 'a'}}}
         for n in ('home', 'guide', 'live')]
IMG = np.zeros((8, 8, 3), dtype=np.uint8)


@pytest.fixture(autouse=True)
def calls(monkeypatch):
    for k in ('JEV_ENABLED', 'JEV_DISABLED_USAGES'):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(jso, '_stamps', jso.deque())
    monkeypatch.setattr(jso, '_slots', threading.BoundedSemaphore(jso.MAX_WORKERS))
    got = Calls()
    done = threading.Event()
    got.done = done
    monkeypatch.setattr(router, 'resolve', lambda usage, team_id=None, **k: type('R', (), {'usage': usage})())

    def choose(res, state, options, **kw):
        got.append(('choose', res.usage, state, options, kw)); done.set()
        return {'success': True}

    def decide(res, state, questions, **kw):
        got.append(('decide', res.usage, state, questions, kw)); done.set()
        return {'success': True}
    monkeypatch.setattr(decisions, 'choose', choose)
    monkeypatch.setattr(decisions, 'decide', decide)
    return got


def cand(n, conf=0.9):
    return {'node_id': n, 'label': n.upper(), 'confidence': conf, 'dist': 3}


def loc(result):
    return jso.localize_shadow(FakeHelpers(), IMG, NODES, result, team_id='t1', userinterface_name='ui', tree_id='tr')


def test_confident_single_makes_no_call(calls):
    assert loc({'candidates': [cand('home')]}) is False
    time.sleep(0.05)
    assert calls == []


def test_tie_calls_choose_with_usage_and_refs(calls):
    assert loc({'candidates': [cand('home'), cand('guide')]}) is True
    assert calls.done.wait(2)
    kind, usage, state, options, kw = calls[0]
    assert (kind, usage) == ('choose', 'text.decision.localize')
    assert [o['id'] for o in options] == ['home', 'guide', 'live', 'none']
    assert kw['log'] is True
    r = kw['refs']
    assert r['source'] == 'localize-shadow' and r['ui'] == 'ui' and r['tree_id'] == 'tr'
    assert r['rule_result'] == 'HOME' and [c['node_id'] for c in r['candidates']] == ['home', 'guide']


def test_abstain_calls_but_low_confidence_is_not_shadowed(calls):
    assert loc({'candidates': [cand('home', 0.5)]}) is False     # decided by confirm_low_confidence, which logs it
    assert loc({'candidates': []}) is True
    assert calls.done.wait(2)
    assert [c[4]['refs']['rule_result'] for c in calls] == ['abstain']


def test_capture_state_makes_no_call(calls):
    assert loc({'candidates': [], 'state': 'black'}) is False


def test_text_band(calls):
    kw = dict(team_id='t1', expected='Hello', threshold=0.8, ocr_text='Hell0', area=None, rule_verdict=False)
    assert jso.text_shadow(score=0.65, **kw) is False       # more than 0.10 below
    assert jso.text_shadow(score=0.95, **kw) is False       # more than 0.10 above
    assert jso.text_shadow(score=0.72, **kw) is True        # inside, fail side
    assert calls.done.wait(2)
    kind, usage, state, questions, k = calls[0]
    assert (kind, usage) == ('decide', 'text.decision.verification')
    assert questions == {'q': jso.VER_Q} and state['score'] == 0.72 and state['ocr_text'] == 'Hell0'
    assert k['log'] is True and k['refs']['source'] == 'verification-shadow'
    assert k['refs']['verification_type'] == 'text' and k['refs']['rule_verdict'] == 'fail'


def test_text_band_pass_side(calls):
    assert jso.text_shadow(team_id='t1', expected='x', score=0.85, threshold=0.8, ocr_text='x', area=None,
                           rule_verdict=True) is True


@pytest.mark.parametrize('env', [{'JEV_ENABLED': 'false'}, {'JEV_DISABLED_USAGES': 'text.decision'},
                                 {'JEV_DISABLED_USAGES': 'text.decision.localize,text.decision.verification'}])
def test_disabled_starts_nothing(calls, monkeypatch, env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(jso, '_submit', lambda job: pytest.fail('no thread when off'))
    assert loc({'candidates': [cand('a'), cand('b')]}) is False
    assert jso.text_shadow(team_id='t1', expected='x', score=0.8, threshold=0.8, ocr_text='', area=None,
                           rule_verdict=True) is False


def test_slow_and_raising_fakes_never_block_or_raise(monkeypatch, calls):
    gate = threading.Event()

    def slow(*a, **k):
        gate.wait(5)
        raise RuntimeError('boom')
    monkeypatch.setattr(decisions, 'choose', slow)
    t0 = time.time()
    assert loc({'candidates': [cand('home'), cand('guide')]}) is True
    assert time.time() - t0 < 0.5
    gate.set()


def test_busy_pool_drops(monkeypatch, calls):
    gate = threading.Event()
    monkeypatch.setattr(decisions, 'choose', lambda *a, **k: gate.wait(5))
    started = [loc({'candidates': [cand('home'), cand('guide')]}) for _ in range(jso.MAX_WORKERS + 3)]
    assert started.count(True) == jso.MAX_WORKERS and started.count(False) == 3
    gate.set()


def test_rate_cap_drops(monkeypatch, calls):
    monkeypatch.setattr(jso, 'MAX_PER_MINUTE', 2)
    out = []
    for _ in range(4):
        out.append(jso.text_shadow(team_id='t1', expected='x', score=0.8, threshold=0.8, ocr_text='', area=None,
                                   rule_verdict=True))
        time.sleep(0.05)
    assert out == [True, True, False, False]


def test_no_team_no_call(calls):
    assert jso.localize_shadow(FakeHelpers(), IMG, NODES, {'candidates': []}, team_id=None,
                               userinterface_name='u', tree_id='t') is False


def test_usages_registered_under_text_decision():
    from shared.src.lib.ai import usages
    for k in ('text.decision.localize', 'text.decision.verification'):
        assert usages.get(k).parent == 'text.decision'


# ---- confirm_low_confidence ----------------------------------------------------------------------

@pytest.fixture
def conf(monkeypatch, calls):
    """choose() answers from `ans`; every call is recorded in `calls`."""
    monkeypatch.setattr(jso, '_confirm_stamps', jso.deque())
    monkeypatch.setattr(jso, '_confirm_cache', {})
    ans = {'out': {'success': True, 'choice': 'home', 'probabilities': {'home': 0.95}, 'confidence': 0.95,
                   'decision_id': None}}

    def choose(res, state, options, **kw):
        calls.append(('choose', res.usage, state, options, kw))
        o = ans['out']
        if isinstance(o, Exception):
            raise o
        return o
    monkeypatch.setattr(decisions, 'choose', choose)
    ans['calls'] = calls
    return ans


def confirm(result, **kw):
    kw.setdefault('team_id', 't1')
    kw.setdefault('cache_key', 'ui')
    return jso.confirm_low_confidence(FakeHelpers(), IMG, NODES, result, **kw)


def low():
    return {'candidates': [cand('home', 0.6)], 'excluded_count': 0}


def test_confirm_confident_single_untouched_no_call(conf):
    r = {'candidates': [cand('home', 0.9)]}
    assert confirm(r) is r and r['candidates'][0]['node_id'] == 'home' and conf['calls'] == []


def test_confirm_other_bands_untouched_no_call(conf):
    for r in ({'candidates': [cand('home', 0.5), cand('guide', 0.5)]}, {'candidates': []},
              {'candidates': [], 'state': 'black'}):
        assert confirm(r)['candidates'] == r['candidates']
    assert conf['calls'] == []


def test_confirm_same_node_high_kept(conf):
    r = confirm(low())
    assert [c['node_id'] for c in r['candidates']] == ['home'] and r['jev_confirmed'] == 0.95
    kind, usage, state, options, kw = conf['calls'][0]
    assert usage == 'text.decision.localize' and kw['timeout_s'] == 3 and kw['log'] is True
    assert kw['refs']['source'] == 'localize-confirm' and kw['refs']['ui'] == 'ui'
    assert [o['id'] for o in options] == ['home', 'guide', 'live', 'none']


def test_confirm_same_node_085_unknown(conf):
    conf['out'] = {'success': True, 'choice': 'home', 'probabilities': {'home': 0.85}, 'confidence': 0.85}
    r = confirm(low())
    assert r['candidates'] == [] and r['reason'] == jso.NOT_CONFIRMED and r['excluded_count'] == 1


def test_confirm_falls_back_to_confidence_without_probabilities(conf):
    conf['out'] = {'success': True, 'choice': 'home', 'probabilities': {}, 'confidence': 0.93}
    assert confirm(low())['jev_confirmed'] == 0.93


@pytest.mark.parametrize('out', [
    {'success': True, 'choice': 'guide', 'probabilities': {'guide': 0.99}, 'confidence': 0.99},
    {'success': True, 'choice': 'none', 'probabilities': {'none': 0.99}, 'confidence': 0.99},
    {'success': False, 'error': 'timeout', 'choice': None},
    RuntimeError('boom')])
def test_confirm_other_none_error_unknown(conf, out):
    conf['out'] = out
    r = confirm(low())
    assert r['candidates'] == [] and r['unconfirmed_candidate']['node_id'] == 'home'


@pytest.mark.parametrize('env', [{'JEV_ENABLED': 'false'}, {'JEV_DISABLED_USAGES': 'text.decision.localize'}])
def test_confirm_jev_off_unknown_no_call(conf, monkeypatch, env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    r = confirm(low())
    assert r['candidates'] == [] and 'Jev off' in r['reason'] and conf['calls'] == []


def test_confirm_no_team_unknown(conf):
    assert confirm(low(), team_id=None)['candidates'] == [] and conf['calls'] == []


def test_confirm_over_cap_unknown_no_call(conf, monkeypatch):
    monkeypatch.setattr(jso, 'CONFIRM_MAX_PER_MINUTE', 1)
    monkeypatch.setattr(jso, '_hamming_hex', lambda a, b: 999)       # no cache hits
    assert confirm(low())['candidates']
    assert confirm(low())['candidates'] == [] and len(conf['calls']) == 1


def test_confirm_cache_hit_no_second_call(conf):
    assert confirm(low())['candidates']
    assert confirm(low())['candidates'] and len(conf['calls']) == 1
    conf['out'] = {'success': True, 'choice': 'none', 'probabilities': {}, 'confidence': 1}
    assert confirm(low())['candidates'] and len(conf['calls']) == 1   # cached verdict wins for 120 s


def test_confirm_cache_expires_and_is_per_ui(conf, monkeypatch):
    confirm(low())
    confirm(low(), cache_key='other')
    assert len(conf['calls']) == 2
    monkeypatch.setattr(jso.time, 'time', lambda: 4e9)
    confirm(low())
    assert len(conf['calls']) == 3


def test_confirm_error_is_cached_briefly(conf):
    conf['out'] = {'success': False, 'error': 'timeout', 'choice': None}
    confirm(low()); confirm(low())
    assert len(conf['calls']) == 1


def test_monitor_and_navigation_give_the_same_verdict(conf, monkeypatch):
    """Both callers use confirm_low_confidence with the same arguments: monitor_localize's verdict for a
    frame equals a direct call, and navigation_executor wires the same function."""
    from backend_host.scripts import monitor_localize as ml
    ne_src = open(os.path.join(os.path.dirname(ml.__file__), '..', 'src', 'services', 'navigation',
                               'navigation_executor.py')).read()    # (importing it needs networkx)
    assert "confirm_low_confidence(helpers, img, match_fps, result, team_id=team_id, cache_key=userinterface_name)" \
        in ne_src

    class H(FakeHelpers):
        def classify_special_state(self, img):
            return None

        def identify_screen(self, img, fps):
            return {'candidates': [cand('home', 0.6)], 'excluded_count': 0, 'total': 3}
    m = ml.MonitorLocalizer(team_id='t1')
    monkeypatch.setattr(m, '_resolve_ui', lambda d: ('ui', 'base'))
    monkeypatch.setattr(m, '_load_node_fps', lambda ui: NODES)
    monkeypatch.setattr(m, '_get_helpers', lambda: H())
    monkeypatch.setattr(m, '_record_change', lambda *a: None)
    import cv2
    monkeypatch.setattr(cv2, 'imread', lambda p: IMG)
    monkeypatch.setattr(ml.cv2_io, 'imread', lambda p: IMG)        # the monitor reads frames through cv2_io
    for out_choice, want in (({'success': True, 'choice': 'home', 'probabilities': {'home': 0.95}}, 'HOME'),
                             ({'success': True, 'choice': 'guide', 'probabilities': {'guide': 0.95}}, None)):
        conf['out'] = out_choice
        jso._confirm_cache.clear()
        direct = jso.confirm_low_confidence(H(), IMG, NODES, H().identify_screen(IMG, NODES),
                                            team_id='t1', cache_key='ui')
        jso._confirm_cache.clear()
        m._matched_thumb.clear()                                   # same IMG twice: no unchanged-frame skip (TASK-115)
        got = m.localize_frame('device1', 'x.jpg')
        assert got['node'] == want == (direct['candidates'][0]['label'] if direct['candidates'] else None)
