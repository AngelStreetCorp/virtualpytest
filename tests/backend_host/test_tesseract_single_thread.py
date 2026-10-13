"""
tests/backend_host/test_tesseract_single_thread.py — every verification tesseract runs with one
OpenMP thread (BUG-0274). On vpt-pi1 at load 8-10 the default nproc threads made a 380x75 crop
take 0.2-7.3 s (p99 21.7 s, max = the 30 s timeout); single-threaded it is 0.19 s flat.
"""
import importlib
import os
import subprocess
import sys

import numpy as np
import pytest

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

cv2 = pytest.importorskip('cv2')
text_helpers = importlib.import_module('backend_host.src.controllers.verification.text_helpers')


def _spy(monkeypatch):
    calls = []

    def run(args, **kw):
        if args and args[0] == 'tesseract':
            calls.append(kw.get('env'))
        return subprocess.CompletedProcess(args, 0, stdout='Home', stderr='')

    monkeypatch.setattr(text_helpers.subprocess, 'run', run)
    return calls


def test_the_check_and_the_dump_run_tesseract_single_threaded(tmp_path, monkeypatch):
    img = tmp_path / 'frame.png'
    cv2.imwrite(str(img), np.full((72, 128, 3), 255, np.uint8))
    h = object.__new__(text_helpers.TextHelpers)
    h.captures_path = str(tmp_path)
    calls = _spy(monkeypatch)
    h.detect_text_in_area(str(img), None)
    h.extract_full_ocr_dump(str(img), 30)
    assert len(calls) >= 2
    assert all(env and env.get('OMP_THREAD_LIMIT') == '1' for env in calls), calls
    assert all(env.get('PATH') == os.environ.get('PATH') for env in calls)  # the rest is inherited
