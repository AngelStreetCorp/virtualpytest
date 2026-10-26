"""The web fingerprint is computed on the browser page area, not the whole desktop (FINGERPRINT.md "Web fingerprints")."""
import numpy as np

from shared.src.lib.utils.web_viewport import crop_to_box, viewport_box


def test_box_of_a_window_with_top_chrome():
    # window at (0, 27) on a 1280x720 screen, 1280x693 outer, page 1272x606: tab strip + address bar = 87 px on top
    m = dict(sx=0, sy=27, ow=1280, oh=693, iw=1272, ih=606, sw=1280, sh=720)
    x, y, w, h = viewport_box(m, 1280, 720)
    assert (x, y) == (4, 110) or (x, y) == (4, 109) or (x, y) == (4, 110)
    assert w == 1272 and h == 606


def test_box_scales_with_the_capture_size():
    m = dict(sx=0, sy=0, ow=1000, oh=600, iw=1000, ih=500, sw=2000, sh=1000)
    assert viewport_box(m, 1000, 500) == (0, 50, 500, 250)


def test_unusable_metrics_give_no_box():
    assert viewport_box({}, 1280, 720) is None
    assert viewport_box(dict(sx=0, sy=0, ow=10, oh=10, iw=10, ih=10, sw=1280, sh=720), 1280, 720) is None


def test_two_pages_in_the_same_chrome_differ_only_after_the_crop():
    from backend_host.src.controllers.verification.image_helpers import ImageHelpers
    ih = ImageHelpers(None, None)
    rng = np.random.RandomState(1)
    chrome = rng.randint(0, 255, (720, 1280, 3)).astype(np.uint8)  # busy, identical desktop around the page
    a, b = chrome.copy(), chrome.copy()
    a[114:, :] = 10
    a[300:360, 200:600] = 240                                       # page A: one bar
    b[114:, :] = 10
    b[500:560, 700:1100] = 240                                      # page B: another bar
    box = (0, 114, 1280, 606)
    full = ih._dhash_hamming(ih._dhash_hex(__import__('cv2').cvtColor(a, 6)), ih._dhash_hex(__import__('cv2').cvtColor(b, 6)))
    crop = ih._dhash_hamming(ih._dhash_hex(__import__('cv2').cvtColor(crop_to_box(a, box), 6)),
                             ih._dhash_hex(__import__('cv2').cvtColor(crop_to_box(b, box), 6)))
    assert crop > full
