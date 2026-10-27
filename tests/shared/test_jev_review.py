"""Offline tests for the Jev screen-review shadow (scripts/jev_review). No DB, no network, no AI."""

import json
import os
import shutil

import cv2
import numpy as np
import pytest

from scripts.jev_review import decide, evidence, export, matchers, report

AREA = {'x': 400, 'y': 300, 'width': 100, 'height': 60, 'fx': 300, 'fy': 250, 'fwidth': 300, 'fheight': 200}


def _frame(seed=0):
    return np.random.RandomState(seed).randint(0, 256, (720, 1280, 3), dtype=np.uint8)


def _with_reference(frame, x=400, y=300, w=100, h=60):
    ref = np.random.RandomState(99).randint(0, 256, (h, w, 3), dtype=np.uint8)
    out = frame.copy()
    out[y:y + h, x:x + w] = ref
    return out, ref


# ---- matchers ---------------------------------------------------------------------------------

def test_reference_pasted_in_the_fuzzy_window_scores_high_and_elsewhere_low():
    frame, ref = _with_reference(_frame())
    assert matchers.match_image(ref, frame, AREA)[:2] == (True, pytest.approx(1.0, abs=1e-3))
    # pasted 12px away from the exact spot: the fuzzy window still finds it
    moved, ref = _with_reference(_frame(), x=412, y=308)
    found, score, loc = matchers.match_image(ref, moved, AREA)
    assert found and score > 0.99 and (loc['x'], loc['y']) == (412, 308)
    # a window far from the paste
    far = dict(AREA, x=900, y=100, fx=800, fy=50, fwidth=300, fheight=200)
    assert matchers.match_image(ref, moved, far)[1] < 0.3


def test_area_only_compares_the_resized_reference_and_no_area_searches_the_frame():
    frame, ref = _with_reference(_frame())
    exact = {'x': 400, 'y': 300, 'width': 100, 'height': 60}
    assert matchers.match_image(ref, frame, exact)[1] == pytest.approx(1.0)
    assert matchers.match_image(ref, frame, dict(exact, x=900, y=100))[1] < 0.2
    found, score, loc = matchers.match_image(ref, frame, None)
    assert found and score > 0.99 and (loc['x'], loc['y']) == (400, 300)


def test_local_reimplementation_matches_the_host_helper():
    frame, ref = _with_reference(_frame())
    small = ref[:20, :30]                      # 600 px: the L1 branch
    small_frame = frame.copy()
    small_frame[310:330, 410:440] = small
    for template, source in ((ref, frame), (small, small_frame)):
        host = matchers.match_image(template, source, AREA)
        local = matchers.match_image(template, source, AREA, helpers=matchers._LocalImage())
        assert host[:2] == pytest.approx(local[:2])
    for extracted, target in (('Settings Home', 'Einstellungen'), ('Uber uns', 'Über'), ('Anrnelden', 'Anmelden')):
        assert matchers.text_helpers().text_match_score(extracted, target) == \
            pytest.approx(matchers._LocalText().text_match_score(extracted, target))


def test_check_image_pass_fail_and_inverted_disappear():
    frame, ref = _with_reference(_frame())
    assert matchers.check_image(frame, ref, AREA, 0.8) == {'kind': 'image', 'score': 1.0, 'threshold': 0.8,
                                                           'passed': True, 'inverted': False}
    absent = matchers.check_image(_frame(5), ref, AREA, 0.8, disappear=True)
    assert absent['inverted'] and absent['passed'] and absent['score'] > 0.7
    present = matchers.check_image(frame, ref, AREA, 0.8, disappear=True)
    assert present['inverted'] and not present['passed'] and present['score'] < 0.1


def test_areas_scale_with_the_frame_size():
    frame, ref = _with_reference(_frame())
    big_frame = cv2.resize(frame, (1920, 1080), interpolation=cv2.INTER_LINEAR)
    assert matchers.scale_area(AREA, 1.5, 1.5)['fx'] == 450
    assert matchers.check_image(big_frame, ref, AREA, 0.8)['score'] > 0.8


def test_text_normalisation_and_alternatives():
    assert matchers.score_text('Welcome to Einstellungen!', 'Settings|Einstellungen') == 1.0
    assert matchers.score_text('Ihre Uber Seite', 'Über') == 1.0           # accent folded
    assert matchers.score_text('Movies Series', 'Movies & Series') == 1.0  # punctuation dropped
    assert 0.8 <= matchers.score_text('Anrnelden', 'Anmelden') < 1.0
    assert matchers.score_text('Systerr', 'Über') < 0.8
    assert matchers.score_text('', 'x') == 0.0 and matchers.score_text('x', ' | ') == 0.0
    assert matchers.alternatives(' Settings | Einstellungen |') == ['Settings', 'Einstellungen']


@pytest.mark.skipif(shutil.which('tesseract') is None, reason='tesseract not installed')
def test_ocr_reads_a_rendered_word():
    frame = np.full((720, 1280, 3), 255, np.uint8)
    cv2.putText(frame, 'Settings', (100, 200), cv2.FONT_HERSHEY_SIMPLEX, 3, (0, 0, 0), 6)
    text = matchers.ocr_area(frame, {'x': 50, 'y': 100, 'width': 700, 'height': 150})
    assert matchers.score_text(text, 'Einstellungen|Settings') >= 0.8


def test_facts_line_formats():
    checks = [{'kind': 'image', 'name': 'settings_info_red', 'score': 0.93, 'threshold': 0.8, 'passed': True, 'inverted': False},
              {'kind': 'text', 'name': 'Settings|Einstellungen', 'score': 1.0, 'threshold': 0.8, 'passed': True, 'inverted': False}]
    assert matchers.format_facts(checks, 6, 64) == (
        "text 'Settings|Einstellungen' found 1.00; image check 'settings_info_red' 0.93 (pass at 0.80); "
        "seed frame 6 of 64 bits away")      # passed checks first, best score first
    assert matchers.format_facts([], None) == 'no reference evidence'
    assert matchers.format_facts([], 12) == 'seed frame 12 of 256 bits away'
    many = [{'kind': 'image', 'name': f'n{i}', 'score': i / 10, 'threshold': 0.8, 'passed': False, 'inverted': False} for i in range(5)]
    line = matchers.format_facts(many, None)
    assert line.startswith("image check 'n4' 0.40 (fail at 0.80)") and line.endswith('2 more checks, lower')
    inv = {'kind': 'image', 'name': 'x', 'score': 0.9, 'threshold': 0.8, 'passed': True, 'inverted': True}
    assert 'inverted' in matchers.format_facts([inv], None)
    assert matchers.best_score(checks + [inv], 'image') == 0.93 and matchers.best_score([], 'text') is None


def test_seed_bits():
    assert matchers.seed_bits('f' * 16, 'f' * 16) == 0
    assert matchers.seed_bits('f' * 16, '0' * 16) == 64
    assert matchers.seed_bits(None, 'f') is None


# ---- export: set selection --------------------------------------------------------------------

def _row(i, ui='stb-testop', source='run', triage=None):
    return {'id': f'r{i}', 'userinterface': ui, 'label_source': source, 'triage': triage,
            'ground_truth': {'node_id': 'n1', 'label': 'home'}}


def test_set_selection_on_fake_rows():
    rows = [_row(1, triage={'status': 'agreed'}),
            _row(2, triage={'status': 'excluded', 'reason': 'disagrees_with_run'}),
            _row(3, source='human'),
            _row(4, source='human', triage={'status': 'agreed'}),                      # human wins
            _row(5, triage={'status': 'excluded', 'reason': 'conflict'}),               # not a set
            _row(6, triage=json.dumps({'status': 'agreed'})),                           # triage as a JSON string
            _row(7, ui='acceptance-stb4-tv-20260901', triage={'status': 'agreed'}),    # deleted tree
            _row(8, ui='acceptance-stb4-tv-20260901', source='human'),
            _row(9, ui=None, triage={'status': 'agreed'}),
            _row(10, triage=None)]
    has_tree = lambda ui: ui == 'stb-testop'  # noqa: E731
    selected, skipped, taken = export.select_sets(rows, export.SETS, has_tree)
    assert [(s, r['id']) for s, r in selected] == [('agreed', 'r1'), ('disputed', 'r2'), ('human', 'r3'),
                                                   ('human', 'r4'), ('agreed', 'r6'), ('open', 'r10')]
    assert skipped == {'acceptance-stb4-tv-20260901': 2, '(none)': 1}
    assert dict(taken) == {'agreed': 2, 'disputed': 1, 'human': 2, 'open': 1}
    only, _, _ = export.select_sets(rows, ['disputed'], has_tree)
    assert [r['id'] for _s, r in only] == ['r2']
    limited, _, _ = export.select_sets(rows, ['agreed', 'human'], has_tree, limit=1)
    assert [r['id'] for _s, r in limited] == ['r1', 'r3']


def test_check_entries_resolve_references_by_reference_name_then_image_path():
    refs = {'settings_info_red_image': {'name': 'settings_info_red_image', 'area': {'x': 1, 'y': 2, 'width': 3, 'height': 4}},
            'settings_info_red': {'name': 'settings_info_red', 'area': None}}
    v = {'command': 'waitForImageToAppear', 'verification_type': 'image',
         'params': {'image_path': 'settings_info_red.jpg', 'reference_name': 'settings_info_red_image', 'threshold': 0.8}}
    entry = export.check_entry(v, refs)
    assert entry['reference'] == 'settings_info_red_image' and entry['area']['x'] == 1
    v['params'].pop('reference_name')
    assert export.check_entry(v, refs)['reference'] == 'settings_info_red'
    text = export.check_entry({'command': 'waitForTextToAppear', 'params': {'text': 'Home|Startseite', 'area': {'x': 0}}}, refs)
    assert text['name'] == 'Home|Startseite' and text['area'] == {'x': 0}
    assert export.check_entry({'command': 'press_key', 'params': {}}, refs) is None
    assert export.check_entry({'command': 'waitForTextToAppear', 'params': {'text': ' '}}, refs) is None


def test_row_record_keeps_only_the_triage_keys():
    row = dict(_row(1, triage={'status': 'agreed', 'teacher_label': {'label': 'home'}, 'teacher_model': 'x'}), dhash='ab', object_key='k')
    rec = export.row_record('agreed', row)
    assert set(rec['triage']) == set(export.TRIAGE_KEYS) and rec['set'] == 'agreed' and rec['object_key'] == 'k'


# ---- evidence ---------------------------------------------------------------------------------

def test_evidence_end_to_end_on_a_synthetic_bundle(tmp_path):
    bundle = str(tmp_path)
    frame, ref = _with_reference(_frame())
    os.makedirs(f'{bundle}/frames')
    os.makedirs(f'{bundle}/ui/app/refs')
    cv2.imwrite(f'{bundle}/frames/r1.png', frame)
    os.rename(f'{bundle}/frames/r1.png', f'{bundle}/frames/r1.jpg')  # jpg decoder reads by content
    cv2.imwrite(f'{bundle}/ui/app/refs/ref.png', ref)
    os.rename(f'{bundle}/ui/app/refs/ref.png', f'{bundle}/ui/app/refs/ref.jpg')
    groups = [{'node_id': 'g1', 'label': 'home', 'members': [{'node_id': 'g1', 'label': 'home', 'focus': None, 'seed': None, 'checks': [
                  {'command': 'waitForImageToAppear', 'name': 'ref', 'threshold': 0.8, 'area': AREA, 'reference_file': 'refs/ref.jpg'}]}]},
              {'node_id': 'g2', 'label': 'other', 'members': [{'node_id': 'g2', 'label': 'other', 'focus': None, 'seed': None, 'checks': []}]}]
    json.dump(groups, open(f'{bundle}/ui/app/groups.json', 'w'))
    row = {'id': 'r1', 'userinterface': 'app', 'dhash': 'ffffffff' * 8, 'set': 'agreed'}
    with open(f'{bundle}/rows.jsonl', 'w') as f:
        f.write(json.dumps(row) + '\n')
    meta = evidence.run_evidence(bundle, workers=1)
    rec = evidence.read_jsonl(f'{bundle}/evidence.jsonl')[0]
    assert meta['samples'] == 1 and rec['informative'] is True and 'frame_fact' not in rec
    g1, g2 = rec['groups']
    assert g1['best_image'] == pytest.approx(1.0, abs=0.02) and 'pass at 0.80' in g1['facts']
    assert g2['facts'] == 'no reference evidence' and g2['seed_distance'] is None
    assert os.path.exists(f'{bundle}/evidence_cache/r1.json')
    row['dhash'] = '0' * 64                                          # a rerun is incremental: the cache wins
    assert evidence._cached((bundle, row))['informative'] is True
    os.remove(f'{bundle}/evidence_cache/r1.json')
    assert evidence.sample_evidence(bundle, row)['frame_fact'] == evidence.LOW_INFO_FACT


# ---- decide: blindness ------------------------------------------------------------------------

def _decision_inputs():
    row = {'id': 's1', 'set': 'disputed', 'userinterface': 'stb-testop', 'device_model': 'stb4',
           'label_source': 'run', 'ground_truth': {'node_id': 'g1', 'label': 'RUNLABEL_home'},
           'triage': {'status': 'excluded', 'teacher_label': {'node_id': 'g2', 'label': 'TEACHER_settings'},
                      'first_pass': {'teacher_label': {'label': 'FIRST_apps'}}}}
    record = {'id': 's1', 'informative': False, 'frame_fact': evidence.LOW_INFO_FACT,
              'groups': [{'group_id': 'g1', 'label': 'home', 'facts': 'no reference evidence'},
                         {'group_id': 'g2', 'label': 'settings', 'facts': "text 'Settings' found 1.00"}]}
    return row, record


def test_state_and_options_never_hold_the_run_or_teacher_label():
    row, record = _decision_inputs()
    state, options, instructions, refs = decide.build_request(row, record)
    hidden = json.dumps([state, options, instructions])
    for secret in ('RUNLABEL', 'TEACHER', 'FIRST', 's1', 'disputed', 'agreed'):
        assert secret not in hidden
    assert state['frame'] == 'low-information' and options[1] == {'id': 'g2', 'facts': "text 'Settings' found 1.00"}
    assert refs['run_label'] == 'RUNLABEL_home' and refs['teacher_label'] == 'TEACHER_settings' and refs['truth'] is None
    row['set'], row['label_source'] = 'human', 'human'
    refs = decide.build_request(row, record)[3]
    assert refs['truth'] == 'RUNLABEL_home' and refs['run_label'] is None


def test_run_decide_with_a_stub_model_writes_decisions_and_resumes(tmp_path):
    bundle = str(tmp_path)
    row, record = _decision_inputs()
    for name, items in (('rows', [row]), ('evidence', [record])):
        with open(f'{bundle}/{name}.jsonl', 'w') as f:
            f.writelines(json.dumps(i) + '\n' for i in items)
    seen = []

    def choose(resolution, state, options, instructions, refs, log):
        seen.append((state, options, refs, log))
        return {'success': True, 'choice': 'g2', 'confidence': 0.91, 'cost': 0.0002, 'ms': 40, 'decision_id': 'd1',
                'probabilities': {'g1': 0.01, 'g2': 0.91, 'g3': 0.05, 'g4': 0.03}}
    out = decide.run_decide(bundle, choose=choose, resolution=object())
    rec = evidence.read_jsonl(f'{bundle}/decisions.jsonl')[0]
    assert out['decided'] == 1 and rec['choice'] == 'g2' and list(rec['probabilities']) == ['g2', 'g3', 'g4'] and seen[0][3] is True
    assert decide.run_decide(bundle, choose=choose, resolution=object())['decided'] == 0


def test_the_screen_review_usage_is_registered_under_text_decision():
    from shared.src.lib.ai import usages
    assert usages.USAGES[decide.USAGE].parent == 'text.decision'
    assert usages.lineage(decide.USAGE)[-1] == 'text.decision' or 'text.decision' in usages.lineage(decide.USAGE)


# ---- report -----------------------------------------------------------------------------------

def _stub_compare(family, truth, answer):
    if answer is None:
        return False, 'unparsed answer'
    return str(truth.get('node_id')) == str(answer.get('node_id')), ''


def test_report_scores_with_a_stub_comparator():
    def rw(i, set_name, truth, teacher=None, first=None):
        return {'id': i, 'set': set_name, 'userinterface': 'ui', 'ground_truth': {'node_id': truth, 'label': truth},
                'triage': {'teacher_label': {'node_id': teacher, 'label': teacher} if teacher else None,
                           'first_pass': {'teacher_label': {'node_id': first, 'label': first}} if first else None}}
    rows = [rw('a', 'agreed', 'g1', 'g1'), rw('b', 'agreed', 'g1', 'g1'), rw('c', 'human', 'g2', 'g1'),
            rw('d', 'agreed', 'g1', 'g1'), rw('e', 'disputed', 'g1', 'g2', 'g3'), rw('f', 'disputed', 'g1', 'g2', 'g1')]
    dec = {'a': ('g1', 0.95), 'b': ('g2', 0.7), 'c': ('g2', 0.85), 'd': (None, None), 'e': ('g2', 0.5), 'f': ('g1', 0.9)}
    decisions = {i: {'choice': c, 'confidence': p, 'cost': 0.001} for i, (c, p) in dec.items()}
    evid = {i: {'informative': i != 'd'} for i in dec}
    recs = report.score(rows, decisions, evid, {'ui': {'g1': 'home', 'g2': 'settings'}}, _stub_compare)
    by = {r['id']: r for r in recs}
    assert by['a']['jev_ok'] and not by['b']['jev_ok'] and by['c']['jev_ok'] and not by['d']['decided']
    assert by['c']['teacher_ok'] is False and by['a']['teacher_ok'] is True
    assert by['e']['with_teacher'] and not by['e']['with_run'] and not by['e']['with_first_pass']
    assert by['f']['with_run'] and by['f']['with_first_pass'] and not by['f']['with_teacher']
    text = report.render(recs, {'skipped_no_tree': {'gone': 3}}, lambda v: (v or {}).get('label') or '(unparsed)', 6)
    assert 'Set agreed' in text and 'Set human' in text and 'Set disputed' in text and '"gone": 3' in text
    assert 'low-information frames (separately)' in text and '| >=0.9 | 1 | 100.0% |' in text
    assert '| g1 | settings | 1 |' in text            # the confusion b: truth g1 -> Jev g2... (labels from the stub key)
    assert 'Jev sides with the run label: 1 (50.0%)' in text and '$0.0060 total' in text
    assert report.bucket_of(0.9) == '>=0.9' and report.bucket_of(0.85) == '0.8-0.9' and report.bucket_of(None) == '<0.6'


def test_report_reads_a_bundle_with_the_real_comparator(tmp_path):
    bundle = str(tmp_path)
    os.makedirs(f'{bundle}/ui/ui')
    json.dump([{'node_id': 'g1', 'label': 'home', 'members': []}], open(f'{bundle}/ui/ui/groups.json', 'w'))
    row = {'id': 'a', 'set': 'agreed', 'userinterface': 'ui', 'ground_truth': {'node_id': 'g1', 'label': 'home'},
           'triage': {'teacher_label': {'node_id': 'g1', 'label': 'home'}}}
    for name, item in (('rows', row), ('evidence', {'id': 'a', 'informative': True}),
                       ('decisions', {'id': 'a', 'choice': 'g1', 'confidence': 0.95, 'cost': 0.0001})):
        open(f'{bundle}/{name}.jsonl', 'w').write(json.dumps(item) + '\n')
    text = report.run_report(bundle)
    assert 'Jev correct 1 (100.0%)' in text and os.path.exists(f'{bundle}/report.md')


def test_open_set_is_what_the_second_pass_would_take():
    rows = [_row(1, triage=None),
            _row(2, source='none', triage={'status': 'needs_human', 'reason': 'low_confidence'}),
            _row(3, source='teacher', triage={'status': 'needs_human', 'reason': 'conflict'}),
            _row(4, triage={'status': 'needs_human', 'reason': 'spot_check'}),      # the human's audit
            _row(5, triage={'status': 'teacher_only'}),
            _row(6, triage={'status': 'excluded', 'reason': 'low_confidence'}),
            {**_row(7, triage=None), 'eval_version': 'eval-v1'}]                       # frozen
    selected, _, _ = export.select_sets(rows, ['open'], lambda ui: True)
    assert [r['id'] for _s, r in selected] == ['r1', 'r2', 'r3']
