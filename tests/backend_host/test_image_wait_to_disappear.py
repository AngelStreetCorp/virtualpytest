"""waitForImageToDisappear passes once the image is gone (regression guard, 2026-10-04).

stb4's home -> live hop checks that the black screen has gone. The channel tuned through
black frames, then played; the check failed with "Image still present" because it needed
the image absent from EVERY frame of its 10 s window, and its KPI branch (disappeared at
frame N) could never run.
"""
import importlib
import os

import pytest


@pytest.fixture
def controller(tmp_path):
    mod = importlib.import_module('backend_host.src.controllers.verification.image')
    ctrl = object.__new__(mod.ImageVerificationController)
    frames = []
    for i in range(5):
        path = tmp_path / f'capture_{i}.jpg'
        path.write_bytes(b'x')
        frames.append(str(path))
    return ctrl, frames


def _run(ctrl, frames, present):
    """present[i]: is the reference in frame i."""
    ctrl.waitForImageToAppear = lambda image_path, timeout, threshold, area, image_list, *a, **k: (
        present[frames.index(image_list[0])], '', {'matching_result': 0.9 if present[frames.index(image_list[0])] else 0.1})
    return ctrl.waitForImageToDisappear('blackscreen', timeout=0, image_list=list(frames))


def test_passes_at_the_first_frame_without_the_image(controller):
    ctrl, frames = controller
    ok, message, data = _run(ctrl, frames, [True, True, False, True, True])
    assert ok and message == 'Image disappeared'
    assert data['kpi_match_index'] == 2
    assert data['kpi_match_timestamp'] == os.path.getmtime(frames[2])


def test_absent_from_the_start_passes_without_a_kpi(controller):
    ctrl, frames = controller
    ok, _, data = _run(ctrl, frames, [False] * 5)
    assert ok
    assert 'kpi_match_index' not in data


def test_present_in_every_frame_fails(controller):
    ctrl, frames = controller
    ok, message, _ = _run(ctrl, frames, [True] * 5)
    assert not ok and message == 'Image still present'


def test_no_capture_on_disk_fails_as_such(controller):
    ctrl, frames = controller
    for f in frames:
        os.remove(f)
    ok, message, _ = _run(ctrl, frames, [True] * 5)
    assert not ok and message == 'No capture to check'
