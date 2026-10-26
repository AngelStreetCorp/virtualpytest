"""waitForNavTabIndex from the RIGHT: the page header is not a column.

The shared detector reads the whole strip above the underline, and on the
Settings page that strip also holds the page header — the user name and its
icon at the top right. The header is not a column, but it sits to the right of
every column, so "count from the right" was one too high in French: the
rightmost column read as 1 instead of 0, the walk pressed one time too many and
the bar's wrap put it on the leftmost column — the profile picker (measured on
the operator's set-top box, the French runs c6b01ba3 / c8a4cd84).

The check therefore counts the blocks on the focus's OWN row — the row just
above the underline, which holds the column labels and nothing else.

Pure-CPU: synthetic frames in a fake capture directory, no device.
"""
import importlib
import os
import time

import numpy as np
import pytest

cv2 = pytest.importorskip('cv2')

W, H = 1280, 720
# the geometry of the French Settings page, measured on the box (2026-10-23)
COLUMNS = [(0.055, 0.101), (0.123, 0.213), (0.236, 0.349),
           (0.372, 0.466), (0.489, 0.550), (0.572, 0.600)]
HEADER = (0.886, 0.944)          # the user name and its icon, top right
LABEL_Y, LABEL_H = 88, 22        # the column labels
HEAD_Y, HEAD_H = 70, 15          # the header line, above the labels
UNDERLINE_Y, UNDERLINE_H = 118, 4


@pytest.fixture
def controller():
    mod = importlib.import_module('backend_host.src.controllers.verification.image')
    helpers_mod = importlib.import_module('backend_host.src.controllers.verification.image_helpers')
    ctrl = object.__new__(mod.ImageVerificationController)
    ctrl.helpers = helpers_mod.ImageHelpers('/nonexistent', None)
    return ctrl


def _text(img, x0, x1, y0, y1, colour):
    """Draw a label as strokes, the way the detector reads real text.

    The detector finds the blocks with a top-hat on the grey image, so it sees
    the EDGES of the glyphs. A solid rectangle would read as two thin blocks
    (its two borders) with a hole in the middle.
    """
    x = int(x0 * W)
    end = int(x1 * W)
    while x < end:
        img[y0:y1, x:min(x + 5, end)] = colour
        x += 9


def _settings_frame(focused=None, header=True):
    """The Settings bar: six columns, the page header at the top right.

    The labels are grey (they are not the focus accent) and the focused one is
    bold white, exactly as on the box.
    """
    img = np.zeros((H, W, 3), dtype=np.uint8)
    for i, (x0, x1) in enumerate(COLUMNS):
        colour = 255 if i == focused else 170
        _text(img, x0, x1, LABEL_Y, LABEL_Y + LABEL_H, colour)
    if header:
        _text(img, HEADER[0], HEADER[1], HEAD_Y, HEAD_Y + HEAD_H, 170)
    if focused is not None:
        x0, x1 = COLUMNS[focused]
        img[UNDERLINE_Y:UNDERLINE_Y + UNDERLINE_H, int(x0 * W):int(x1 * W)] = (0, 0, 220)
    return img


def _capture_dir(tmp_path):
    cold = tmp_path / 'capture1' / 'captures'
    hot = tmp_path / 'capture1' / 'hot' / 'captures'
    cold.mkdir(parents=True)
    hot.mkdir(parents=True)
    return cold, hot


def _floor(cold, img, name='floor.png', age=10.0):
    path = cold / name
    cv2.imwrite(str(path), img)
    now = time.time()
    os.utime(str(path), (now - age, now - age))
    return str(path)


def test_the_header_is_not_a_column(controller, tmp_path):
    """The rightmost column is right index 0 — the header must not push it to 1.

    The shared detector reads seven blocks on this frame (six columns and the
    header), so counting from the right with that number gives 1 for the
    rightmost column and the walk never finds its target.
    """
    cold, hot = _capture_dir(tmp_path)
    floor = _floor(cold, _settings_frame(focused=5))

    ok, message, details = controller.waitForNavTabIndex(
        expected_index=0, expected_count=None, timeout=0.3, source_path=floor,
        direction='right', wait_for_redraw=True)
    assert ok, message
    assert details['focus_signature']['tab_count'] == 7, 'the shared count still holds the header'


def test_the_second_column_from_the_right_reads_one(controller, tmp_path):
    """One column from the right is still 1 — the count is not shifted."""
    cold, hot = _capture_dir(tmp_path)
    floor = _floor(cold, _settings_frame(focused=4))

    ok, message, _ = controller.waitForNavTabIndex(
        expected_index=1, expected_count=None, timeout=0.3, source_path=floor,
        direction='right', wait_for_redraw=True)
    assert ok, message


def test_a_bar_without_a_header_is_unchanged(controller, tmp_path):
    """A bar with no header reads the same as before: the count is the columns."""
    cold, hot = _capture_dir(tmp_path)
    floor = _floor(cold, _settings_frame(focused=4, header=False))

    ok, message, details = controller.waitForNavTabIndex(
        expected_index=1, expected_count=None, timeout=0.3, source_path=floor,
        direction='right', wait_for_redraw=True)
    assert ok, message
    assert details['focus_signature']['tab_count'] == 6


def test_counting_from_the_left_is_unchanged(controller, tmp_path):
    """The header sits at the far right: the indices from the left do not move."""
    cold, hot = _capture_dir(tmp_path)
    floor = _floor(cold, _settings_frame(focused=5))

    ok, message, details = controller.waitForNavTabIndex(
        expected_index=5, expected_count=None, timeout=0.3, source_path=floor,
        direction='left', wait_for_redraw=True)
    assert ok, message
    assert details['focus_signature']['tab_index'] == 5
