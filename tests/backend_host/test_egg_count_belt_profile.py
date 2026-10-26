"""The count-only egg profile (BUG-0906): it counts eggs and claims nothing about their quality.

THE MODEL FILE IS NOT IN GIT, so nothing here loads it. What IS pinned is the part that can
silently rot: the manifest the img service reads, and the promise the profile makes — a COUNT, and
no grade. The good/bad grade on this feed is not a measurement (a white egg on a blue belt in
daylight carries no evidence of what is inside it), so the profile must keep carrying NO grader
and NO good/bad counter.

The measured numbers (98.6 % recall on a ground truth built WITHOUT this model, 0.65-0.75 s a pass
on the box) live in the profile's comment block and in BUG-0906 / BUG-0907; they are re-measured by
hand with the model file present, not by this test.
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
COUNT = os.path.join(PROFILE_DIR, 'egg_count_yolo_belt.yaml')


@pytest.fixture(scope='module')
def manifest():
    with open(COUNT, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def test_the_count_profile_exists_and_passes_both_validators():
    """The shared light validator and the img service's pydantic model must agree on it."""
    with open(COUNT, 'r', encoding='utf-8') as f:
        raw = yaml.safe_load(f)
    mp.validate_manifest_light(raw, 'egg_count_yolo_belt')       # the UI / other services
    prof = P.load_profile('egg_count_yolo_belt')                  # the img service
    assert prof.name == 'egg_count_yolo_belt'


def test_the_count_profile_has_no_grader(manifest):
    """NO `egg_classify` stage, and no `condition` attribute anywhere.

    The grader grades a white egg on a blue belt in daylight, where the image carries no evidence
    of interior quality, so it reports ~99 % bad because that is what the model says. Publishing
    that as a counter would read as a measurement (BUG-0906). The profile counts eggs; it does
    not grade them.
    """
    analyzers = manifest['img']['analyzers']
    assert [a['type'] for a in analyzers] == ['yolo_seg_detect']
    assert 'condition' not in yaml.safe_dump(manifest)


def test_the_count_profile_publishes_no_good_bad_counter(manifest):
    """No `ui.counters`, no `colour_by: verdict`: there is no second number that could be read
    as a quality, and no class to colour a circle by."""
    ui = manifest['ui']
    assert 'counters' not in ui
    assert ui['box']['colour_by'] == 'none'
    assert ui['box']['shape'] == 'ellipse'
    assert ui['box']['badge'] == 'votes'


def test_the_count_profile_counts_each_egg_once(manifest):
    """`egg_seen` fires once per TRACK, so the KPI is distinct eggs and not detections per frame.

    The event matches on the detection LABEL (`attr: label`), which the detector gives every egg,
    and the tracker's vote window (`votes: 2`) is what turns "seen in three frames" into "counted
    once": the event is finalised when the track has its votes, or when it leaves the frame.
    """
    assert manifest['events'] == {'egg_seen': {'attr': 'label', 'in': ['egg']}}
    kpis = manifest['kpis']
    assert len(kpis) == 1
    assert kpis[0]['name'] == 'count_total'
    assert kpis[0]['of'] == 'egg_seen'
    assert 'group_by' not in kpis[0]
    track = manifest['img']['track']
    assert track['algo'] == 'ocsort'
    assert track['votes'] == 2
    assert track['min_votes'] == 1


def test_the_count_profile_reads_the_belt_model(manifest):
    """Same model as the graded profile, through the same dedicated env key.

    MONITOR_YOLO_BELT_MODEL is a YOLOv8n DETECTION model (head: 4 + classes); MONITOR_YOLO_MODEL
    is the Roboflow SEGMENTATION model (head: 4 + classes + 32 mask coefficients). One key cannot
    serve both, so this profile must not borrow the other one.
    """
    det = manifest['img']['analyzers'][0]
    assert det['model_env'] == 'MONITOR_YOLO_BELT_MODEL'
    assert det['classes'] == ['egg']
    assert det['input_size'] == 960
    assert det['fill'] == 'letterbox'
    assert 'tile' not in det
    assert 'color_filter' not in det


def test_the_count_profile_samples_at_the_speed_the_box_can_keep_up_with(manifest):
    """`sample_hz: 1.2`, which is the measured limit on the box (BUG-0907).

    One whole-frame pass is 0.65-0.75 s and the rest of the pipeline ~0.15 s, so a cycle is
    ~0.9 s; the worker's cycle is `max(period, analysis time)`, and 1.2 Hz (0.83 s) is the
    fastest setting whose period still matches the work. The graded profile asks for 1.0 Hz
    because grading the ~195 crops adds another 0.25 s.
    """
    assert manifest['img']['analyzers'][0]['sample_hz'] == pytest.approx(1.2)


def test_the_count_profile_says_what_the_count_is(manifest):
    """The file must keep saying that the count is a detection count and that a real grade needs
    candling — otherwise a reader takes the counter for more than it is."""
    text = open(COUNT, 'r', encoding='utf-8').read()
    assert 'candling' in text.lower()
    assert 'detection count' in text.lower()
    assert 'once per tracked egg' in text.lower()


def test_the_model_provenance_is_written_down():
    """The model file is not in git, so where it comes from has to be in the manifest."""
    text = open(COUNT, 'r', encoding='utf-8').read()
    assert 'Moein-Talebi/egg-detection-tracking' in text
    assert 'c219a234ad9a6ebaf64fed76331e596376f420ee3ee58dc5061769e1113b7767' in text


# ---- the fast twin (BUG-0909) -------------------------------------------------------------------

FAST = os.path.join(PROFILE_DIR, 'egg_count_yolo_belt_fast.yaml')


@pytest.fixture(scope='module')
def fast_manifest():
    with open(FAST, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def test_the_fast_profile_exists_and_passes_both_validators():
    """A third egg profile is only useful if the img service can read it."""
    with open(FAST, 'r', encoding='utf-8') as f:
        raw = yaml.safe_load(f)
    mp.validate_manifest_light(raw, 'egg_count_yolo_belt_fast')
    prof = P.load_profile('egg_count_yolo_belt_fast')
    assert prof.name == 'egg_count_yolo_belt_fast'


def test_the_fast_profile_uses_its_own_model_file(fast_manifest):
    """Its own env key, because the input size is BAKED INTO the ONNX graph.

    The 960 model cannot be fed a 640x640 blob (OpenCV refuses the shape), and the 640 model
    cannot be fed a 960 one, so one key cannot serve both exports. Pointing this profile at
    MONITOR_YOLO_BELT_MODEL would load the 960 export against a 640 input and the pass would fail
    on the host rather than in the test.
    """
    det = fast_manifest['img']['analyzers'][0]
    assert det['model_env'] == 'MONITOR_YOLO_BELT_FAST_MODEL'
    assert det['input_size'] == [640, 352]
    assert det['backend'] == 'onnxruntime'
    assert det['sample_hz'] == pytest.approx(5.0)


def test_the_fast_profile_dedupes_further_than_the_slow_one(fast_manifest):
    """`dedupe_dist: 0.40`, measured: at 640 the boxes are smaller and the same egg is found
    twice a few pixels apart, so 0.35 left 3 duplicated pairs and 0.40 leaves 0 — without merging
    a single pair of neighbouring eggs (the recall does not move: 144 of 147 either way)."""
    fast = fast_manifest['img']['analyzers'][0]
    slow_path = os.path.join(PROFILE_DIR, 'egg_quality_yolo_belt.yaml')
    slow = yaml.safe_load(open(slow_path, 'r', encoding='utf-8'))['img']['analyzers'][0]
    assert fast['dedupe_dist'] == pytest.approx(0.40)
    assert fast['dedupe_dist'] > slow['dedupe_dist']


def test_the_fast_profile_is_still_only_a_count(fast_manifest):
    """No grader and no good/bad counter in the fast twin either: speed is not a reason to
    publish a number the picture cannot support (BUG-0906)."""
    assert [a['type'] for a in fast_manifest['img']['analyzers']] == ['yolo_seg_detect']
    assert 'counters' not in fast_manifest['ui']
    assert fast_manifest['ui']['box']['colour_by'] == 'none'
    text = open(FAST, 'r', encoding='utf-8').read()
    assert 'candling' in text.lower()


def test_the_fast_model_hash_is_written_down():
    """The fast export is a different file, so its hash has to be in the manifest next to the
    hash of the weights it was exported from."""
    text = open(FAST, 'r', encoding='utf-8').read()
    assert 'c54d950787f2e29404553ca534dc57bee0002d234262cdba2e5387a3d04c0036' in text
    assert 'c219a234ad9a6ebaf64fed76331e596376f420ee3ee58dc5061769e1113b7767' in text
