"""Unit tests for the unknown-screen classification benchmark (pure parts).

The live DB/R2 build and the cascade run are exercised on a host; here we pin
the transforms, the scoring rules and the classifier wrapper.
"""
import os
import sys

import numpy as np
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'localize'))

import classify_bench as cb  # noqa: E402

pytestmark = pytest.mark.unit


def test_transforms_are_deterministic_and_keep_the_shape():
    img = np.full((90, 160, 3), 100, dtype=np.uint8)
    img[10:30, 20:80] = 200
    for name in cb.TRANSFORMS:
        first = cb.apply_transform(img, name)
        second = cb.apply_transform(img, name)
        assert np.array_equal(first, second), name
        if name == 'letterbox':
            assert first.shape[0] > img.shape[0] and first.shape[1] > img.shape[1]
        else:
            assert first.shape[:2] == img.shape[:2], name


def test_unknown_transform_raises():
    with pytest.raises(ValueError):
        cb.apply_transform(np.zeros((10, 10, 3), dtype=np.uint8), 'nope')


def test_label_match_is_fuzzy_on_half_the_tokens():
    assert cb.label_match('Settings Menu', 'settings_main_menu')
    assert cb.label_match('TV Guide', 'tvguide')
    assert not cb.label_match('Settings Menu', 'netflix_home')
    assert not cb.label_match('', 'anything')


def test_score_known_and_modified_require_the_expected_node():
    known = {'kind': 'known', 'expect_node': 'n1'}
    assert cb.score_verdict(known, {'kind': 'node', 'node_id': 'n1'})
    assert not cb.score_verdict(known, {'kind': 'node', 'node_id': 'n2'})
    assert not cb.score_verdict(known, {'kind': 'unknown'})
    modified = {'kind': 'modified', 'expect_node': 'n1'}
    assert cb.score_verdict(modified, {'kind': 'node', 'node_id': 'n1'})


def test_score_unknown_must_not_claim_a_node():
    unknown = {'kind': 'unknown'}
    assert cb.score_verdict(unknown, {'kind': 'unknown'})
    assert cb.score_verdict(unknown, {'kind': 'known_screen'})
    assert not cb.score_verdict(unknown, {'kind': 'node', 'node_id': 'x'})


def test_classify_hybrid_wraps_the_two_stage_classifier(monkeypatch):
    import importlib
    screen_classifier = importlib.import_module('shared.src.lib.utils.screen_classifier')
    monkeypatch.setattr(screen_classifier, 'classify_screen',
                        lambda path, team_id, options=None: {'ok': True, 'source': 'jev', 'choice': 'none'})
    out = cb.classify_hybrid('/tmp/x.jpg', 't1', [{'id': 'a', 'description': 'a'}])
    assert out['source'] == 'jev' and out['choice'] == 'none'
    assert isinstance(out['ms'], int)


def test_score_negative_must_not_claim_a_node():
    negative = {'kind': 'negative'}
    assert cb.score_verdict(negative, {'kind': 'signal'})
    assert cb.score_verdict(negative, {'kind': 'unknown'})
    assert not cb.score_verdict(negative, {'kind': 'node', 'node_id': 'x'})


def test_classify_frame_returns_the_proposed_label():
    out = cb.classify_frame(
        '/tmp/frame.jpg', 't1',
        classifier=lambda path, team_id=None: {'screen_type': 'menu', 'screen_summary': 'settings'},
        propose=lambda dom, screen_type: 'settings_menu')
    assert out['ok'] is True
    assert out['label'] == 'settings_menu'
    assert out['screen_type'] == 'menu'
    assert isinstance(out['ms'], int)


def test_classify_frame_handles_a_classifier_error():
    out = cb.classify_frame('/tmp/frame.jpg', 't1',
                            classifier=lambda path, team_id=None: {'error': 'not an image'},
                            propose=lambda dom, screen_type: 'x')
    assert out['ok'] is False
    assert 'not an image' in out['error']


def test_classify_frame_handles_an_exception():
    def boom(path, team_id=None):
        raise RuntimeError('provider down')
    out = cb.classify_frame('/tmp/frame.jpg', 't1', classifier=boom,
                            propose=lambda dom, screen_type: 'x')
    assert out['ok'] is False
    assert 'provider down' in out['error']


def test_classify_frame_empty_label_is_not_ok():
    out = cb.classify_frame('/tmp/frame.jpg', 't1',
                            classifier=lambda path, team_id=None: {'screen_type': 'menu'},
                            propose=lambda dom, screen_type: '')
    assert out['ok'] is False


def test_pct_handles_empty_and_percentiles():
    assert cb._pct([], 50) is None
    assert cb._pct([10], 50) == 10
    assert cb._pct([10, 20, 30], 50) == 20
    assert cb._pct([10, 20, 30], 95) == 30


def test_score_jev_closed_choice_outcomes():
    known = {'kind': 'known', 'expect_node': 'n1'}
    assert cb.score_jev(known, {'ok': True, 'choice': 'n1'}) == ('correct', 'n1')
    assert cb.score_jev(known, {'ok': True, 'choice': 'none'}) == ('abstain', None)
    assert cb.score_jev(known, {'ok': True, 'choice': 'n2'}) == ('false_node', 'n2')
    assert cb.score_jev(known, {'ok': False, 'error': 'empty_answer'}) == ('error', None)
    unknown = {'kind': 'unknown'}
    assert cb.score_jev(unknown, {'ok': True, 'choice': 'none'}) == ('abstain', None)
    assert cb.score_jev(unknown, {'ok': True, 'choice': 'n1'}) == ('false_node', 'n1')


def test_score_qwen_uses_the_expected_label():
    known = {'kind': 'known', 'label': 'settings_profiles'}
    assert cb.score_qwen(known, {'ok': True, 'label': 'settings_profiles_menu'}) is True
    assert cb.score_qwen(known, {'ok': True, 'label': 'home_screen'}) is False
    assert cb.score_qwen(known, {'ok': False, 'error': 'x'}) is False


def test_score_hybrid_prefers_a_correct_node_and_falls_back_on_none():
    known = {'kind': 'known', 'expect_node': 'n1', 'label': 'settings'}
    assert cb.score_hybrid(known, {'ok': True, 'source': 'jev', 'choice': 'n1'}) == (
        True, 'jev_node', 'n1')
    assert cb.score_hybrid(known, {'ok': True, 'source': 'jev', 'choice': 'n2'}) == (
        False, 'jev_false_node', 'n2')
    ok, mode, _ = cb.score_hybrid(
        known, {'ok': True, 'source': 'qwen', 'label': 'settings_menu',
                'jev': {'choice': 'none'}})
    assert (ok, mode) == (True, 'qwen')
    unknown = {'kind': 'unknown', 'expect_label': 'netflix_home'}
    assert cb.score_hybrid(unknown, {'ok': True, 'source': 'jev', 'choice': 'n1'})[0] is False
    assert cb.score_hybrid(
        unknown, {'ok': True, 'source': 'qwen', 'label': 'netflix_home'})[0] is True


def test_selected_samples_filters_kinds_uis_transforms_and_limit():
    manifest = {'samples': [
        {'kind': 'known', 'ui': 'a'},
        {'kind': 'modified', 'ui': 'a', 'transform': 'jpeg40'},
        {'kind': 'modified', 'ui': 'a', 'transform': 'overlay'},
        {'kind': 'unknown', 'ui': 'b'},
        {'kind': 'negative', 'ui': 'a'},
    ]}
    out = cb._selected_samples(manifest, uis={'a'}, transforms={'jpeg40'},
                               kinds={'modified'})
    assert len(out) == 1 and out[0]['transform'] == 'jpeg40'
    assert len(cb._selected_samples(manifest, kinds={'known', 'unknown'})) == 2
    assert len(cb._selected_samples(manifest, limit=1)) == 1


def test_summarize_counts_outcomes_per_arm_and_kind():
    samples = [{'ui': 'a'}, {'ui': 'a'}, {'ui': 'b'}]
    rows = [
        {'arm': 'jev', 'kind': 'known', 'ui': 'a', 'ok': True,
         'outcome': 'correct', 'ms': 100},
        {'arm': 'jev', 'kind': 'known', 'ui': 'a', 'ok': False,
         'outcome': 'abstain', 'ms': 200},
        {'arm': 'jev', 'kind': 'unknown', 'ui': 'b', 'ok': False,
         'outcome': 'false_node', 'ms': 300},
        {'arm': 'qwen', 'kind': 'known', 'ui': 'a', 'ok': True,
         'outcome': 'correct', 'ms': 50},
        {'arm': 'hybrid', 'kind': 'known', 'ui': 'a', 'ok': True,
         'outcome': 'correct', 'mode': 'jev_node', 'ms': 150},
    ]
    report = cb.summarize(rows, samples)
    assert report['arms']['jev:known']['n'] == 2
    assert report['arms']['jev:known']['ok'] == 1
    assert report['arms']['jev:known']['abstain'] == 1
    assert report['arms']['jev:known']['p50_ms'] == 100
    assert report['arms']['jev:unknown']['false_node'] == 1
    assert report['arms']['qwen:known']['false'] == 0
    assert report['arms']['hybrid:known']['by_mode']['jev_node'] == 1
    assert report['per_ui']['a']['jev:known']['n'] == 2


def test_markdown_report_renders_the_arm_and_cost_tables():
    report = {
        'date': '2026-10-17T00:00:00+00:00', 'n': 1, 'uis': ['a'], 'transforms': [],
        'arms': {'jev:known': {'n': 1, 'ok': 1, 'pct': 100.0, 'false_node': 0,
                               'abstain': 0, 'error': 0, 'p50_ms': 100, 'p95_ms': 100},
                 'hybrid:known': {'n': 1, 'ok': 1, 'pct': 100.0, 'false': 0,
                                  'error': 0, 'p50_ms': 150, 'p95_ms': 150}},
        'per_ui': {}, 'per_transform': {},
        'passes': {'jev': {'jev': {'calls': 1, 'cost': 0.0018}},
                   'hybrid': {'jev': {'calls': 1, 'cost': 0.0018},
                              'qwen': {'calls': 1, 'cost': 0.0002}}},
    }
    text = cb.markdown_report(report)
    assert '| arm | kind |' in text
    assert '| jev | known |' in text
    assert '| hybrid | 1 | $0.0018 | 1 | $0.0002 | $0.002 |' in text


def test_summarize_unknown_jev_abstention_is_correct():
    rows = [
        {'arm': 'jev', 'kind': 'unknown', 'ui': 'a', 'ok': False,
         'outcome': 'abstain', 'ms': 10},
        {'arm': 'jev', 'kind': 'unknown', 'ui': 'a', 'ok': False,
         'outcome': 'false_node', 'ms': 10},
    ]
    report = cb.summarize(rows, [{'ui': 'a'}])
    item = report['arms']['jev:unknown']
    assert item['ok'] == 1 and item['pct'] == 50.0
    assert item['abstain'] == 1 and item['false_node'] == 1
