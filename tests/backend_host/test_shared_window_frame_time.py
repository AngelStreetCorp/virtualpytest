"""
tests/backend_host/test_shared_window_frame_time.py — a leg's window in the shared verification
window is measured in FRAME time, not in time spent checking.

vpt-pi1 / stb4, 2026-10-04 (QualiAi run 7, TC_08 home_tvguide -> home_apps): the node has an
image leg (timeout 10 s) and an OCR leg (20 s). The image scored 0.000 on the base frame, taken
11 ms after the key; the OCR leg then took 17.3 s on that same frame (tesseract shared with the
capture monitor, load 8.5 on 4 cores). Measured in wall time, the image leg's 10 s window had
closed before it saw a single newer frame, so the hop failed although the frame 0.8 s after the
key matched at 0.949 (reproduced 1 run in 4 with the same hop).

These tests fail on the code before the fix (elapsed = time.time() - window_start).
"""
import asyncio
import importlib
import os
import sys
import time

import pytest

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

ve = importlib.import_module('backend_host.src.services.verifications.verification_executor')

SLOW_OCR_S = 1.2  # longer than the image leg's 1 s window


def _frames(tmp_path, offsets):
    """capture_N.jpg files whose mtimes are base + offset (seconds)."""
    base = time.time()
    paths = []
    for i, off in enumerate(offsets):
        p = tmp_path / f'capture_{i:04d}.jpg'
        p.write_bytes(b'x')
        os.utime(p, (base + off, base + off))
        paths.append(str(p))
    return paths


def _executor(matching_frame_names):
    ex = object.__new__(ve.VerificationExecutor)
    ex.text_controller = None
    ex.image_controller = None
    seen = []

    async def single(verification, _ui, frame_path, _ctx, _team):
        name = os.path.basename(frame_path)
        seen.append((verification['verification_type'], name))
        if verification['verification_type'] == 'text':
            time.sleep(SLOW_OCR_S)  # a slow OCR, as on the box
            return {'success': True, 'message': 'text found'}
        ok = name in matching_frame_names
        return {'success': ok, 'message': f'image {"found" if ok else "not detected"} in {name}'}

    ex._execute_single_verification = single
    return ex, seen


LEGS = [
    {'command': 'waitForImageToAppear', 'verification_type': 'image', 'params': {'timeout': 1000}},
    {'command': 'waitForTextToAppear', 'verification_type': 'text', 'params': {'timeout': 3000}},
]


def _run(ex, base):
    return asyncio.run(ex._execute_shared_window(LEGS, base, 3.0, 'ui', None, 'team', 'all'))


def test_a_slow_ocr_leg_does_not_close_the_image_legs_window(tmp_path):
    base, early = _frames(tmp_path, [0.0, 0.3])  # the image shows 0.3 s after the base frame
    ex, seen = _executor({os.path.basename(early)})
    results, passed = _run(ex, base)
    assert ('image', os.path.basename(early)) in seen
    assert passed == 2, results


def test_CONTROL_a_frame_captured_after_the_legs_window_is_not_accepted(tmp_path):
    base, late = _frames(tmp_path, [0.0, 1.5])  # 1.5 s > the image leg's 1 s window
    ex, seen = _executor({os.path.basename(late)})
    results, passed = _run(ex, base)
    assert passed == 1
    assert results[0]['success'] is False
    assert ('image', os.path.basename(late)) not in seen
