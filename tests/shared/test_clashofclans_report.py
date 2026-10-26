"""
Unit tests for ``shared.src.lib.game.clashofclans.report`` (§81.1.8).

Mirrors the per-game ``test_<game>_*.py`` pattern (per the GAME_BOTS
template, §1 "Templates"). Tests run against synthetic data + a tiny
JPEG on disk -- never on real game screenshots.
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
import unittest


from shared.src.lib.game.clashofclans import report as coc_report


# 1x1 transparent PNG (48 bytes); written to a temp file by the tests.
_TINY_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


def _make_data():
    return {
        "userinterface": "clashofclans-android-mobile",
        "device_model": "s21_phone",
        "play_duration_s": 47.3,
        "cycles_observed": 8,
        "cycles_completed": 1,
        "gold_gained": 1234, "elixir_gained": 567, "dark_elixir_gained": 0,
        "troops_trained": 2, "troops_donated": 0,
        "capital_chests_collected": 0, "dailies_collected": 1,
        "actions_fired": 5, "guard_scan_count": 8,
        "no_observation_cycles": 0, "transition_cycles": 0,
        "buy_surface_refused": 0, "idle_seconds": 6,
        "attack_attempted": False, "account_warning_seen": False,
        "stop_reason": "max_cycles",
    }


def _make_events(cold_path=""):
    return [
        {"t": 0.0, "kind": "run_start", "cycle_index": -1,
         "userinterface": "clashofclans-android-mobile",
         "device_model": "s21_phone",
         "max_runtime_s": 1800, "max_cycles": 8},
        {"t": 0.5, "kind": "cycle_start", "cycle_index": 0},
        {"t": 1.0, "kind": "screen", "cycle_index": 0,
         "screen": "home", "collector_ready": [], "gold": 1000, "elixir": 750},
        {"t": 1.5, "kind": "decision", "cycle_index": 0,
         "action_name": "idle", "target": "home",
         "reason": "nothing_ready", "is_idle": True},
        {"t": 2.0, "kind": "idle", "cycle_index": 0,
         "reason": "nothing_ready", "idle_seconds": 1, "cold_path": cold_path},
        {"t": 11.0, "kind": "action_fired", "cycle_index": 5,
         "action_name": "collect_ready_collectors",
         "tree_node": "collect_resources",
         "success": True, "cycles_completed": 1,
         "kpi_count": 1, "cold_path": cold_path},
        {"t": 47.3, "kind": "run_stop", "cycle_index": -1,
         "stop_reason": "max_cycles", "play_duration_s": 47.3,
         "cycles_observed": 8, "cycles_completed": 1,
         "kpis": {"gold_gained": 1234, "elixir_gained": 567}},
    ]


class TestCocReport(unittest.TestCase):

    def setUp(self):
        self.data = _make_data()
        self.events = _make_events()

    def test_build_html_minimal(self):
        """A run with no screenshots produces HTML with the KPI bar and
        the event timeline; the URL is self-contained."""
        html = coc_report.build_html(self.data, self.events,
                                     title="CoC unit-test run")
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertIn("CoC unit-test run", html)
        self.assertIn("Cycles completed", html)
        self.assertIn("stop=max_cycles", html)
        self.assertIn("Run start", html)
        self.assertIn("Run stop", html)
        # Friendly badge labels for kinds.
        self.assertIn("Cycle", html)
        self.assertIn("Action", html)
        self.assertIn("Idle", html)

    def test_build_html_empty_events(self):
        """Zero events must not crash and the timeline row count is 0."""
        html = coc_report.build_html(self.data, [],
                                     title="CoC empty run")
        self.assertIn("Event timeline (0 events)", html)

    def test_build_html_with_screenshot(self):
        """A real screenshot on disk is inlined as a data: URI."""
        # Tiny PNG.
        png_bytes = base64.b64decode(_TINY_PNG_BASE64)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(png_bytes)
            png_path = f.name
        try:
            events = _make_events(cold_path=png_path)
            html = coc_report.build_html(self.data, events,
                                         title="CoC shots")
            # at least one inline image
            self.assertIn("data:image/png;base64,", html)
        finally:
            os.unlink(png_path)

    def test_build_html_dedupes_screenshots(self):
        """The timeline + gallery de-duplicate identical COLD paths.

        The defensive cap (200) is hard to test cheaply without 250 real
        PNGs on disk, so this only asserts that 10 events pointing at the
        same file produce exactly one inline screenshot + one gallery
        entry, not ten."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(base64.b64decode(_TINY_PNG_BASE64))
            png_path = f.name
        try:
            events = [
                {"t": float(i), "kind": "idle", "cycle_index": i,
                 "reason": "x", "cold_path": png_path}
                for i in range(10)
            ]
            html = coc_report.build_html(self.data, events,
                                         title="CoC dedup")
            # ten events -> one inline screenshot per timeline row but the
            # gallery is bounded by the unique count (== 1).
            self.assertIn("Screenshot gallery (1 unique)", html)
        finally:
            os.unlink(png_path)

    def test_build_event_json_round_trip(self):
        """Event JSON has every input event + every kpi key we care about."""
        events = _make_events()
        payload = json.loads(coc_report.build_event_json(self.data, events))
        self.assertEqual(payload["kpis"]["gold_gained"], 1234)
        self.assertEqual(payload["userinterface"], "clashofclans-android-mobile")
        self.assertEqual(payload["device_model"], "s21_phone")
        self.assertEqual(payload["play_duration_s"], 47.3)
        self.assertEqual(payload["cycles_observed"], 8)
        self.assertEqual(len(payload["event_log"]), len(events))
        # every kind in the kinds we exercise must be present
        kinds = [e["kind"] for e in payload["event_log"]]
        self.assertIn("run_start", kinds)
        self.assertIn("cycle_start", kinds)
        self.assertIn("decision", kinds)
        self.assertIn("action_fired", kinds)
        self.assertIn("run_stop", kinds)

    def test_build_html_video_section_present(self):
        """When data carries a run_video_path + chunks the report embeds a
        ``<video>`` element; when it does not, an inert card explains."""
        # Without a video: the "not recorded" card shows.
        html0 = coc_report.build_html(self.data, [], title="CoC no-video")
        self.assertIn("Run video (not recorded)", html0)
        self.assertNotIn("<video", html0)
        # With a video: a <video controls muted playsinline> element exists
        # and the data: URI is inlined.
        self.data["run_video_path"] = "/var/lib/vpt/coc_frames/run.mp4"
        self.data["run_video_chunk_count"] = 3
        # Build a 1 KB dummy "video" file so the inline reader finds it
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"\x00\x00\x00\x14ftypmp42" * 50)
            vpath = f.name
        try:
            self.data["run_video_path"] = vpath
            html1 = coc_report.build_html(self.data, [], title="CoC with-video")
            self.assertIn("<video", html1)
            self.assertIn("data:video/mp4;base64,", html1)
        finally:
            os.unlink(vpath)
            self.data["run_video_path"] = ""

    def test_build_html_video_oversize_skips_embed(self):
        """A video file > 50 MB does NOT inline (keeps the page light);
        instead a 'too large' notice + filename appears."""
        self.data["run_video_path"] = "/var/lib/vpt/coc_frames/big.mp4"
        self.data["run_video_chunk_count"] = 12
        # use a real file but smaller -- we exercise the branch by stubbing
        # _video_data_uri via the report's own helper.
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"x")  # 1 byte to satisfy exists()
            p = f.name
        try:
            self.data["run_video_path"] = p
            # Patch the size check by monkeypatching the helper at module level
            orig = coc_report._video_data_uri
            coc_report._video_data_uri = lambda x: None
            try:
                html = coc_report.build_html(self.data, [], title="CoC big")
            finally:
                coc_report._video_data_uri = orig
            self.assertIn("too large to inline", html)
        finally:
            os.unlink(p)
            self.data["run_video_path"] = ""

    def test_build_event_json_includes_run_video(self):
        """When run_video_path is set, the JSON has a ``run_video`` block
        with the local path, R2 URL, chunk count, and disabled reason."""
        data = dict(_make_data(), run_video_path="/var/lib/vpt/coc_frames/x.mp4",
                    run_video_r2_url="https://r2.example/x.mp4",
                    run_video_chunk_count=4,
                    run_video_disabled_reason="")
        events = _make_events()
        payload = json.loads(coc_report.build_event_json(data, events))
        self.assertIn("run_video", payload)
        self.assertEqual(payload["run_video"]["local_path"], "/var/lib/vpt/coc_frames/x.mp4")
        self.assertEqual(payload["run_video"]["r2_url"], "https://r2.example/x.mp4")
        self.assertEqual(payload["run_video"]["chunks"], 4)
        # No video key when path is empty
        data2 = _make_data()
        payload2 = json.loads(coc_report.build_event_json(data2, events))
        self.assertNotIn("run_video", payload2)


class TestCocScoreScript(unittest.TestCase):
    """The ``scripts/coc_score.py`` CLI ``metric=`` line."""

    def setUp(self):
        # Lazy import; the script may want to read /var/lib/vpt/coc_frames
        # which doesn't exist on the dev host. Always re-load so any
        # previous test that mutated sys.modules can't leak.
        import importlib.util
        import sys
        for k in [k for k in sys.modules if k == "coc_score"
                  or k.startswith("coc_score.")]:
            sys.modules.pop(k, None)
        spec = importlib.util.spec_from_file_location(
            "coc_score", "scripts/coc_score.py")
        self.coc_score = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.coc_score)

    def _payload(self, **overrides):
        p = _make_data()
        p.update(overrides)
        # Always include the full kpi dict (the grader reads k.*):
        if "kpis" in overrides:
            return {"userinterface": p["userinterface"],
                    "device_model": p["device_model"],
                    "play_duration_s": p["play_duration_s"],
                    "cycles_observed": p["cycles_observed"],
                    "kpis": overrides["kpis"],
                    "event_log": overrides.get("event_log", [])}
        return p

    def test_good_run_scores_10(self):
        payload = self._payload(
            kpis={
                "gold_gained": 4321, "elixir_gained": 1234,
                "dark_elixir_gained": 0,
                "troops_trained": 4, "troops_donated": 0,
                "capital_chests_collected": 1, "dailies_collected": 1,
                "cycles_completed": 1, "attack_attempted": False,
                "account_warning_seen": False,
                "stop_reason": "max_cycles",
                "actions_fired": 6, "guard_scan_count": 12,
                "no_observation_cycles": 0, "transition_cycles": 0,
                "buy_surface_refused": 0, "idle_seconds": 8,
            },
            event_log=[
                {"t": 0.0, "kind": "run_start", "cycle_index": -1},
                {"t": 0.5, "kind": "cycle_start", "cycle_index": 0},
                {"t": 11.0, "kind": "action_fired", "cycle_index": 5,
                 "action_name": "collect_ready_collectors",
                 "tree_node": "collect_resources",
                 "success": True, "cycles_completed": 1, "kpi_count": 1},
                {"t": 130.5, "kind": "run_stop", "cycle_index": -1,
                 "stop_reason": "max_cycles"},
            ],
        )
        score, _max, _rows = self.coc_score._grade(payload)
        # Good run WITHOUT video recording gets the 10 non-video criteria;
        # the 2 video criteria fail (no recording).
        self.assertEqual(score, 10)
        for n, h, _note in _rows:
            if n.startswith("run_video_"):
                self.assertFalse(h)

    def test_video_block_picks_up_both_criteria(self):
        """A run with the §81.1.9 run_video block scores both new criteria."""
        payload = {
            "userinterface": "clashofclans-android-mobile",
            "device_model": "s21_phone",
            "play_duration_s": 130.5,
            "cycles_observed": 14,
            "event_log": [
                {"t": 0.0, "kind": "run_start", "cycle_index": -1},
                {"t": 11.0, "kind": "action_fired", "cycle_index": 5,
                 "action_name": "collect_ready_collectors",
                 "tree_node": "collect_resources",
                 "success": True, "cycles_completed": 1, "kpi_count": 1},
            ],
            "kpis": {
                "gold_gained": 4321, "elixir_gained": 1234,
                "troops_trained": 4, "troops_donated": 0,
                "capital_chests_collected": 1, "dailies_collected": 1,
                "cycles_completed": 1, "attack_attempted": False,
                "account_warning_seen": False, "stop_reason": "max_cycles",
                "actions_fired": 6, "guard_scan_count": 14,
                "no_observation_cycles": 0, "transition_cycles": 0,
                "buy_surface_refused": 0, "idle_seconds": 8,
                "run_video_path": "/var/lib/vpt/coc_frames/x.mp4",
                "run_video_r2_url": "https://r2.example/x.mp4",
                "run_video_chunk_count": 4,
            },
            "run_video": {
                "local_path": "/var/lib/vpt/coc_frames/x.mp4",
                "r2_url": "https://r2.example/x.mp4",
                "chunks": 4, "disabled_reason": "",
            },
        }
        score, max_n, rows = self.coc_score._grade(payload)
        self.assertEqual(score, max_n)        # every criterion passes
        for n, h, _note in rows:
            if n.startswith("run_video_"):
                self.assertTrue(h)
        self.assertEqual(score, 12)            # full score on this fixture

    def test_video_recorded_but_not_uploaded_partial(self):
        """When the MP4 was recorded but R2 upload failed, the recorded
        criterion still hits -- the upload one doesn't."""
        payload = {
            "userinterface": "clashofclans-android-mobile",
            "device_model": "s21_phone",
            "play_duration_s": 30, "cycles_observed": 6,
            "event_log": [
                {"t": 0.0, "kind": "run_start", "cycle_index": -1},
                {"t": 11.0, "kind": "action_fired", "cycle_index": 5,
                 "action_name": "collect_ready_collectors",
                 "tree_node": "collect_resources",
                 "success": True, "cycles_completed": 1, "kpi_count": 1},
            ],
            "kpis": {
                "gold_gained": 100, "elixir_gained": 0, "dark_elixir_gained": 0,
                "troops_trained": 0, "troops_donated": 0,
                "capital_chests_collected": 0, "dailies_collected": 0,
                "cycles_completed": 1, "attack_attempted": False,
                "account_warning_seen": False, "stop_reason": "max_cycles",
                "actions_fired": 3, "guard_scan_count": 6,
                "no_observation_cycles": 0, "transition_cycles": 0,
                "buy_surface_refused": 0, "idle_seconds": 4,
                "run_video_path": "/var/lib/vpt/coc_frames/x.mp4",
                "run_video_r2_url": "",
                "run_video_chunk_count": 1, "run_video_disabled_reason": "",
            },
        }
        score, max_n, _rows = self.coc_score._grade(payload)
        recorded_hit = False
        uploaded_hit = False
        for n, h, _note in self.coc_score._grade(payload)[2]:
            if n == "run_video_recorded":
                recorded_hit = bool(h)
            elif n == "run_video_uploaded_to_R2":
                uploaded_hit = bool(h)
        self.assertTrue(recorded_hit)
        self.assertFalse(uploaded_hit)
        self.assertGreater(score, 10)        # 11/12: all + video recorded
        self.assertLess(score, max_n)        # but not 12/12 (upload failed)

    def test_guard_tripped_drops_score(self):
        payload = self._payload(
            # The _make_data default is cycles_observed=8; override so the
            # guard-tripped fixture actually represents a short abort.
            cycles_observed=1,
            play_duration_s=5.2,
            kpis={
                "gold_gained": 0, "elixir_gained": 0, "dark_elixir_gained": 0,
                "troops_trained": 0, "troops_donated": 0,
                "capital_chests_collected": 0, "dailies_collected": 0,
                "cycles_completed": 0, "attack_attempted": False,
                "account_warning_seen": True, "stop_reason": "guard",
                "actions_fired": 0, "guard_scan_count": 1,
                "no_observation_cycles": 0, "transition_cycles": 0,
                "buy_surface_refused": 0, "idle_seconds": 0,
            },
            event_log=[
                {"t": 0.0, "kind": "run_start", "cycle_index": -1},
                {"t": 0.5, "kind": "cycle_start", "cycle_index": 0},
                {"t": 5.0, "kind": "guard", "cycle_index": 0},
            ],
        )
        score, _max, rows = self.coc_score._grade(payload)
        # Guard-tripped run: cycles_observed=1 (so the >=5 fails), stop=guard
        # (so clean_budget_exit fails), action_fired_in_log fails (only guard
        # event), R5_quiet fails (warning was seen), no video recorded. The
        # three things that still pass are R1_locked, no_buy_surface_block,
        # guard_ran. Total = 3/12.
        self.assertEqual(score, 3)
        # the video criteria must not pass on the guard-tripped fixture
        for n, h, _note in rows:
            if n.startswith("run_video_"):
                self.assertFalse(h)
        # the video criteria must not pass on the guard-tripped fixture
        for n, h, _note in rows:
            if n.startswith("run_video_"):
                self.assertFalse(h)


if __name__ == "__main__":
    unittest.main()
