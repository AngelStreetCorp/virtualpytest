"""The belt-model egg profile (BUG-0870): the manifest, and the analyzer knobs it pins.

THE MODEL FILE IS NOT IN GIT, so nothing here loads it. What IS pinned is the part that can
silently rot: the manifest the img service reads, and the exact analyzer settings that the
measurement on the device3 frame was made with. If somebody changes `min_conf`, `input_size`,
`fill` or `dedupe_dist` in the YAML, the numbers in the YAML's comment block stop being true and
the test says so instead of letting them rot quietly.

The measured numbers themselves (98.6 % recall on a ground truth built WITHOUT this model, 1
duplicate pair, 0.36 s a frame) come from the device3 frame and live in the profile's comment
block; they are re-measured by hand with the model file present, not by this test.
"""
import os
import sys

import pytest
import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
for p in (os.path.join(ROOT, 'backend_host', 'scripts'), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from monitor import profiles as P  # noqa: E402
import shared.src.lib.utils.monitor_profile as mp  # noqa: E402

PROFILE_DIR = os.path.join(ROOT, 'backend_host', 'config', 'monitor', 'profiles')
BELT = os.path.join(PROFILE_DIR, 'egg_quality_yolo_belt.yaml')


@pytest.fixture(scope='module')
def manifest():
    with open(BELT, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def test_the_belt_profile_exists_and_passes_both_validators():
    """The shared light validator and the img service's pydantic model must agree on it."""
    with open(BELT, 'r', encoding='utf-8') as f:
        raw = yaml.safe_load(f)
    mp.validate_manifest_light(raw, 'egg_quality_yolo_belt')     # the UI / other services
    prof = P.load_profile('egg_quality_yolo_belt')                # the img service
    assert prof.name == 'egg_quality_yolo_belt'


def test_the_belt_profile_reads_its_own_model(manifest):
    """The model comes from MONITOR_YOLO_BELT_MODEL, NOT from MONITOR_YOLO_MODEL.

    The two models are different animals: MONITOR_YOLO_MODEL points at the Roboflow segmentation
    model (`egg_quality_yolo`), this one at a YOLOv8n DETECTION model. Pointing this profile at
    the other variable would load a model whose head is `4 + classes + 32 mask coefficients`
    against a profile that declares one class, and the shape of the head would not match what
    the profile says it is.
    """
    det = manifest['img']['analyzers'][0]
    assert det['type'] == 'yolo_seg_detect'
    assert det['model_env'] == 'MONITOR_YOLO_BELT_MODEL'
    assert det['classes'] == ['egg']


def test_the_belt_profile_pins_the_settings_the_measurement_was_made_with(manifest):
    """Every knob here is a measured choice; changing one invalidates the numbers in the YAML.

    input_size 960  the ONNX input is a fixed square; 960 measured best (640: 98.0 %, 1280: 97.3 %)
    fill letterbox  the frame is 1280x720 and the input square: stretch measured 94.5 %
    min_conf 0.02   the head's scores are already activated, so 0.02 is a real 2 % confidence
    nms_iou 0.60    touching eggs overlap ~0.04, the same egg twice ~0.6
    dedupe_dist .35 the duplicate-circle distance; 0.35 left 1 duplicate pair, 0 left 49
    min_side 8      the far eggs at the top of the frame are small
    """
    det = manifest['img']['analyzers'][0]
    assert det['input_size'] == 960
    assert det['fill'] == 'letterbox'
    assert det['min_conf'] == pytest.approx(0.02)
    assert det['nms_iou'] == pytest.approx(0.60)
    assert det['dedupe_dist'] == pytest.approx(0.35)
    assert det['dedupe_ratio'] == pytest.approx(0.35)
    assert det['min_side'] == 8


def test_the_belt_profile_runs_one_whole_frame_pass(manifest):
    """No `tile`: one whole-frame forward replaces the twelve the sliced profile needs.

    This is the whole speed story of the profile — a 960x960 forward on the whole frame is one
    pass, while `egg_quality_yolo` slices the frame into twelve 640x640 tiles. It is also why
    this profile can sample once a second where the other one samples every 12 s.

    `sample_hz` is 1.0, which is what the measured cycle on the box allows: the detection pass is
    0.65-0.75 s and grading the ~195 crops costs another 0.23-0.26 s, so a graded cycle is ~1.0 s
    and the worker's cycle is `max(period, analysis time)` (BUG-0907). At the 0.5 Hz this profile
    used to ask for, the model was idle more than half the time (measured: 0.47 analyses/s).
    """
    det = manifest['img']['analyzers'][0]
    assert 'tile' not in det
    assert det['sample_hz'] == pytest.approx(1.0)


def test_the_belt_profile_has_no_colour_filter(manifest):
    """No `color_filter`: the belt model was trained on this kind of belt.

    Its boxes are already on eggs (97.4 % of them sit on a white egg), so the belt filter would
    only throw away real eggs — and it was measured to change nothing on this frame. Leaving it
    out is deliberate; if it is added back, the number in the comment block has to be re-measured.
    """
    det = manifest['img']['analyzers'][0]
    assert 'color_filter' not in det


def test_the_belt_profile_keeps_the_ellipse_and_the_vote_window(manifest):
    """The overlay draws an ellipse (the egg's shape), and the votes window is reachable again.

    The vote window is only meaningful because the profile samples at 1 Hz: the sliced profile
    samples every 12 s, so an egg is seen once before it leaves the belt and every egg came out
    `unverified` (measured: 191 of 191).
    """
    assert manifest['ui']['box']['shape'] == 'ellipse'
    track = manifest['img']['track']
    assert track['algo'] == 'ocsort'
    assert track['votes'] == 3
    assert track['min_votes'] == 2


def test_the_belt_profile_does_not_claim_the_grade_means_anything(manifest):
    """`egg_classify` grades white eggs on a blue belt in daylight: there is no image evidence of
    interior quality there, so it reports ~99 % bad because that is what the model says.

    The counters stay because they are part of the block. The comment has to keep saying so, or
    somebody will read `bad_pct: 99` as a measurement.
    """
    classifiers = [a for a in manifest['img']['analyzers'] if a['type'] == 'egg_classify']
    assert len(classifiers) == 1
    assert classifiers[0]['classes'] == ['good', 'bad']
    text = open(BELT, 'r', encoding='utf-8').read()
    assert 'candling' in text.lower()


def test_the_model_provenance_is_written_down(manifest):
    """The model file is not in git, so where it comes from has to be in the manifest.

    A future reader must be able to fetch the same weights: the GitHub repo, the file inside it
    and the SHA-256 of what was downloaded. Without the hash, "the model" is not a thing anyone
    can reproduce.
    """
    text = open(BELT, 'r', encoding='utf-8').read()
    assert 'Moein-Talebi/egg-detection-tracking' in text
    assert 'c219a234ad9a6ebaf64fed76331e596376f420ee3ee58dc5061769e1113b7767' in text
