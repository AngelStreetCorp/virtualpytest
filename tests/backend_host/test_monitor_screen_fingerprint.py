"""TASK-162 / BUG-0847: the monitor stores a real fingerprint when it registers a screen.

The registration call passed only ``fp`` = ``{dhash, region_center}`` (the identity) and left
``fingerprint`` NULL, so every screen the live monitor created was named-or-not but never fingerprinted.
``compute_fingerprint(img, ocr=False)`` is the cheap subset the matcher actually reads
(``localize_verdicts_db.SAMPLE_KEYS``), and it must cost no tesseract subprocess.
"""
import os
import sys

import cv2
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
for p in (os.path.join(ROOT, 'backend_host', 'scripts'), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import monitor_localize as ml  # noqa: E402
from backend_host.src.controllers.verification.image_helpers import ImageHelpers  # noqa: E402
from shared.src.lib.database.localize_verdicts_db import SAMPLE_KEYS  # noqa: E402


def frame():
    """A structured screen: header, tab bar, a few panels — enough for regions and focus."""
    img = np.full((360, 640, 3), 30, np.uint8)
    cv2.putText(img, 'Home', (40, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (240, 240, 240), 2)
    cv2.line(img, (40, 74), (150, 74), (40, 40, 220), 4)
    for r in range(3):
        cv2.rectangle(img, (40 + 120 * r, 110), (140 + 120 * r, 210), (70, 70, 90), -1)
    return img


def test_ocr_false_keeps_every_matcher_layer():
    fp = ImageHelpers(None, None).compute_fingerprint(frame(), ocr=False)
    assert fp is not None
    for key in SAMPLE_KEYS:                      # v, dhash, regions, crop, focus
        assert key in fp, f'{key} missing from the cheap fingerprint'
    assert fp['dhash']
    assert isinstance(fp['regions'], dict) and fp['regions']


def test_ocr_false_omits_the_two_ocr_layers():
    fp = ImageHelpers(None, None).compute_fingerprint(frame(), ocr=False)
    assert 'title' not in fp
    assert 'text' not in fp


def test_default_still_asks_for_ocr():
    """The capture/backfill path keeps the full fingerprint; only the monitor asks for the cheap one."""
    full = ImageHelpers(None, None).compute_fingerprint(frame())
    assert full is not None
    assert 'title' in full and 'text' in full
    # the layers both paths produce are identical
    cheap = ImageHelpers(None, None).compute_fingerprint(frame(), ocr=False)
    for key in SAMPLE_KEYS:
        assert full[key] == cheap[key] or key == 'captured_at'


def test_register_unknown_passes_the_fingerprint_to_register_screen(monkeypatch):
    """_register_unknown must hand the blob to register_screen; a NULL there is the bug."""
    seen = {}

    def fake_register(team_id, scope, fp, **kwargs):
        seen.update(kwargs)
        return {'id': 'x', 'label': 'unknown_1', 'dist': 0, 'is_new': True,
                'verdict': 'unknown', 'seen': 1}

    import shared.src.lib.database.screen_fingerprints_db as sfdb
    monkeypatch.setattr(sfdb, 'register_screen', fake_register)

    monitor = ml.MonitorLocalizer.__new__(ml.MonitorLocalizer)   # no __init__: only team_id is used
    monitor.team_id = 'team'
    monitor._reg_result = {}
    monitor._registering = {}

    blob = {'v': 6, 'dhash': 'ab' * 32, 'regions': {'center': 'cd' * 32}, 'crop': None, 'focus': {}}
    monitor._register_unknown('device1', 'host/device1', {'dhash': 'ab' * 32, 'region_center': 'cd' * 32},
                              frame(), blob)

    assert seen.get('fingerprint') == blob, 'the fingerprint blob was dropped on the way to register_screen'
    assert seen.get('sample_image_path', '') is not None, 'the durable thumbnail must still be stored'


def test_register_unknown_survives_a_fingerprint_failure(monkeypatch):
    """A fingerprint that cannot be computed must degrade to identity only, never skip the registration."""
    calls = []

    def fake_register(team_id, scope, fp, **kwargs):
        calls.append(kwargs)
        return {'id': 'x', 'label': 'unknown_1', 'dist': 0, 'is_new': True,
                'verdict': 'unknown', 'seen': 1}

    import shared.src.lib.database.screen_fingerprints_db as sfdb
    monkeypatch.setattr(sfdb, 'register_screen', fake_register)

    monitor = ml.MonitorLocalizer.__new__(ml.MonitorLocalizer)
    monitor.team_id = 'team'
    monitor._reg_result = {}
    monitor._registering = {}

    monitor._register_unknown('device1', 'host/device1', {'dhash': 'ab' * 32, 'region_center': 'cd' * 32},
                              frame(), None)

    assert len(calls) == 1, 'the screen must still be registered without a blob'
    assert calls[0].get('fingerprint') is None


def test_the_freeze_path_registers_a_fingerprinted_row(monkeypatch, tmp_path):
    """The freeze path is the SECOND place a screen row is created, and it dropped the fingerprint.

    A frozen screen that Localize never published gets registered here, with only the identity hashes.
    The row is then born with ``fingerprint = NULL`` -- the same hole BUG-0847 closed for the monitor,
    and the reason a recurring frozen screen kept re-appearing in the coverage report.
    """
    import incident_manager as im
    from shared.src.lib import screen_memory

    monkeypatch.setattr(screen_memory, 'mode', lambda: 'on')
    monkeypatch.setattr(screen_memory, 'fingerprint_frame',
                        lambda f: {'dhash': 'ab' * 32, 'region_center': 'cd' * 32})

    shots = tmp_path / 'captures'
    shots.mkdir()
    path = shots / 'x.jpg'
    cv2.imwrite(str(path), frame())

    import shared.src.lib.ai.freeze_strip as freeze_strip
    monkeypatch.setattr(freeze_strip, 'select_frames', lambda meta, fps=None: ([(str(path), 0)], 0.0))

    import shared.src.lib.database.screen_fingerprints_db as sfdb
    seen = {}

    def fake_register(team_id, scope, fp, **kwargs):
        seen.update(kwargs)
        return {'id': 'x', 'label': 'unknown_1', 'dist': 0, 'is_new': True,
                'verdict': 'unknown', 'seen': 1}

    monkeypatch.setattr(sfdb, 'register_screen', fake_register)
    monkeypatch.setattr(sfdb, 'count_sighting_by_id', lambda *a, **k: None)

    hit = im.IncidentManager._freeze_screen({}, 'vpt-pi1', 'device3', str(tmp_path))

    assert hit is not None, 'the freeze must still stamp its screen'
    blob = seen.get('fingerprint')
    assert blob, 'the freeze path dropped the fingerprint blob'
    assert blob.get('dhash'), 'the blob must carry the identity the matcher reads'
    assert seen.get('sample_image_path'), 'the durable thumbnail must still be stored'