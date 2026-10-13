"""Image-match results must be plain Python types (regression guard, 2026-10-02).

waitForImageToDisappear on vpt-pi1/device4 ("blackscreen" with an area) passed,
then every status poll of the testcase answered HTTP 500 "Object of type bool_
is not JSON serializable": the area matcher compared an np.float64 score to the
threshold, the resulting np.bool_ reached the verification details
(greyscale_found), and jsonify refused it.

Pure-CPU: synthetic frames, no device, no capture directory.
"""
import importlib
import json

import numpy as np
import pytest

cv2 = pytest.importorskip('cv2')


@pytest.fixture
def controller():
    mod = importlib.import_module('backend_host.src.controllers.verification.image')
    helpers_mod = importlib.import_module('backend_host.src.controllers.verification.image_helpers')
    ctrl = object.__new__(mod.ImageVerificationController)
    ctrl.helpers = helpers_mod.ImageHelpers('/nonexistent', None)
    return ctrl


def _frames():
    rng = np.random.default_rng(0)
    source = rng.integers(0, 255, size=(120, 160, 3), dtype=np.uint8)
    ref = source[20:60, 30:90].copy()
    return source, ref


def _assert_native(found, score, location):
    assert type(found) is bool
    assert type(score) is float
    if location is not None:
        assert all(type(v) is int for v in location.values())
    json.dumps({'found': found, 'score': score, 'location': location})


def test_positive_control_numpy_comparison_is_not_serializable():
    # Without the coercion this is what the matcher produced.
    raw = np.float64(0.5) >= 0.8
    assert isinstance(raw, np.bool_)
    # numpy 1 names the type bool_, numpy 2 names it bool.
    with pytest.raises(TypeError, match=r'bool_?'):
        json.dumps({'greyscale_found': raw})


@pytest.mark.parametrize('area', [
    None,  # full-image cv2.matchTemplate path
    {'x': 30, 'y': 20, 'width': 60, 'height': 40},  # pixel-diff area path (the blackscreen case)
    {'x': 30, 'y': 20, 'width': 60, 'height': 40,  # fuzzy-area path
     'fx': 10, 'fy': 5, 'fwidth': 120, 'fheight': 90},
])
@pytest.mark.parametrize('threshold', [0.8, 1.01])  # one hit, one miss
def test_match_template_returns_native_types(controller, area, threshold):
    source, ref = _frames()
    _assert_native(*controller._match_template(ref, source, area, threshold))


def test_greyscale_retry_score_compare_is_native(controller):
    source, ref = _frames()
    to_grey = importlib.import_module('backend_host.src.controllers.verification.image')._to_grey
    _, grey_score, _ = controller._match_template(
        to_grey(ref), to_grey(source), {'x': 0, 'y': 0, 'width': 60, 'height': 40}, 0.8)
    assert type(grey_score >= 0.8) is bool


def test_flask_provider_serializes_numpy_scalars():
    flask = pytest.importorskip('flask')
    from shared.src.lib.utils.app_utils import NumpyJSONProvider

    app = flask.Flask('t')
    app.json = NumpyJSONProvider(app)
    with app.app_context():
        body = flask.jsonify({'ok': np.bool_(True), 'n': np.int64(3),
                              'score': np.float32(0.25), 'arr': np.array([1, 2])}).get_json()
    assert body == {'ok': True, 'n': 3, 'score': 0.25, 'arr': [1, 2]}


def test_to_native_converts_nested_numpy_structures():
    from shared.src.lib.utils.app_utils import to_native

    raw = {
        'found': np.bool_(True),
        'details': {
            'score': np.float64(0.93),
            'location': (np.int64(3), np.int32(4)),
            'hist': np.array([[1, 2], [3, 4]], dtype=np.uint8),
            'frames': [{'dark': np.float32(0.5), 'black': np.bool_(False)}],
        },
        'label': 'home',
        'none': None,
    }
    out = to_native(raw)

    assert out == {
        'found': True,
        'details': {
            'score': 0.93,
            'location': [3, 4],
            'hist': [[1, 2], [3, 4]],
            'frames': [{'dark': 0.5, 'black': False}],
        },
        'label': 'home',
        'none': None,
    }
    assert type(out['found']) is bool
    assert type(out['details']['location'][0]) is int
    assert type(out['details']['frames'][0]['black']) is bool
    json.dumps(out)
    # Input is not mutated.
    assert isinstance(raw['found'], np.bool_)


def test_to_native_nan_to_none():
    from shared.src.lib.utils.app_utils import to_native

    out = to_native({'a': np.float64('nan'), 'b': float('inf'), 'c': 1.5}, nan_to_none=True)
    assert out == {'a': None, 'b': None, 'c': 1.5}
    # Default leaves non-finite floats alone (jsonify accepts them).
    assert to_native({'a': float('inf')}) == {'a': float('inf')}


def test_appear_then_disappear_unpacks_match_template(controller, tmp_path, monkeypatch):
    """_match_template returns (found, score, location); this path unpacked two names
    and raised ValueError on the first readable frame, so it could never pass."""
    import sys
    import types

    source, ref = _frames()
    area = {'x': 30, 'y': 20, 'width': 60, 'height': 40}
    ref_path = tmp_path / 'ref.png'
    cv2.imwrite(str(ref_path), ref)
    blank = np.zeros_like(source)
    frames = []
    for i, img in enumerate([blank, source, blank]):
        path = tmp_path / f'frame_{i}.png'
        cv2.imwrite(str(path), img)
        frames.append(str(path))

    fake_cf = types.ModuleType('shared.src.lib.utils.cloudflare_utils')
    fake_cf.get_cloudflare_utils = lambda: types.SimpleNamespace(get_public_url=lambda key: f'http://r2/{key}')
    monkeypatch.setitem(sys.modules, 'shared.src.lib.utils.cloudflare_utils', fake_cf)
    controller.av_controller = None
    monkeypatch.setattr(controller, '_resolve_reference_image', lambda *a, **k: (str(ref_path), area), raising=False)
    monkeypatch.setattr(controller, '_generate_comparison_images', lambda *a, **k: {}, raising=False)

    ok, message, data = controller.waitForImageToAppearThenDisappear(
        str(ref_path), timeout=5, threshold=0.8, image_list=frames)

    assert ok, message
    assert data['kpi_appear_index'] == 1
    assert data['kpi_disappear_index'] == 2
    json.dumps(data)


def test_blackscreen_helpers_return_native_types(tmp_path):
    mod = importlib.import_module('backend_host.src.controllers.verification.video_content_helpers')
    helpers = mod.VideoContentHelpers(None, 'test')
    img = np.zeros((200, 320), dtype=np.uint8)
    img[150:, :] = 255  # bright banner at the bottom
    path = tmp_path / 'black.png'
    cv2.imwrite(str(path), img)

    is_black, pct = helpers._analyze_blackscreen_simple(str(path), None, 5)
    assert type(is_black) is bool and is_black
    assert type(pct) is float

    zap = helpers.detect_zap_with_edge_analysis(str(path))
    assert zap['success'], zap
    assert type(zap['blackscreen']) is bool
    assert type(zap['zap']) is bool
    assert type(zap['has_bottom_content']) is bool
    # 'edges' is the raw Canny array, kept for in-process reuse by subtitle detection.
    json.dumps({k: v for k, v in zap.items() if k != 'edges'})
