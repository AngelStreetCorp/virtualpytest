"""TASK-107 goal 4: android / web devices name the node from their identity before pixels.

Pure matching (activity, texts, URL, title) and the executor wiring: a decided identity answers
kind=node without running the pixel matcher, a shared place narrows it, a web device with no AV
still answers. Fakes only.
"""
import importlib
from types import SimpleNamespace

import networkx as nx
import numpy as np
import pytest

li = importlib.import_module('shared.src.lib.utils.localize_identity')
nav = importlib.import_module('backend_host.src.services.navigation.navigation_executor')
di = importlib.import_module('backend_host.src.lib.utils.device_identity')
jso = importlib.import_module('backend_host.src.controllers.verification.jev_second_opinion')

pytestmark = pytest.mark.unit


def nfp(node_id, **identity):
    fp = {'dhash': 'ab' * 32}
    if identity:
        fp['identity'] = identity
    return {'node_id': node_id, 'label': node_id, 'fingerprint': fp}


DUMPSYS = """
  Display #0 (activities from top to bottom):
    * Task{abc #12 type=standard A=10123:com.google.android.youtube U=0 visible=true}
      mResumedActivity: ActivityRecord{7f1 u0 com.google.android.youtube/.app.honeycomb.Shell$HomeActivity t12}
"""


def test_parse_activity_reads_the_resumed_activity():
    assert li.parse_activity(DUMPSYS) == ('com.google.android.youtube',
                                          'com.google.android.youtube.app.honeycomb.Shell$HomeActivity')
    focus = "  mCurrentFocus=Window{1 u0 com.example/com.example.MainActivity}"
    assert li.parse_activity(focus) == ('com.example', 'com.example.MainActivity')
    assert li.parse_activity('nothing here') is None


def test_normalize_url_keeps_hash_routes_drops_query():
    assert li.normalize_url('https://Shop.example.com/cart/?x=1') == 'shop.example.com/cart'
    assert li.normalize_url('https://app.example.com/#/settings/') == 'app.example.com#/settings'
    assert li.normalize_url('https://example.com/#top') == 'example.com'
    assert li.normalize_url('') is None


def test_one_node_at_the_place_decides():
    nodes = [nfp('home', kind='android', activity='a.Home'), nfp('search', kind='android', activity='a.Search'),
             nfp('noid')]
    m = li.match_identity({'kind': 'android', 'activity': 'a.Search'}, nodes)
    assert m['decided']['node_id'] == 'search' and m['reason'] == 'unique place'
    v = li.identity_verdict(m, {'kind': 'android', 'package': 'a', 'activity': 'a.Search'})
    assert (v['kind'], v['node_id'], v['confidence']) == ('node', 'search', 1.0)
    assert v['evidence']['identity']['activity'] == 'a.Search'


def test_shared_activity_is_decided_by_texts_or_left_to_pixels():
    nodes = [nfp('home', kind='android', activity='a.Main', texts=['home', 'shorts', 'subscriptions', 'trending']),
             nfp('library', kind='android', activity='a.Main', texts=['library', 'history', 'your videos'])]
    live = {'kind': 'android', 'activity': 'a.Main', 'texts': ['library', 'history', 'your videos', 'downloads']}
    assert li.match_identity(live, nodes)['decided']['node_id'] == 'library'
    m = li.match_identity({'kind': 'android', 'activity': 'a.Main'}, nodes)
    assert m['decided'] is None and [n['node_id'] for n in m['candidates']] == ['home', 'library']


def test_web_url_then_title():
    nodes = [nfp('cart', kind='web', url='https://shop.test/cart', title='Cart'),
             nfp('p1', kind='web', url='https://shop.test/#/p', title='One'),
             nfp('p2', kind='web', url='https://shop.test/#/p', title='Two')]
    assert li.match_identity({'kind': 'web', 'url': 'https://shop.test/cart?ref=1'}, nodes)['decided']['node_id'] == 'cart'
    assert li.match_identity({'kind': 'web', 'url': 'https://shop.test/#/p', 'title': 'two'}, nodes)['decided']['node_id'] == 'p2'
    assert li.match_identity({'kind': 'web', 'url': 'https://other.test/'}, nodes)['reason'] == 'place not in the tree'


# ---------------------------------------------------------------- executor wiring

def _ui_frame():
    img = np.full((360, 640, 3), 60, dtype=np.uint8)
    img[40:120, 40:300] = 200
    return img


class _Av:
    def __init__(self):
        self.n = 0

    def take_screenshot(self):
        self.n += 1
        return f'/tmp/frame_{self.n}.jpg'


def _graph(identities):
    g = nx.DiGraph()
    for node_id, ident in identities.items():
        fp = {'dhash': 'ab' * 32, **({'identity': ident} if ident else {})}
        g.add_node(node_id, label=node_id, metadata={}, __fingerprint=fp, variant_state={'active': True})
    return g


@pytest.fixture
def run(monkeypatch):
    def _run(model, identities, live, av=True, texts=None):
        cam = _Av() if av else None
        ex = nav.NavigationExecutor.__new__(nav.NavigationExecutor)
        ex.device = SimpleNamespace(navigation_context={}, device_id='device1',
                                    _get_controller=lambda kind: cam if kind == 'av' else None)
        ex.device_id, ex.host_name, ex.device_model = 'device1', 'h', model
        calls = []
        monkeypatch.setattr(ex, '_sync_unified_graph', lambda *a, **k: _graph(identities))
        monkeypatch.setattr(ex, '_read_classifier_diagnostics', lambda *a, **k: None)
        monkeypatch.setattr(ex, '_frame_url_from_path', lambda p: 'url')
        monkeypatch.setattr(nav.cv2_io, 'imread', lambda p: _ui_frame())
        monkeypatch.setattr(nav.time, 'sleep', lambda s: None)
        monkeypatch.setattr(jso, 'confirm_low_confidence', lambda *a, **k: None)
        monkeypatch.setattr(jso, 'localize_shadow', lambda *a, **k: None)
        monkeypatch.setattr(di, 'read_identity', lambda device, with_texts=False: dict(live) if live else None)
        monkeypatch.setattr(di, 'android_texts', lambda device: texts)

        def fake_match(helpers, img, node_fps, site):
            calls.append([n['node_id'] for n in node_fps])
            return {'candidates': [], 'excluded_count': len(node_fps), 'total': len(node_fps)}
        monkeypatch.setattr(nav, 'run_identify_screen', fake_match)
        result = ex.localize('team', 'ui', tree_id='tree-1')
        result['_grabbed'] = cam.n if cam else 0
        return result, calls
    return _run


def test_android_activity_answers_node_without_pixels(run):
    result, calls = run('android_mobile', {'home': {'kind': 'android', 'activity': 'a.Home'},
                                           'search': {'kind': 'android', 'activity': 'a.Search'}},
                        {'kind': 'android', 'package': 'a', 'activity': 'a.Search'})
    assert (result['verdict']['kind'], result['verdict']['node_id']) == ('node', 'search')
    assert result['verdict']['evidence']['by'] == 'unique place'
    assert calls == [] and result['_grabbed'] == 1          # one frame for the popover, no motion grab
    assert [c['node_id'] for c in result['candidates']] == ['search']


def test_shared_activity_narrows_the_pixel_matcher(run):
    result, calls = run('android_tablet', {'home': {'kind': 'android', 'activity': 'a.Main'},
                                           'lib': {'kind': 'android', 'activity': 'a.Main'},
                                           'settings': {'kind': 'android', 'activity': 'a.Settings'}},
                        {'kind': 'android', 'activity': 'a.Main'}, texts=None)
    assert calls == [['home', 'lib']]
    assert result['verdict']['evidence']['identity']['narrowed_to'] == ['home', 'lib']


def test_web_device_without_av_answers_from_the_url(run):
    result, calls = run('web', {'cart': {'kind': 'web', 'url': 'https://shop.test/cart'},
                                'home': {'kind': 'web', 'url': 'https://shop.test/'}},
                        {'kind': 'web', 'url': 'https://shop.test/', 'title': 'Shop'}, av=False)
    assert result['success'] is True and result['verdict']['node_id'] == 'home' and calls == []


def test_tv_and_nodes_without_identity_keep_the_pixels(run):
    _, calls = run('stb', {'home': {'kind': 'android', 'activity': 'a.Home'}}, {'kind': 'android', 'activity': 'a.Home'})
    assert calls == [['home']]
    _, calls = run('android_mobile', {'home': None}, {'kind': 'android', 'activity': 'a.Home'})
    assert calls == [['home']]


def test_web_identity_runs_the_controller_coroutine():
    """PlaywrightWebController.get_page_info is a coroutine: the identity read must run it."""
    class Web:
        _browser, _context = object(), object()

        async def get_page_info(self):
            return {'success': True, 'url': 'https://shop.test/cart', 'title': 'Cart'}
    dev = SimpleNamespace(device_model='host_vnc', _get_controller=lambda kind: Web() if kind == 'web' else None)
    assert di.read_identity(dev) == {'kind': 'web', 'url': 'https://shop.test/cart', 'title': 'Cart'}
    Web._browser = None                                   # a browser not connected is never launched
    assert di.read_identity(dev) is None


# --- language-free web identity (BUG-0703) -------------------------------------------------------

def test_strip_locale_only_known_language_segments():
    from shared.src.lib.utils.localize_identity import strip_locale
    assert strip_locale('/de/home') == '/home'
    assert strip_locale('/en-GB/home') == '/home'
    assert strip_locale('/en') == '/'
    assert strip_locale('/settings/de') == '/settings/de'
    assert strip_locale('/ab/home') == '/ab/home'          # not a language
    assert strip_locale('/deals/x') == '/deals/x'          # prefix of a word is not a segment


def test_url_matches_ignores_language_host_and_query():
    from shared.src.lib.utils.localize_identity import url_matches
    de = 'https://www.example.com/de/epg/initial?x=1'
    en = 'https://www.example.com/en/epg/initial'
    for pat in ('/epg/initial', '/*/epg/initial', '/de/epg/initial', 'epg/initial/', 'https://other/en/epg/initial'):
        assert url_matches(de, pat), pat
        assert url_matches(en, pat), pat
    assert not url_matches(de, '/epg/other')
    assert not url_matches('', '/epg/initial')
    assert not url_matches(de, '')


def test_url_matches_glob_over_dynamic_ids():
    from shared.src.lib.utils.localize_identity import url_matches
    assert url_matches('https://h/fr/watchtv/linearplayer/123/BBC', '/watchtv/linearplayer/*')
    assert not url_matches('https://h/fr/watchtv', '/watchtv/linearplayer/*')
    assert url_matches('https://h/fr/replaycatalog/0/details/replaytv/a//b/show', '/replaycatalog/0/details/*/show')


def test_same_place_web_across_languages():
    from shared.src.lib.utils.localize_identity import same_place
    stored = {'kind': 'web', 'url': 'https://h/en/settings'}
    assert same_place({'kind': 'web', 'url': 'https://h/de/settings'}, stored)
    assert not same_place({'kind': 'web', 'url': 'https://h/de/watchtv'}, stored)
    assert not same_place({'kind': 'web', 'url': 'https://other/de/settings'}, stored)


def test_resolve_app_url_keeps_the_apps_current_language():
    from shared.src.lib.utils.localize_identity import resolve_app_url as r
    cur = 'https://h/de/settings/accessibility'
    assert r('/settings', cur) == 'https://h/de/settings'
    assert r('/{lang}/settings', cur) == 'https://h/de/settings'
    assert r('/en/settings', cur) == 'https://h/en/settings'      # explicit language is the author's choice
    assert r('https://h/en/settings', cur) == 'https://h/en/settings'
    assert r('/settings', 'https://h/settings') == 'https://h/settings'
    assert r('/settings', '') == '/settings'
