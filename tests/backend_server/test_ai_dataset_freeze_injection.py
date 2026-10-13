"""freeze_injection.py: phase checks (TASK-27, 2026-10-05). The ffplay / capture parts need a VNC host.

Run: pytest tests/backend_server/test_ai_dataset_freeze_injection.py -v
"""
import importlib.util
import os

import cv2
import numpy as np
import pytest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
pytestmark = pytest.mark.unit


def _load():
    path = os.path.join(_REPO_ROOT, "features", "ai-dataset", "scripts", "freeze_injection.py")
    spec = importlib.util.spec_from_file_location("freeze_injection_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fi = _load()


def test_a_phase_is_kept_only_when_its_frames_show_it():
    assert fi.phase_ok(True, [0.0, 0.3]) and not fi.phase_ok(True, [16.4, 0.0])
    assert fi.phase_ok(False, [84.0, 89.6]) and not fi.phase_ok(False, [0.0, 0.01])  # the stream never played


def test_change_pct_is_a_percentage(tmp_path):
    a, b = tmp_path / "a.jpg", tmp_path / "b.jpg"
    cv2.imwrite(str(a), np.zeros((10, 10), np.uint8))
    img = np.zeros((10, 10), np.uint8)
    img[:5] = 255
    cv2.imwrite(str(b), img)
    assert fi.change_pct(str(a), str(a)) == 0.0
    assert 45.0 <= fi.change_pct(str(a), str(b)) <= 55.0
