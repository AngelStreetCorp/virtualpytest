"""waitForNavTabIndex: the language-free "which tab is focused" check.

The focus underline of a menu bar moves with the UI language — a longer label
pushes every tab behind it sideways (measured on the operator's set-top box:
French moved TV Shop by +0.037 of the width). An image reference of that
underline therefore only matches in the language it was captured in, which is
what made the French run of the operator's tree fail on every Home tab.

The INDEX of the focused tab does not move: the tab order and the tab count are
the same in every language. This check reads that index off the live frame
(ImageHelpers._focus_signature) instead of matching pixels, so the same tree
passes in German, French, Italian and English.

Pure-CPU: synthetic frames, no device, no capture directory.
"""
import importlib

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
    """Left edge of tab `index`."""
    return TAB_X0 + index * (TAB_W + TAB_GAP)


def _frame(focused=None, tabs=8, underline=(0, 0, 220)):
    """A menu bar: `tabs` bright labels, an underline under tab `focused`.

    `underline` is the BGR colour of the underline. The operator's app flips it
    with the background: red under a dark hero, white under a bright one — and
    a red-only accent mask misses the white one completely.
    """
    img = np.zeros((H, W, 3), dtype=np.uint8)
    for i in range(tabs):
        x = _tab_x(i)
        img[LABEL_Y:LABEL_Y + LABEL_H, x:x + TAB_W] = 255  # white label
    if focused is not None:
        x = _tab_x(focused)
        img[UNDERLINE_Y:UNDERLINE_Y + UNDERLINE_H, x:x + TAB_W] = underline
    return img


def _write(tmp_path, img, name='frame.png'):
    path = tmp_path / name
    cv2.imwrite(str(path), img)
    return str(path)


def test_focus_signature_reads_the_tab_index(controller):
    img = _frame(focused=3)
    sig = controller.helpers._focus_signature(img)
    assert sig['kind'] == 'nav'
    assert sig['tab_index'] == 3


def test_white_underline_is_read_too(controller):
    """The app flips the underline colour with the background.

    Under a bright hero the focus underline is WHITE, and a red-only accent
    mask misses it completely — that is why the red underline crops scored
    0.000 on a bright screen.
    """
    img = _frame(focused=3, underline=(250, 250, 250))
    sig = controller._nav_underline_signature(img)
    assert sig is not None
    assert sig['kind'] == 'nav'
    assert sig['tab_index'] == 3


def test_a_red_poster_in_the_band_is_not_the_underline(controller):
    """A red poster inside the band must not be read as the focus underline."""
    img = _frame(focused=3)
    img[120:150, 600:800] = (0, 0, 220)  # a red block in the band, no index
    sig = controller._nav_underline_signature(img)
    assert sig is not None
    assert sig['tab_index'] == 3


def test_matching_index_passes(controller, tmp_path):
    path = _write(tmp_path, _frame(focused=3))
    ok, message, details = controller.waitForNavTabIndex(
        expected_index=3, expected_count=8, timeout=0.2, source_path=path)
    assert ok, message
    assert details['matching_result'] == 1.0
    assert details['focus_signature']['tab_index'] == 3


def test_wrong_index_fails_and_reports_the_seen_one(controller, tmp_path):
    path = _write(tmp_path, _frame(focused=3))
    ok, message, details = controller.waitForNavTabIndex(
        expected_index=5, expected_count=8, timeout=0.2, source_path=path)
    assert not ok
    assert '3' in message and '5' in message
    assert details['matching_result'] == 0.0


def test_tab_count_outside_the_slack_fails(controller, tmp_path):
    """A bar with 6 tabs is not the 9-tab bar of the operator's box."""
    path = _write(tmp_path, _frame(focused=3, tabs=6))
    ok, _message, _ = controller.waitForNavTabIndex(
        expected_index=3, expected_count=9, timeout=0.2, source_path=path)
    assert not ok


def test_tab_count_within_the_slack_passes(controller, tmp_path):
    """An old frame may merge or split one icon: FP_TAB_COUNT_SLACK is 1."""
    path = _write(tmp_path, _frame(focused=3, tabs=8))
    ok, message, _ = controller.waitForNavTabIndex(
        expected_index=3, expected_count=9, timeout=0.2, source_path=path)
    assert ok, message


def test_frame_without_an_underline_fails(controller, tmp_path):
    path = _write(tmp_path, _frame(focused=None))
    ok, message, _ = controller.waitForNavTabIndex(
        expected_index=0, expected_count=8, timeout=0.2, source_path=path)
    assert not ok
    assert 'nav' in message.lower()


def test_missing_tab_index_is_rejected(controller, tmp_path):
    path = _write(tmp_path, _frame(focused=1))
    ok, message, _ = controller.waitForNavTabIndex(
        expected_index=None, expected_count=8, timeout=0.2, source_path=path)
    assert not ok
    assert 'tab_index' in message


def test_timeout_zero_scores_only_the_given_frame(controller, tmp_path):
    """timeout=0 means "score exactly this frame".

    The verification executor runs the legs of a node against one shared frame
    window and feeds each leg frame by frame with timeout=0; the leg's own
    timeout is the eligibility window. Polling the capture directory inside the
    leg would double the work and slow every leg down by about a second (the hot
    directory holds a thousand frames).
    """
    path = _write(tmp_path, _frame(focused=2))
    ok, message, details = controller.waitForNavTabIndex(
        expected_index=2, expected_count=9, timeout=0, source_path=path)
    assert ok, message
    assert details['matching_result'] == 1.0

    ok, message, _ = controller.waitForNavTabIndex(
        expected_index=3, expected_count=9, timeout=0, source_path=path)
    assert not ok
    assert '2' in message and '3' in message


def test_localize_focus_signature_reads_a_white_underline(controller):
    """Localize's own matcher (identify_screen) uses ImageHelpers._focus_signature, not the controller's check.

    A white underline under a bright hero used to read as no underline: the focus fell to a 'box' (the one+ badge),
    Home abstained and the registry made one row per hero poster (TASK-159). The same Home tab must read as the
    same nav tab whatever colour the underline has, and a red block in the band must not be taken for it.
    """
    h = controller.helpers
    red = h._focus_signature(_frame(focused=3))
    white = h._focus_signature(_frame(focused=3, underline=(250, 250, 250)))
    assert white['kind'] == 'nav' and white['tab_index'] == red['tab_index'] == 3
    img = _frame(focused=3, underline=(250, 250, 250))
    img[120:150, 600:800] = (0, 0, 220)
    assert h._focus_signature(img)['tab_index'] == 3
    assert h._focus_signature(_frame(focused=None))['kind'] != 'nav'

