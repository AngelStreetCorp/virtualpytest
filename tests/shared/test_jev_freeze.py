"""Freeze triage benchmark (TASK-38 goal 5): strip split, change metrics, facts, selection, report.
Offline: synthetic strips from freeze_strip.render_strip, a stub model. OCR tests skip without tesseract."""
import json
import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..')))

cv2 = pytest.importorskip('cv2')
np = pytest.importorskip('numpy')

from scripts.jev_freeze import decide, export, report  # noqa: E402
from shared.src.lib.ai.freeze_strip import render_strip  # noqa: E402
from shared.src.lib.ai import freeze_facts as metrics, freeze_triage  # noqa: E402


def _frame(seed: int, block_at=None) -> np.ndarray:
    rng = np.random.default_rng(seed)
    img = (rng.random((720, 1280, 3)) * 60 + 80).astype(np.uint8)
    img = cv2.GaussianBlur(img, (9, 9), 0)
    if block_at is not None:
        x, y = block_at
        img[y:y + 200, x:x + 300] = 250
    return img


def _strip(frames) -> np.ndarray:
    data = render_strip([(f, 1.5 * i) for i, f in enumerate(frames)], 'frozen 30.0 s | diff 0.10%')
    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)


@pytest.mark.parametrize('n', [2, 3])
def test_split_finds_the_tiles(n):
    strip = _strip([_frame(i) for i in range(n)])
    assert len(metrics.split_strip(strip)) == n


def test_identical_frames_barely_change_and_moving_block_does():
    base = _frame(1)
    still = metrics.measure(_strip([base, base.copy(), base.copy()]), with_ocr=False)
    assert still['first_last']['changed_pct'] < 1 and still['first_last']['regions_changed'] == 0
    moving = metrics.measure(_strip([base, _frame(1, (100, 400)), _frame(1, (800, 400))]), with_ocr=False)
    assert moving['first_last']['changed_pct'] > 5
    assert 1 <= moving['first_last']['regions_changed'] <= 8


def test_facts_never_carry_the_truth():
    m = metrics.measure(_strip([_frame(1), _frame(2)]), with_ocr=False)
    text = ' '.join(m['facts']).lower()
    assert 'static_screen' not in text and 'truth' not in text and len(m['facts']) >= 3


def test_truth_and_selection_prefer_human():
    assert metrics.truth_of({'incident_type': 'freeze'}) == 'freeze'
    assert metrics.truth_of({'static_screen': True}) == 'still'
    assert metrics.truth_of({'static_screen': False}) == 'moving'
    assert metrics.truth_of({}) is None
    rows = [{'id': 't', 'label_source': 'teacher', 'ground_truth': {'static_screen': False},
             'source_ref': {'alert_id': 'a1'}},
            {'id': 'h', 'label_source': 'human', 'ground_truth': {'static_screen': True},
             'source_ref': {'alert_id': 'a1'}},
            {'id': 'x', 'label_source': 'teacher', 'ground_truth': {}, 'source_ref': {'alert_id': 'a2'}}]
    out = export.select(rows)
    assert [(r['id'], r['truth']) for r in out] == [('h', 'still')]


def test_best_threshold():
    rows = [{'changed_pct': 0.1, 'truth': 'still'}, {'changed_pct': 0.3, 'truth': 'still'},
            {'changed_pct': 4.0, 'truth': 'moving'}, {'changed_pct': 9.0, 'truth': 'moving'}]
    best = metrics.best_threshold(rows)
    assert best['correct'] == 4 and 0.3 < best['threshold'] <= 4.0


def test_decide_hides_truth_and_report_scores(tmp_path):
    b = tmp_path
    rows = [{'id': 's1', 'truth': 'still', 'label_source': 'human'},
            {'id': 's2', 'truth': 'moving', 'label_source': 'teacher'}]
    facts = [{'id': 's1', 'n_frames': 3, 'facts': ['0% changed'], 'first_last': {'changed_pct': 0.0}},
             {'id': 's2', 'n_frames': 3, 'facts': ['9% changed'], 'first_last': {'changed_pct': 9.0}}]
    for name, recs in (('rows.jsonl', rows), ('facts.jsonl', facts)):
        (b / name).write_text(''.join(json.dumps(r) + '\n' for r in recs))
    seen = []

    def choose(resolution, state, options, **kw):
        seen.append((state, options, kw['refs']))
        pick = 'still' if '0%' in state['facts'][0] else 'still'
        return {'success': True, 'choice': pick, 'confidence': 0.95, 'cost': 0.00001}

    out = decide.run_decide(str(b), choose=choose, resolution='r')
    assert out['decided'] == 2
    for state, options, refs in seen:
        assert 'still' not in json.dumps(state) and 'moving' not in json.dumps(state)
        assert refs['truth'] in ('still', 'moving')
    assert decide.run_decide(str(b), choose=choose, resolution='r')['decided'] == 0
    text = report.build_report(str(b))
    assert 'Jev right: 1/2 (50%)' in text and 'moving -> still: 1' in text


@pytest.mark.skipif(shutil.which('tesseract') is None, reason='tesseract not installed')
def test_footer_is_read():
    m = metrics.measure(_strip([_frame(1), _frame(2), _frame(3)]))
    assert m['footer']['frozen_s'] == 30.0


def test_triage_rule_and_ui_question(tmp_path):
    assert freeze_triage.triage('freeze', 0.1) == 'keep'
    assert freeze_triage.triage('freeze', 0.8) == 'dismiss'
    assert freeze_triage.triage('freeze', None) == 'keep'
    assert freeze_triage.triage('moving', 0.0) == 'dismiss' and freeze_triage.triage('still', None) == 'dismiss'
    b = tmp_path
    (b / 'rows.jsonl').write_text(json.dumps({'id': 'f', 'truth': 'freeze', 'label_source': 'teacher',
                                              'device_model': 'stb'}) + '\n')
    (b / 'facts.jsonl').write_text(json.dumps({'id': 'f', 'n_frames': 3, 'facts': ['0% changed'],
                                               'first_last': {'changed_pct': 0.0},
                                               'text': {'read_first': 'Entdecken Filme', 'read_last': ''}}) + '\n')
    asked = []

    def choose(resolution, state, options, **kw):
        return {'success': True, 'choice': 'freeze', 'confidence': 0.7}

    def ask(resolution, state, questions, **kw):
        asked.append(state)
        return {'success': True, 'answers': {'ui': {'noul': 0.9}}}

    decide.run_decide(str(b), choose=choose, resolution='r', decide=ask)
    rec = json.loads((b / 'decisions.jsonl').read_text())
    assert rec['triage'] == 'dismiss' and rec['ui'] == 0.9
    assert asked[0]['words_first_frame'] == 'Entdecken Filme' and 'freeze' not in json.dumps(asked[0])
    assert 'False alerts dismissed' in report.build_report(str(b))


def test_facts_from_frames_match_the_strip_measurement():
    base = _frame(1)
    frames = [base, _frame(1, (100, 400)), _frame(1, (800, 400))]
    m = metrics.facts_from_frames(frames, with_ocr=False)
    assert m['n_frames'] == 3 and len(m['pairs']) == 2 and 'footer' not in m
    assert m['first_last']['changed_pct'] > 5 and len(m['facts']) >= 3
    still = metrics.facts_from_frames([base, base.copy()], with_ocr=False)
    assert still['first_last']['regions_changed'] == 0
    with pytest.raises(ValueError):
        metrics.facts_from_frames([base])


def test_camera_is_never_dismissed():
    assert freeze_triage.triage('still', 0.9, 'camera') == 'keep'
    assert freeze_triage.triage('moving', None, 'Camera_X') == 'keep'
    assert freeze_triage.triage('moving', None, 'H96_MAX') == 'dismiss'
