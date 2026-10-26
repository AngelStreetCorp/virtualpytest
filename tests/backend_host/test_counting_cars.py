"""counting_cars building blocks on still images (TASK-90 goal 5): tracker, colour, detector decoding, pipeline."""
import os
import sys
import time

import cv2
import numpy as np
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
for p in (os.path.join(ROOT, 'backend_host', 'scripts'), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from monitor import profiles as P  # noqa: E402
from monitor.analyzers import coco_detect as cd  # noqa: E402
from monitor.analyzers.hsv_colour import classify_crop  # noqa: E402
from monitor.analyzers import pipeline as pl  # noqa: E402
from monitor.events import ProfileEvents  # noqa: E402
from monitor import tracking  # noqa: E402
from monitor.tracking import Tracker, iou, make_tracker  # noqa: E402


# ---- tracker -------------------------------------------------------------------------------

def test_one_object_over_many_frames_is_one_track():
    t = Tracker(max_gap_s=2.0, min_iou=0.3)
    new = 0
    for i in range(20):                                  # 20 samples at 2 Hz, the car drifts 6 px each time
        out = t.update([('car', (100 + 6 * i, 50, 80, 40))], now=i * 0.5)
        new += sum(1 for _, _, is_new in out if is_new)
    assert new == 1 and len(t.tracks) == 1
    assert next(iter(t.tracks.values())).hits == 20


def test_two_objects_two_tracks_and_ids_are_stable():
    t = Tracker()
    ids = []
    for i in range(5):
        out = t.update([('car', (10 + i, 10, 50, 30)), ('truck', (200 + i, 80, 90, 50))], now=i * 0.5)
        ids.append(tuple(tr.track_id for _, tr, _ in out))
    assert len(set(ids)) == 1 and len(ids[0]) == 2


def test_gap_longer_than_max_ends_the_track():
    t = Tracker(max_gap_s=2.0)
    t.update([('car', (10, 10, 50, 30))], now=0)
    out = t.update([('car', (10, 10, 50, 30))], now=2.5)  # same place, but the track expired
    assert out[0][2] is True and len(t.tracks) == 1


def test_a_different_label_never_matches():
    t = Tracker()
    t.update([('car', (10, 10, 50, 30))], now=0)
    out = t.update([('bus', (10, 10, 50, 30))], now=0.5)
    assert out[0][2] is True


def test_iou():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (20, 20, 5, 5)) == 0.0
    assert iou((0, 0, 10, 10), (5, 0, 10, 10)) == pytest.approx(1 / 3)


# ---- colour --------------------------------------------------------------------------------

def solid(bgr, size=(60, 100)):
    return np.full((size[0], size[1], 3), bgr, np.uint8)


@pytest.mark.parametrize('bgr,expected', [
    ((250, 250, 250), 'white'),
    ((15, 15, 15), 'black'),
    ((120, 120, 120), 'grey'),
    ((30, 30, 200), 'red'),
    ((200, 60, 30), 'blue'),
    ((40, 170, 40), 'green'),
    ((30, 210, 220), 'yellow'),
    ((20, 130, 230), 'other'),     # orange is not one of the classes
])
def test_solid_colours(bgr, expected):
    assert classify_crop(solid(bgr)) == expected


def test_car_like_crop_red_body_dark_windows_and_background_edge():
    img = solid((90, 90, 90), (80, 160))                         # grey road around the box
    img[16:64, 32:128] = (25, 25, 190)                           # red body (the central 60 %)
    img[24:36, 50:110] = (20, 20, 20)                            # dark window band
    assert classify_crop(img) == 'red'


# ---- detector decoding ---------------------------------------------------------------------

def test_letterbox_scale_and_padding():
    frame = np.zeros((180, 320, 3), np.uint8)
    canvas, r = cd.letterbox(frame, 416)
    assert r == pytest.approx(1.3) and canvas.shape == (416, 416, 3)
    assert (canvas[300:, :] == 114).all()                         # bottom padding


def test_postprocess_maps_a_box_back_to_frame_pixels_and_nms_merges_duplicates():
    size = 416
    out = np.zeros((3549, 85), np.float32)
    car = 2
    # anchor on the stride-8 grid cell (20, 10): box centre (20.5*8, 10.5*8)=(164, 84), size exp(1.5)*8 ~ 35.9
    def put(i, cx_off, conf):
        out[i, 0], out[i, 1] = cx_off, 0.5
        out[i, 2] = out[i, 3] = np.log(40 / 8)
        out[i, 4] = conf
        out[i, 5 + car] = 1.0
    cell = 10 * 52 + 20
    put(cell, 0.5, 0.9)
    put(cell + 1, 0.5 - 1.0 + 1.0, 0.8)                           # neighbour cell: nearly the same box -> NMS drops it
    dets = cd.postprocess(out, scale=1.0, frame_shape=(416, 416), size=size, class_ids=[car], min_conf=0.4, nms_iou=0.45)
    assert len(dets) == 1 and dets[0].label == 'car' and dets[0].conf == pytest.approx(0.9)
    x, y, w, h = dets[0].bbox
    assert (x + w / 2, y + h / 2) == pytest.approx((164, 84), abs=1)
    assert (w, h) == pytest.approx((40, 40), abs=1)
    half = cd.postprocess(out, scale=0.5, frame_shape=(832, 832), size=size, class_ids=[car], min_conf=0.4, nms_iou=0.45)
    assert half[0].bbox[2] == pytest.approx(80, abs=1)            # frame is twice the letterbox: boxes double


def test_postprocess_ignores_other_classes_and_low_confidence():
    out = np.zeros((3549, 85), np.float32)
    out[100, 4] = 0.9
    out[100, 5 + 0] = 1.0                                         # a person
    out[200, 4] = 0.3
    out[200, 5 + 2] = 1.0                                         # a car below min_conf
    assert cd.postprocess(out, 1.0, (416, 416), 416, [2], 0.4, 0.45) == []


def test_missing_model_names_the_env_var(monkeypatch):
    monkeypatch.delenv('MONITOR_COCO_MODEL', raising=False)
    with pytest.raises(FileNotFoundError, match='MONITOR_COCO_MODEL'):
        cd.CocoDetect(['car'])


# ---- events / KPIs -------------------------------------------------------------------------

def counting():
    prof = P.load_profile('counting_cars')
    return prof, ProfileEvents(prof.events, prof.kpis)


def obs(tid, label='car', colour='red'):
    return {'label': label, 'track_id': tid, 'attrs': {'colour': colour}}


def fin(tid, label='car', colour='red'):
    return {'track_id': tid, 'label': label, 'attrs': {'colour': colour}}


def test_kpis_count_final_verdicts_once_and_expire_with_the_window():
    prof, ev = counting()
    longest, kpis, _ = ev.update([obs(1)], [fin(1)], now=0)
    assert (kpis['count_per_min'], kpis['count_by_colour'], kpis['count_total']) == (1, {'red': 1}, 1)
    assert longest['car_seen']['duration_ms'] == 0
    for t in (0.5, 1.0, 1.5):                                     # same track, no new verdict: count stays 1
        longest, kpis, _ = ev.update([obs(1)], [], now=t)
    assert kpis['count_per_min'] == 1 and longest['car_seen']['duration_ms'] == 1500
    _, kpis, _ = ev.update([obs(2, 'bus', 'white')], [fin(2, 'bus', 'white')], now=10)
    assert (kpis['count_per_min'], kpis['count_by_colour']) == (2, {'red': 1, 'white': 1})
    _, kpis, _ = ev.update([], [], now=65)                        # 60 s window: only the one from t=10 is left
    assert kpis['count_per_min'] == 1 and kpis['count_by_colour'] == {'red': 1, 'white': 1}   # the 600 s window keeps both
    _, kpis, _ = ev.update([], [], now=75)
    assert kpis['count_per_min'] == 0 and kpis['count_by_colour'] == {'red': 1, 'white': 1}
    _, kpis, _ = ev.update([], [], now=700)
    assert kpis['count_by_colour'] == {}


def test_event_ignores_labels_it_does_not_name():
    prof, ev = counting()
    _, kpis, _ = ev.update([obs(1, 'person')], [fin(1, 'person', colour=None)], now=0)
    assert kpis['count_per_min'] == 0 and kpis['count_by_colour'] == {}


# ---- pipeline on still images --------------------------------------------------------------

class FakeDetector:
    def __init__(self):
        self.calls = 0

    def detect(self, frame):
        self.calls += 1
        x = 20 + 4 * self.calls                                   # the car drifts across the frames
        return [cd.Detection('car', 0.9, (x, 40, 80, 40))]


def test_pipeline_counts_one_red_car_seen_in_many_frames_once(tmp_path, monkeypatch):
    frame = np.full((180, 320, 3), 90, np.uint8)
    frame[48:72, 40:200] = (25, 25, 190)                          # red car body
    path = str(tmp_path / 'f.jpg')
    cv2.imwrite(path, frame)
    prof = P.load_profile('counting_cars')
    from monitor.analyzers.hsv_colour import HsvColour
    monkeypatch.setattr(pl, '_build_stage', lambda spec: FakeDetector() if spec.type == 'coco_detect' else HsvColour())
    a = pl.PipelineAnalyzer(core=None, profile=prof)
    a.register_device('capture1')
    last = None
    for i in range(12):
        last = a.process('capture1', path, ts=1000 + i * 0.5)
    assert len(last['observations']) == 1 and last['observations'][0]['track_id'] == 1
    assert last['observations'][0]['attrs'] == {'colour': 'red'}
    assert (last['kpis']['count_total'], last['kpis']['count_by_colour']) == (1, {'red': 1})
    assert last['frame_size'] == [320, 180]


def test_pipeline_rejects_a_manifest_without_a_detector_first():
    prof = P.load_profile('counting_cars')
    prof.img.analyzers.reverse()
    with pytest.raises(ValueError, match='one detector then attributors'):
        pl.PipelineAnalyzer(core=None, profile=prof)


@pytest.mark.skipif(not (os.getenv('MONITOR_COCO_MODEL') and os.getenv('MONITOR_TEST_IMAGE')),
                    reason='needs MONITOR_COCO_MODEL (yolox_nano.onnx) and MONITOR_TEST_IMAGE (a photo with a vehicle)')
def test_real_model_finds_a_vehicle_in_a_photo():
    det = cd.CocoDetect(['car', 'truck', 'bus'], min_conf=0.4)
    dets = det.detect(cv2.imread(os.environ['MONITOR_TEST_IMAGE']))
    assert dets and all(d.label in ('car', 'truck', 'bus') for d in dets)


# ---- inside the frame monitor --------------------------------------------------------------

def test_frame_monitor_writes_counting_output_into_every_frame_json(tmp_path, monkeypatch):
    """counting_cars through FrameMonitor with a stub detector: per-frame JSON carries the generic keys,
    the car is one track across 2 Hz samples, no subtitle work is requested."""
    from tests.backend_host.test_monitor_replay import run_replay   # the frozen-clock harness of the tv_app gate
    from monitor.analyzers.hsv_colour import HsvColour

    def configure():
        monkeypatch.setattr(pl, '_build_stage', lambda spec: FakeDetector() if spec.type == 'coco_detect' else HsvColour())
        monkeypatch.setattr(pl.PipelineAnalyzer, 'start', lambda self: None)   # no thread: the test drives the worker

    out = run_replay(str(tmp_path), env_extra={'MONITOR_PROFILE': 'counting_cars'}, frames=60, configure=configure,
                     after_frame=lambda fm, name, folder: [a.run_pending() for a in fm.device_analyzers[folder]])
    frames = [out['frames'][n] for n in sorted(out['frames'])]
    assert len(frames) == 60
    assert all(f['profile'] == 'counting_cars' and f['subtitle_ocr_pending'] is False for f in frames)
    assert 'blackscreen' not in frames[-1] and 'freeze' not in frames[-1]     # no tv_app keys
    last = frames[-1]
    assert len(last['observations']) == 1 and last['observations'][0]['track_id'] == 1
    assert last['kpis']['count_total'] == 1                                  # one car, 60 frames = 12 s = ~24 samples
    assert list(last['kpis']['count_by_colour']) and sum(last['kpis']['count_by_colour'].values()) == 1
    assert last['events']['car_seen']['duration_ms'] > 5000
    assert last['frame_size'] == [320, 180]
    chunk_frames = [fr for c in out['chunks'].values() for fr in c['frames']]
    assert chunk_frames and all(fr['profile'] == 'counting_cars' and isinstance(fr['observations'], list) for fr in chunk_frames)
    assert chunk_frames[-1]['kpis']['count_per_min'] == 1     # the archive playback overlay reads these from the chunk


# ---- a vehicle the detector calls car, then truck, is still one track (review WARN) ----------------

def test_label_flip_inside_an_event_group_keeps_one_track():
    t = Tracker(label_group=pl.label_groups(P.load_profile('counting_cars').events))
    new = 0
    for i, label in enumerate(['car', 'truck', 'car', 'bus', 'truck']):
        out = t.update([(label, (100 + 3 * i, 50, 80, 40))], now=i * 0.5)
        new += sum(1 for _, _, is_new in out if is_new)
    assert new == 1 and len(t.tracks) == 1 and next(iter(t.tracks.values())).label == 'car'   # first label kept
    out = t.update([('person', (100, 50, 80, 40))], now=3.0)      # not in the group: its own track
    assert out[0][2] is True


def test_pipeline_does_not_double_count_a_flipping_label(tmp_path, monkeypatch):
    frame = np.full((180, 320, 3), 90, np.uint8)
    path = str(tmp_path / 'f.jpg')
    cv2.imwrite(path, frame)
    labels = iter(['car', 'truck', 'car', 'truck'])

    class Flip:
        def detect(self, f):
            return [cd.Detection(next(labels), 0.9, (40, 40, 80, 40))]
    from monitor.analyzers.hsv_colour import HsvColour
    monkeypatch.setattr(pl, '_build_stage', lambda spec: Flip() if spec.type == 'coco_detect' else HsvColour())
    a = pl.PipelineAnalyzer(core=None, profile=P.load_profile('counting_cars'))
    a.register_device('capture1')
    for i in range(4):
        last = a.process('capture1', path, ts=1000 + i * 0.5)
    assert last['kpis']['count_total'] == 1 and [o['label'] for o in last['observations']] == ['car']


# ---- per-track voting (owner reference: "1/3 2/3 3/3", one verdict per track, unverified) -------------

class SeqColour:
    """An attributor that votes the given colours in order."""
    attr = 'colour'

    def __init__(self, seq):
        self.seq = iter(seq)

    def classify(self, frame, bbox):
        return next(self.seq)


class Still:
    """A detector that sees one car at the same place `n` times, then nothing."""

    def __init__(self, n):
        self.n = n

    def detect(self, frame):
        if self.n <= 0:
            return []
        self.n -= 1
        return [cd.Detection('car', 0.9, (40, 40, 80, 40))]


def voting_pipeline(tmp_path, monkeypatch, samples, colours, votes=3, min_votes=2):
    frame = np.full((180, 320, 3), 90, np.uint8)
    path = str(tmp_path / 'f.jpg')
    cv2.imwrite(path, frame)
    prof = P.load_profile('counting_cars')
    prof.img.track.votes, prof.img.track.min_votes = votes, min_votes
    stages = {'coco_detect': Still(samples), 'hsv_colour': SeqColour(colours)}
    monkeypatch.setattr(pl, '_build_stage', lambda spec: stages[spec.type])
    a = pl.PipelineAnalyzer(core=None, profile=prof)
    a.register_device('capture1')
    return a, path


def test_majority_of_three_votes_decides_the_colour_and_emits_one_event(tmp_path, monkeypatch):
    a, path = voting_pipeline(tmp_path, monkeypatch, samples=5, colours=['red', 'white', 'red'])
    seen = []
    for i in range(5):
        r = a.process('capture1', path, ts=1000 + i * 0.5)
        seen.append((r['observations'][0]['votes'] if r['observations'] else None, r['kpis']['count_per_min'],
                     dict(r['kpis']['count_by_colour'])))
    assert [s[0] for s in seen[:3]] == ['1/3', '2/3', '3/3']
    assert seen[0][1] == seen[1][1] == 0                  # nothing counted until the third vote
    assert seen[2][1:] == (1, {'red': 1})                 # red, white, red -> red, counted once
    assert seen[4][1:] == (1, {'red': 1})                 # more samples of the same track add nothing


def test_a_track_that_leaves_with_enough_votes_is_counted_with_its_majority(tmp_path, monkeypatch):
    a, path = voting_pipeline(tmp_path, monkeypatch, samples=2, colours=['blue', 'blue'])
    a.process('capture1', path, 1000)
    a.process('capture1', path, 1000.5)
    r = a.process('capture1', path, 1004)                 # nothing in view for longer than max_gap_s: the track ended
    assert r['kpis']['count_by_colour'] == {'blue': 1} and r['kpis']['count_per_min'] == 1


def test_a_track_that_leaves_with_too_few_votes_is_unverified(tmp_path, monkeypatch):
    a, path = voting_pipeline(tmp_path, monkeypatch, samples=1, colours=['green'])
    a.process('capture1', path, 1000)
    r = a.process('capture1', path, 1004)
    assert r['kpis']['count_per_min'] == 0                 # not a verified car ...
    assert r['kpis']['count_by_colour'] == {'unverified': 1}   # ... but counted, as unverified


def test_votes_one_keeps_the_old_behaviour(tmp_path, monkeypatch):
    a, path = voting_pipeline(tmp_path, monkeypatch, samples=3, colours=['red', 'blue', 'white'], votes=1, min_votes=1)
    r = a.process('capture1', path, 1000)
    assert 'votes' not in r['observations'][0] and r['kpis']['count_by_colour'] == {'red': 1}   # decided at first sight


# ---- trackers ------------------------------------------------------------------------------

def run_track(algo, dets_by_t, **kw):
    t = make_tracker(algo, **kw)
    new = 0
    for now, dets in dets_by_t:
        out = t.update(dets, now)
        new += sum(1 for _, _, is_new in out if is_new)
    return new, t


def test_ocsort_follows_an_accelerating_object_the_iou_tracker_loses():
    """A car that speeds up so that its next box no longer overlaps its last one: IoU opens new tracks; the box predicted from
    the track's observed velocity still overlaps, so the OC-SORT-style tracker keeps one track."""
    xs = [20, 50, 90, 140, 200, 270, 350]                  # steps of 30, 40, 50, 60, 70, 80 px; boxes 80 px wide
    seq = [(i * 0.5, [('car', (x, 60, 80, 40))]) for i, x in enumerate(xs)]
    assert run_track('iou', seq)[0] > 1
    assert run_track('ocsort', seq)[0] == 1


def test_ocsort_recovers_a_track_after_a_missed_detection():
    seq = [(0.0, [('car', (100, 60, 80, 40))]), (0.5, [('car', (110, 60, 80, 40))]), (1.0, []),
           (1.5, [('car', (130, 60, 80, 40))])]
    assert run_track('ocsort', seq)[0] == 1


def test_ocsort_keeps_two_crossing_objects_apart_by_direction():
    a = [(i * 0.5, [('car', (40 + 30 * i, 50, 60, 40)), ('car', (400 - 30 * i, 52, 60, 40))]) for i in range(10)]
    new, t = run_track('ocsort', a)
    assert new == 2 and len(t.tracks) == 2


def test_hungarian_is_optimal():
    cost = [[4, 1, 3], [2, 0, 5], [3, 2, 2]]
    pairs = dict(tracking.hungarian(cost))
    assert sum(cost[r][c] for r, c in pairs.items()) == 5                      # 1 + 2 + 2, not the greedy 0 + 4 + 2
    assert len(tracking.hungarian([[1, 2]])) == 1 and tracking.hungarian([]) == []
    assert len(tracking.hungarian([[1], [2], [3]])) == 1


def test_unknown_algo_is_refused():
    with pytest.raises(ValueError):
        make_tracker('kalman9000')


# ---- percentage KPIs and incidents -------------------------------------------------------------

def test_pct_where_kpi_leaves_unverified_out_and_the_incident_follows_it():
    prof = P.Profile.model_validate({
        'name': 'egg_like', 'img': {'analyzers': [{'type': 'coco_detect'}]},
        'events': {'egg_seen': {'attr': 'label', 'in': ['egg']}},
        'kpis': [{'name': 'broken_pct', 'of': 'egg_seen', 'window_s': 300,
                  'pct_where': {'attr': 'condition', 'in': ['cracked', 'dirty']}}],
        'incidents': {'broken_rate': {'kpi': 'broken_pct', 'above': 5, 'window_s': 300, 'min_watch_s': 0}}})     # no warm-up: this test is about the percentage
    ev = ProfileEvents(prof.events, prof.kpis, prof.incidents)

    def egg(tid, cond):
        return {'track_id': tid, 'label': 'egg', 'attrs': {'condition': cond}}
    fins = [egg(i, 'clean') for i in range(1, 10)] + [egg(10, 'unverified'), egg(11, 'cracked')]
    _, kpis, inc = ev.update([], fins, now=0)
    assert kpis['broken_pct'] == 10.0                     # 1 cracked of 10 verified; the unverified egg is not in it
    assert inc['broken_rate'] == {'active': True, 'value': 10.0}
    _, kpis, inc = ev.update([], [egg(12, 'clean')] * 10, now=1)
    assert kpis['broken_pct'] == round(100 * 1 / 20, 1) and inc['broken_rate']['active'] is False   # 5.0 is not above 5


# ---- findings of the public-clip run (class-agnostic NMS, parked vehicles) ---------------------------

def test_one_vehicle_with_a_car_and_a_truck_box_is_one_detection():
    out = np.zeros((3549, 85), np.float32)
    cell = 10 * 52 + 20
    for i, cls, conf in ((cell, 2, 0.9), (cell + 1, 7, 0.8)):          # car 0.9 and truck 0.8 on nearly the same box
        out[i, 0], out[i, 1] = 0.5, 0.5
        out[i, 2] = out[i, 3] = np.log(40 / 8)
        out[i, 4], out[i, 5 + cls] = conf, 1.0
    per_class = cd.postprocess(out, 1.0, (416, 416), 416, [2, 7], 0.4, 0.45, class_agnostic=False)
    agnostic = cd.postprocess(out, 1.0, (416, 416), 416, [2, 7], 0.4, 0.45, class_agnostic=True)
    assert len(per_class) == 2 and len(agnostic) == 1 and agnostic[0].label == 'car'      # the more confident one stays


def test_a_parked_vehicle_that_is_detected_on_and_off_is_one_track():
    box = ('truck', (590, 300, 80, 70))
    seq = [(0.0, [box]), (0.6, [box]), (1.2, [box]), (1.8, []), (7.0, []), (12.0, [('bus', (592, 301, 79, 69))])]
    for algo in ('iou', 'ocsort'):
        new, t = run_track(algo, seq, label_group=lambda label: 'vehicle')
        assert new == 1 and len(t.tracks) == 1, algo          # back after 10 s, same place, same group: the same vehicle
    new, _ = run_track('iou', [(0.0, [box]), (12.0, [box])])   # seen once only: not "parked", expires after max_gap_s
    assert new == 2


# ---- counting one pass of a looped clip (TASK-90: a videofile device plays the same file for ever) -----------

def reset_pipeline(tmp_path, monkeypatch, every_s, sees=8):
    """A cars pipeline over stub stages whose counters restart every `every_s` seconds (None = never)."""
    frame = np.full((180, 320, 3), 90, np.uint8)
    path = str(tmp_path / 'f.jpg')
    cv2.imwrite(path, frame)
    prof = P.load_profile('counting_cars')
    prof.img.reset_counters = P.ResetCounters(every_s=every_s) if every_s else None
    stages = {'coco_detect': Still(sees), 'hsv_colour': SeqColour(['red'] * 400)}
    monkeypatch.setattr(pl, '_build_stage', lambda spec: stages[spec.type])
    a = pl.PipelineAnalyzer(core=None, profile=prof)
    a.register_device('capture1')
    return a, path


def test_the_counters_start_again_when_the_source_does_so_they_describe_one_pass(tmp_path, monkeypatch):
    a, path = reset_pipeline(tmp_path, monkeypatch, every_s=10.0)
    clock = [1000.0]
    def pass_of(n_samples):
        seen = []
        for _ in range(n_samples):
            seen.append(a.process('capture1', path, clock[0]))
            clock[0] += 0.5
            a.process('capture1', path, clock[0])
            clock[0] += 0.2                                      # the car leaves on the next sample
        return seen
    first = pass_of(12)                                          # 8.4 s, still inside the 10 s pass
    assert a._state['capture1']['restarts'] == 0
    assert first[-1]['kpis']['count_total'] == 1                 # the one car of this pass, counted once
    second = pass_of(12)                                         # the clip starts over
    assert a._state['capture1']['restarts'] == 1                 # the source went round again
    assert second[-1]['kpis']['count_total'] < 1                 # so the counter is back near 0, not 2 for the day
    assert second[-1]['counting'] == {'restarts': 1, 'since': second[-1]['counting']['since']}


def test_a_profile_without_reset_counters_keeps_its_totals_for_the_whole_run(tmp_path, monkeypatch):
    a, path = reset_pipeline(tmp_path, monkeypatch, every_s=None, sees=200)
    for i in range(40):                                          # 20 s of the same clip, twice over
        a.process('capture1', path, 1000.0 + i * 0.5)
        a.process('capture1', path, 1000.5 + i * 0.5)
    assert a._state['capture1']['restarts'] == 0


def test_reset_counters_needs_a_trigger():
    import yaml
    from pydantic import ValidationError
    from monitor import profiles as P
    raw = yaml.safe_load(open(P.PROFILES_DIR + '/counting_cars.yaml'))
    raw['img']['reset_counters'] = {'for_samples': 2}
    with pytest.raises(ValidationError):
        P.Profile(**raw)


# ---- counting at a line (BUG-0915) ----------------------------------------------------------------
class _Belt:
    """Eggs moving right 20 px a sample; `drop` = the samples at which egg A is not detected, which ends its track."""
    def __init__(self, drop=()):
        self.i, self.drop = 0, set(drop)

    def detect(self, frame):
        i, self.i = self.i, self.i + 1
        out = []
        if i not in self.drop:
            out.append(cd.Detection('egg', 0.9, (20 + 20 * i, 40, 30, 30)))   # A crosses x = 160 at sample 6
        out.append(cd.Detection('egg', 0.9, (200 + 20 * i, 100, 30, 30)))      # B starts right of the line
        return out


def _line_pipeline(tmp_path, monkeypatch, belt, **track):
    path = str(tmp_path / 'f.jpg')
    cv2.imwrite(path, np.full((180, 320, 3), 90, np.uint8))
    prof = P.load_profile('egg_count_yolo_belt_fast')              # counts at x = 0.5, eggs, no attributor
    for k, v in track.items():
        setattr(prof.img.track, k, v)
    monkeypatch.setattr(pl, '_build_stage', lambda spec: belt)
    a = pl.PipelineAnalyzer(core=None, profile=prof)
    a.register_device('c')
    return a, path


def test_a_count_line_counts_what_crosses_it_and_nothing_born_past_it(tmp_path, monkeypatch):
    belt = _Belt()
    a, path = _line_pipeline(tmp_path, monkeypatch, belt)
    for i in range(5):                                              # A still left of the line, B right of it
        last = a.process('c', path, ts=1000 + i * 0.2)
    assert last['kpis']['count_total'] == 0
    for i in range(5, 9):
        last = a.process('c', path, ts=1000 + i * 0.2)
    assert last['kpis']['count_total'] == 1                       # A crossed; B never did


def test_a_track_broken_before_the_line_is_still_counted_once(tmp_path, monkeypatch):
    # A is missed for 2 s (10 samples) with max_gap_s 1: its track ends and a new one starts on the same egg.
    # Counted per track that is two eggs; counted at the line it is one.
    belt = _Belt(drop=range(2, 4))
    a, path = _line_pipeline(tmp_path, monkeypatch, belt, max_gap_s=0.3)
    for i in range(14):
        last = a.process('c', path, ts=1000 + i * 0.2)
    assert last['kpis']['count_total'] == 1



def test_the_worker_waits_only_until_the_next_frame_is_due(tmp_path, monkeypatch):
    """A frame that arrives just before its slot is analysed when the slot opens, not one whole period later (BUG-0917)."""
    a, path = _line_pipeline(tmp_path, monkeypatch, _Belt())
    period = 1.0 / a.sample_hz
    assert a._next_due_in(period) == pytest.approx(period)             # nothing pending: the plain period
    a._state['c']['last_run'] = time.time() - period + 0.01         # ran 10 ms short of a period ago
    a._pending['c'] = (path, 0.0)
    assert a._next_due_in(period) <= 0.011


def test_tiles_find_each_vehicle_once_in_frame_pixels():
    """2x2 tiles (BUG-0927): a box found in a tile comes back in frame pixels, and a vehicle in the overlap of two tiles
    is one box after the merge."""
    d = cd.CocoDetect.__new__(cd.CocoDetect)
    d.tiles, d.tile_overlap, d.min_conf, d.nms_iou = (2, 2), 0.15, 0.25, 0.45

    def one(crop):                                   # "detects" the white block wherever it is in the crop
        ys, xs = np.nonzero(crop[:, :, 0] > 200)
        if not len(xs):
            return []
        return [cd.Detection('car', 0.9, (float(xs.min()), float(ys.min()), float(xs.ptp() + 1), float(ys.ptp() + 1)))]
    d._detect_one = one
    frame = np.zeros((720, 1280, 3), np.uint8)
    frame[100:120, 600:640] = 255                    # in the top-left AND the top-right tile (they overlap at 544-736)
    out = d.detect(frame)
    assert len(out) == 1
    assert out[0].bbox == (600.0, 100.0, 40.0, 20.0)


def test_with_a_count_line_the_focus_is_the_last_object_counted(tmp_path, monkeypatch):
    """The gold outline / "Last egg" is the egg that just crossed the line, not the newest track to vote (often a stray
    low-confidence box on bare belt)."""
    a, path = _line_pipeline(tmp_path, monkeypatch, _Belt())
    for i in range(5):                                              # nothing has crossed yet: no focus
        last = a.process('c', path, ts=1000 + i * 0.2)
    assert last.get('focus') is None
    for i in range(5, 9):                                           # A crosses at sample 6
        last = a.process('c', path, ts=1000 + i * 0.2)
    a_track = next(o['track_id'] for o in last['observations'] if o['bbox'][1] == 40)
    assert last['focus']['track_id'] == a_track
