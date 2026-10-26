"""waitForNavTabIndex with direction='right': the count that survives a merged label.

The Home bar of the operator's set-top box keeps the same tab COUNT in every
language, so the index from the left works there. The Settings COLUMN bar does
not: the detector reads the labels with a gap threshold, and two neighbouring
labels that sit close enough together are read as ONE block. On stb4 the French
Settings page reads 5 blocks on one frame and 6 on the next — the merge of
'Profils' and 'Accessibilite' flickers with the frame. The index from the LEFT
therefore differs between two frames of the same screen.

The merge eats into the bar from the left, so the number of blocks to the RIGHT
of the focused one does not move: the last column is 0 from the right in German,
French and Italian, whether or not the left pair merged.

Pure-CPU: synthetic frames, no device, no capture directory.
"""
import importlib

import numpy as np
import pytest

cv2 = pytest.importorskip('cv2')

W, H = 1280, 720
LABEL_Y, LABEL_H = 40, 20
UNDERLINE_Y, UNDERLINE_H = 85, 4
COL_W = 60


@pytest.fixture
def controller():
    mod = importlib.import_module('backend_host.src.controllers.verification.image')
    helpers_mod = importlib.import_module('backend_host.src.controllers.verification.image_helpers')
    ctrl = object.__new__(mod.ImageVerificationController)
    ctrl.helpers = helpers_mod.ImageHelpers('/nonexistent', None)
    return ctrl


def _frame(focused=None, merged_left=False):
    """A column bar of six labels; the underline sits under column `focused`.

    `merged_left` puts the first two labels 8 px apart — close enough for the
    block detector to read them as one block, which is what the French Settings
    page does.
    """
    img = np.zeros((H, W, 3), dtype=np.uint8)
    xs = [100, 220, 340, 460, 580, 700]
    if merged_left:
        xs[1] = xs[0] + COL_W + 8
    for x in xs:
        img[LABEL_Y:LABEL_Y + LABEL_H, x:x + COL_W] = 255
    if focused is not None:
        x = xs[focused]
        img[UNDERLINE_Y:UNDERLINE_Y + UNDERLINE_H, x:x + COL_W] = (0, 0, 220)
    return img


def _write(tmp_path, img, name='frame.png'):
    path = tmp_path / name
    cv2.imwrite(str(path), img)
    return str(path)


def test_the_left_pair_really_merges(controller):
    """The fixture must reproduce the merge the French Settings page shows."""
    merged = controller.helpers._focus_signature(_frame(focused=5, merged_left=True))
    plain = controller.helpers._focus_signature(_frame(focused=5))
    assert merged['tab_count'] == 5
    assert plain['tab_count'] == 6
    assert merged['tab_index'] == 4       # the last column, counted from the left
    assert plain['tab_index'] == 5


def test_index_from_the_right_is_the_same_in_both_frames(controller):
    """The merge is on the LEFT, so the count from the right does not move."""
    assert controller._nav_focus_index(4, 5, 'right') == 0
    assert controller._nav_focus_index(5, 6, 'right') == 0
    assert controller._nav_focus_index(3, 5, 'right') == 1
    assert controller._nav_focus_index(4, 6, 'right') == 1


def test_direction_left_is_the_default(controller):
    assert controller._nav_focus_index(4, 6) == 4
    assert controller._nav_focus_index(4, 6, 'left') == 4


def test_the_last_column_passes_from_the_right_in_both_frames(controller, tmp_path):
    merged = _write(tmp_path, _frame(focused=5, merged_left=True), 'merged.png')
    plain = _write(tmp_path, _frame(focused=5), 'plain.png')
    for path in (merged, plain):
        ok, message, details = controller.waitForNavTabIndex(
            expected_index=0, expected_count=None, timeout=0.2, source_path=path, direction='right')
        assert ok, message
        assert details['matching_result'] == 1.0
        assert details['direction'] == 'right'


def test_the_left_count_would_fail_on_the_merged_frame(controller, tmp_path):
    """This is the bug the direction parameter fixes: same screen, same column,
    two different left-hand indices."""
    merged = _write(tmp_path, _frame(focused=5, merged_left=True), 'merged.png')
    ok, message, _ = controller.waitForNavTabIndex(
        expected_index=5, expected_count=None, timeout=0.2, source_path=merged)
    assert not ok
    assert '4' in message


def test_the_second_column_from_the_right_passes_from_the_right(controller, tmp_path):
    merged = _write(tmp_path, _frame(focused=4, merged_left=True), 'merged.png')
    plain = _write(tmp_path, _frame(focused=4), 'plain.png')
    for path in (merged, plain):
        ok, message, _ = controller.waitForNavTabIndex(
            expected_index=1, expected_count=None, timeout=0.2, source_path=path, direction='right')
        assert ok, message


def test_a_bad_direction_is_rejected(controller, tmp_path):
    path = _write(tmp_path, _frame(focused=5))
    ok, message, _ = controller.waitForNavTabIndex(
        expected_index=0, expected_count=None, timeout=0.2, source_path=path, direction='sideways')
    assert not ok
    assert 'direction' in message


def test_the_count_still_guards_the_bar(controller, tmp_path):
    """expected_count still says "this is the 6-column bar", with the slack of 1
    that lets a merged frame (5 blocks) through."""
    merged = _write(tmp_path, _frame(focused=5, merged_left=True), 'merged.png')
    ok, message, _ = controller.waitForNavTabIndex(
        expected_index=0, expected_count=6, timeout=0.2, source_path=merged, direction='right')
    assert ok, message
