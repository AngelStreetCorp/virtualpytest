"""ad_meter (TASK-90 goal 10): the learned channel mark, the cut rate, the break state machine, the repetition library, the KPIs.

Synthetic channel: programme scenes last 8 s and carry a small high-contrast mark in the top-right corner; ad scenes last 1.5 s and carry
none. No model and no recording is needed, so these run everywhere (the SRF 1 measurement is in the task doc, section 9).
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend_host', 'scripts'))

from monitor.analyzers import build_analyzers  # noqa: E402
from monitor.analyzers.ad_meter import AdMeterAnalyzer, SpotStore, MarkLearner, choose_corner, corner_patches  # noqa: E402
from monitor.events import ProfileEvents  # noqa: E402
from monitor.profiles import KpiSpec, EventSpec, load_profile  # noqa: E402

HZ = 2.0
MARK = (np.random.RandomState(7).rand(8, 20) > 0.5).astype(np.uint8) * 255


def scene_base(rng, level, w, h):
    """One scene's picture: its own brightness and smooth random blobs (nothing that correlates from one scene to the next)."""
    import cv2
    blobs = cv2.resize(rng.rand(6, 10).astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC)
    return np.clip(level + (blobs - 0.5) * 160, 0, 255).astype(np.uint8)


def with_mark(g, w):
    g = g.copy()
    s = w // 320
    g[8 * s:16 * s, w - 30 * s:w - 10 * s] = np.kron(MARK, np.ones((s, s), np.uint8))
    return np.dstack([g, g, g])


class Channel:
    """Feeds the analyzer one sample every 1/HZ s. `segments` is a list of (seconds, 'prog'|'ad'|'doc')."""

    def __init__(self, analyzer, folder='cap', width=320, height=180, seed=1, t0=1_000_000.0):
        self.a, self.folder, self.w, self.h = analyzer, folder, width, height
        self.rng = np.random.RandomState(seed)
        self.t = t0
        self.scene_until, self.level, self.base = 0.0, 100, None
        self.last = None

    def run(self, segments):
        """(seconds, kind) or (seconds, kind, seed): a seed starts the block's scenes from the same sequence every time (a repeated spot).
        Kinds: prog (mark, slow scenes), ad (no mark, fast scenes), doc (no mark, slow scenes), adslow (mark ON, slow scenes: an ad that
        shows the channel mark and cuts slowly)."""
        for seg in segments:
            seconds, kind = seg[0], seg[1]
            if len(seg) > 2:
                self.rng = np.random.RandomState(seg[2])
                self.scene_until = 0
            end = self.t + seconds
            while self.t < end:
                if self.t >= self.scene_until or self.base is None:
                    self.level = int(self.rng.randint(15, 235))
                    self.base = scene_base(self.rng, self.level, self.w, self.h)
                    self.scene_until = self.t + {'prog': 8.0, 'ad': 1.5, 'doc': 9.0, 'adslow': 8.0}[kind]
                f = with_mark(self.base, self.w) if kind in ('prog', 'adslow') else np.dstack([self.base] * 3)
                self.last = self.a.process_frame(self.folder, f, self.t)
                self.t += 1.0 / HZ
        return self.last


LIB_TEST = {'lib_min_repeat': 2, 'lib_run': 3, 'head_s': 15.0}      # the synthetic channel repeats its spots exactly: the shipped defaults are stricter


def make(tmp_path=None, **settings):
    settings = {**LIB_TEST, **settings}
    prof = load_profile('ad_meter')
    for k, v in settings.items():
        prof.img.analyzers[0].__pydantic_extra__[k] = v
    a = AdMeterAnalyzer(None, prof, library_dir_fn=(lambda f: str(tmp_path)) if tmp_path else None,
                        action_dir_fn=(lambda f: str(tmp_path)) if tmp_path else None)
    a.register_device('cap')
    return a


def test_manifest_is_valid_in_both_validators():
    import yaml
    from shared.src.lib.utils.monitor_profile import PROFILES_DIR, validate_manifest_light
    validate_manifest_light(yaml.safe_load(open(os.path.join(PROFILES_DIR, 'ad_meter.yaml'))), 'ad_meter')
    p = load_profile('ad_meter')
    assert p.ui.state_badge.event == 'ad_break' and p.ui.headline.unit == '%'
    assert isinstance(build_analyzers(None, p)[0], AdMeterAnalyzer)


def test_unknown_setting_is_refused():
    prof = load_profile('ad_meter')
    prof.img.analyzers[0].__pydantic_extra__['cuts_per_30'] = 8        # a typo
    with pytest.raises(ValueError, match='unknown settings'):
        AdMeterAnalyzer(None, prof)


def test_learns_the_marks_corner_and_scores_it():
    a = make()
    ch = Channel(a)
    r = ch.run([(60, 'prog')])
    assert r['ad']['state'] == 'learning'                              # under warmup_s of history
    r = ch.run([(240, 'prog')])
    assert r['ad']['state'] == 'program'
    assert r['ad']['corner'] == 'top-right'
    assert r['ad']['mark'] > 0.6


def test_a_break_is_found_with_its_span_and_the_overlay_state():
    a = make()
    ch = Channel(a)
    ch.run([(600, 'prog')])
    t_ad = ch.t
    mid = ch.run([(130, 'ad')])
    assert mid['ad']['state'] == 'ad'
    assert mid['events']['ad_break']['duration_ms'] > 60_000           # in progress, backdated to where the evidence began
    r = ch.run([(240, 'prog')])
    assert r['ad']['state'] == 'program'
    fired = a._state['cap'].events._fired['ad_break']
    assert len(fired) == 1
    start, end = fired[0][1]['span']
    assert abs(start - t_ad) < 40 and abs(end - (t_ad + 130)) < 15
    assert r['kpis']['breaks_per_hour'] == 1
    assert 0 < r['kpis']['ads_pct_today'] < 100
    assert r['kpis']['breaks_by_kind'] == {'new': 1}


def test_no_break_when_the_mark_is_gone_but_nothing_cuts():
    """A programme without the mark that does not cut fast (a bright documentary) is not an ad."""
    a = make()
    ch = Channel(a)
    ch.run([(600, 'prog')])
    r = ch.run([(150, 'doc')])
    assert not a._state['cap'].events._fired['ad_break']
    assert 'ad_break' not in r['events']


def test_a_short_candidate_is_dropped():
    a = make()
    ch = Channel(a)
    ch.run([(600, 'prog')])
    ch.run([(50, 'ad'), (200, 'prog')])                               # 50 s of evidence is under min_break_s
    assert not a._state['cap'].events._fired['ad_break']


def test_a_channel_change_is_learned_again():
    a = make()
    ch = Channel(a)
    ch.run([(600, 'prog')])
    a.reset_mark('cap')
    assert ch.run([(10, 'prog')])['ad']['state'] == 'learning'
    assert ch.run([(200, 'prog')])['ad']['state'] == 'program'


def test_mark_gone_for_long_without_cuts_relearns():
    a = make(relearn_after_s=120)
    ch = Channel(a)
    ch.run([(600, 'prog')])
    r = ch.run([(400, 'doc')])
    assert r['ad']['state'] in ('learning', 'no_mark', 'program')
    assert not a._state['cap'].events._fired['ad_break']


def test_repeated_spots_make_the_second_break_confirmed_and_the_library_persists(tmp_path):
    a = make(tmp_path)
    ch1 = Channel(a, seed=3)
    ch1.run([(600, 'prog')])
    # the same ad scenes both times: same seed for the ad frames' scenes
    def ad_block(ch):
        ch.rng = np.random.RandomState(99)
        ch.scene_until = 0
        ch.run([(130, 'ad')])
    ad_block(ch1)
    ch1.rng = np.random.RandomState(5)
    ch1.scene_until = 0
    ch1.run([(500, 'prog')])
    ad_block(ch1)
    r = ch1.run([(240, 'prog')])
    assert r['kpis']['breaks_by_kind'] == {'new': 1, 'confirmed': 1}
    assert os.path.isfile(os.path.join(str(tmp_path), 'ad_library.json'))
    lib = SpotStore(os.path.join(str(tmp_path), 'ad_library.json'))
    assert len(lib) > 20 and lib.active(2) > 20            # the second break repeated them: active spots now


def test_damaged_library_starts_empty(tmp_path):
    path = os.path.join(str(tmp_path), 'ad_library.json')
    open(path, 'w').write('{not json')
    assert len(SpotStore(path)) == 0


def test_library_is_bounded_and_forgets_the_oldest():
    lib = SpotStore(None, max_items=50, hamming=2)
    lib.add_break([int(x) for x in np.random.RandomState(1).randint(0, 2 ** 62, 200)], now=1.0, break_id=1)
    assert len(lib) == 50


def test_choose_corner_split_and_always_there():
    rng = np.random.RandomState(0)
    mark = np.concatenate([rng.uniform(0.6, 0.9, 80), rng.uniform(-0.1, 0.1, 20)])      # mark most of the time, gone sometimes
    noise = rng.uniform(-0.2, 0.2, 100)
    assert choose_corner(np.stack([noise, mark, noise, noise], axis=1)) == 1
    always = rng.uniform(0.6, 0.9, 100)
    assert choose_corner(np.stack([noise, always, noise, noise], axis=1)) == 1
    assert choose_corner(np.stack([noise, noise, noise, noise], axis=1)) is None
    assert choose_corner(np.zeros((5, 4))) is None


def test_full_resolution_frames_use_a_finer_patch_and_find_the_mark():
    g = np.zeros((720, 1280), np.uint8)
    assert corner_patches(g).shape == (4, 64, 128)
    a = make()
    ch = Channel(a, width=1280, height=720)
    r = ch.run([(300, 'prog')])
    assert r['ad']['corner'] == 'top-right' and r['frame_size'] == [1280, 720]


def test_pct_time_and_first_in_hour_in_profile_events():
    kpis = [KpiSpec(name='pct', of='b', window_s=100, pct_time=True),
            KpiSpec(name='first', of='b', window_s=3600, first_in_hour=True)]
    ev = ProfileEvents({'b': EventSpec(attr='state', equals='ad')}, kpis)
    ev.update([], [], 0.0)
    ev.update([], [{'track_id': 1, 'label': 'b', 'attrs': {'state': 'ad'}, 'span': (20.0, 40.0)}], 50.0)
    _, k, _ = ev.update([], [], 50.0)
    assert k['pct'] == 40.0                                            # 20 s of the 50 s observed
    _, k, _ = ev.update([{'label': 'b', 'track_id': 2, 'attrs': {'state': 'ad'}, 'start': 80.0}], [], 100.0)
    assert k['pct'] == 40.0                                            # 20 s + 20 s still open, over the 100 s window
    assert k['first'] is not None


def test_kpi_shapes_are_exclusive():
    with pytest.raises(ValueError):
        KpiSpec(name='x', of='b', window_s=10, pct_time=True, first_in_hour=True)
    with pytest.raises(ValueError):
        KpiSpec(name='x', of='b', window_s=10, pct_time=True, group_by='kind')


def test_the_incident_state_of_an_ads_kpi_is_evaluated():
    """ads_pct_hour above 35 % marks the incident active in the result (raised as an alert by the incident manager, test_profile_incidents)."""
    a = make()
    ch = Channel(a)
    ch.run([(300, 'prog'), (300, 'ad'), (200, 'prog')])
    r = ch.run([(1, 'prog')])
    assert 'ads_overload' in r['incidents']


# ---- "today" since local midnight, restart, DST, the break event format (owner follow-up) ------------------------------

def _zurich(y, mo, d, h=0, mi=0):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime(y, mo, d, h, mi, tzinfo=ZoneInfo('Europe/Zurich')).timestamp()


def _events(tz='Europe/Zurich'):
    from zoneinfo import ZoneInfo
    kpis = [KpiSpec(name='today', of='b', window_s=100000, pct_time=True, since_midnight=True),
            KpiSpec(name='rolling', of='b', window_s=86400, pct_time=True)]
    return ProfileEvents({'b': EventSpec(attr='state', equals='ad')}, kpis, tz=ZoneInfo(tz))


def _span(a, b):
    return {'track_id': 1, 'label': 'b', 'attrs': {'state': 'ad'}, 'span': (a, b)}


def test_today_resets_at_local_midnight_and_the_rolling_24h_does_not():
    ev = _events()
    start = _zurich(2026, 10, 12, 22, 0)
    ev.update([], [], start)
    ev.update([], [_span(_zurich(2026, 10, 12, 23, 50), _zurich(2026, 10, 13, 0, 10))], _zurich(2026, 10, 13, 0, 10))
    _, k, _ = ev.update([], [], _zurich(2026, 10, 13, 0, 20))
    assert k['today'] == 50.0                          # 10 of the 20 minutes since midnight
    assert round(k['rolling'], 1) == round(100 * 20 / 140, 1)   # 20 of the 140 minutes watched
    _, k, _ = ev.update([], [], _zurich(2026, 10, 13, 12, 0))
    assert k['today'] == round(100 * 10 / (12 * 60), 1)   # the 23:50-00:00 half belongs to yesterday


def test_today_on_a_dst_day_uses_the_real_length_of_the_day():
    for day, hours_since_midnight in ((_zurich(2026, 3, 29), 11), (_zurich(2026, 10, 25), 13)):
        ev = _events()
        ev.update([], [], day)
        ev.update([], [_span(day + 9 * 3600, day + 10 * 3600)], day + 10 * 3600)
        now = _zurich(2026, 3, 29, 12) if day == _zurich(2026, 3, 29) else _zurich(2026, 10, 25, 12)
        _, k, _ = ev.update([], [], now)
        assert round(now - day) == hours_since_midnight * 3600     # spring: 23 h day, autumn: 25 h day
        assert k['today'] == round(100 / hours_since_midnight, 1)


def test_a_break_open_across_midnight_counts_only_its_part_of_today():
    ev = _events()
    ev.update([], [], _zurich(2026, 10, 12, 23, 0))
    obs = [{'label': 'b', 'track_id': 9, 'attrs': {'state': 'ad'}, 'start': _zurich(2026, 10, 12, 23, 50)}]
    _, k, _ = ev.update(obs, [], _zurich(2026, 10, 13, 0, 20))
    assert k['today'] == 100.0                          # the break covers all of the 20 minutes of today so far


def test_a_restart_rebuilds_today_from_the_persisted_breaks(tmp_path):
    a = make(tmp_path, timezone='UTC')
    ch = Channel(a, seed=3)
    ch.run([(600, 'prog'), (130, 'ad'), (300, 'prog')])
    before = ch.last['kpis']['ads_pct_today']
    assert before > 0
    lines = [__import__('json').loads(x) for x in open(os.path.join(str(tmp_path), 'ad_breaks.jsonl'))]
    assert [x['type'] for x in lines if x['type'] != 'alive'] == ['start', 'break'] and any(x['type'] == 'alive' for x in lines)   # heartbeats in between
    # a new process on the same folder, 30 s later
    b = make(tmp_path, timezone='UTC')
    ch2 = Channel(b, seed=4, t0=ch.t + 30)
    after = ch2.run([(2, 'prog')])['kpis']['ads_pct_today']
    assert abs(after - before) < 1.5, (before, after)    # rebuilt from the file, not from memory (the new process saw nothing yet)
    assert [x['type'] for x in map(__import__('json').loads, open(os.path.join(str(tmp_path), 'ad_breaks.jsonl'))) if x['type'] == 'start'] == ['start', 'start']   # plus a second start marker


def test_old_lines_are_dropped_and_a_replay_ignores_its_own_future(tmp_path):
    import json
    path = os.path.join(str(tmp_path), 'ad_breaks.jsonl')
    t0 = 1_000_000.0
    with open(path, 'w') as f:
        f.write(json.dumps({'type': 'break', 'v': 1, 'start': t0 - 5 * 86400, 'end': t0 - 5 * 86400 + 200, 'kind': 'new'}) + '\n')   # too old
        f.write(json.dumps({'type': 'break', 'v': 1, 'start': t0 + 3000, 'end': t0 + 3200, 'kind': 'new'}) + '\n')                  # in this stream's future
        f.write('{broken\n')
    a = make(tmp_path, timezone='UTC')
    Channel(a, t0=t0).run([(2, 'prog')])
    dev = a._state['cap']
    assert not dev.events._fired['ad_break']
    lines = open(path).read().splitlines()
    assert len(lines) == 2 and all(json.loads(x) for x in lines)       # the old and the broken line are gone, the future one stays, plus the start marker


def test_the_break_event_has_what_the_timeline_page_reads(tmp_path):
    import json
    a = make(tmp_path, timezone='UTC')
    ch = Channel(a, seed=3)
    ch.run([(600, 'prog'), (130, 'ad'), (300, 'prog')])
    rec = [json.loads(x) for x in open(os.path.join(str(tmp_path), 'ad_breaks.jsonl')) if '"type":"break"' in x][0]
    assert set(rec) == {'type', 'v', 'id', 'device', 'channel', 'start', 'end', 'duration_s', 'confidence', 'confirmed', 'kind', 'opened_by',
                        'start_snapped', 'thumbs'}
    assert rec['type'] == 'break' and rec['v'] == 1 and rec['device'] == 'cap' and rec['id'] == f"cap:{int(rec['start'])}"
    assert rec['end'] - rec['start'] == rec['duration_s'] and 0 < rec['confidence'] <= 1
    assert isinstance(rec['channel'], str) and len(rec['channel']) == 8 and rec['confirmed'] is False and rec['kind'] == 'new'
    assert rec['opened_by'] == 'mark+cuts' and rec['start_snapped'] is False


def test_since_midnight_needs_pct_time_and_a_long_window():
    with pytest.raises(ValueError):
        KpiSpec(name='x', of='b', window_s=100000, since_midnight=True)
    with pytest.raises(ValueError):
        KpiSpec(name='x', of='b', window_s=86400, pct_time=True, since_midnight=True)


# ---- the library improves detection (owner follow-up) ---------------------------------------------------------------------

def _two_known_breaks(tmp_path, **settings):
    """A channel that has had two breaks made of the same spots (seed 99): the spots are active in the library now."""
    a = make(tmp_path, timezone='UTC', **settings)
    ch = Channel(a, seed=3)
    ch.run([(600, 'prog'), (130, 'ad', 99), (400, 'prog', 5), (130, 'ad', 99), (400, 'prog', 6)])
    return a, ch


def _breaks(tmp_path):
    import json
    return [json.loads(x) for x in open(os.path.join(str(tmp_path), 'ad_breaks.jsonl')) if '"type":"break"' in x]


def test_a_repeated_spot_opens_a_break_with_the_mark_on_screen_and_slow_cutting(tmp_path):
    a, ch = _two_known_breaks(tmp_path)
    t = ch.t
    ch.run([(110, 'adslow', 99), (300, 'prog', 7)])           # the same spots, the channel mark still on, scenes of 8 s: no cut evidence
    third = _breaks(tmp_path)[-1]
    assert abs(third['start'] - t) < 12 and third['opened_by'] == 'library' and third['confirmed'] is True
    t = ch.t
    ch.run([(110, 'doc', 99), (300, 'prog', 8)])             # the same spots again, mark gone but scenes of 9 s: no cut evidence either
    fourth = _breaks(tmp_path)[-1]
    assert abs(fourth['start'] - t) < 12 and fourth['opened_by'] == 'library'
    # the same block with the library off is not an ad as far as marks and cuts can tell
    b, ch2 = _two_known_breaks(tmp_path / 'off', lib_assist=False) if (tmp_path / 'off').mkdir() is None else (None, None)
    n = len(_breaks(tmp_path / 'off'))
    ch2.run([(110, 'adslow', 99), (300, 'prog', 7), (110, 'doc', 99), (300, 'prog', 8)])
    assert len(_breaks(tmp_path / 'off')) == n


def test_a_break_seen_only_once_cannot_open_anything(tmp_path):
    a = make(tmp_path, timezone='UTC')
    ch = Channel(a, seed=3)
    ch.run([(600, 'prog'), (130, 'ad', 99), (400, 'prog', 5)])
    assert a._state['cap'].library.active(2) == 0 and len(a._state['cap'].library) > 20      # candidates, none of them a spot
    ch.run([(110, 'adslow', 99), (300, 'prog', 7)])
    assert len(_breaks(tmp_path)) == 1                         # nothing opened on a spot that only one break has shown


def test_the_start_snaps_back_to_where_a_known_spot_began(tmp_path):
    a, ch = _two_known_breaks(tmp_path)
    t = ch.t
    ch.run([(130, 'ad', 99), (300, 'prog', 7)])
    snapped = _breaks(tmp_path)[-1]
    assert snapped['start_snapped'] is True and abs(snapped['start'] - t) < 4
    off = tmp_path / 'off'
    off.mkdir()
    b, chb = _two_known_breaks(off, lib_assist=False)
    tb = chb.t
    chb.run([(130, 'ad', 99), (300, 'prog', 7)])
    plain = _breaks(off)[-1]
    assert plain['start'] - tb > 8 and (plain['start'] - tb) > (snapped['start'] - t) + 5   # the evidence alone is late by its build-up time


def test_a_break_marked_not_an_ad_is_not_taken_again_and_not_counted(tmp_path):
    a = make(tmp_path, timezone='UTC')
    ch = Channel(a, seed=3)
    ch.run([(600, 'prog'), (130, 'ad', 7), (400, 'prog', 5)])  # a programme opener that cuts fast and has no mark: taken for a break
    first = _breaks(tmp_path)
    assert len(first) == 1
    before = a._state['cap'].events._fired['ad_break']
    assert len(before) == 1
    assert a.mark_not_ad('cap', first[0]['id']) is True
    assert a.mark_not_ad('cap', 'cap:123') is False
    assert a._state['cap'].library.active(1) == 0              # the library forgot it
    ch.run([(130, 'ad', 7), (400, 'prog', 6)])                 # the opener again
    assert len(_breaks(tmp_path)) == 1                         # no second break
    # a restart does not count the corrected break
    b = make(tmp_path, timezone='UTC')
    r = Channel(b, seed=9, t0=ch.t + 30).run([(2, 'prog')])
    assert r['kpis']['ads_pct_today'] == 0.0


def test_blank_frames_are_not_hashed():
    a = make(timezone='UTC') if False else make()
    black = np.zeros((180, 320, 3), np.uint8)
    for i in range(20):
        a.process_frame('cap', black, 1000.0 + i / HZ)
    dev = a._state['cap']
    assert all(blank for _t, _h, blank in dev.hashes)


def test_a_correction_applies_even_with_the_library_assist_off(tmp_path):
    a = make(tmp_path, timezone='UTC', lib_assist=False)
    ch = Channel(a, seed=3)
    ch.run([(600, 'prog'), (130, 'ad', 7), (400, 'prog', 5)])
    first = _breaks(tmp_path)
    assert len(first) == 1 and a.mark_not_ad('cap', first[0]['id']) is True
    ch.run([(130, 'ad', 7), (400, 'prog', 6)])
    assert len(_breaks(tmp_path)) == 1


def test_the_shipped_defaults_are_the_conservative_ones():
    from monitor.analyzers.ad_meter import DEFAULTS
    assert (DEFAULTS['lib_min_repeat'], DEFAULTS['lib_run'], DEFAULTS['head_s'], DEFAULTS['lib_assist']) == (3, 6, 0.0, True)


# ---- review 2: a break cannot stay open forever, the zap signal ----------------------------------------------------------

def test_a_break_that_never_ends_is_closed_as_suspect_overlong_and_teaches_nothing(tmp_path):
    a = make(tmp_path, timezone='UTC', max_break_s=600)
    ch = Channel(a, seed=3)
    ch.run([(600, 'prog'), (900, 'ad', 99)])                   # the channel went on cutting fast without its mark: a zap nobody told us about
    recs = _breaks(tmp_path)
    assert [r['kind'] for r in recs] == ['suspect_overlong'] and recs[0]['confirmed'] is False and recs[0]['confidence'] == 0.0
    dev = a._state['cap']
    assert dev.brk is None or dev.brk['start'] > recs[0]['end']        # it did not stay open
    assert not dev.events._fired['ad_break']                    # counted nowhere
    assert len(dev.library) == 0                                # and never taught to the library
    assert dev.learner.mark_id is None and ch.last['kpis']['ads_pct_hour'] < 100.0   # the mark is learned again; ads did not become 100 %


def test_the_hashes_of_an_open_break_are_capped(tmp_path):
    a = make(tmp_path, timezone='UTC', max_break_hashes=50)
    ch = Channel(a, seed=3)
    ch.run([(600, 'prog'), (200, 'ad', 99)])
    assert len(a._state['cap'].brk['hashes']) == 50


def test_a_zap_after_a_system_action_ends_the_break_and_relearns_the_mark(tmp_path):
    import json
    a = make(tmp_path, timezone='UTC')
    ch = Channel(a, seed=3)
    ch.run([(600, 'prog'), (150, 'ad', 99)])
    assert a._state['cap'].brk is not None
    with open(os.path.join(str(tmp_path), 'last_action.json'), 'w') as f:
        json.dump({'command': 'press_key', 'timestamp': ch.t - 1.0}, f)
    black = np.zeros((180, 320, 3), np.uint8)
    for i in range(6):
        a.process_frame('cap', black, ch.t + i / HZ)
    recs = _breaks(tmp_path)
    assert len(recs) == 1 and recs[0]['kind'] != 'suspect_overlong'          # closed as a break, at the last evidence before the zap
    assert recs[0]['end'] <= ch.t + 0.5
    assert a._state['cap'].brk is None and a._state['cap'].learner.mark_id is None
    assert a._state['cap'].last_result['ad']['state'] in ('learning', 'no_mark')


def test_a_black_frame_without_a_recent_action_is_not_a_zap(tmp_path):
    a = make(tmp_path, timezone='UTC')
    ch = Channel(a, seed=3)
    ch.run([(600, 'prog')])
    mark = a._state['cap'].learner.mark_id
    black = np.zeros((180, 320, 3), np.uint8)
    for i in range(6):
        a.process_frame('cap', black, ch.t + i / HZ)
    assert a._state['cap'].learner.mark_id == mark


# ---- review 2: a KPI incident needs a watched window and enough items ----------------------------------------------------

def _incident_events(kpi, incident):
    from monitor.profiles import IncidentSpec
    return ProfileEvents({'b': EventSpec(attr='state', equals='ad'), 'e': EventSpec(attr='label', equals='egg')}, [kpi],
                         {'inc': IncidentSpec(**incident)})


def test_a_kpi_incident_waits_until_the_window_has_been_watched():
    from monitor.profiles import KpiSpec as K
    ev = _incident_events(K(name='ads', of='b', window_s=3600, pct_time=True), {'kpi': 'ads', 'above': 35, 'window_s': 3600, 'min_watch_s': 1800})
    ev.update([], [], 0.0)
    ev.update([], [{'track_id': 1, 'label': 'b', 'attrs': {'state': 'ad'}, 'span': (10.0, 150.0)}], 160.0)
    _, k, inc = ev.update([], [], 170.0)
    assert k['ads'] > 80 and inc['inc'] == {'active': False, 'value': k['ads'], 'warming_up': True}    # 140 of 170 s are ads, nothing is believed yet
    _, k, inc = ev.update([{'label': 'b', 'track_id': 2, 'attrs': {'state': 'ad'}, 'start': 160.0}], [], 1900.0)
    assert inc['inc']['active'] is True and 'warming_up' not in inc['inc']                              # half an hour watched, still over 35 %


def test_the_default_wait_is_half_the_window_and_events_incidents_are_not_held_back():
    from monitor.profiles import KpiSpec as K
    ev = _incident_events(K(name='ads', of='b', window_s=1000, pct_time=True), {'kpi': 'ads', 'above': 1, 'window_s': 1000})
    ev.update([], [], 0.0)
    ev.update([{'label': 'b', 'track_id': 1, 'attrs': {'state': 'ad'}, 'start': 0.0}], [], 400.0)
    assert ev.update([{'label': 'b', 'track_id': 1, 'attrs': {'state': 'ad'}, 'start': 0.0}], [], 400.0)[2]['inc']['warming_up'] is True
    assert ev.update([{'label': 'b', 'track_id': 1, 'attrs': {'state': 'ad'}, 'start': 0.0}], [], 600.0)[2]['inc']['active'] is True
    from monitor.profiles import IncidentSpec
    ev2 = ProfileEvents({'b': EventSpec(attr='state', equals='ad')}, [], {'long': IncidentSpec(event='b', after_s=5)})
    ev2.update([], [], 0.0)
    assert ev2.update([{'label': 'b', 'track_id': 1, 'attrs': {'state': 'ad'}, 'start': 0.0}], [], 6.0)[2]['long']['active'] is True


def test_one_bad_egg_is_not_a_broken_rate():
    from monitor.profiles import KpiSpec as K
    kpi = K(name='bad_pct', of='e', window_s=300, pct_where=EventSpec(attr='condition', equals='bad'))
    ev = _incident_events(kpi, {'kpi': 'bad_pct', 'above': 5, 'window_s': 300, 'min_watch_s': 0})
    ev.update([], [], 0.0)
    egg = lambda c: {'track_id': 1, 'label': 'egg', 'attrs': {'condition': c}}
    _, k, inc = ev.update([], [egg('bad')], 10.0)
    assert k['bad_pct'] == 100.0 and inc['inc']['warming_up'] is True                                    # one egg: not enough to call it a rate
    for t in range(11, 20):
        ev.update([], [egg('good')], float(t))
    _, k, inc = ev.update([], [egg('good')], 21.0)
    assert k['bad_pct'] < 15 and 'warming_up' not in inc['inc'] and inc['inc']['active'] is True         # 10+ judged, 1 of 11 bad is 9 %, above 5
    ev_unset = _incident_events(kpi, {'kpi': 'bad_pct', 'above': 5, 'window_s': 300, 'min_watch_s': 0, 'min_samples': 0})
    ev_unset.update([], [], 0.0)
    assert ev_unset.update([], [egg('bad')], 1.0)[2]['inc']['active'] is True                           # the manifest can still ask for no minimum


def test_the_shipped_manifests_ask_for_a_warm_up_and_both_validators_check_the_keys():
    import yaml
    from shared.src.lib.utils.monitor_profile import PROFILES_DIR, validate_manifest_light
    egg = load_profile('egg_quality').incidents['broken_rate']
    assert (egg.min_watch_s, egg.min_samples) == (120, 10)
    assert load_profile('ad_meter').incidents['ads_overload'].min_watch_s == 1800
    raw = yaml.safe_load(open(os.path.join(PROFILES_DIR, 'ad_meter.yaml')))
    raw['incidents']['ads_overload']['min_watch_s'] = -1
    with pytest.raises(ValueError):
        validate_manifest_light(raw, 'ad_meter')
    from monitor.profiles import IncidentSpec
    with pytest.raises(ValueError):
        IncidentSpec(kpi='x', above=1, window_s=10, min_watch_s=-1)
    with pytest.raises(ValueError):
        IncidentSpec(event='b', after_s=5, min_samples=3)


# ---- review 2: a worker that fails every sample ----------------------------------------------------------------------

def test_a_worker_that_always_fails_drops_its_stale_result_and_logs_rarely(caplog, monkeypatch):
    import logging
    from monitor.analyzers.sampled import SampledWorkerAnalyzer

    class Broken(SampledWorkerAnalyzer):
        def process(self, folder, frame_path, ts):
            raise RuntimeError('model file gone')

    clock = [1000.0]
    monkeypatch.setattr('monitor.analyzers.sampled.time.time', lambda: clock[0])
    a = Broken(None, load_profile('ad_meter'), 2.0)
    a._state['cap'] = {'last_run': 0.0}
    a._latest['cap'] = {'incidents': {'ads_overload': {'active': True, 'value': 50.0}}}      # the last good result: an incident that would never clear
    with caplog.at_level(logging.ERROR, logger='capture_monitor'):
        for i in range(100):                                                                  # 50 s of failing samples at 2 Hz
            clock[0] += 0.5
            a._pending['cap'] = (f'/x/{i}.jpg', clock[0])
            a.run_pending()
        assert 'cap' not in a._latest                                                         # dropped after 5 in a row, frames stop carrying it
        assert len([r for r in caplog.records if r.levelno >= logging.ERROR]) <= 3            # the first failure, the drop, nothing at 2 Hz
        clock[0] += 61
        a._pending['cap'] = ('/x/late.jpg', clock[0])
        a.run_pending()
        assert 'in a row' in caplog.records[-1].getMessage() and '101 in a row' in caplog.records[-1].getMessage()   # then once a minute, with the count


def test_a_success_resets_the_failure_count(monkeypatch):
    from monitor.analyzers.sampled import SampledWorkerAnalyzer
    calls = []

    class Flaky(SampledWorkerAnalyzer):
        def process(self, folder, frame_path, ts):
            calls.append(ts)
            if len(calls) % 3:
                raise RuntimeError('x')
            self._latest[folder] = {'ok': True}

    clock = [1000.0]
    monkeypatch.setattr('monitor.analyzers.sampled.time.time', lambda: clock[0])
    a = Flaky(None, load_profile('ad_meter'), 2.0)
    a._state['cap'] = {'last_run': 0.0}
    for i in range(30):
        clock[0] += 0.5
        a._pending['cap'] = ('/x.jpg', clock[0])
        a.run_pending()
    assert a._latest.get('cap') == {'ok': True}                                              # never 5 failures in a row: the good result stays


# ---- review 2: the ui block once per chunk, not once per frame --------------------------------------------------------

def test_the_ui_block_is_written_once_per_chunk_and_not_in_every_chunk_entry(tmp_path, monkeypatch):
    from tests.backend_host.test_monitor_replay import run_replay
    from monitor.analyzers.ad_meter import AdMeterAnalyzer as A

    def configure():
        monkeypatch.setattr(A, 'start', lambda self: None)         # no thread: the test drives the worker

    out = run_replay(str(tmp_path), env_extra={'MONITOR_PROFILE': 'ad_meter'}, frames=60, configure=configure,
                     after_frame=lambda fm, name, folder: [a.run_pending() for a in fm.device_analyzers[folder]])
    live = [out['frames'][n] for n in sorted(out['frames'])][-30:]                                                  # after the first sample
    assert all(f['profile'] == 'ad_meter' and f['ui']['title'] == 'Ad meter' for f in live)                       # the live frame JSON still has it
    chunks = list(out['chunks'].values())
    assert chunks and all(c['ui']['title'] == 'Ad meter' for c in chunks)                                         # once per chunk
    assert all('ui' not in fr for c in chunks for fr in c['frames']) and sum(len(c['frames']) for c in chunks) > 5   # and in no chunk entry
    assert all('ad' in fr and fr['profile'] == 'ad_meter' for c in chunks for fr in c['frames'][-30:])


def test_chunk_fields_carry_no_ui_and_the_header_does():
    from monitor.analyzers.sampled import SampledWorkerAnalyzer
    a = SampledWorkerAnalyzer(None, load_profile('ad_meter'), 2.0)
    data = {'profile': 'ad_meter', 'ui': {'title': 'Ad meter'}, 'kpis': {}}
    assert 'ui' not in a.chunk_fields(data) and a.chunk_header(data) == {'ui': {'title': 'Ad meter'}} and a.chunk_header({'profile': 'tv_app'}) == {}


# ---- review 2: one bad line must not skip the restore -----------------------------------------------------------------

def test_a_malformed_record_is_skipped_and_the_rest_is_restored(tmp_path):
    import json
    path = os.path.join(str(tmp_path), 'ad_breaks.jsonl')
    t0 = 1_000_000.0
    good = {'type': 'break', 'v': 1, 'id': 'cap:1', 'start': t0 - 5000, 'end': t0 - 4800, 'kind': 'confirmed'}
    lines = [json.dumps({'type': 'start', 't': t0 - 6000, 'device': 'cap'}),
             json.dumps({'type': 'break', 'id': 'cap:2'}),                                   # no start / end: used to raise KeyError
             json.dumps({'type': 'break', 'id': 'cap:3', 'start': 'soon', 'end': None}),
             json.dumps({'type': 'start', 't': 'yesterday'}),
             json.dumps([1, 2, 3]), '"just a string"', '17', '{broken', json.dumps(good),
             json.dumps({'type': 'break', 'id': 'cap:4', 'start': t0 - 3000, 'end': t0 - 3500, 'kind': 'new'}),   # ends before it starts
             json.dumps({'type': 'break', 'id': 'cap:5', 'start': t0 - 2000, 'end': t0 - 1900, 'kind': 'suspect_overlong'})]   # not an ad
    open(path, 'w').write('\n'.join(lines) + '\n')
    a = make(tmp_path, timezone='UTC')
    Channel(a, t0=t0).run([(2, 'prog')])
    fired = a._state['cap'].events._fired['ad_break']
    assert [(round(x[1]['span'][0]), round(x[1]['span'][1]), x[1]['kind']) for x in fired] == [(round(t0 - 5000), round(t0 - 4800), 'confirmed')]
    assert a._state['cap'].events._watched == [(t0 - 6000, t0 - 1900)]                   # from the good start marker to the last thing the monitor wrote (a suspect break's end counts: it was running)
    kept = [json.loads(x) for x in open(path)]
    assert good in kept and all(isinstance(k, dict) for k in kept)                       # the broken lines are gone, the good one stays


# ---- review 2: an outage is not "watched without ads" -----------------------------------------------------------------

def test_downtime_does_not_dilute_the_percentage(tmp_path):
    a = make(tmp_path, timezone='UTC')
    ch = Channel(a, seed=3)
    ch.run([(600, 'prog'), (130, 'ad', 99), (300, 'prog', 5)])                    # about 1030 s watched, 130 s of ads
    before = ch.last['kpis']['ads_pct_today']
    assert 10 < before < 15
    # the monitor is down for 3 hours, then a new process starts on the same folder
    b = make(tmp_path, timezone='UTC')
    ch2 = Channel(b, seed=4, t0=ch.t + 3 * 3600)
    after = ch2.run([(60, 'prog')])['kpis']
    assert 9 < after['ads_pct_today'] < 14, after                                  # over the ~1090 s watched, not over 3 h 18 min (that would be about 1 %)
    assert 9 < after['ads_pct_24h'] < 14


def test_a_crash_leaves_heartbeats_that_bound_the_watched_time(tmp_path):
    import json
    a = make(tmp_path, timezone='UTC')
    ch = Channel(a, seed=3)
    ch.run([(600, 'prog')])
    marks = [json.loads(x) for x in open(os.path.join(str(tmp_path), 'ad_breaks.jsonl'))]
    alive = [m['t'] for m in marks if m['type'] == 'alive']
    assert marks[0]['type'] == 'start' and 8 <= len(alive) <= 10 and all(y - x >= 59 for x, y in zip(alive, alive[1:]))   # one a minute
    b = make(tmp_path, timezone='UTC')
    Channel(b, seed=4, t0=ch.t + 7200).run([(2, 'prog')])
    (watched,) = b._state['cap'].events._watched
    assert abs(watched[0] - marks[0]['t']) < 1 and abs(watched[1] - alive[-1]) < 1                                        # from the start to the last heartbeat
    assert b._state['cap'].events.watched_s(ch.t + 7202, 86400) < 700                                                    # the 2 h gap is not in it


def test_the_warm_up_counts_watched_time_not_time_since_the_first_start(tmp_path):
    a = make(tmp_path, timezone='UTC')
    ch = Channel(a, seed=3)
    ch.run([(100, 'prog')])
    b = make(tmp_path, timezone='UTC')
    Channel(b, seed=4, t0=ch.t + 7200).run([(5, 'prog')])
    assert b._state['cap'].events.watched_s(ch.t + 7205, 3600) < 200                                                     # not 2 h


# ---- review: a picture of every break (owner, 2026-10-26) ----------------------------------------------------------------

def test_a_break_keeps_thumbnails_and_names_them_in_its_record(tmp_path):
    a = make(tmp_path, timezone='UTC')
    Channel(a, seed=3).run([(600, 'prog'), (130, 'ad'), (300, 'prog')])
    rec = _breaks(tmp_path)[0]
    assert 3 <= len(rec['thumbs']) <= 6                        # one at the start, then every 30 s of a ~2 min break
    for name in rec['thumbs']:
        path = os.path.join(str(tmp_path), 'ads', name)
        assert os.path.isfile(path) and open(path, 'rb').read(2) == b'\xff\xd8'   # a JPEG


def test_a_dropped_candidate_leaves_no_thumbnails(tmp_path):
    a = make(tmp_path, timezone='UTC', min_break_s=400)        # no break this short is believed
    Channel(a, seed=3).run([(600, 'prog'), (130, 'ad'), (300, 'prog')])
    assert _breaks(tmp_path) == []
    ads = os.path.join(str(tmp_path), 'ads')
    assert not os.path.isdir(ads) or [n for n in os.listdir(ads) if n.startswith('b')] == []


def test_a_not_an_ad_request_file_is_applied_by_the_monitor(tmp_path):
    import json
    a = make(tmp_path, timezone='UTC')
    ch = Channel(a, seed=3)
    ch.run([(600, 'prog'), (130, 'ad', 7), (400, 'prog', 5)])
    brk = _breaks(tmp_path)[0]
    req = os.path.join(str(tmp_path), 'ads', 'requests')
    os.makedirs(req, exist_ok=True)
    with open(os.path.join(req, '1_x.json'), 'w') as f:            # what the host route writes
        json.dump({'break_id': brk['id']}, f)
    with open(os.path.join(req, '2_y.json'), 'w') as f:            # a break too old to unlearn: still recorded
        json.dump({'break_id': 'cap:123'}, f)
    ch.run([(10, 'prog', 6)])
    assert os.listdir(req) == []
    corrections = [json.loads(x) for x in open(os.path.join(str(tmp_path), 'ad_breaks.jsonl')) if '"type":"correction"' in x]
    assert {c['id'] for c in corrections} == {brk['id'], 'cap:123'}
    assert a._state['cap'].library.active(1) == 0

