"""Unit tests for the two-stage screen classifier (Jev options, Qwen fallback).

The model calls are faked; the profile resolution and the live API are exercised
on a server. Pins the parse rules and the routing between the two stages.
"""
import importlib

import pytest

sc = importlib.import_module('shared.src.lib.utils.screen_classifier')

pytestmark = pytest.mark.unit

OPTIONS = [{'id': 'settings', 'description': 'the settings menu'},
           {'id': 'apps', 'description': 'the app grid'}]


def test_slug_is_short_and_lowercase():
    assert sc._slug('Settings / Profiles!') == 'settings_profiles'
    assert sc._slug('  TV   Guide ') == 'tv_guide'
    assert sc._slug('') == ''


def test_parse_choice_exact_word_and_none():
    assert sc._parse_choice('settings', ['settings', 'apps', 'none']) == 'settings'
    assert sc._parse_choice('The answer is apps.', ['settings', 'apps', 'none']) == 'apps'
    assert sc._parse_choice('none', ['settings', 'apps', 'none']) == 'none'
    assert sc._parse_choice('I am not sure', ['settings', 'apps', 'none']) is None


def test_parse_choice_does_not_match_a_substring():
    assert sc._parse_choice('settings_profiles', ['settings', 'profiles', 'none']) is None


def test_parse_choice_maps_a_unique_label_to_its_node_id():
    assert sc._parse_choice('Settings Profiles', ['n1', 'n2', 'none'],
                            {'settings_profiles': 'n1'}) == 'n1'
    assert sc._parse_choice('the settings profiles screen', ['n1', 'n2', 'none'],
                            {'settings_profiles': 'n1'}) == 'n1'


def test_aliases_drop_a_label_shared_by_two_nodes():
    aliases = sc._aliases([{'id': 'a', 'description': 'Home'},
                           {'id': 'b', 'description': 'home'},
                           {'id': 'c', 'description': 'Settings'}])
    assert aliases == {'settings': 'c'}


def test_call_uses_the_vision_classify_route_by_default(monkeypatch, tmp_path):
    img = tmp_path / 'x.png'
    img.write_bytes(b'x')
    calls = {}
    from shared.src.lib.ai import gateway, router

    def fake_resolve(usage_key, team_id=None, **kw):
        calls['usage'] = usage_key
        return 'resolution'

    monkeypatch.setattr(router, 'resolve', fake_resolve)
    monkeypatch.setattr(gateway, 'execute',
                        lambda res, prompt, **kw: {'success': True, 'content': 'ok'})
    out = sc._call(None, 'prompt', str(img), 't1')
    assert out['ok'] is True
    assert calls['usage'] == 'vision.classify'


def test_call_pins_a_profile_under_the_classify_usage(monkeypatch, tmp_path):
    img = tmp_path / 'x.png'
    img.write_bytes(b'x')
    calls = {}
    from shared.src.lib.ai import gateway, router

    def fake_resolve_profile(profile, usage_key, team_id=None, **kw):
        calls.update(profile=profile, usage=usage_key)
        return 'resolution'

    monkeypatch.setattr(router, 'resolve_profile', fake_resolve_profile)
    monkeypatch.setattr(gateway, 'execute',
                        lambda res, prompt, **kw: {'success': True, 'content': 'ok'})
    out = sc._call('jev-router', 'prompt', str(img), 't1')
    assert out['ok'] is True
    assert calls == {'profile': 'jev-router', 'usage': 'vision.classify'}


def test_classify_with_options_returns_the_choice(monkeypatch):
    monkeypatch.setattr(sc, '_call', lambda *a, **k: {'ok': True, 'content': 'apps', 'model': 'm'})
    out = sc.classify_with_options('/tmp/x.jpg', OPTIONS, 't1')
    assert out['ok'] is True
    assert out['choice'] == 'apps'
    assert out['source'] == 'jev'


def test_classify_with_options_none(monkeypatch):
    monkeypatch.setattr(sc, '_call', lambda *a, **k: {'ok': True, 'content': 'none'})
    out = sc.classify_with_options('/tmp/x.jpg', OPTIONS, 't1')
    assert out['ok'] is True and out['choice'] == 'none'


def test_classify_with_options_unparsed_is_not_ok(monkeypatch):
    monkeypatch.setattr(sc, '_call', lambda *a, **k: {'ok': True, 'content': '???'})
    out = sc.classify_with_options('/tmp/x.jpg', OPTIONS, 't1')
    assert out['ok'] is False


def test_classify_with_options_allows_room_for_reasoning_tokens(monkeypatch):
    """A reasoning model needs room for its reasoning plus the one-word answer."""
    seen = {}

    def fake(profile, prompt, image_path, team_id, max_tokens=64):
        seen['max_tokens'] = max_tokens
        return {'ok': True, 'content': 'none'}

    monkeypatch.setattr(sc, '_call', fake)
    out = sc.classify_with_options('/tmp/x.jpg', OPTIONS, 't1')
    assert out['ok'] is True
    assert seen['max_tokens'] == sc.OPTIONS_MAX_TOKENS
    assert seen['max_tokens'] >= 96


def test_classify_with_options_empty_answer_is_not_ok(monkeypatch):
    """The 32-token regression: reasoning filled the budget, content was empty."""
    monkeypatch.setattr(sc, '_call', lambda *a, **k: {'ok': True, 'content': ''})
    out = sc.classify_with_options('/tmp/x.jpg', OPTIONS, 't1')
    assert out['ok'] is False


def test_classify_open_returns_a_slug(monkeypatch):
    monkeypatch.setattr(sc, '_call', lambda *a, **k: {'ok': True, 'content': 'Settings Profiles', 'model': 'q'})
    out = sc.classify_open('/tmp/x.jpg', 't1')
    assert out['ok'] is True
    assert out['label'] == 'settings_profiles'
    assert out['source'] == 'qwen'


def test_classify_screen_uses_jev_when_options_match(monkeypatch):
    monkeypatch.setattr(sc, '_call', lambda profile, *a, **k: {'ok': True, 'content': 'settings'})
    out = sc.classify_screen('/tmp/x.jpg', 't1', options=OPTIONS)
    assert out['source'] == 'jev' and out['choice'] == 'settings'


def test_classify_screen_falls_back_to_open_on_none(monkeypatch):
    def fake(profile, *a, **k):
        return ({'ok': True, 'content': 'none'} if profile == 'jev-router'
                else {'ok': True, 'content': 'netflix home'})
    monkeypatch.setattr(sc, '_call', fake)
    out = sc.classify_screen('/tmp/x.jpg', 't1', options=OPTIONS)
    assert out['source'] == 'qwen'
    assert out['label'] == 'netflix_home'
    assert out['jev']['choice'] == 'none'


def test_classify_screen_falls_back_to_open_when_jev_errors(monkeypatch):
    def fake(profile, *a, **k):
        return ({'ok': False, 'error': 'provider down'} if profile == 'jev-router'
                else {'ok': True, 'content': 'menu'})
    monkeypatch.setattr(sc, '_call', fake)
    out = sc.classify_screen('/tmp/x.jpg', 't1', options=OPTIONS)
    assert out['source'] == 'qwen' and out['label'] == 'menu'


def test_classify_screen_without_options_is_open(monkeypatch):
    monkeypatch.setattr(sc, '_call', lambda *a, **k: {'ok': True, 'content': 'home screen'})
    out = sc.classify_screen('/tmp/x.jpg', 't1')
    assert out['source'] == 'qwen'
    assert 'jev' not in out


def test_classify_open_pins_the_qwen_profile(monkeypatch):
    seen = {}

    def fake(profile, prompt, image_path, team_id, max_tokens=64):
        seen['profile'] = profile
        return {'ok': True, 'content': 'home'}

    monkeypatch.setattr(sc, '_call', fake)
    out = sc.classify_open('/tmp/x.jpg', 't1')
    assert out['ok'] is True
    assert seen['profile'] == 'qwen3-vl-8b'


def test_classify_with_options_pins_the_jev_profile(monkeypatch):
    seen = {}

    def fake(profile, prompt, image_path, team_id, max_tokens=64):
        seen['profile'] = profile
        return {'ok': True, 'content': 'none'}

    monkeypatch.setattr(sc, '_call', fake)
    out = sc.classify_with_options('/tmp/x.jpg', OPTIONS, 't1')
    assert out['ok'] is True
    assert seen['profile'] == 'jev-router'
