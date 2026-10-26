"""yolo_seg_detect: the parts that do not need the model file (the ONNX is not in git).

The head-decoding and NMS here are the two places where a plausible-looking mistake silently
destroys the result, so they are pinned with the numbers they have to reproduce:

* `nms` must take (x, y, w, h). Handing `cv2.dnn.NMSBoxes` xyxy makes every box overlap every other
  and deletes most of them, which is how a correct model measured at 36 boxes instead of 87.
* `_tiles` must overlap, or the eggs straddling a tile edge lose their circle.
* the sliver filter must throw away a clipped box and keep a real egg.
"""
import os
import sys

import numpy as np
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
for p in (os.path.join(ROOT, 'backend_host', 'scripts'), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from monitor.analyzers.yolo_seg_detect import YoloSegDetect, _Raw, nms  # noqa: E402


def raw(x0, y0, x1, y1, conf=0.9, cls=0):
    return _Raw(cls, conf, x0, y0, x1, y1)


def build(**kw):
    """An instance without a model: the geometry and the filters do not need one."""
    d = YoloSegDetect.__new__(YoloSegDetect)
    d.min_conf = kw.get('min_conf', 0.25)
    d.in_w = d.in_h = 640
    d.tile_overlap = kw.get('tile_overlap', 0.12)
    d.nms_iou = kw.get('nms_iou', 0.30)
    d.min_side = kw.get('min_side', 14.0)
    d.max_aspect = kw.get('max_aspect', 2.6)
    d.use_masks = False
    d.labels = None
    d.label = 'egg'
    d.tile = kw.get('tile')
    d.fill = kw.get('fill', 'letterbox')
    d.preprocess = kw.get('preprocess', [])
    d.flip_tta = kw.get('flip_tta', False)
    d.dedupe_dist = kw.get('dedupe_dist', 0.0)
    d.dedupe_ratio = kw.get('dedupe_ratio', 0.35)
    d.color_filter = kw.get('color_filter')
    d._protos_shape = None
    d._n_mask_coeff = 0
    d._n_classes = 1
    d._attrs = 5                 # 4 box + 1 class: what _probe measured on the graph
    return d


# ---- NMS: the xyxy trap -----------------------------------------------------------------------

def test_nms_keeps_every_box_it_is_given_when_none_of_them_overlap():
    boxes = [raw(10, 10, 60, 60), raw(200, 10, 250, 60), raw(400, 10, 450, 60)]
    assert len(nms(boxes, 0.25, 0.30)) == 3


def test_nms_drops_a_duplicate_but_not_a_neighbour():
    # a second box on the same egg (near-identical) and one on the egg touching it
    boxes = [raw(100, 100, 160, 160, 0.9), raw(104, 103, 164, 163, 0.8), raw(162, 100, 222, 160, 0.7)]
    kept = nms(boxes, 0.25, 0.30)
    assert len(kept) == 2, 'the near-duplicate must go, both real eggs must stay'
    assert {round(k.x0) for k in kept} == {100, 162}


def test_nms_does_not_swallow_a_frame_of_boxes():
    """The bug this guards: xyxy handed to NMSBoxes reports success and drops most of them."""
    boxes = [raw(20 * i, 20 * i, 20 * i + 40, 20 * i + 40) for i in range(25)]
    assert len(nms(boxes, 0.25, 0.30)) == 25


def test_nms_is_class_aware():
    boxes = [raw(0, 0, 50, 50, 0.9, cls=0), raw(2, 2, 52, 52, 0.8, cls=1)]
    assert len(nms(boxes, 0.25, 0.30)) == 2


def test_nms_of_nothing_is_nothing():
    assert nms([], 0.25, 0.3) == []


# ---- the tile grid ---------------------------------------------------------------------------

def test_no_tile_is_one_crop_of_the_whole_frame():
    assert build()._tiles(1280, 720) == [(0, 0, 1280, 720)]


def test_tiles_overlap_so_an_egg_on_a_border_is_whole_somewhere():
    tiles = build(tile=(480, 270), tile_overlap=0.25)._tiles(1280, 720)
    xs = sorted({t[0] for t in tiles})
    ys = sorted({t[1] for t in tiles})
    assert len(tiles) > 1
    for a, b in zip(xs, xs[1:]):
        assert b - a < 480, 'consecutive tiles must overlap, or the eggs between them are cut in half'
    for a, b in zip(ys, ys[1:]):
        assert b - a < 270
    assert xs[-1] + 480 >= 1280 and ys[-1] + 270 >= 720, 'the grid must reach the far edge'


def test_the_overlap_is_the_overlap_and_not_the_step():
    """A quarter overlap must step three quarters of a tile, not a quarter.

    Using the overlap as the step is the same grid four times over: measured on the egg frame it ran
    240 forwards (75 s) where 12 (one pass per tile) is what 0.25 asks for.
    """
    tiles = build(tile=(480, 270), tile_overlap=0.25)._tiles(1280, 720)
    xs = sorted({t[0] for t in tiles})
    ys = sorted({t[1] for t in tiles})
    # the last tile on each axis is snapped to the frame edge, so only the regular steps are compared
    steps_x = [b - a for a, b in zip(xs, xs[1:])][:-1]
    steps_y = [b - a for a, b in zip(ys, ys[1:])][:-1]
    assert steps_x and all(280 <= s <= 380 for s in steps_x), f'x step should be ~360 (480 * 0.75), got {steps_x}'
    assert steps_y and all(150 <= s <= 230 for s in steps_y), f'y step should be ~202 (270 * 0.75), got {steps_y}'
    assert len(tiles) <= 20, f'about 16 tiles expected for a 1280x720 frame, got {len(tiles)}'


def test_a_tile_is_never_bigger_than_the_frame():
    tiles = build(tile=(2000, 2000))._tiles(640, 480)
    assert all(t[2] - t[0] <= 640 and t[3] - t[1] <= 480 for t in tiles)


# ---- head decoding ---------------------------------------------------------------------------

def head(boxes, n_anchors=None):
    """A YOLOv8 head [1, 4 + n_classes, n_anchors] in letterbox pixels, cx,cy,w,h + one score."""
    n = n_anchors or len(boxes)
    h = np.zeros((1, 5, n), np.float32)
    for i, (cx, cy, w, hh, s) in enumerate(boxes):
        h[0, :, i] = (cx, cy, w, hh, s)
    return h


def test_decode_returns_frame_pixels_and_drops_below_min_conf():
    d = build(min_conf=0.25)
    # one 60 px egg, in a 1280x720 frame letterboxed to 640 (scale 0.5), plus one weak box
    out = d._decode(head([(200, 150, 60, 60, 0.9), (400, 300, 60, 60, 0.10)]), 2.0, 2.0, 0, 0, (720, 1280))
    assert len(out) == 1
    assert out[0].x0 == pytest.approx(340, abs=1) and out[0].x1 == pytest.approx(460, abs=1)
    assert out[0].y0 == pytest.approx(240, abs=1) and out[0].y1 == pytest.approx(360, abs=1)


def test_decode_applies_the_tile_offset():
    d = build(min_conf=0.25)
    out = d._decode(head([(200, 150, 60, 60, 0.9)]), 2.0, 2.0, 480, 270, (720, 1280))
    assert out[0].x0 == pytest.approx(480 + 340, abs=1)
    assert out[0].y0 == pytest.approx(270 + 240, abs=1)


def test_decode_clips_to_the_frame_so_a_border_box_is_not_off_picture():
    d = build(min_conf=0.25)
    # letterbox centre (-10, -10) with a 40 px box -> frame (-60, -60, 20, 20): half on, half off
    out = d._decode(head([(-10, -10, 40, 40, 0.9)]), 2.0, 2.0, 0, 0, (720, 1280))
    assert len(out) == 1
    assert out[0].x0 == 0.0 and out[0].y0 == 0.0
    assert out[0].x1 == pytest.approx(20, abs=1) and out[0].y1 == pytest.approx(20, abs=1)


def test_a_box_entirely_off_the_frame_is_dropped_not_clipped_to_nothing():
    d = build(min_conf=0.25)
    assert d._decode(head([(-200, -200, 40, 40, 0.9)]), 2.0, 2.0, 0, 0, (720, 1280)) == []


def test_decode_of_all_weak_boxes_is_empty():
    d = build(min_conf=0.25)
    assert d._decode(head([(200, 150, 60, 60, 0.01)]), 2.0, 2.0, 0, 0, (720, 1280)) == []


# ---- the sliver filter -----------------------------------------------------------------------

def test_the_sliver_filter_keeps_a_60px_egg_and_drops_a_border_artefact():
    d = build()
    kept = [raw(0, 0, 60, 60), raw(0, 0, 200, 3), raw(0, 0, 8, 60)]
    w = [(k.x1 - k.x0, k.y1 - k.y0) for k in kept]
    sides = [min(a, b) for a, b in w]
    aspects = [max(a, b) / max(1e-6, min(a, b)) for a, b in w]
    good = [(s >= d.min_side) and (a <= d.max_aspect) for s, a in zip(sides, aspects)]
    assert good == [True, False, False]


def test_a_whole_frame_of_boxes_keeps_the_eggs():
    d = build()
    boxes = [raw(40 * i, 40 * i, 40 * i + 55, 40 * i + 55) for i in range(20)]
    kept = nms(boxes, 0.25, d.nms_iou)
    assert len(kept) == 20
    for k in kept:
        side = min(k.x1 - k.x0, k.y1 - k.y0)
        assert side >= d.min_side

# ---- the shipped profile ----------------------------------------------------------------------

def test_the_shipped_yolo_profile_loads_and_says_what_it_costs():
    from monitor import profiles as P
    p = P.load_profile('egg_quality_yolo')
    spec = p.img.analyzers[0]
    assert spec.type == 'yolo_seg_detect'
    # a tile WIDER than the 640 input can only be scaled down to fit it, which is the whole-frame
    # failure again (47 boxes); 640 itself is scale 1.0 and works because each crop holds fewer eggs
    assert spec.tile[0] <= 640, 'a tile wider than the input square can only be shrunk, never zoomed'
    assert 0 < spec.tile_overlap < 1
    assert p.ui.stats and p.ui.stats[0].kpi == 'count_total' and p.ui.stats[1].observations is True


def test_the_two_egg_profiles_differ_only_in_the_detector():
    from monitor import profiles as P
    fast = P.load_profile('egg_quality')
    slow = P.load_profile('egg_quality_yolo')
    assert fast.img.analyzers[0].type == 'egg_detect'
    assert slow.img.analyzers[0].type == 'yolo_seg_detect'
    # both must count the same thing, or the two numbers on the overlay are not comparable
    assert {e for e in fast.events} == set(slow.events)
    assert [k.name for k in fast.kpis] == [k.name for k in slow.kpis]
    assert slow.img.analyzers[0].sample_hz <= 0.2, 'the sample rate has to match a ~10 s pass'
    # measured on the box: votes 3 / min_votes 2 (the 5 Hz profile's) gave 191 of 191 `unverified`,
    # because an egg crosses this belt before it is seen a third time
    assert (slow.img.track.votes, slow.img.track.min_votes) == (2, 1)
    assert slow.img.track.max_gap_s >= 20, 'a gap of three 10 s passes is normal on this cadence'


def test_everything_that_reaches_the_frame_json_is_a_plain_python_number():
    """The frame JSON is written with json.dumps, and a np.float32 in an ellipse breaks it.

    The head is a numpy array, so every value derived from it is a numpy scalar unless it is cast;
    `Object of type float32 is not JSON serializable` then kills the worker for the whole frame.
    """
    import json
    d = build(min_conf=0.25)
    head_arr = np.zeros((1, 5, 1), np.float32)
    head_arr[0, :, 0] = (200, 150, 60, 60, 0.9)          # a numpy float32 head, as cv2 returns it
    raw = d._decode(head_arr, 2.0, 2.0, 0, 0, (720, 1280))
    det = _Raw(0, raw[0].conf, raw[0].x0, raw[0].y0, raw[0].x1, raw[0].y1)
    bw, bh = float(det.x1 - det.x0), float(det.y1 - det.y0)
    shape = {'ellipse': [round((det.x0 + det.x1) / 2, 1), round((det.y0 + det.y1) / 2, 1),
                         round(bw, 1), round(bh, 1), 0.0]}
    for v in list(shape['ellipse']) + [det.conf]:
        assert type(v) is float, f'{v!r} is {type(v)}, and json.dumps refuses that'
    json.dumps(shape)                                   # must not raise


def test_a_stretched_crop_is_scaled_back_by_its_own_factor():
    """A stretched 480 px tile fills the 640 input, so a box comes back 480/640 = 0.75 of its size.

    Getting this wrong (returning 1.0, the scale of a letterboxed tile) drew every circle 1.33x too
    big, which is what the first stretched run looked like: 207 boxes, none of them on an egg.
    """
    d = build()
    d.fill = 'stretch'
    d.in_w = d.in_h = 640
    crop = np.zeros((480, 480, 3), np.uint8)
    _, rx, ry = d._letterbox(crop)
    assert rx == pytest.approx(480 / 640) and ry == pytest.approx(480 / 640)
    out = d._decode(head([(320, 320, 64, 64, 0.9)]), rx, ry, 0, 0, (720, 1280))
    assert len(out) == 1
    assert out[0].x1 - out[0].x0 == pytest.approx(64 * 480 / 640, abs=0.5)
    assert out[0].y1 - out[0].y0 == pytest.approx(64 * 480 / 640, abs=0.5)


def test_a_letterboxed_crop_is_scaled_back_by_the_letterbox_ratio():
    d = build()
    d.fill = 'letterbox'
    d.in_w = d.in_h = 640
    crop = np.zeros((360, 640, 3), np.uint8)
    _, rx, ry = d._letterbox(crop)
    assert rx == pytest.approx(1.0) and ry == pytest.approx(1.0)   # 640 wide fills the input exactly
    out = d._decode(head([(320, 180, 64, 64, 0.9)]), rx, ry, 0, 0, (720, 1280))
    assert out[0].x1 - out[0].x0 == pytest.approx(64, abs=0.5)

def test_a_rectangular_input_letterboxes_a_16_9_frame_without_a_square_of_padding():
    """640x384 holds a 1280x720 frame at the same scale as the 640 square, with 24 rows of pad
    instead of 280 (BUG-0917): same eggs, 0.6x the work."""
    d = build()
    d.fill = 'letterbox'
    d.in_w, d.in_h = 640, 384
    canvas, rx, ry = d._letterbox(np.zeros((720, 1280, 3), np.uint8))
    assert canvas.shape == (384, 640, 3)
    assert rx == pytest.approx(2.0) and ry == pytest.approx(2.0)
    out = d._decode(head([(320, 180, 32, 32, 0.9)]), rx, ry, 0, 0, (720, 1280))
    assert out[0].x0 == pytest.approx(608, abs=0.5) and out[0].y1 - out[0].y0 == pytest.approx(64, abs=0.5)


# ---- the centre-distance dedupe -----------------------------------------------------------------
#
# Two boxes on the SAME egg are offset by a few pixels, so their IoU lands around 0.3-0.5: some
# survive NMS, some do not, and the overlay draws two or three circles on one egg. Two DIFFERENT
# eggs that touch overlap by ~0.04 and their centres are a full diameter apart. So the test for
# "same egg" is DISTANCE, not overlap.

def test_the_dedupe_merges_two_circles_on_one_egg():
    d = build(dedupe_dist=0.35)
    same_egg = [raw(100, 100, 160, 160, 0.9), raw(110, 106, 170, 166, 0.8)]
    assert len(d.merge_duplicates(same_egg)) == 1, 'two looks at ONE egg are one egg'


def test_the_dedupe_keeps_two_eggs_that_touch():
    d = build(dedupe_dist=0.35)
    touching = [raw(100, 100, 160, 160, 0.9), raw(160, 100, 220, 160, 0.8)]
    assert len(d.merge_duplicates(touching)) == 2, 'two eggs a diameter apart are two eggs'


def test_the_dedupe_keeps_the_more_confident_box():
    d = build(dedupe_dist=0.35)
    kept = d.merge_duplicates([raw(100, 100, 160, 160, 0.4), raw(110, 106, 170, 166, 0.9)])
    assert len(kept) == 1 and kept[0].conf == 0.9


def test_the_dedupe_does_not_merge_two_classes():
    d = build(dedupe_dist=0.35)
    assert len(d.merge_duplicates([raw(100, 100, 160, 160, 0.9, cls=0),
                                   raw(104, 103, 164, 163, 0.8, cls=1)])) == 2


def test_the_dedupe_is_off_when_it_is_not_asked_for():
    d = build(dedupe_dist=0.0)
    assert len(d.merge_duplicates([raw(100, 100, 160, 160), raw(110, 106, 170, 166)])) == 2


# ---- the belt filter ---------------------------------------------------------------------------

def _frame_with(patch, size=120):
    """A frame that is blue belt, with one white egg box painted on it."""
    frame = np.zeros((size, size, 3), np.uint8)
    frame[:, :] = (180, 60, 20)                       # BGR: saturated blue belt
    x0, y0, x1, y1 = patch
    frame[y0:y1, x0:x1] = (235, 235, 235)             # a white egg
    return frame


def test_the_belt_filter_drops_a_bare_belt_box_and_keeps_an_egg():
    d = build(color_filter=dict(mode='belt', max_ratio=0.35))
    frame = _frame_with((40, 40, 80, 80))
    on_egg = raw(40, 40, 80, 80)
    on_belt = raw(0, 0, 20, 20)
    assert d.egg_ratio(frame, on_egg) < 0.35, 'a white egg is not belt'
    assert d.egg_ratio(frame, on_belt) > 0.35, 'bare blue belt is belt'


def test_the_colour_filter_is_off_by_default():
    """It is a property of THIS scene (white eggs on a blue belt), so it must be opt-in."""
    d = build()
    assert d.color_filter is None
    frame = _frame_with((40, 40, 80, 80))
    assert d.egg_ratio(frame, raw(0, 0, 20, 20)) == 1.0, 'with no filter, everything is "belt"'


def test_the_white_mode_filter_keeps_a_bright_unsaturated_box():
    d = build(color_filter=dict(mode='white', v_min=140, s_max=70, min_ratio=0.55))
    frame = _frame_with((40, 40, 80, 80))
    assert d.egg_ratio(frame, raw(40, 40, 80, 80)) > 0.9
    assert d.egg_ratio(frame, raw(0, 0, 20, 20)) < 0.2


def test_the_shipped_profile_carries_the_measured_configuration():
    """The knobs in the profile are MEASURED numbers, not preferences — pin them.

    Each of them was chosen by measuring the device3 frame (one fixed frame, ~200 eggs):
    `stretch` because a square 640 tile fills the square input, `whitebalance`+`unsharp` because
    they move the scene towards the training distribution, `flip_tta` because it is the biggest
    recall lever, the belt filter because it is the only test that separates an egg from bare belt
    in this scene, and the dedupe because IoU NMS cannot tell "the same egg twice" from "two eggs".
    """
    from monitor import profiles as P
    spec = P.load_profile('egg_quality_yolo').img.analyzers[0]
    assert spec.fill == 'stretch'
    assert list(spec.preprocess) == ['whitebalance', 'unsharp']
    assert spec.flip_tta is True
    assert spec.tile == [640, 640]
    assert spec.min_conf <= 0.02, 'the belt filter is the arbiter, so the detector may offer candidates'
    assert spec.dedupe_dist > 0, 'without it, IoU NMS leaves two circles on one egg'
    assert spec.color_filter['mode'] == 'belt'


def test_the_shipped_yolo_profile_passes_the_shared_validator():
    """The shared validator is the one the HOST uses to decide which services a device gets.

    It used to refuse ANY stats row: it demanded that `observations` be a bool on EVERY stat, and a
    stat that reads a KPI has no such key at all — so `{label: Eggs, kpi: count_total}` was read as
    "observations is not a bool" and the whole profile was "unusable": its devices fell back to
    tv_app and the egg line ran without the stat row it was supposed to show.
    """
    import yaml
    from shared.src.lib.utils.monitor_profile import validate_manifest_light
    from monitor import profiles as P
    raw = yaml.safe_load(open(os.path.join(P.PROFILES_DIR, 'egg_quality_yolo.yaml')))
    validate_manifest_light(raw, 'egg_quality_yolo')      # must not raise


@pytest.mark.parametrize('mutate', [
    lambda s: s[0].update(observations='yes'),          # observations must be a bool
    lambda s: s[0].update(kpi='count_total', observations=True),   # exactly one of the two
    lambda s: s[0].update(label='Eggs', surprise=1),     # no extra keys
    lambda s: s.append({'label': 'Both'}),              # a stat needs exactly one source
])
def test_the_shared_validator_still_refuses_a_broken_stat(mutate):
    import yaml
    from shared.src.lib.utils.monitor_profile import validate_manifest_light
    from monitor import profiles as P
    raw = yaml.safe_load(open(os.path.join(P.PROFILES_DIR, 'egg_quality_yolo.yaml')))
    mutate(raw['ui']['stats'])
    with pytest.raises(ValueError):
        validate_manifest_light(raw, 'egg_quality_yolo')
