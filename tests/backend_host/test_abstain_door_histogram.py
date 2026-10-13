"""Abstain-door attribution: the three doors that used to drop candidates silently
(TASK-68 row 7) and the histogram that measures them (EXPERIMENT-01's stop condition).

Doors 1-3 already carried a reason; doors 4 (title disambiguation), 5 (dHash fallback
narrowing) and 6 (confidence floor) did not, so an abstain could not be told apart from a
narrowing and the "what share of the 61.6% is model-addressable" question had no input.
`reason` is additive: these tests pin that it never changes which candidates survive.

Fakes only — no device, no DB, no network. The matcher is the REAL ImageHelpers.
"""
import importlib
import importlib.util
import os
import sys

import cv2
import numpy as np
import pytest

ih = importlib.import_module('backend_host.src.controllers.verification.image_helpers')

_LOCALIZE = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..', 'features', 'avq', 'backend_host', 'localize'))


def _load_histogram():
    """The replay script lives under features/ (not an importable package) — load it by path."""
    path = os.path.join(_LOCALIZE, 'abstain_histogram.py')
    spec = importlib.util.spec_from_file_location('abstain_histogram', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ah = _load_histogram()


# ── the note chain: append, never overwrite ──────────────────────────────────────────

def test_a_note_is_set_when_there_was_no_reason():
    out = {}
    ih.ImageHelpers._note_reason(out, 'door 6')
    assert out == {'reason': 'door 6'}


def test_a_later_door_appends_and_keeps_the_earlier_one():
    """Doors 4/5/6 can fire in sequence on one frame. Overwriting would erase the fact that
    an earlier door narrowed the set — which is the whole point of the chain."""
    out = {'reason': 'low-content frame'}
    ih.ImageHelpers._note_reason(out, 'door 4')
    ih.ImageHelpers._note_reason(out, 'door 6')
    assert out['reason'] == 'low-content frame +door 4 +door 6'


def test_the_chain_uses_the_same_separator_as_the_existing_v6crop_marker():
    out = {'reason': 'anything +v6crop'}
    ih.ImageHelpers._note_reason(out, 'door 5')
    assert out['reason'].endswith(' +door 5')


def test_an_empty_reason_string_is_treated_as_no_reason():
    out = {'reason': ''}
    ih.ImageHelpers._note_reason(out, 'door 6')
    assert out['reason'] == 'door 6'


# ── attribution through the real matcher ──────────────────────────────────────────────

def _page(seed, n=140):
    rng = np.random.RandomState(seed)
    img = np.full((720, 1280, 3), 245, np.uint8)
    for _ in range(n):
        x, y = int(rng.randint(0, 1080)), int(rng.randint(0, 620))
        cv2.rectangle(img, (x, y), (x + int(rng.randint(40, 190)), y + int(rng.randint(20, 90))),
                      (0, 0, 0), int(rng.choice([2, -1])))
    return img


@pytest.fixture(scope='module')
def helpers():
    return ih.ImageHelpers(None, None)


@pytest.fixture(scope='module')
def node_fps(helpers):
    return [{'node_id': f'n{i}', 'label': f'n{i}', 'fingerprint': helpers.compute_fingerprint(_page(i))}
            for i in range(4)]


def test_a_black_frame_is_door_1_and_names_its_capture_state(helpers, node_fps):
    result = helpers.identify_screen(np.zeros((720, 1280, 3), np.uint8), node_fps)
    assert result['candidates'] == []
    assert result['reason'] == 'low-content frame'
    assert result['state'] == 'blackscreen'


def test_a_frame_far_from_every_stored_screen_is_door_5_and_carries_no_new_note(helpers, node_fps):
    """`no qualifying screen` is the v5 near-band exit (FP_SELF_DRIFT_FLOOR = 14 = the same 14
    as FP_CANDIDATE_MARGIN). It already had a reason; the new door-5 note must not double it,
    because identify_screen's own narrowing cannot empty the list."""
    blurred = cv2.GaussianBlur(np.roll(_page(0), 90, axis=1), (15, 15), 6)
    result = helpers.identify_screen(blurred, node_fps)
    assert result['candidates'] == []
    assert result['reason'].startswith('no qualifying screen')
    assert 'dHash fallback narrowing' not in result['reason']
    assert ah.door_of_note(result['reason']) == 5


def test_an_exact_frame_still_matches_with_no_reason(helpers, node_fps):
    result = helpers.identify_screen(_page(0), node_fps)
    assert [c['label'] for c in result['candidates']] == ['n0']
    assert not result.get('reason')


def test_the_confidence_floor_door_records_how_many_it_dropped_and_why(helpers, node_fps, monkeypatch):
    """Door 6 on a REAL frame: put the floor just above the confidence this frame really has, so
    the floor — not the v5 qualification — is what empties the list. Then the terminal note must
    be door 6 and name the floor it used."""
    img = np.roll(_page(0), 6, axis=1)                     # drifts, but stays inside the v5 band
    real = helpers.identify_screen(img, node_fps)
    assert real['candidates'], 'fixture drifted out of the v5 band'
    floor = round(real['candidates'][0]['confidence'] + 0.001, 3)
    monkeypatch.setattr(ih.ImageHelpers, 'FP_MIN_CONFIDENCE', floor)
    result = helpers.identify_screen(img, node_fps)
    assert result['candidates'] == []
    assert result['reason'].startswith('confidence floor: ')
    assert f'FP_MIN_CONFIDENCE {floor}' in result['reason']
    assert ah.door_of_note(result['reason']) == 6


def _stub_matchers(monkeypatch, cands, total=6):
    """Replace match_fingerprint_v6 with a FIXED candidate list.

    Doors 4-6 are fail-safe or unreachable on a synthetic page (door 5 can never empty the
    list; door 6 is unreachable because v5 pre-filters at region distance 14 while the floor
    needs ~115), so driving them needs a candidate list that puts them in play. Only the
    MATCHER's output is faked — the doors themselves are the real code.
    """
    monkeypatch.setattr(ih.ImageHelpers, 'match_fingerprint_v6',
                        lambda self, gray, regions, focus, crop, fps: {
                            'candidates': [dict(c) for c in cands],
                            'excluded_count': 0, 'total': total, 'reason': None})


def _tied_candidates():
    # region distance pairs (dhash_dist + second): 10, 12, 80 -> only the first two are a near band
    return [{'node_id': 'a', 'label': 'a', 'dist': 4, 'dhash_dist': 4, 'second': 6, 'confidence': 0.98},
            {'node_id': 'b', 'label': 'b', 'dist': 5, 'dhash_dist': 5, 'second': 7, 'confidence': 0.97},
            {'node_id': 'c', 'label': 'c', 'dist': 40, 'dhash_dist': 40, 'second': 40, 'confidence': 0.84}]


def test_door_5_records_its_narrowing_even_though_it_cannot_empty_the_list(helpers, monkeypatch):
    """Doors 4 and 5 are fail-safe (`0 < len(near) < len(cands)`), so they can NEVER abstain on
    their own. The note is the only evidence they fired, and the histogram needs it."""
    _stub_matchers(monkeypatch, _tied_candidates())
    result = helpers.identify_screen(_page(0), node_fps=[])
    assert [c['label'] for c in result['candidates']] == ['a', 'b']     # 'c' narrowed away
    assert result['reason'] == ('dHash fallback narrowing: 1 candidate(s) beyond best + '
                               'FP_CANDIDATE_MARGIN 14')
    assert ah.door_of_note(result['reason']) == 5


def test_the_floor_note_is_appended_after_an_earlier_door_rather_than_overwriting(helpers,
                                                                                monkeypatch):
    """Door 5 narrows, then door 6 empties what was left: BOTH must survive in the chain, and the
    terminal door (the one that actually abstained) must be door 6."""
    _stub_matchers(monkeypatch, _tied_candidates())
    monkeypatch.setattr(ih.ImageHelpers, 'FP_MIN_CONFIDENCE', 0.99)
    result = helpers.identify_screen(_page(0), node_fps=[])
    assert result['candidates'] == []
    assert ah.doors_seen(result) == [5, 6]
    assert result['reason'].startswith('dHash fallback narrowing: 1 candidate(s)')
    assert ' +confidence floor: 2 candidate(s) below FP_MIN_CONFIDENCE 0.99 (best 0.98)' in \
        result['reason']
    assert ah.classify(result)[:2] == ('abstain', 6)


def test_a_matched_frame_with_a_narrowing_note_keeps_its_candidates(helpers, monkeypatch):
    """The attribution is additive: a frame that still matched keeps its answer, and the note
    rides along without changing which candidates survived."""
    _stub_matchers(monkeypatch, _tied_candidates())
    monkeypatch.setattr(ih.ImageHelpers, 'FP_MIN_CONFIDENCE', 0.98)     # drops only 'b'
    result = helpers.identify_screen(_page(0), node_fps=[])
    assert [c['label'] for c in result['candidates']] == ['a']
    assert ah.doors_seen(result) == [5, 6]
    assert ah.classify(result)[0] == 'matched'


def _nav_focus(monkeypatch, scores):
    """Make the frame look like a NAV menu and pin the title scores the far-region gate will see."""
    monkeypatch.setattr(ih.ImageHelpers, '_focus_signature',
                        lambda self, img: {'kind': 'nav', 'x': 0.2, 'width': 0.05})
    monkeypatch.setattr(ih.ImageHelpers, 'title_pivot', staticmethod(lambda t: t or ''))
    monkeypatch.setattr(ih.ImageHelpers, '_title_text', lambda self, img: 'Home')
    it = iter(scores)
    monkeypatch.setattr(ih.ImageHelpers, 'title_score', lambda self, live, stored: next(it))


_NAV_FPS = [{'node_id': 'a', 'label': 'a', 'fingerprint': {'dhash': 'x', 'title': 'Home'}},
            {'node_id': 'b', 'label': 'b', 'fingerprint': {'dhash': 'y', 'title': 'Tips'}}]


def test_the_far_region_gate_records_door_4_when_the_title_corroborates_only_some_nodes(helpers,
                                                                                     monkeypatch):
    """Door 4 also lives INSIDE door 3's gate: the underline is far from the chrome, but the
    title did match one of the two candidates — so door 3 does not fire, the frame still
    matches, and the dropped candidate is recorded as door 4 rather than lost."""
    _stub_matchers(monkeypatch, [{'node_id': 'a', 'label': 'a', 'dist': 70, 'dhash_dist': 70,
                                  'confidence': 0.73},
                                 {'node_id': 'b', 'label': 'b', 'dist': 71, 'dhash_dist': 71,
                                  'confidence': 0.72}])
    _nav_focus(monkeypatch, [0.9, 0.1])              # 'a' corroborates, 'b' does not
    result = helpers.identify_screen(_page(0), _NAV_FPS)
    assert [c['label'] for c in result['candidates']] == ['a']
    assert result['reason'] == 'title disambiguation: 1 candidate(s) below title_score 0.5'
    assert ah.doors_seen(result) == [4]
    assert ah.classify(result)[0] == 'matched'


def test_the_far_region_gate_still_names_door_3_when_no_title_corroborates(helpers, monkeypatch):
    _stub_matchers(monkeypatch, [{'node_id': 'a', 'label': 'a', 'dist': 70, 'dhash_dist': 70,
                                  'confidence': 0.73},
                                 {'node_id': 'b', 'label': 'b', 'dist': 71, 'dhash_dist': 71,
                                  'confidence': 0.72}])
    _nav_focus(monkeypatch, [0.1, 0.2])              # neither corroborates
    result = helpers.identify_screen(_page(0), _NAV_FPS)
    assert result['candidates'] == []
    assert result['reason'].startswith('nav underline far from chrome, no title match')
    assert ah.doors_seen(result) == [3]


def test_the_matcher_used_by_the_replay_is_recorded_and_can_be_overridden(monkeypatch, tmp_path):
    """The report must say WHICH image_helpers answered, so a replay on a host that has not been
    deployed to is auditable rather than silently measuring the deployed matcher."""
    Helpers, path = ah.load_image_helpers()
    assert os.path.basename(path) == 'image_helpers.py'
    copy = tmp_path / 'candidate_image_helpers.py'
    copy.write_text(open(path).read())
    monkeypatch.setenv('VIRTUALPYTEST_IMAGE_HELPERS', str(copy))
    Candidate, candidate_path = ah.load_image_helpers()
    assert candidate_path == str(copy)
    assert Candidate.REASON_DOOR6_DROPPED == Helpers.REASON_DOOR6_DROPPED


def test_the_new_reasons_carry_the_door_the_histogram_reads(helpers, node_fps, monkeypatch):
    """Every note identify_screen writes must be classifiable to exactly one door."""
    img = np.roll(_page(0), 6, axis=1)
    real = helpers.identify_screen(img, node_fps)
    monkeypatch.setattr(ih.ImageHelpers, 'FP_MIN_CONFIDENCE',
                        round(real['candidates'][0]['confidence'] + 0.001, 3))
    result = helpers.identify_screen(img, node_fps)
    bucket, door, reason, _state = ah.classify(result)
    assert bucket == 'abstain' and door == 6 and reason


def test_a_result_with_candidates_is_never_counted_as_an_abstain(helpers, node_fps):
    result = helpers.identify_screen(_page(2), node_fps)
    assert ah.classify(result)[0] == 'matched'


# ── the histogram tally ──────────────────────────────────────────────────────────────

def _res(candidates=(), reason=None, state=None):
    r = {'candidates': list(candidates), 'excluded_count': 0, 'total': 4}
    if reason is not None:
        r['reason'] = reason
    if state is not None:
        r['state'] = state
    return r


def test_classify_attributes_a_chained_reason_to_its_last_door():
    reason = ('title disambiguation: 2 candidate(s) below title_score 0.5 +dHash fallback '
              'narrowing: 1 candidate(s) beyond best + FP_CANDIDATE_MARGIN 14 +confidence floor: '
              '1 candidate(s) below FP_MIN_CONFIDENCE 0.55 (best 0.5)')
    bucket, door, _reason, _state = ah.classify(_res(reason=reason))
    assert (bucket, door) == ('abstain', 6)
    assert ah.doors_seen(_res(reason=reason)) == [4, 5, 6]


def test_classify_reports_an_empty_result_with_no_reason_as_unattributed():
    assert ah.classify(_res())[0] == 'unattributed'
    assert ah.classify(_res(state='blackscreen'))[:2] == ('unattributed', None)


def test_an_unknown_reason_is_never_folded_into_a_door():
    result = _res(reason='no v5 region fingerprints')
    bucket, door, _r, _s = ah.classify(result)
    assert (bucket, door) == ('unattributed', None)


def test_every_door_string_image_helpers_can_write_maps_to_its_door():
    """The matcher's own exits (doors 1, 2, 3) plus the three new notes must all be readable."""
    assert ah.door_of_note('low-content frame') == 1
    assert ah.door_of_note('nav underline matched no node') == 2
    assert ah.door_of_note('nav underline far from chrome, no title match '
                           '(spurious underline / non-menu content)') == 3
    assert ah.door_of_note(ih.ImageHelpers.REASON_DOOR4_NARROWED.format(n=2)) == 4
    assert ah.door_of_note(ih.ImageHelpers.REASON_DOOR5_NARROWED.format(n=1, margin=14)) == 5
    assert ah.door_of_note(ih.ImageHelpers.REASON_DOOR6_DROPPED.format(
        n=1, floor=0.55, best=0.4)) == 6


def test_tally_counts_matched_abstained_and_named_states_separately():
    t = ah.Tally('g')
    t.add(_res([{'node_id': 'a', 'label': 'home'}], reason='some narrowing'))
    t.add(_res(reason='low-content frame', state='blackscreen'))
    t.add(_res(reason='nav underline matched no node'))
    assert (t.frames, t.matched, t.abstained) == (3, 1, 2)
    assert t.door_frames == {1: 1, 2: 1}
    assert t.states == {'blackscreen': 1}
    assert t.nodes == {'home': 1}


def test_a_narrowing_note_on_a_matched_frame_counts_as_seen_but_not_as_an_abstain():
    t = ah.Tally('g')
    t.add(_res([{'label': 'home'}], reason='title disambiguation: 1 candidate(s) below '
                                              'title_score 0.5'))
    assert (t.matched, t.abstained) == (1, 0)
    assert t.door_frames == {}
    assert t.door_seen == {4: 1}


def test_rows_are_sorted_by_frequency_and_rows_carry_the_fix():
    t = ah.Tally('g')
    for _ in range(5):
        t.add(_res(reason='confidence floor: 1 candidate(s) below FP_MIN_CONFIDENCE 0.55 (best 0.5)'))
    t.add(_res(reason='low-content frame', state='blackscreen'))
    t.add(_res(reason='nav underline matched no node'))
    rows = t.rows()
    assert [r[0] for r in rows] == [6, 1, 2]           # 5, 1, 1 — descending
    assert all(r[2] for r in rows)                     # every row states its fix
    assert rows[0][4] == 100 * 5 / 7


def test_the_stop_condition_number_is_doors_2_plus_5_plus_6_over_abstains():
    t = ah.Tally('g')
    t.add(_res(reason='low-content frame', state='blackscreen'))          # door 1
    t.add(_res(reason='nav underline matched no node'))                   # door 2
    t.add(_res(reason='nav underline far from chrome, no title match (x)'))  # door 3
    for _ in range(4):
        t.add(_res(reason='no qualifying screen (best region 42)'))        # door 5
    assert t.abstained == 7
    assert t.model_addressable_share() == pytest.approx(500 / 7)


def test_the_share_is_zero_not_a_crash_when_nothing_abstained():
    t = ah.Tally('g')
    t.add(_res([{'label': 'home'}]))
    assert t.model_addressable_share() == 0.0


def test_a_named_capture_state_is_counted_but_left_out_of_the_content_population():
    """`no_signal` / `blackscreen` are a capture-side fault, not an unidentified screen, and on a
    host whose STB is powered down they are most of the archive. They stay in the all-frames
    tally and are excluded from the door percentages the stop condition reads."""
    t = ah.Tally('g')
    t.add(_res(reason='low-content frame', state='no_signal'))     # named state + door 1
    t.add(_res(reason='no qualifying screen (best region 42)'))    # content, door 5
    t.add(_res([{'label': 'home'}], reason='title disambiguation: 1 candidate(s) below '
                                           'title_score 0.5'))
    assert (t.frames, t.abstained, t.states) == (3, 2, {'no_signal': 1})
    assert t.content_frames == 2 and t.content_abstained == 1 and t.content_matched == 1
    assert t.door_frames == {1: 1, 5: 1}
    assert t.content_door_frames == {5: 1}
    assert t.model_addressable_share() == 50.0
    assert t.model_addressable_share(content_only=True) == 100.0


def test_rows_can_be_read_for_the_content_population_only():
    t = ah.Tally('g')
    t.add(_res(reason='low-content frame', state='no_signal'))
    t.add(_res(reason='no qualifying screen (best region 42)'))
    assert [r[0] for r in t.rows()] == [1, 5]              # tied at 1 frame -> door number breaks it
    content = {r[0]: r[3] for r in t.rows(content_only=True)}
    assert content == {1: 0, 5: 1}      # door 1 still listed (it fired, on the no-signal frame)
    assert t.model_addressable_share(content_only=True) == 100.0


def test_merge_adds_the_content_counters_too():
    a, b = ah.Tally('a'), ah.Tally('b')
    a.add(_res(reason='low-content frame', state='blackscreen'))
    b.add(_res(reason='nav underline matched no node'))
    a.merge(b)
    assert (a.frames, a.abstained, a.content_frames) == (2, 2, 1)
    assert a.content_door_frames == {2: 1}


def test_merge_adds_every_counter():
    a, b = ah.Tally('a'), ah.Tally('b')
    a.add(_res(reason='low-content frame', state='blackscreen'))
    b.add(_res(reason='nav underline matched no node'))
    a.merge(b)
    assert (a.frames, a.abstained, a.unattributed) == (2, 2, 0)
    assert a.door_frames == {1: 1, 2: 1}
    assert a.states == {'blackscreen': 1}


def test_render_prints_a_frequency_ordered_table_with_a_percentage_per_door():
    t = ah.Tally('stb_tv')
    t.add(_res(reason='low-content frame', state='blackscreen'))
    for _ in range(3):
        t.add(_res(reason='nav underline matched no node'))
    md = ah.render([t])
    assert '| 2 | nav underline matched no node | semantic model | 3 | 75.0% | 3 |' in md
    assert '| 1 | low-content frame |' in md
    assert 'doors 2+5+6 = 75.0% of all abstains' in md
    assert '100.0% of the no-state abstains' in md   # the blackscreen frame left the content set
    assert md.index('| 2 | nav underline matched no node') < md.index('| 1 | low-content frame')


# ── frame discovery + the read-only cap ──────────────────────────────────────────────

def test_find_frames_walks_the_cold_hour_dirs_and_deduplicates(tmp_path):
    for hour in ('04', '05'):
        d = tmp_path / 'captures' / hour
        d.mkdir(parents=True)
        (d / f'capture_{hour}0001.jpg').write_bytes(b'')
    (tmp_path / 'captures' / 'notes.txt').write_bytes(b'')
    found = ah.find_frames(str(tmp_path))
    assert len(found) == 2 and all(f.endswith('.jpg') for f in found)


def test_find_frames_prefers_cold_and_ignores_the_live_hot_buffer_by_default(tmp_path):
    cold = tmp_path / 'captures' / '05'
    cold.mkdir(parents=True)
    (cold / 'capture_000001.jpg').write_bytes(b'')
    hot = tmp_path / 'hot' / 'captures'
    hot.mkdir(parents=True)
    (hot / 'capture_000002.jpg').write_bytes(b'')
    assert len(ah.find_frames(str(tmp_path), 'cold')) == 1
    assert len(ah.find_frames(str(tmp_path), 'hot')) == 1


def test_the_limit_samples_across_the_whole_archive_not_just_the_first_n():
    paths = [f'/f/{i:04d}.jpg' for i in range(1000)]
    picked = ah.sample(paths, 10)
    assert len(picked) == 10
    assert picked[0] == paths[0] and picked[-1] == paths[999]      # spans first..last


def test_a_limit_at_or_above_the_archive_size_is_a_no_op():
    paths = [f'/f/{i}.jpg' for i in range(5)]
    assert ah.sample(paths, 5) == paths and ah.sample(paths, 50) == paths


def test_a_corpus_becomes_one_node_fingerprint_per_screenshot(tmp_path):
    from image_helpers import ImageHelpers as Standalone      # the harness import convention
    helpers = Standalone(None, None)
    for i in range(3):
        cv2.imwrite(str(tmp_path / f'{i:03d}_home.jpg'), _page(i))
    node_fps = ah.load_node_fps_from_corpus(helpers, str(tmp_path))
    assert [n['label'] for n in node_fps] == ['000_home', '001_home', '002_home']
    assert all(n['fingerprint'].get('dhash') for n in node_fps)


def test_replay_writes_only_its_own_dump_and_counts_every_frame(tmp_path):
    from image_helpers import ImageHelpers as Standalone
    helpers = Standalone(None, None)
    for i in range(4):
        cv2.imwrite(str(tmp_path / f'n{i}.jpg'), _page(i))
    node_fps = ah.load_node_fps_from_corpus(helpers, str(tmp_path))
    frames = []
    for i in range(4):
        p = tmp_path / f'f{i}.jpg'
        cv2.imwrite(str(p), _page(i) if i == 0 else np.zeros((720, 1280, 3), np.uint8))
        frames.append(str(p))
    dump = tmp_path / 'frames.tsv'
    with open(dump, 'w') as fh:
        tally, samples = ah.replay(helpers, node_fps, frames, dump=fh)
    assert tally.frames == 4 and tally.matched == 1 and tally.door_frames.get(1) == 3
    assert len(samples) == 4
    assert [p.name for p in sorted(tmp_path.iterdir())] == ['f0.jpg', 'f1.jpg', 'f2.jpg',
                                                            'f3.jpg', 'frames.tsv',
                                                            'n0.jpg', 'n1.jpg', 'n2.jpg', 'n3.jpg']


def test_main_refuses_to_run_without_a_capture_dir_or_a_node_set():
    with pytest.raises(SystemExit):
        ah.main([])
    with pytest.raises(SystemExit):
        ah.main(['--capture', '/tmp', '--limit', '1'])