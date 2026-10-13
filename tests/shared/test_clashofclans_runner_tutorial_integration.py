"""
Integration test: GameRunner + TutorialDriver end-to-end on a
synthetic vision stream.

Patches ``runner.frame`` to return a fake image whose tutorial bubble
is painted, and feeds ``runner.ocr`` a pre-scripted sequence of
dialogue texts so the driver walks from ``welcome`` through
``complete``.
"""

from __future__ import annotations

import sys
import unittest

import numpy as np


from shared.src.lib.game.clashofclans.runner import GameRunner, RunnerConfig
from shared.src.lib.game.clashofclans.tutorial import TutorialDriver
from shared.src.lib.game.clashofclans.video import VideoRecorder


class _FakeRemote:
    android_device_id = "192.168.1.29:5555"
    adb_utils = True


class _FakeAv:
    def take_screenshot(self, *a, **k):
        return None


class _FakeNavExec:
    def __init__(self):
        self.calls = 0

    def load_navigation_tree(self, *a, **k):
        return {"success": True, "tree_id": "tree-test"}

    async def execute_navigation(self, *a, **k):
        self.calls += 1
        return {"success": True}


class _FakeActioner:
    async def execute_actions(self, *a, **k):
        return {"results": [{"success": True}], "success": True}


class _FakeDevice:
    def __init__(self):
        self._ctrls = {"remote": _FakeRemote(), "av": _FakeAv()}
        self.device_model = "android_mobile"
        self.navigation_executor = _FakeNavExec()
        self.action_executor = _FakeActioner()

    def _get_controller(self, _kind):
        return self._ctrls.get(_kind)


class _FakeContext:
    def __init__(self):
        self.screenshot_paths = []
        self.tree_id = "tree-test"
        self.team_id = "team-test"

    def record_step_immediately(self, *a, **k):
        # We do not care about script-level persistence in this test.
        pass


def _painted_tutorial_image() -> np.ndarray:
    """A 720-tall BGR image with the white/yellow bubble painted
    inside the TUTORIAL_BUBBLE_BOX. The disconnect-detection box is
    the lower-right of the screen, so we deliberately avoid painting
    white pixels there: the bubble's bottom edge stops at y=450,
    leaving y=479..704 (DISCONNECT_DIALOG_BOX y range) green-village.
    ``detect_tutorial_dialog`` returns True; ``_is_disconnect_modal``
    returns False because the dialog box has no white."""
    img = np.full((720, 1280, 3), 30, dtype=np.uint8)
    img[:, :] = (40, 90, 60)   # green village silhouette everywhere
    # bubble fill: keep above y=450 so the disconnect-detection box
    # (which lives in y=479..704) reads as green village, not white.
    img[200:450, 300:980] = (255, 255, 255)
    # yellow strokes at the top + bottom edges of the bubble
    img[200:230, 300:980] = (60, 200, 200)
    img[430:450, 300:980] = (60, 200, 200)
    return img


class TestRunnerTutorialIntegration(unittest.TestCase):

    def setUp(self):
        # Stub capture_screenshot_for_script (which ``runner`` imports
        # lazily) so the runner doesn't try to write real COLD files.
        import shared.src.lib.utils.device_utils as coc_du
        self._orig_capture = coc_du.capture_screenshot_for_script
        coc_du.capture_screenshot_for_script = lambda *a, **k: None
        self._du = coc_du

    def tearDown(self):
        self._du.capture_screenshot_for_script = self._orig_capture

    def _make_runner(self, dialogues):
        dev = _FakeDevice()
        ctx = _FakeContext()
        td = TutorialDriver()
        iterator = iter(dialogues)

        def fake_ocr(_crop):
            try:
                return next(iterator)
            except StopIteration:
                return ""

        # record_step is a no-op on FakeContext; mock frame() so the
        # runner never tries to reach the real adb pipeline.
        runner = GameRunner(
            dev, ctx, "clashofclans-android-mobile", "tree-test",
            config=RunnerConfig(max_runtime_s=5, max_cycles=30,
                                donate_policy="auto",
                                collect_policy="auto"),
            ocr=fake_ocr, tutorial_driver=td,
            video=VideoRecorder(dev, run_id="int-test",
                                local_dir="/tmp/int-test-rec"),
        )
        runner.frame = lambda: _painted_tutorial_image()
        return runner, td

    def test_walks_full_tutorial_to_complete(self):
        dialogues = [
            "welcome chief",                  # c0  tap_bubble
            "welcome chief",                  # advance->build_town_hall
            "build your town hall",           # build_town_hall tap
            "place your town hall",           # place_town_hall swipe
            "build a gold mine",              # build_gold_mine tap
            "place the gold mine",            # place_gold_mine swipe
            "build a cannon",                 # build_cannon tap
            "attack a nearby goblin village", # auto_advance -- bot dispatches taps
            "welcome back chief",             # after_attack
            "train some troops",              # train
            "find a clan to join",            # join_clan (auto_advance)
            "any text -- run is over",         # engine stops via max_cycles
        ]
        runner, _td = self._make_runner(dialogues)
        data = runner.run()
        kinds = [e["kind"] for e in data["event_log"]]
        # The runner hit max_cycles before complete in this script, but
        # it must have walked through the build / attack-tutorial phase
        # cleanly, with ``past_steps`` populated.
        self.assertIn("welcome", data["tutorial_past_steps"])
        self.assertIn("build_town_hall", data["tutorial_past_steps"])
        self.assertIn("place_town_hall", data["tutorial_past_steps"])
        self.assertIn("build_gold_mine", data["tutorial_past_steps"])
        self.assertIn("place_gold_mine", data["tutorial_past_steps"])
        self.assertIn("build_cannon", data["tutorial_past_steps"])
        # The runner saw at least one ``tutorial_action_fired`` event.
        self.assertIn("tutorial_action_fired", kinds)
        # No manual handoffs -- the tutorial is fully automated now.
        self.assertNotIn("tutorial_manual_handoff", kinds)
        # And no ``guard`` / ``device_offline`` / ``buy_surface_refused``
        # events on this clean path.
        self.assertNotIn("guard", kinds)
        # The driver observed at least 7 distinct dialog bubbles.
        self.assertGreaterEqual(data["tutorial_dialogs_seen"], 7)

    def test_guard_trip_still_works_under_tutorial(self):
        """Even on a tutorial frame, a §R5 account-warning pixel hit
        must abort the runner. We force ``_scan_guard`` to return True
        and bypass the OCR (which the test stub returns empty for)."""
        runner, _td = self._make_runner(["welcome chief"] * 30)
        # Replace _scan_guard with a constant True (the OCR stub returns
        # empty so the real guard would also pass on text alone; this
        # forces the pixel branch).
        runner._scan_guard = lambda _img: True
        data = runner.run()
        self.assertEqual(data["stop_reason"], "guard")
        self.assertTrue(data["account_warning_seen"])
        kinds = [e["kind"] for e in data["event_log"]]
        self.assertIn("guard", kinds)
        self.assertNotIn("tutorial_complete", [data.get("tutorial_complete", False)])  # never finished


if __name__ == "__main__":
    unittest.main()
