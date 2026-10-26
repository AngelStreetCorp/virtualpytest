"""egg_quality profile building blocks (TASK-90 goal 9): detector, voting with probabilities, focus crop, ui block, cold gate."""
import os
import sys

import cv2
import numpy as np
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
for p in (os.path.join(ROOT, 'backend_host', 'scripts'), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from monitor import profiles as P  # noqa: E402
from monitor.analyzers import pipeline as pl  # noqa: E402
from monitor.analyzers.egg_classify import EggClassify, crop_for_model  # noqa: E402
from monitor.analyzers.egg_detect import EggDetect  # noqa: E402
from monitor.analyzers.pipeline import PipelineAnalyzer  # noqa: E402
from monitor.tracking import make_tracker  # noqa: E402


def belt(eggs, size=(720, 1280)):
    img = np.zeros((*size, 3), np.uint8)
    for cx, cy, ax, ay, ang in eggs:
        cv2.ellipse(img, ((cx, cy), (ax, ay), ang), (40, 90, 255), -1)
    return img


# ---- detector ------------------------------------------------------------------------------

def test_egg_detect_finds_ellipses_with_their_shape():
    dets = EggDetect().detect(belt([(300, 350, 150, 110, 0), (900, 400, 160, 100, 30)]))
    assert len(dets) == 2
    (cx, cy, ax, ay, ang) = dets[0].shape['ellipse']
    assert (cx, cy) == pytest.approx((300, 350), abs=6) and ax == pytest.approx(150, abs=8) and ay == pytest.approx(110, abs=8)
    assert dets[1].shape['ellipse'][4] == pytest.approx(30, abs=8)          # the rotation survives
    assert dets[0].bbox[0] < dets[1].bbox[0]                               # left to right


def test_egg_detect_ignores_specks_and_empty_belts_and_reports_size():
    img = belt([(640, 360, 150, 110, 0)])
    cv2.circle(img, (100, 100), 6, (255, 255, 255), -1)                    # dust
    assert len(EggDetect().detect(img)) == 1
    assert EggDetect().detect(np.zeros((720, 1280, 3), np.uint8)) == []
    d = EggDetect(px_per_mm=3.0).detect(img)[0]
    assert d.size_mm == pytest.approx(150 / 3.0, abs=3)


# ---- crop and classifier loading --------------------------------------------------------------

def test_crop_for_model_is_square_and_keeps_the_aspect():
    img = np.full((720, 1280, 3), 255, np.uint8)
    c = crop_for_model(img, (100, 100, 200, 100))
    assert c.shape == (64, 64, 3) and c[0, 0].sum() == 0 and c[32, 32].sum() > 0     # padded top/bottom, egg in the middle


def test_missing_egg_model_names_the_env_var(monkeypatch):
    monkeypatch.delenv('MONITOR_EGG_MODEL', raising=False)
    with pytest.raises(FileNotFoundError, match='MONITOR_EGG_MODEL'):
        EggClassify(['good', 'bad'])


# ---- tracker cold start ----------------------------------------------------------------------

def test_cold_gate_follows_a_small_object_that_moves_more_than_its_size_between_samples():
    seq = [(i * 0.4, [('egg', (20 + 90 * i, 300, 70, 30))]) for i in range(8)]        # 90 px per sample, 70 px wide, no overlap
    def new(**kw):
        t = make_tracker('ocsort', min_iou=0.1, **kw)
        return sum(1 for now, d in seq for _, _, is_new in t.update(d, now) if is_new)
    assert new() == 8                                       # every sample a new object
    assert new(cold_gate=1.5) == 1


# ---- manifest --------------------------------------------------------------------------------

def test_shipped_egg_and_car_profiles_load_with_their_ui():
    egg = P.load_profile('egg_quality')
    assert egg.ui.title == 'Egg quality control' and egg.ui.box.shape == 'ellipse' and egg.ui.box.colour_by == 'verdict'
    assert [c.key for c in egg.ui.counters.items] == ['good', 'bad', 'unverified']
    assert egg.img.track.cold_gate == 1.5 and egg.img.track.votes == 3
    assert egg.incidents['broken_rate'].kpi == 'bad_pct'
    # BUG-0837: the headline is gone, the eggs/detections pair replaced it
    assert egg.ui.headline is None
    assert [(s.label, s.kpi, s.observations) for s in egg.ui.stats] == [
        ('Eggs', 'count_total', False), ('Detections', None, True)]
    cars = P.load_profile('counting_cars')
    # BUG-0927: at the rate the box allows, the picture supports the vehicles in view, not a traffic count
    assert cars.ui.box.shape == 'rect' and cars.ui.headline is None
    assert [(s.label, s.observations) for s in cars.ui.stats] == [('Vehicles in view', True)]
    assert cars.img.analyzers[0].model_dump().get('tiles') == [2, 2]


@pytest.mark.parametrize('mutate,match', [
    (lambda d: d['ui'].update(headline={'kpi': 'count_by_condition', 'label': 'x'}), 'plain'),
    (lambda d: d['ui']['stats'][0].update(kpi='count_by_condition'), 'plain'),
    (lambda d: d['ui']['stats'][0].update(observations=True), 'exactly one'),
    (lambda d: d['ui']['stats'][0].update(kpi=None), 'exactly one'),
    (lambda d: d['ui']['stats'][0].pop('kpi'), 'exactly one'),
    (lambda d: d['ui']['stats'][0].update(surprise=1), 'surprise|extra'),
    (lambda d: d['ui']['counters'].update(kpi='count_total'), 'group_by'),
    (lambda d: d['ui']['counters']['items'][0].update(colour='mauve'), 'mauve|colour'),
    (lambda d: d['ui']['box'].update(shape='star'), 'star|shape'),
    (lambda d: d['ui'].update(surprise=1), 'surprise|extra'),
])
def test_bad_ui_blocks_are_refused_by_both_validators(mutate, match):
    import yaml
    from shared.src.lib.utils.monitor_profile import validate_manifest_light
    raw = yaml.safe_load(open(os.path.join(P.PROFILES_DIR, 'egg_quality.yaml')))
    mutate(raw)
    with pytest.raises(Exception):
        P.Profile.model_validate(raw)
    with pytest.raises(ValueError):
        validate_manifest_light(raw, 'egg_quality')


# ---- pipeline: probabilities, verdicts, focus crop ----------------------------------------------

class ScriptedClassifier:
    attr = 'condition'

    def __init__(self, probs_per_vote):
        self.seq = iter(probs_per_vote)

    def classify_det(self, frame, det):
        probs = next(self.seq)
        return max(probs, key=probs.get), probs


def egg_pipeline(tmp_path, monkeypatch, probs_per_vote, votes=3, min_votes=2):
    prof = P.load_profile('egg_quality')
    prof.img.track.votes, prof.img.track.min_votes = votes, min_votes
    stages = {'egg_detect': EggDetect(), 'egg_classify': ScriptedClassifier(probs_per_vote)}
    monkeypatch.setattr(pl, '_build_stage', lambda spec: stages[spec.type])
    a = pl.PipelineAnalyzer(core=None, profile=prof)
    a.register_device('capture1')
    a.focus_dir_fn = lambda folder: str(tmp_path / 'meta')
    path = str(tmp_path / 'f.jpg')
    cv2.imwrite(path, belt([(640, 360, 150, 110, 0)]))
    return a, path


def test_votes_probabilities_verdict_and_focus(tmp_path, monkeypatch):
    votes = [{'good': 0.9, 'bad': 0.1}, {'good': 0.3, 'bad': 0.7}, {'good': 0.8, 'bad': 0.2}]
    a, path = egg_pipeline(tmp_path, monkeypatch, votes)
    outs = [a.process('capture1', path, ts=1000 + i * 0.4) for i in range(3)]
    o0, o2 = outs[0]['observations'][0], outs[2]['observations'][0]
    assert (o0['votes'], o0['verdict']) == ('1/3', None)
    assert (o2['votes'], o2['verdict']) == ('3/3', 'good')                       # majority of good, bad, good
    assert o2['probs'] == {'good': 0.667, 'bad': 0.333}                          # mean of the three votes
    assert o2['shape']['ellipse'][2] == pytest.approx(150, abs=8)
    f = outs[2]['focus']
    assert (f['track_id'], f['check'], f['checks'], f['verdict'], f['final']) == (1, 3, 3, 'good', True)
    assert f['crop'] and os.path.isfile(tmp_path / 'meta' / f['crop'])
    assert max(cv2.imread(str(tmp_path / 'meta' / f['crop'])).shape[:2]) <= 160   # a small jpeg, not the frame
    assert outs[2]['kpis']['count_total'] == 1 and outs[2]['kpis']['count_by_condition'] == {'good': 1}
    assert outs[2]['ui']['title'] == 'Egg quality control'


def test_an_egg_that_leaves_after_one_vote_is_unverified_and_the_focus_says_so(tmp_path, monkeypatch):
    a, path = egg_pipeline(tmp_path, monkeypatch, [{'good': 0.6, 'bad': 0.4}])
    a.process('capture1', path, ts=1000)
    r = a.settle('capture1', 1005)
    assert r['kpis']['count_by_condition'] == {'unverified': 1} and r['kpis']['bad_pct'] == 0.0


def test_old_crops_are_removed(tmp_path, monkeypatch):
    votes = [{'good': 0.9, 'bad': 0.1}] * 3
    a, path = egg_pipeline(tmp_path, monkeypatch, votes)
    monkeypatch.setattr(pl, 'FOCUS_CROPS_KEPT', 2)
    for i in range(3):
        a.process('capture1', path, ts=1000 + i * 0.4)
    assert len([f for f in os.listdir(tmp_path / 'meta') if f.startswith('focus_')]) == 2


@pytest.mark.skipif(not os.getenv('MONITOR_EGG_MODEL'), reason='needs MONITOR_EGG_MODEL (a locally trained egg classifier)')
def test_real_model_loads_and_answers():
    clf = EggClassify(['good', 'bad'])
    d = EggDetect().detect(belt([(640, 360, 150, 110, 0)]))[0]
    label, probs = clf.classify_det(belt([(640, 360, 150, 110, 0)]), d)
    assert label in ('good', 'bad') and sum(probs.values()) == pytest.approx(1.0, abs=1e-3)


def test_a_restart_removes_the_focus_crops_of_the_previous_run(tmp_path):
    import os
    import threading
    from monitor.analyzers.pipeline import PipelineAnalyzer
    from monitor.profiles import load_profile

    class NoModel(PipelineAnalyzer):                       # the detector model is not needed to register a device
        def __init__(self):
            self.profile = load_profile('counting_cars')
            self._lock = threading.Lock()
            self._state = {}
            self._algo, self._track_cfg = 'iou', {}
            self.focus_dir_fn = lambda folder: str(tmp_path)
    for n in ('focus_1_1.jpg', 'focus_9_3.jpg', 'capture_000000001.json', 'chunk_10min_0.json'):
        (tmp_path / n).write_bytes(b'x')
    NoModel().register_device('capture1')
    assert sorted(os.listdir(str(tmp_path))) == ['capture_000000001.json', 'chunk_10min_0.json']      # only the crops go



# ---- one box per egg: the blob method, for eggs that are not brighter than what is behind them ---------------

def test_the_blob_method_gives_one_box_per_egg_where_a_threshold_welds_them_into_one():
    # brown eggs on a grey machine: low absolute brightness, so the threshold path (bright egg, dark belt) is blind to
    # them, and the Otsu cut lands on the background instead
    img = np.full((720, 1280, 3), 90, np.uint8)
    for cx in range(240, 1100, 120):
        cv2.ellipse(img, (cx, 360), (48, 40), 0, 0, 360, (128, 112, 98), -1)
    dets = EggDetect(method='blob').detect(img)
    assert len(dets) == 8                                        # one per egg, not one per row
    assert all(d.shape['ellipse'][2] > 10 for d in dets)          # each carries the ellipse the overlay draws


def test_a_row_of_touching_eggs_is_one_blob_for_the_threshold_and_one_box_each_for_blob():
    img = np.zeros((720, 1280, 3), np.uint8)
    for cx in range(300, 1000, 116):                              # centres 116 apart, radii 55: they just touch
        cv2.ellipse(img, (cx, 360), (55, 50), 0, 0, 360, (40, 90, 255), -1)
    assert len(EggDetect().detect(img)) == 1                      # the candling detector: one long "egg" track
    assert len(EggDetect(method='blob').detect(img)) == 7         # one box per egg


def test_the_shipped_egg_profile_detects_with_the_blob_method():
    det = EggDetect(method='blob', blob_min_threshold=10, blob_min_circularity=0.45)
    spec = P.load_profile('egg_quality').img.analyzers[0]
    assert spec.type == 'egg_detect' and spec.method == 'blob' and spec.blob_min_threshold == 10


# ---- BUG-0836: the overlay has to sit on the eggs, so the boxes carry a velocity and the frame a capture time ----

def test_detect_width_finds_the_same_eggs_on_a_smaller_copy_and_scales_the_boxes_back():
    img = np.full((720, 1280, 3), 90, np.uint8)
    for cx in range(240, 1100, 120):
        cv2.ellipse(img, (cx, 360), (48, 40), 0, 0, 360, (128, 112, 98), -1)
    full = EggDetect(method='blob').detect(img)
    small = EggDetect(method='blob', detect_width=640).detect(img)
    assert len(small) == len(full) == 8
    # same boxes, in frame pixels of the ORIGINAL frame (a half-size image would report half the position)
    for f, s in zip(full, small):
        assert abs(f.bbox[0] - s.bbox[0]) < 12
        assert abs((f.bbox[0] + f.bbox[2] / 2) - (s.bbox[0] + s.bbox[2] / 2)) < 12
    assert abs(small[0].shape['ellipse'][0] - full[0].shape['ellipse'][0]) < 12


def test_detect_width_is_off_by_default_and_never_upscales_a_frame_that_is_already_small():
    img = np.full((720, 1280, 3), 90, np.uint8)
    cv2.ellipse(img, (400, 360), (48, 40), 0, 0, 360, (128, 112, 98), -1)
    assert len(EggDetect(method='blob').detect(img)) == len(EggDetect(method='blob', detect_width=800).detect(img)) == 1
    # a 320-wide frame is left alone: detect_width is a ceiling, not a scale factor
    tiny = cv2.resize(img, (320, 180))
    assert EggDetect(method='blob', detect_width=800).detect(tiny)[0].bbox == EggDetect(method='blob').detect(tiny)[0].bbox


def test_the_shipped_egg_profile_detects_at_800px_and_8hz():
    spec = P.load_profile('egg_quality').img.analyzers[0]
    # 8 Hz instead of 4 Hz is only affordable because the detector is 1.7x cheaper, and it halves the
    # time a box is drawn away from its egg before the client moves it forward
    assert spec.detect_width == 800 and spec.sample_hz == 8


def test_every_observation_carries_the_velocity_the_tracker_measured(tmp_path):
    # a belt moving right: the frame JSON must let the client put each box back on its egg. Detector only, so
    # the test needs no trained classifier -- the velocity comes from the tracker, not from the attributor.
    img = np.zeros((720, 1280, 3), np.uint8)
    cv2.ellipse(img, (160, 360), (34, 28), 0, 0, 360, (255, 255, 255), -1)     # one egg-shaped blob
    prof = P.Profile.model_validate({
        'name': 'eggs_only',
        'img': {'analyzers': [{'type': 'egg_detect', 'sample_hz': 8, 'method': 'blob'}],
                'track': {'algo': 'ocsort', 'max_gap_s': 1.0, 'min_iou': 0.1, 'votes': 1}},
        'events': {'egg_seen': {'attr': 'label', 'in': ['egg']}},
    })
    an = PipelineAnalyzer(core=None, profile=prof)
    an.register_device('capture1')
    seen = []
    for i, dx in enumerate((0, 25, 50, 75, 100)):                  # 25 px per 1/8 s = 200 px/s, a belt
        f = str(tmp_path / f'f{i}.jpg')
        cv2.imwrite(f, np.roll(img, dx, axis=1))
        seen.append(an.process('capture1', f, i * 0.125))
    moving = [o for o in seen[-1]['observations'] if o.get('v')]
    assert moving, 'the last frame has no observation with a velocity'
    # rightwards, at the 200 px/s the belt actually moves at
    assert any(120 < o['v'][0] < 320 for o in moving), moving
    # an egg that has not moved reports no motion at all rather than a made-up one
    cv2.imwrite(str(tmp_path / 'still.jpg'), img)
    still = PipelineAnalyzer(core=None, profile=prof)
    still.register_device('capture2')
    r = [still.process('capture2', str(tmp_path / 'still.jpg'), i * 0.125) for i in range(3)]
    assert all('v' not in o for o in r[-1]['observations'])


def test_captured_at_is_utc_with_an_offset_not_naive_local_time():
    # The client subtracts captured_at from its OWN clock to get the age, and a naive ISO string parses as
    # the browser's local time: a browser in another timezone would read the age off by hours and shift
    # every box by that much. A missing offset is therefore a silent, total failure of BUG-0836.
    from datetime import datetime, timezone
    import tempfile as _tf
    from monitor.analyzers.sampled import SampledWorkerAnalyzer

    class Bare(SampledWorkerAnalyzer):
        def process(self, folder, frame_path, ts):
            self._latest[folder] = {'observations': []}

    an = Bare(core=None, profile=None, sample_hz=8)
    from monitor.context import FrameContext
    ctx = FrameContext(capture_folder='capture1', device_index=1, sequence=1, timestamp=1_700_000_000.0,
                       frame_path='x.jpg', thumbnail=None, device_state={}, profile=None, filename='capture_000000001.jpg')
    an.analyze(ctx)
    an.run_pending()
    rec = an.frame_record(ctx, None, {})
    parsed = datetime.fromisoformat(rec['captured_at'])
    assert parsed.tzinfo is not None, f"captured_at has no offset: {rec['captured_at']}"
    assert parsed.utcoffset() == timezone.utc.utcoffset(None)
    # and it is the CAPTURE time, not the analysis time: 1000 s after the epoch, whatever "now" is
    assert parsed.timestamp() == 1_700_000_000.0


def test_the_frame_json_names_the_frame_the_boxes_were_measured_on():
    """The boxes belong to the ANALYSED frame, so the JSON must name that frame.

    The worker analyses one frame and its result is attached to every frame's JSON until the next
    analysis. The JSON of a LATER capture therefore carries boxes of an EARLIER frame, and the client
    draws the boxes on the picture it fetches from `filename` (BUG-0836's frame-lock). When `filename`
    was the later capture, the picture was newer than the boxes by up to one sample period plus one
    analysis time — and on a belt that put every circle on bare belt next to its egg: measured live on
    the device3 egg line, 19 px median offset and 33 of 223 circles on empty belt.
    """
    from monitor.analyzers.sampled import SampledWorkerAnalyzer
    from monitor.context import FrameContext

    class Bare(SampledWorkerAnalyzer):
        def process(self, folder, frame_path, ts):
            self._latest[folder] = {'observations': []}

    an = Bare(core=None, profile=None, sample_hz=8)
    analysed = FrameContext(capture_folder='capture1', device_index=1, sequence=1,
                            timestamp=1_700_000_000.0, frame_path='/x/capture_000000001.jpg',
                            thumbnail=None, device_state={}, profile=None,
                            filename='capture_000000001.jpg')
    an.analyze(analysed)
    an.run_pending()                       # the worker analyses THAT frame
    later = FrameContext(capture_folder='capture1', device_index=1, sequence=2,
                         timestamp=1_700_000_005.0, frame_path='/x/capture_000000002.jpg',
                         thumbnail=None, device_state={}, profile=None,
                         filename='capture_000000002.jpg')
    rec = an.frame_record(later, None, {})
    assert rec['filename'] == 'capture_000000001.jpg', 'the JSON must name the analysed frame, not the newer one'
    # and before any analysis there is nothing to name but the frame itself
    fresh = Bare(core=None, profile=None, sample_hz=8)
    assert fresh.frame_record(later, None, {})['filename'] == 'capture_000000002.jpg'
