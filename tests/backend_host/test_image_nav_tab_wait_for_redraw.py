"""waitForNavTabIndex: judge the frame that shows the EFFECT of the key.

A walk ("press RIGHT until the focused column reads index N") spends most of its
steps on a frame that does NOT match — it is walking towards the target. The
default polling mode ("poll until a frame matches") therefore burns its whole
window on every step: measured on the operator's set-top box, four of five steps
cost the full 30 s each, and the edge took 260 s.

`wait_for_redraw` changes the question from "when does the condition become
true?" to "when did the picture catch up with the key?": the check waits for the
focus to MOVE (a different index than the frame it was handed) and judges THAT
frame. The step then costs the device's own redraw (7-13 s on that box) and no
more — and the verdict is never read off a frame that predates the key.

Pure-CPU: synthetic frames in a fake capture directory, no device.
"""
import importlib
import os
import time

import numpy as np
import pytest

cv2 = pytest.importorskip('cv2')

W, H = 1280, 720
LABEL_Y, LABEL_H = 40, 20
UNDERLINE_Y, UNDERLINE_H = 85, 4
TAB_W, TAB_GAP, TAB_X0 = 60, 40, 100


@pytest.fixture
def controller():
    mod = importlib.import_module('backend_host.src.controllers.verification.image')
    helpers_mod = importlib.import_module('backend_host.src.controllers.verification.image_helpers')
    ctrl = object.__new__(mod.ImageVerificationController)
    ctrl.helpers = helpers_mod.ImageHelpers('/nonexistent', None)
    return ctrl


def _tab_x(index):
    return TAB_X0 + index * (TAB_W + TAB_GAP)


def _frame(focused=None, tabs=8, skip=()):
    """A bar of `tabs` labels, the focused one underlined.

    `skip` drops labels (the platform merges neighbouring ones) without moving
    the underline: the frame then carries a different block count and a
    different block index although the focus sits in the same place.
    """
    img = np.zeros((H, W, 3), dtype=np.uint8)
    for i in range(tabs):
        if i in skip:
            continue
        x = _tab_x(i)
        img[LABEL_Y:LABEL_Y + LABEL_H, x:x + TAB_W] = 255
    if focused is not None:
        x = _tab_x(focused)
        img[UNDERLINE_Y:UNDERLINE_H + UNDERLINE_Y, x:x + TAB_W] = (0, 0, 220)
    return img


def _capture_dir(tmp_path):
    """A capture tree the controller can derive a hot directory from."""
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


def _hot_frame(hot, img, name='capture_000000001.jpg', age=5.0):
    path = hot / name
    cv2.imwrite(str(path), img)
    now = time.time()
    os.utime(str(path), (now - age, now - age))
    return str(path)


def test_the_redraw_mode_judges_the_frame_where_the_focus_moved(controller, tmp_path):
    """The frame we were handed still shows the OLD column — it must not decide it.

    The floor shows tab 3, the device has moved to tab 4, and the walk expects
    tab 3. The default mode matches the stale floor frame and says "yes"; the
    redraw mode waits for the movement and judges the frame that shows it.
    """
    cold, hot = _capture_dir(tmp_path)
    floor = _floor(cold, _frame(focused=3))
    _hot_frame(hot, _frame(focused=4))

    ok, message, details = controller.waitForNavTabIndex(
        expected_index=3, expected_count=8, timeout=0.5, source_path=floor,
        wait_for_redraw=True)
    assert not ok
    assert '4' in message
    assert details['focus_signature']['tab_index'] == 4


def test_the_redraw_mode_passes_when_the_moved_frame_is_the_target(controller, tmp_path):
    cold, hot = _capture_dir(tmp_path)
    floor = _floor(cold, _frame(focused=3))
    _hot_frame(hot, _frame(focused=4))

    ok, message, details = controller.waitForNavTabIndex(
        expected_index=4, expected_count=8, timeout=0.5, source_path=floor,
        wait_for_redraw=True)
    assert ok, message
    assert details['matching_result'] == 1.0
    assert details['focus_signature']['tab_index'] == 4


def test_the_redraw_mode_returns_as_soon_as_the_focus_moves(controller, tmp_path):
    """It waits for the redraw, not for the window to run out."""
    cold, hot = _capture_dir(tmp_path)
    floor = _floor(cold, _frame(focused=3))

    def _late_frame():
        time.sleep(0.3)
        _hot_frame(hot, _frame(focused=4), age=0.0)

    import threading
    t = threading.Thread(target=_late_frame)
    t.start()
    started = time.time()
    ok, message, _ = controller.waitForNavTabIndex(
        expected_index=4, expected_count=8, timeout=5.0, source_path=floor,
        wait_for_redraw=True)
    elapsed = time.time() - started
    t.join()
    assert ok, message
    assert elapsed < 3.0, f"waited {elapsed:.1f}s — it should return when the focus moves"


def test_the_redraw_mode_falls_back_to_the_newest_frame(controller, tmp_path):
    """Nothing moves on screen: the verdict is the device's current state."""
    cold, hot = _capture_dir(tmp_path)
    floor = _floor(cold, _frame(focused=3))

    ok, message, details = controller.waitForNavTabIndex(
        expected_index=0, expected_count=8, timeout=0.3, source_path=floor,
        wait_for_redraw=True)
    assert not ok
    assert details['focus_signature']['tab_index'] == 3
    assert '3' in message


def test_the_default_mode_is_unchanged(controller, tmp_path):
    """Without the flag the check still waits for a MATCHING frame."""
    cold, hot = _capture_dir(tmp_path)
    floor = _floor(cold, _frame(focused=3))
    _hot_frame(hot, _frame(focused=4))

    ok, message, _ = controller.waitForNavTabIndex(
        expected_index=3, expected_count=8, timeout=0.5, source_path=floor)
    assert ok, message


def test_the_redraw_mode_counts_from_the_right_too(controller, tmp_path):
    """The movement is detected in the direction the leg asked for."""
    cold, hot = _capture_dir(tmp_path)
    floor = _floor(cold, _frame(focused=3))
    _hot_frame(hot, _frame(focused=2))

    # counting from the right of 8 tabs: tab 3 (from the left) is index 4, tab 2 is 5
    ok, message, details = controller.waitForNavTabIndex(
        expected_index=5, expected_count=8, timeout=0.5, source_path=floor,
        direction='right', wait_for_redraw=True)
    assert ok, message
    assert details['focus_signature']['tab_index'] == 2


def test_a_block_count_flip_is_not_a_movement(controller, tmp_path):
    """The focus did not move, only the bar's block count changed.

    The platform's block counter merges neighbouring labels, and it does so
    frame to frame: the French Settings bar reads 5, 6 or 7 blocks for its six
    columns. A frame where the labels before the focused one merged therefore
    carries a DIFFERENT index although the underline sits in the same place —
    and a walk that waits for the index to change burns its whole window on
    every step (measured on the box: the French walk read 5, 4, 3, 2, 1, 6, 5
    and never reached its target, the edge failed after 312 s).

    The check must keep waiting: the device has not caught up with the key yet.
    """
    cold, hot = _capture_dir(tmp_path)
    floor = _floor(cold, _frame(focused=3, tabs=8))
    # the label before the focus merged away: 7 blocks, the focused block is #2
    _hot_frame(hot, _frame(focused=3, tabs=8, skip=(1,)))

    started = time.time()
    ok, message, details = controller.waitForNavTabIndex(
        expected_index=5, expected_count=8, timeout=0.6, source_path=floor,
        wait_for_redraw=True)
    elapsed = time.time() - started
    assert not ok, 'the focus never moved — the check must not call it a movement'
    assert elapsed >= 0.4, (f'returned after {elapsed:.2f}s — the flipped frame '
                            f'was taken for a movement')


def test_a_movement_is_seen_even_when_the_index_stays_the_same(controller, tmp_path):
    """The focus moved one column, but the index of its block stayed the same.

    This is the same flip seen from the other side: a label merged on the way,
    so the focused block keeps its number although the underline sits on
    another column. The check must return that frame — it is the frame that
    shows the effect of the key — instead of waiting for its whole window.
    """
    cold, hot = _capture_dir(tmp_path)
    floor = _floor(cold, _frame(focused=3, tabs=8))

    def _late_frame():
        time.sleep(0.3)
        # the focus moved to tab 4 and the label before it merged: still 7
        # blocks, but the focused one is #3 — the same index as the floor
        _hot_frame(hot, _frame(focused=4, tabs=8, skip=(3,)), age=0.0)

    import threading
    t = threading.Thread(target=_late_frame)
    t.start()
    started = time.time()
    ok, message, details = controller.waitForNavTabIndex(
        expected_index=3, expected_count=8, timeout=2.0, source_path=floor,
        wait_for_redraw=True)
    elapsed = time.time() - started
    t.join()
    assert elapsed < 1.5, (f'waited {elapsed:.2f}s — the movement was not seen '
                           f'(the index alone cannot tell it)')
    assert details['focus_signature']['tab_index'] == 3


def test_the_baseline_is_the_frame_from_before_the_press(controller, tmp_path):
    """The frame the check is handed may already show the effect of the key.

    The screenshot the check is handed is taken AFTER the press, and on a busy
    host it can be taken after the device already redrew — then the check has no
    "before" to compare against and judges the still picture it was handed.
    `pressed_at` says when the key went out, so the newest capture written
    before that moment is the baseline. Measured on the operator's set-top box:
    the French walk read the state of the PREVIOUS press every time, so it
    pressed one column too far and the bar's wrap threw the target away.
    """
    cold, hot = _capture_dir(tmp_path)
    # the state before the press: the focus on tab 3
    _hot_frame(hot, _frame(focused=3), name='capture_000000001.jpg', age=30.0)
    # the frame the check is handed: taken after the redraw, the focus on tab 4
    floor = _floor(cold, _frame(focused=4), name='floor.png', age=0.0)
    # a frame written after the press that still shows the old focus
    _hot_frame(hot, _frame(focused=3), name='capture_000000002.jpg', age=5.0)

    pressed_at = time.time() - 10.0
    ok, message, details = controller.waitForNavTabIndex(
        expected_index=4, expected_count=8, timeout=0.5, source_path=floor,
        wait_for_redraw=True, pressed_at=pressed_at)
    assert ok, message
    assert details['focus_signature']['tab_index'] == 4


def test_without_the_press_time_the_handed_frame_is_the_baseline(controller, tmp_path):
    """A leg that does not say when the key went out keeps the old behaviour.

    The handed frame is then the baseline, and the check cannot tell a movement
    from the still picture it was given: it waits for its whole window.
    """
    cold, hot = _capture_dir(tmp_path)
    _hot_frame(hot, _frame(focused=3), name='capture_000000001.jpg', age=30.0)
    floor = _floor(cold, _frame(focused=4), name='floor.png', age=0.0)

    started = time.time()
    controller.waitForNavTabIndex(
        expected_index=4, expected_count=8, timeout=0.6, source_path=floor,
        wait_for_redraw=True)
    elapsed = time.time() - started
    assert elapsed >= 0.4, (f'returned after {elapsed:.2f}s — without the press '
                            f'time the handed frame is the baseline')


def test_a_frame_without_an_underline_does_not_break_the_check(controller, tmp_path):
    """A frame with no underline carries no focus: it must not break the check.

    The box shows live TV between the menus, and a live picture holds no
    underline at all. The check asked such a frame whether the focus moved and
    then read its tab count — 'NoneType' object has no attribute 'get' — so the
    whole check died on it and the walk pressed again (measured on the box:
    "Image verification execution error: 'NoneType' object has no attribute
    'get'").
    """
    cold, hot = _capture_dir(tmp_path)
    floor = _floor(cold, _frame(focused=3))
    # a picture without an underline: live TV between the menus
    _hot_frame(hot, _frame(focused=None))

    ok, message, details = controller.waitForNavTabIndex(
        expected_index=4, expected_count=8, timeout=0.3, source_path=floor,
        wait_for_redraw=True)
    assert not ok, message
    # the verdict still describes the focus the device showed
    assert details['focus_signature']['tab_index'] == 3


def test_the_newest_frame_answers_the_check(controller, tmp_path):
    """When nothing moves on screen, the verdict is the NEWEST frame.

    The capture directory hands its files back in no particular order, and the
    capture stream lags the screen (the round-trip on a busy host adds
    seconds), so reading them in that order let an OLD frame answer the check:
    the walk then read the state from before its own key and pressed one step
    too far (measured on the box: the French walk read 6, 5, 4, 3, 2, 1, 6 and
    never reached its target).
    """
    cold, hot = _capture_dir(tmp_path)
    floor = _floor(cold, _frame(focused=3, tabs=8))
    # an older frame: the label before the focus merged away (7 blocks)
    _hot_frame(hot, _frame(focused=3, tabs=8, skip=(1,)),
               name='capture_000000001.jpg', age=6.0)
    # the newest frame: all 8 blocks, the same focus
    _hot_frame(hot, _frame(focused=3, tabs=8),
               name='capture_000000002.jpg', age=1.0)

    ok, message, details = controller.waitForNavTabIndex(
        expected_index=5, expected_count=8, timeout=0.3, source_path=floor,
        wait_for_redraw=True)
    assert not ok, message
    # the NEWEST frame is the one that answers: 8 blocks, the focused one #3
    assert details['focus_signature']['tab_count'] == 8
    assert details['focus_signature']['tab_index'] == 3
