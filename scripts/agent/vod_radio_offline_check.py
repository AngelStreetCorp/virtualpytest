#!/usr/bin/env python3
"""Offline check of the content suite's CAUSE rules — no device, no host, no lease.

The suite's value is its split: a failure is a PRODUCT defect only when the
product really misbehaved. Everything else is infra (the platform could not do
the job, or the test could not measure it) or coverage (the surface is not
there / not mapped in that UI). This file proves that split without touching
anything: every platform is a fake.

Usage:
    python3 scripts/agent/vod_radio_offline_check.py

Exit code 0 = every check passed, 1 = at least one failed.
"""

from __future__ import annotations

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import test_scripts.content._mobile_adapter as mobile      # noqa: E402
import test_scripts.content._stb_adapter as stb            # noqa: E402
import test_scripts.content._web_adapter as web            # noqa: E402
from test_scripts.content._harness import (                # noqa: E402
    CAUSE_COVERAGE,
    CAUSE_INFRA,
    CAUSE_PRODUCT,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_SKIP,
    CaseContext,
    navigate_to,
)

RESULTS = []


def check(name, condition, detail=""):
    RESULTS.append((name, bool(condition), detail))
    print(f"{'PASS' if condition else 'FAIL'}  {name}"
          + (f"   [{detail}]" if detail else ""))


def expect(name, outcome, status, cause):
    check(name,
          outcome.status == status and outcome.cause == cause,
          f"status={outcome.status} cause={outcome.cause} reason={outcome.reason[:70]}")


# --------------------------------------------------------------------------
# fakes
# --------------------------------------------------------------------------

class FakeGraph:
    """A graph with edges, as the navigation executor exposes it."""

    def __init__(self, edges):
        self._edges = edges

    def edges(self, data=False):
        return list(self._edges)


class FakeExecutor:
    """A navigation executor: known labels have an id, unknown ones raise."""

    def __init__(self, known=(), failing=(), on_navigation=None, graph=None):
        self.known = set(known)
        self.failing = set(failing)
        self.on_navigation = on_navigation
        self.unified_graph = graph

    def load_navigation_tree(self, userinterface, team_id=None):
        return {"success": True, "tree_id": "tree-1"}

    def get_node_id(self, label, tree_id=None, team_id=None):
        if label in self.known:
            return f"node-{label}"
        raise ValueError(f"no node named '{label}' in the tree")

    async def execute_navigation(self, tree_id=None, userinterface_name=None,
                                 target_node_label=None, team_id=None, context=None):
        if target_node_label in self.failing:
            return {"success": False, "error": "the screen did not open"}
        if self.on_navigation:
            self.on_navigation(target_node_label)
        return {"success": True, "error": ""}


class FakeStuckExecutor(FakeExecutor):
    """A navigation that never answers: the platform's executor can wait for
    an element that never comes, and a case that waits forever is a case that
    never reports."""

    async def execute_navigation(self, tree_id=None, userinterface_name=None,
                                 target_node_label=None, team_id=None, context=None):
        await asyncio.sleep(30)
        return {"success": True, "error": ""}


class FakeContext:
    def __init__(self, userinterface="stb_tv"):
        self.tree_id = "tree-1"
        self.team_id = "team-1"
        self.userinterface = userinterface
        self.screenshot_paths = []
        self.metadata = {}


class FakeDevice:
    def __init__(self, executor=None, controllers=None, model="stb"):
        self.navigation_executor = executor
        self.device_model = model
        self.device_name = "fake-device"
        self._controllers = controllers or {}

    def _get_controller(self, kind):
        return self._controllers.get(kind)


class FakeRemote:
    """An IR / BLE / appium remote that always answers."""

    def press_key(self, key):
        return True

    def execute_command(self, command, params=None):
        if command in ("tap_coordinates", "click_element"):
            return {"success": True}
        if command == "get_installed_apps":
            return {"success": True, "apps": []}
        return {"success": True}

    def dump_elements(self):
        return True, [{"text": "Radio SRF 1", "content_desc": "",
                       "bounds": [10, 100, 200, 160], "clickable": True}], ""

    def get_status(self):
        return {"success": True}


class FakeWeb:
    """A browser controller that answers every command the adapter sends."""

    def __init__(self):
        self.url = "https://app.example/home"
        self.time = 0.0
        self.frames = 0
        # the reference tree is English; a profile that was never put in English
        # starts in German (the reference tree was built in German too)
        self.language = "en"

    async def execute_command(self, command, params=None):
        if command == "navigate_to_url":
            self.url = (params or {}).get("url") or self.url
            return {"success": True}
        if command == "execute_javascript":
            script = (params or {}).get("script") or ""
            if "video, audio" in script:
                self.time += 5.0
                self.frames += 30
                return {"success": True, "result": {
                    "found": True, "tag": "audio", "currentTime": self.time,
                    "paused": False, "ended": False, "readyState": 4,
                    "muted": False, "volume": 1.0, "count": 1,
                    "totalVideoFrames": self.frames}}
            if "no visible element matches" in script:
                return {"success": True, "result": {"pressed": True, "label": "Radio SRF 1"}}
            if "body.innerText" in script:
                return {"success": True, "result": "Radio SRF 1"}
            if "listitem" in script:
                return {"success": True, "result": ["Radio SRF 1"]}
            return {"success": True, "result": {
                "href": self.url, "path": "/home", "origin": "https://app.example",
                "username": "tester", "language": self.language}}
        return {"success": True}


class Args:
    def __init__(self, **kw):
        for key, value in kw.items():
            setattr(self, key, value)


def ctx_for(executor=None, controllers=None, model="stb", ui="stb_tv", **args):
    device = FakeDevice(executor, controllers, model)
    return device, Args(**args)


# --------------------------------------------------------------------------
# STB
# --------------------------------------------------------------------------

print("== stb ==")
stb.capture = lambda *a, **k: None

AUDIO = {"audible": None, "level_db": None, "frames": 0, "detail": "no reading"}


def fake_motion(ctx, threshold=None, window=None):
    return {"playing": False, "change": 0.0, "detail": "frame change 0.0% (threshold 1.0%)"}


def fake_audio(ctx, window_s=8.0, level_db=-50.0):
    return dict(AUDIO)


stb.motion_probe = fake_motion
stb.audio_probe = fake_audio

FAST = dict(settle_ms=0, play_seconds=0, stb_item_settle_s=0, stb_list_settle_s=0,
            stb_probe_gap_s=0, stb_probe_retries=1, max_items=1)

# (a) / (b): a caught exception is attributed by its type
for label, error, cause in (("AttributeError", AttributeError("boom"), CAUSE_INFRA),
                            ("RuntimeError", RuntimeError("the app refused"), CAUSE_PRODUCT)):
    def raiser(ctx, node, exc=error):
        raise exc

    original = stb.navigate_to
    stb.navigate_to = raiser
    device, args = ctx_for(FakeExecutor(), {"remote": FakeRemote()}, **FAST)
    outcome = stb.StbAdapter().run_radio(
        CaseContext(device, FakeContext(), args, "radio", "stb"))
    stb.navigate_to = original
    expect(f"stb radio catches a {label} -> {cause}", outcome, STATUS_FAIL, cause)

# (c) / (d): the surface that could not be opened
for name, known, cause, status in (
        ("node absent from the tree", (), CAUSE_COVERAGE, STATUS_SKIP),
        ("node in the tree but broken", ("replay",), CAUSE_PRODUCT, STATUS_FAIL)):
    device, args = ctx_for(FakeExecutor(known=known, failing={"replay"}),
                           {"remote": FakeRemote()}, **FAST)
    outcome = stb.StbAdapter().run_replay(
        CaseContext(device, FakeContext(), args, "replay", "stb"))
    expect(f"stb replay, {name} -> {cause}", outcome, status, cause)

# the radio rule: a still picture proves nothing
for audible, level, status, cause in ((True, -18.0, STATUS_PASS, None),
                                      (False, -60.0, STATUS_FAIL, CAUSE_PRODUCT),
                                      (None, None, STATUS_SKIP, CAUSE_INFRA)):
    AUDIO.clear()
    AUDIO.update({"audible": audible, "level_db": level, "frames": 3,
                   "detail": "3 frame(s), peak %s dB" % level})
    device, args = ctx_for(FakeExecutor(), {"remote": FakeRemote()}, **FAST)
    outcome = stb.StbAdapter().run_radio(
        CaseContext(device, FakeContext(), args, "radio", "stb"))
    expect(f"stb radio, still picture + audio {audible} -> {status}/{cause}",
           outcome, status, cause)

# a later silent row does not take the verdict of the row that was audible
AUDIO_SEQ = [{"audible": True, "level_db": -18.0, "frames": 3, "detail": "audible"},
             {"audible": False, "level_db": -60.0, "frames": 3, "detail": "silent"}]


def fake_audio_seq(ctx, window_s=8.0, level_db=-50.0):
    return dict(AUDIO_SEQ.pop(0)) if AUDIO_SEQ else dict(AUDIO)


stb.audio_probe = fake_audio_seq
device, args = ctx_for(FakeExecutor(), {"remote": FakeRemote()},
                       **dict(FAST, max_items=2))
outcome = stb.StbAdapter().run_radio(
    CaseContext(device, FakeContext(), args, "radio", "stb"))
expect("stb radio, audible row then a silent row -> PASS", outcome, STATUS_PASS, None)
stb.audio_probe = fake_audio

# the radio tile on the screen: a tree gap, never a defect of the product
def failing_nav(ctx, node, tree_id=None, timeout_s=90.0):
    return False, ("navigation to 'apps_radio' failed: verification failed - reference: "
                   "apps_radio.jpg not detected in source: capture_002945949.jpg. "
                   "Match score: 0.236 (required: 0.800)")


def failing_nav_no_tile(ctx, node, tree_id=None, timeout_s=90.0):
    return False, "navigation to 'apps_radio' failed: the screen never answered"


original_nav = stb.navigate_to
original_capture = stb.StbAdapter._capture
original_lines = stb.StbAdapter._screen_lines
stb.navigate_to = failing_nav
stb.StbAdapter._capture = lambda self, ctx, label: "/tmp/fake-frame.jpg"
stb.StbAdapter._screen_lines = lambda self, path, top_pct=0.0: [
    "apps appstore", "radio", "stingray music", "dance tv"]
device, args = ctx_for(FakeExecutor(known=("apps_radio",)),
                       {"remote": FakeRemote()},
                       **dict(FAST, stb_radio_tile_gap_s=0))
outcome = stb.StbAdapter().run_radio(
    CaseContext(device, FakeContext(), args, "radio", "stb"))
expect("stb radio, the Radio tile is on the screen but the tree cannot reach it "
       "-> FAIL/infra (a tree gap, not a defect)", outcome, STATUS_FAIL, CAUSE_INFRA)
check("stb radio, that row says the surface is present and names the tree gap",
      "Radio app IS on this box" in (outcome.reason or "")
      and "not a defect of the product" in (outcome.reason or ""),
      f"reason={outcome.reason[:70]}")

stb.StbAdapter._screen_lines = lambda self, path, top_pct=0.0: [
    "apps appstore", "stingray music", "dance tv"]
outcome = stb.StbAdapter().run_radio(
    CaseContext(device, FakeContext(), args, "radio", "stb"))
expect("stb radio, no radio tile on the screen -> the tree decides (infra on a "
       "stale reference)", outcome, STATUS_FAIL, CAUSE_INFRA)
check("stb radio, without a radio tile the row does not claim the surface exists",
      "Radio app IS on this box" not in (outcome.reason or ""),
      f"reason={outcome.reason[:70]}")

stb.navigate_to = failing_nav_no_tile
outcome = stb.StbAdapter().run_radio(
    CaseContext(device, FakeContext(), args, "radio", "stb"))
expect("stb radio, the tree route failed and no tile is visible -> infra",
       outcome, STATUS_FAIL, CAUSE_INFRA)

stb.navigate_to = original_nav
stb.StbAdapter._capture = original_capture
stb.StbAdapter._screen_lines = original_lines

# --------------------------------------------------------------------------
# the recording rule: a recording that was never requested is NOT a defect
# --------------------------------------------------------------------------

print("== stb recording ==")

LIST_BEFORE = ["aufgenommen", "malcolm mittendrin", "the big bang theory"]
LIST_AFTER = ["aufgenommen", "malcolm mittendrin", "the big bang theory", "neue sendung"]


def run_recording(lines_after, audible=None):
    """Run the recording case with a list that reads `lines_after` after the record."""
    adapter = stb.StbAdapter()
    state = {"recorded": False}

    def fake_capture(ctx, label):
        return f"/fake/{label}.jpg"

    def fake_lines(path, top_pct=0.25):
        return lines_after if state["recorded"] else LIST_BEFORE

    def fake_press_key(ctx, key_name, settle=0.5):
        if key_name == stb.StbAdapter.DEFAULT_RECORD_KEY:
            state["recorded"] = True
        return True, ""

    adapter._capture = fake_capture
    adapter._screen_lines = fake_lines
    audio = {"audible": audible, "level_db": -60.0 if audible is False else -18.0,
             "frames": 3, "detail": "the audio probe"}
    adapter._probe_audio = lambda ctx, *a, **k: dict(audio)
    original_press = stb.press_key
    stb.press_key = fake_press_key
    try:
        device, args = ctx_for(FakeExecutor(known={"recordings", "live"}),
                               {"remote": FakeRemote()},
                               **dict(FAST, record_wait_s=1, stb_record_poll_s=0.2))
        return adapter.run_recording(
            CaseContext(device, FakeContext(), args, "recording", "stb"))
    finally:
        stb.press_key = original_press


# the list does not change: nothing proves a recording was ever requested, so
# the product cannot be blamed for a recording that was never asked for
outcome = run_recording(LIST_BEFORE)
expect("stb recording, the list does not change -> SKIP/coverage (not a product defect)",
       outcome, STATUS_SKIP, CAUSE_COVERAGE)

# the recording IS listed but plays back silent: that is a product defect
outcome = run_recording(LIST_AFTER, audible=False)
expect("stb recording, listed but silent -> FAIL/product",
       outcome, STATUS_FAIL, CAUSE_PRODUCT)

# the recording is listed and plays back with sound: the case passes
outcome = run_recording(LIST_AFTER, audible=True)
expect("stb recording, listed and audible -> PASS", outcome, STATUS_PASS, None)

# --------------------------------------------------------------------------
# mobile
# --------------------------------------------------------------------------

print("== mobile ==")
mobile.capture = lambda *a, **k: None


def fake_mobile_motion(ctx, threshold=None, window=None):
    return {"playing": False, "change": 0.0, "detail": "frame change 0.0%"}


mobile.motion_probe = fake_mobile_motion

for label, error, cause in (("AttributeError", AttributeError("boom"), CAUSE_INFRA),
                            ("RuntimeError", RuntimeError("the app refused"), CAUSE_PRODUCT)):
    def raiser(ctx, node, exc=error):
        raise exc

    original = mobile.navigate_to
    mobile.navigate_to = raiser
    device = FakeDevice(FakeExecutor(), {"remote": FakeRemote()}, model="android_mobile")
    outcome = mobile.MobileAdapter().run_replay(
        CaseContext(device, FakeContext("stb_android_mobile"), Args(), "replay", "mobile"))
    mobile.navigate_to = original
    expect(f"mobile replay catches a {label} -> {cause}", outcome, STATUS_FAIL, cause)

for name, known, cause, status in (
        ("node absent from the tree", (), CAUSE_COVERAGE, STATUS_SKIP),
        ("node in the tree but broken", ("home_replay",), CAUSE_PRODUCT, STATUS_FAIL)):
    device = FakeDevice(FakeExecutor(known=known, failing={"home_replay"}),
                        {"remote": FakeRemote()}, model="android_mobile")
    outcome = mobile.MobileAdapter().run_replay(
        CaseContext(device, FakeContext("stb_android_mobile"), Args(), "replay", "mobile"))
    expect(f"mobile replay, {name} -> {cause}", outcome, status, cause)

# the radio rule on the phone: no motion is never a product defect
device = FakeDevice(FakeExecutor(known={"home"}), {"remote": FakeRemote()},
                    model="android_mobile")
outcome = mobile.MobileAdapter().run_radio(
    CaseContext(device, FakeContext("stb_android_mobile"),
                Args(play_seconds=1, settle_ms=0, radio_probe_nodes="home"),
                "radio", "mobile"))
expect("mobile radio, still picture -> SKIP/infra (never a product FAIL)",
       outcome, STATUS_SKIP, CAUSE_INFRA)

# a guest session plays nothing: that is the session, never a defect
def replay_with_session(guest):
    adapter = mobile.MobileAdapter()
    adapter._guest_session = guest
    device = FakeDevice(FakeExecutor(known=("home_replay",)), {"remote": FakeRemote()},
                        model="android_mobile")
    return adapter.run_replay(
        CaseContext(device, FakeContext("stb_android_mobile"),
                    Args(play_seconds=1, settle_ms=0, max_items=1), "replay", "mobile"))


outcome = replay_with_session(True)
expect("mobile replay, a guest session that plays nothing -> infra, not a defect",
       outcome, STATUS_FAIL, CAUSE_INFRA)
check("mobile replay: the row names the guest session",
      "guest session" in str(outcome.reason or ""), str(outcome.reason or "")[:110])

outcome = replay_with_session(False)
expect("mobile replay, a signed-in session that plays nothing -> a defect",
       outcome, STATUS_FAIL, CAUSE_PRODUCT)


# the app says why it plays nothing: "Please sign in with your account to
# play this content." That is the session, whatever the suite knows about it.
class FakeRemoteSignIn(FakeRemote):
    """A phone whose app refuses to play and says why."""

    def dump_elements(self):
        return True, [{"text": "Radio SRF 1", "content_desc": "",
                       "bounds": [10, 100, 200, 160], "clickable": True},
                      {"text": "<no text>",
                       "content_desc": "Please sign in with your account to play this content.",
                       "bounds": [48, 1404, 897, 1450], "clickable": False}], ""


device = FakeDevice(FakeExecutor(known=("home_replay",)), {"remote": FakeRemoteSignIn()},
                    model="android_mobile")
outcome = mobile.MobileAdapter().run_replay(
    CaseContext(device, FakeContext("stb_android_mobile"),
                Args(play_seconds=1, settle_ms=0, max_items=1), "replay", "mobile"))
expect("mobile replay, the app asks for a sign-in to play -> infra, not a defect",
       outcome, STATUS_FAIL, CAUSE_INFRA)
check("mobile replay: the row names the sign-in the app asked for",
      "sign-in" in str(outcome.reason or ""), str(outcome.reason or "")[:120])

# the app identity comes from the TREE, not from an environment variable: the
# entry edge of a mobile tree carries the launch action of the app it drives.
class FakeGraph:
    def __init__(self, edges):
        self._edges = edges

    def edges(self, data=True):
        return list(self._edges)


class FakeTreeExecutor(FakeExecutor):
    """An executor whose loaded tree carries a launch action."""

    def __init__(self, package=None, **kw):
        super().__init__(**kw)
        self.package = package
        self.unified_graph = FakeGraph([
            ("node-1", "node-2", {"action_sets": [
                {"actions": [{"command": "click_element",
                              "params": {"element_id": "Home"}}],
                 "retry_actions": ([{"command": "launch_app",
                                     "params": {"package": self.package}}]
                                   if self.package else [])}]}),
        ])

    def load_navigation_tree(self, userinterface, team_id=None):
        return {"success": True, "tree_id": "tree-1"}


adapter = mobile.MobileAdapter()
check("mobile: the app package is read from the tree's launch action",
      adapter._app_package_from_tree(
          CaseContext(FakeDevice(FakeTreeExecutor("com.example.tv")), FakeContext(),
                      Args(), "radio", "mobile")) == "com.example.tv")
check("mobile: no launch action in the tree -> no package",
      adapter._app_package_from_tree(
          CaseContext(FakeDevice(FakeTreeExecutor(None)), FakeContext(),
                      Args(), "radio", "mobile")) is None)

# a launch that fails is said as precisely as the phone allows
class FakeInstalledApps(FakeRemote):
    def __init__(self, packages):
        super().__init__()
        self.packages = list(packages)

    def execute_command(self, command, params=None):
        if command == "get_installed_apps":
            return {"success": True,
                    "apps": [{"app_name": "x", "package_name": p} for p in self.packages]}
        return super().execute_command(command, params)


adapter = mobile.MobileAdapter()
reason = adapter._launch_failure(
    CaseContext(FakeDevice(FakeExecutor(), {"remote": FakeInstalledApps([])}), FakeContext(),
                Args(), "radio", "mobile"), "com.example.tv", "")
check("mobile: a package that is not installed -> the reason says so",
      "not installed" in reason, reason[:90])
reason = adapter._launch_failure(
    CaseContext(FakeDevice(FakeExecutor(), {"remote": FakeInstalledApps(["com.example.tv"])}),
                FakeContext(), Args(), "radio", "mobile"), "com.example.tv", "")
check("mobile: an installed package that will not launch -> the reason says so",
      "installed but could not be launched" in reason, reason[:90])

# the phone's app sits behind a system dialog and the app's login screen:
# both are answered without a credential
class FakePhoneBehindDialog(FakeRemote):
    """A phone whose app is covered by Android's permission dialog and by
    the app's own login screen.

    Neither is answered with a credential: the suite taps "Don't allow" on
    the system dialog and uses the app's own "Skip login". After that the
    app's own surface is readable.
    """

    def __init__(self):
        super().__init__()
        self.dialog = True
        self.bypassed = False
        self.taps = []

    def dump_elements(self):
        elements = []
        if self.dialog:
            elements.append({"text": "Allow Example TV to send you notifications?",
                             "content_desc": "<no content-desc>",
                             "bounds": [102, 1717, 978, 1776], "clickable": False})
            elements.append({"text": "Don't allow", "content_desc": "<no content-desc>",
                             "bounds": [72, 1980, 1008, 2088], "clickable": True})
            elements.append({"text": "Allow", "content_desc": "<no content-desc>",
                             "bounds": [72, 1824, 1008, 1932], "clickable": True})
        if not self.bypassed:
            # the app publishes its labels in the content description, and the
            # dump fills the empty text field with the placeholder
            elements.append({"text": "<no text>", "content_desc": "Skip login. Button",
                             "bounds": [823, 147, 1032, 219], "clickable": True})
            elements.append({"text": "<no text>", "content_desc": "LOGIN. Button",
                             "bounds": [387, 750, 693, 858], "clickable": True})
        if not self.dialog and self.bypassed:
            # the app's own tab bar, with the widget's role attached
            elements.append({"text": "<no text>", "content_desc": "TV Guide. Button",
                             "bounds": [0, 690, 200, 780], "clickable": True})
            elements.append({"text": "<no text>", "content_desc": "Replay. Button",
                             "bounds": [200, 690, 400, 780], "clickable": True})
        return True, elements, ""

    def execute_command(self, command, params=None):
        if command == "tap_coordinates":
            x, y = int(params.get("x") or 0), int(params.get("y") or 0)
            self.taps.append((x, y))
            if self.dialog and 1980 <= y <= 2088:
                self.dialog = False
            if not self.bypassed and 147 <= y <= 219:
                self.bypassed = True
            return {"success": True}
        if command == "click_element":
            label = str(params.get("element_id") or "").lower()
            if label.startswith("don't allow"):
                self.dialog = False
            elif label.startswith("skip login"):
                self.bypassed = True
            return {"success": True}
        return super().execute_command(command, params)


phone = FakePhoneBehindDialog()
adapter = mobile.MobileAdapter()
adapter.prepare(CaseContext(FakeDevice(FakeTreeExecutor("com.example.tv"),
                                        {"remote": phone}),
                             FakeContext("stb_android_mobile"),
                             Args(app_ready_wait_s=2, app_ready_poll_s=0.5),
                             "radio", "mobile"))
check("mobile: Android's own permission dialog is answered",
      phone.dialog is False, f"dialog={phone.dialog}")
check("mobile: the app's own bypass is used, so no credential is needed",
      phone.bypassed is True, f"bypassed={phone.bypassed}")
check("mobile: the labels that carry the widget's role ('Skip login. Button') "
      "are still found", phone.bypassed is True, f"bypassed={phone.bypassed}")
check("mobile: a label that lives in the content description is found "
      "(the dump fills the empty text field with a placeholder)",
      phone.bypassed is True, f"bypassed={phone.bypassed}")
check("mobile: the app is ready once the dialog and the login are answered",
      adapter._app_ready is True and adapter._infra_reason == "",
      f"ready={adapter._app_ready} reason={adapter._infra_reason[:60]}")

# without the bypass the app never shows its own surface: the wait says so
class FakePhoneStuckOnLogin(FakePhoneBehindDialog):
    """The same phone, but the login screen is never answered."""

    def execute_command(self, command, params=None):
        if command == "tap_coordinates":
            self.taps.append((int(params.get("x") or 0), int(params.get("y") or 0)))
            return {"success": True}
        if command == "click_element":
            self.taps.append((0, 0))
            return {"success": True}
        return super().execute_command(command, params)


stuck = FakePhoneStuckOnLogin()
adapter = mobile.MobileAdapter()
stuck_ctx = CaseContext(FakeDevice(FakeTreeExecutor("com.example.tv"),
                                    {"remote": stuck}),
                         FakeContext("stb_android_mobile"),
                         Args(app_ready_wait_s=1, app_ready_poll_s=0.5),
                         "radio", "mobile")
adapter.prepare(stuck_ctx)
check("mobile: an app that stays behind its login screen never shows its surface",
      adapter._app_on_screen(stuck_ctx) is False, "the app's own surface is not readable")
check("mobile: the dialog and the bypass are tried again while the app is up",
      len(stuck.taps) >= 2, f"taps={len(stuck.taps)}")

# --------------------------------------------------------------------------
# web
# --------------------------------------------------------------------------

print("== web ==")
web.capture = lambda *a, **k: None

for label, error, cause in (("AttributeError", AttributeError("boom"), CAUSE_INFRA),
                            ("RuntimeError", RuntimeError("the app refused"), CAUSE_PRODUCT)):
    def raiser(*a, exc=error, **k):
        raise exc

    adapter = web.WebAdapter()
    original = adapter._goto
    adapter._goto = raiser
    device = FakeDevice(FakeExecutor(), {"web": FakeWeb()}, model="host_vnc")
    outcome = adapter.run_replay(
        CaseContext(device, FakeContext("web_tv"), Args(), "replay", "web"))
    adapter._goto = original
    expect(f"web replay catches a {label} -> {cause}", outcome, STATUS_FAIL, cause)

for name, known, cause, status in (
        ("node absent from the tree", (), CAUSE_COVERAGE, STATUS_SKIP),
        ("node in the tree but broken", ("radio_home",), CAUSE_PRODUCT, STATUS_FAIL)):
    device = FakeDevice(FakeExecutor(known=known, failing={"radio_home"}),
                        {"web": FakeWeb()}, model="host_vnc")
    outcome = web.WebAdapter().run_radio(
        CaseContext(device, FakeContext("web_tv"),
                    Args(radio_probe_nodes="radio_home"), "radio", "web"))
    expect(f"web radio, {name} -> {cause}", outcome, status, cause)

# the web radio case keeps its own proof: the media element advances
device = FakeDevice(FakeExecutor(), {"web": FakeWeb()}, model="host_vnc")
outcome = web.WebAdapter().run_radio(
    CaseContext(device, FakeContext("web_tv"),
                Args(play_seconds=1, probe_interval_s=0.5, settle_ms=0), "radio", "web"))
expect("web radio, the media element advances -> PASS", outcome, STATUS_PASS, None)


# --------------------------------------------------------------------------
# web: the app's language, and the sign-in box it puts over the app
# --------------------------------------------------------------------------

print("== web: the app's language ==")

check("web: the app's language is read from the page, never assumed",
      web.app_language({"language": '"de"'}) == "de"
      and web.app_language({"language": "en"}) == "en"
      and web.app_language({}) == "",
      f"quoted={web.app_language({'language': chr(34) + 'de' + chr(34)})!r} "
      f"empty={web.app_language({})!r}")

check("web: the suite speaks the language the app publishes",
      "alle sendungen" in web.CATALOGUE_TILE_LABELS["replay"]
      and "neue filme zum mieten" in web.CATALOGUE_TILE_LABELS["vod"]
      and any("schauen" in label for label in web.PLAY_ACTION_LABELS),
      f"replay={web.CATALOGUE_TILE_LABELS['replay']} "
      f"vod={web.CATALOGUE_TILE_LABELS['vod']}")

check("web: the sign-in box over the app is looked for, not only the sign-in page",
      "anmeldung" in web.SIGN_IN_PHRASES
      and "melde dich bitte mit deinen zugangsdaten an" in web.SIGN_IN_PHRASES,
      ", ".join(web.SIGN_IN_PHRASES))


# --------------------------------------------------------------------------
# web: the catalogue tile that opens a CATEGORY page is not the item
# --------------------------------------------------------------------------

class FakeWebCatalogue(FakeWeb):
    """A browser whose catalogue tile opens a category page, not the item.

    The item is only reachable through the tree's own route: the play action
    answers on the detail page and nowhere else. This is the shape of the
    real app (the catalogue shows its categories first), and the shape that
    produced the false "the catalogue offers no play action" defect.
    """

    def __init__(self, username="tester"):
        super().__init__()
        self.url = "https://app.example/en/home"
        self.username = username

    async def execute_command(self, command, params=None):
        if command == "navigate_to_url":
            self.url = (params or {}).get("url") or self.url
            return {"success": True}
        if command == "execute_javascript":
            script = (params or {}).get("script") or ""
            if "no tile found in the main area" in script:
                # the tile opens a category page: the URL changes, the item is not held
                self.url = "https://app.example/en/catalog/0/replay/ReplayCatalog"
                return {"success": True, "result": {
                    "pressed": True, "label": "Discover, Tab currently selected",
                    "x": 120, "y": 200}}
            if "no visible element matches" in script:
                if "/details/" not in self.url:
                    return {"success": True, "result": {
                        "pressed": False,
                        "reason": "no visible element matches [\"watch\",\"play\"]"}}
                self.url = "https://app.example/en/replaycatalog/0/details/replaytv/ch/show/1"
                return {"success": True, "result": {
                    "pressed": True, "label": "Watch, Press Enter or Space to Select",
                    "x": 300, "y": 300}}
            if "video, audio" in script:
                self.time += 5.0
                self.frames += 30
                return {"success": True, "result": {
                    "found": True, "tag": "video", "currentTime": self.time,
                    "paused": False, "ended": False, "readyState": 4,
                    "muted": False, "volume": 1.0, "count": 1,
                    "totalVideoFrames": self.frames}}
            if "totalVideoFrames" in script:
                # the video probe of the web adapter
                self.time += 5.0
                self.frames += 30
                return {"success": True, "result": {
                    "found": True, "tag": "video", "currentTime": self.time,
                    "paused": False, "ended": False, "readyState": 4,
                    "muted": False, "volume": 1.0, "count": 1,
                    "totalVideoFrames": self.frames}}
            if "body.innerText" in script:
                return {"success": True, "result": "More episodes"}
            if "listitem" in script:
                return {"success": True, "result": ["More episodes"]}
            return {"success": True, "result": {
                "href": self.url, "path": self.url.split("app.example")[-1],
                "origin": "https://app.example", "username": self.username,
                "language": "en"}}
        return {"success": True}


browser = FakeWebCatalogue()


def to_detail(label):
    """The tree's route puts the browser on the item's own page."""
    browser.url = "https://app.example/en/replaycatalog/0/details/replaytv/ch/show"


device = FakeDevice(FakeExecutor(on_navigation=to_detail),
                    {"web": browser}, model="host_vnc")
outcome = web.WebAdapter().run_replay(
    CaseContext(device, FakeContext("web_tv"),
                Args(play_seconds=1, probe_interval_s=0.5, settle_ms=0), "replay", "web"))
expect("web replay, a tile that opens a category page is not the item -> the tree route "
       "takes over -> PASS", outcome, STATUS_PASS, None)
check("web replay: the category page is never taken for the item",
      "category page" not in str(outcome.reason or ""), str(outcome.reason or "")[:90])


# the app's own sign-in box on a page that plays content: a session problem
class FakeWebSignInBox(FakeWebCatalogue):
    """A browser whose item page asks for a sign-in instead of playing."""

    def __init__(self):
        super().__init__()
        self.url = "https://app.example/en/replaycatalog/0/details/replaytv/ch/show"

    async def execute_command(self, command, params=None):
        if command == "execute_javascript":
            script = (params or {}).get("script") or ""
            if "body.innerText" in script:
                return {"success": True, "result": (
                    "Tagesschau, Verfuegbar fuer Replay. Anmelden "
                    "Melde dich bitte mit deinen Zugangsdaten an, um diesen Inhalt "
                    "abzuspielen.")}
        return await super().execute_command(command, params)


browser = FakeWebSignInBox()


def stay_on_detail(label):
    """the tree route keeps the item page open"""


device = FakeDevice(FakeExecutor(on_navigation=stay_on_detail),
                    {"web": browser}, model="host_vnc")
outcome = web.WebAdapter().run_replay(
    CaseContext(device, FakeContext("web_tv"),
                Args(play_seconds=1, probe_interval_s=0.5, settle_ms=0), "replay", "web"))
expect("web replay, the app asks for a sign-in to play -> infra, not a defect",
       outcome, STATUS_FAIL, CAUSE_INFRA)
check("web replay: the reason names the sign-in the app asked for",
      "sign-in" in str(outcome.reason or ""), str(outcome.reason or "")[:110])

# a guest session that finds no play action: the session, not a defect
class FakeWebGuestNoPlay(FakeWebCatalogue):
    """A guest session: the item page offers no play action.

    The app stores the guest account as the quoted empty string, so the
    session reads as a guest. The playback needs a signed-in user, so the
    item page carries no play button -- that is the session, never a defect
    of the app.
    """

    def __init__(self):
        super().__init__(username='""')

    async def execute_command(self, command, params=None):
        if command == "execute_javascript":
            script = (params or {}).get("script") or ""
            if "no visible element matches" in script and "/details/" in self.url:
                return {"success": True, "result": {
                    "pressed": False,
                    "reason": "no visible element matches [\"watch\",\"play\"]"}}
        return await super().execute_command(command, params)


guest_browser = FakeWebGuestNoPlay()


def to_detail_guest(label):
    """the tree route puts the guest browser on the item's own page"""
    guest_browser.url = "https://app.example/en/replaycatalog/0/details/replaytv/ch/show"


device = FakeDevice(FakeExecutor(on_navigation=to_detail_guest),
                    {"web": guest_browser}, model="host_vnc")
outcome = web.WebAdapter().run_replay(
    CaseContext(device, FakeContext("web_tv"),
                Args(play_seconds=1, probe_interval_s=0.5, settle_ms=0), "replay", "web"))
expect("web replay, a guest session with no play action -> infra, not a defect",
       outcome, STATUS_FAIL, CAUSE_INFRA)
check("web replay: the row names the guest session",
      "guest session" in str(outcome.reason or ""), str(outcome.reason or "")[:110])

# a signed-in session that finds no play action: that IS a defect
signed_browser = FakeWebGuestNoPlay()
signed_browser.username = "tester"


def to_detail_signed(label):
    signed_browser.url = "https://app.example/en/replaycatalog/0/details/replaytv/ch/show"


device = FakeDevice(FakeExecutor(on_navigation=to_detail_signed),
                    {"web": signed_browser}, model="host_vnc")
outcome = web.WebAdapter().run_replay(
    CaseContext(device, FakeContext("web_tv"),
                Args(play_seconds=1, probe_interval_s=0.5, settle_ms=0), "replay", "web"))
expect("web replay, a signed-in session with no play action -> a defect",
       outcome, STATUS_FAIL, CAUSE_PRODUCT)

# the app's own sign-in bypass: a guest session needs no credential
class FakeWebSignedOut(FakeWeb):
    """A browser that is logged out and shows the app's own bypass control."""

    def __init__(self):
        super().__init__()
        self.url = "https://app.example/en/home"
        self.skipped = False

    async def execute_command(self, command, params=None):
        if command == "navigate_to_url":
            self.url = (params or {}).get("url") or self.url
            return {"success": True}
        if command == "execute_javascript":
            script = (params or {}).get("script") or ""
            if "no visible element matches" in script:
                if not self.skipped:
                    return {"success": True, "result": {
                        "pressed": True, "label": "Skip login, Press Enter or Space to Select",
                        "x": 200, "y": 400}}
                return {"success": True, "result": {"pressed": False, "reason": "no match"}}
            if "body.innerText" in script:
                return {"success": True, "result": "Home"}
            return {"success": True, "result": {
                "href": self.url, "path": self.url.split("app.example")[-1],
                "origin": "https://app.example", "username": None, "language": "de"}}
        return {"success": True}


signed_out = FakeWebSignedOut()
device = FakeDevice(FakeExecutor(), {"web": signed_out}, model="host_vnc")
adapter = web.WebAdapter()
ready, why = adapter._ready(
    CaseContext(device, FakeContext("web_tv"), Args(), "replay", "web"))
check("web: the app's own sign-in bypass opens the app without a credential",
      ready, why[:90])
check("web: the bypass is used when the browser has no account",
      "skip login" in str(signed_out.url or "") or adapter._session == "guest",
      adapter._session)


# the app is open without an account: that is a guest session, not a dead run
class FakeWebGuest(FakeWeb):
    """A browser that shows the app's own home page without an account."""

    def __init__(self):
        super().__init__()
        self.url = "https://app.example/en/home"

    async def execute_command(self, command, params=None):
        if command == "execute_javascript":
            script = (params or {}).get("script") or ""
            if "body.innerText" in script:
                return {"success": True, "result": "Home"}
            return {"success": True, "result": {
                "href": self.url, "path": "/en/home",
                "origin": "https://app.example", "username": None, "language": "en"}}
        return {"success": True}


device = FakeDevice(FakeExecutor(), {"web": FakeWebGuest()}, model="host_vnc")
adapter = web.WebAdapter()
ready, why = adapter._ready(
    CaseContext(device, FakeContext("web_tv"), Args(), "replay", "web"))
check("web: an app that is open without an account is a guest session, not a skip",
      ready, why[:90])
check("web: the guest session is recorded as a guest",
      adapter._session == "guest", adapter._session)


# the recordings area that asks for a fresh sign-in
class FakeWebRecordings(FakeWeb):
    """A browser whose recordings screen sends the run to its sign-in page."""

    def __init__(self):
        super().__init__()
        self.url = "https://app.example/en/home"

    async def execute_command(self, command, params=None):
        if command == "navigate_to_url":
            self.url = (params or {}).get("url") or self.url
            if "/recordings" in self.url:
                self.url = "https://app.example/en/recordings/login"
            return {"success": True}
        if command == "execute_javascript":
            script = (params or {}).get("script") or ""
            if "body.innerText" in script:
                return {"success": True, "result": "Sign in"}
            return {"success": True, "result": {
                "href": self.url, "path": self.url.split("app.example")[-1],
                "origin": "https://app.example", "username": "tester", "language": "en"}}
        return {"success": True}


device = FakeDevice(FakeExecutor(), {"web": FakeWebRecordings()}, model="host_vnc")
outcome = web.WebAdapter().run_recording(
    CaseContext(device, FakeContext("web_tv"), Args(record_enabled=1), "recording", "web"))
expect("web recording, the recordings screen asks for a sign-in -> infra",
       outcome, STATUS_FAIL, CAUSE_INFRA)
check("web recording: the reason says which session the app asked for",
      "sign-in" in str(outcome.reason or ""), str(outcome.reason or "")[:110])

# a fresh browser opens a blank new tab: the app's address comes from the tree
class FakeWebBlankTab(FakeWeb):
    """A browser that shows nothing but a blank new tab."""

    def __init__(self):
        super().__init__()
        self.url = "http://chrome//new-tab-page/"

    async def execute_command(self, command, params=None):
        if command == "navigate_to_url":
            self.url = (params or {}).get("url") or self.url
            return {"success": True}
        if command == "execute_javascript":
            script = (params or {}).get("script") or ""
            if "body.innerText" in script:
                return {"success": True, "result": ""}
            return {"success": True, "result": {
                "href": self.url, "path": "//new-tab-page/",
                "origin": "http://chrome", "username": None, "language": None}}
        return {"success": True}


blank = FakeWebBlankTab()
tree_graph = FakeGraph([(
    "Entry", "home",
    {"action_sets": [{"actions": [{"command": "navigate_to_url",
                                  "params": {"url": "https://app.example/en/home"}}]}]},
)])
device = FakeDevice(FakeExecutor(graph=tree_graph), {"web": blank}, model="host_vnc")
adapter = web.WebAdapter()
ctx = CaseContext(device, FakeContext("web_tv"), Args(), "replay", "web")
check("web: a blank new tab is not the app",
      not adapter._app_is_open({"path": "//new-tab-page/", "href": blank.url}),
      "the app is open")
check("web: the app's address comes from the tree when the browser is blank",
      adapter._app_base_url(ctx) == "https://app.example/en/home",
      adapter._app_base_url(ctx))
adapter._goto(ctx, "/replaycatalog/0")
check("web: a path on a blank browser opens the app's own address",
      blank.url.startswith("https://app.example/") and "replaycatalog" in blank.url,
      blank.url)

# a navigation that never answers must not hang the suite
device = FakeDevice(FakeStuckExecutor(), {}, model="host_vnc")
ok, why = navigate_to(
    CaseContext(device, FakeContext("stb_tv"), Args(), "replay", "stb"),
    "replay", timeout_s=1.0)
check("harness: a navigation that never answers is bounded",
      not ok and "did not finish" in why, why[:90])

# --------------------------------------------------------------------------
# mobile: an empty app list is an ANSWER, not a failure
# --------------------------------------------------------------------------

class FakeEmptyApps(FakeRemote):
    """A phone that answers with an empty app list (the controller's
    `success: False` with an `apps` key)."""

    def execute_command(self, command, params=None):
        if command == "get_installed_apps":
            return {"success": False, "apps": [], "count": 0}
        return super().execute_command(command, params)


adapter = mobile.MobileAdapter()
reason = adapter._launch_failure(
    CaseContext(FakeDevice(FakeExecutor(), {"remote": FakeEmptyApps()}), FakeContext(),
                Args(), "radio", "mobile"), "com.example.tv", "")
check("mobile: an empty app list on a live phone -> the app is not installed",
      "not installed" in reason, reason[:90])


class FakeSilentPhone(FakeEmptyApps):
    """A phone that answers nothing: the app list and the screen both fail."""

    def dump_elements(self):
        return False, [], "the phone did not answer"


reason = adapter._launch_failure(
    CaseContext(FakeDevice(FakeExecutor(), {"remote": FakeSilentPhone()}), FakeContext(),
                Args(), "radio", "mobile"), "com.example.tv", "")
check("mobile: an unreachable phone -> the phone did not answer, not the app",
      "phone did not answer" in reason, reason[:90])


class FakeUnauthorizedPhone(FakeRemote):
    """A phone whose USB link is not authorized: it answers the app list with
    an error and no list at all, and its screen cannot be read either."""

    def execute_command(self, command, params=None):
        if command == "get_installed_apps":
            return {"success": False, "error": "adb: device unauthorized"}
        return super().execute_command(command, params)

    def dump_elements(self):
        return False, [], "adb: device unauthorized"


reason = adapter._launch_failure(
    CaseContext(FakeDevice(FakeExecutor(), {"remote": FakeUnauthorizedPhone()}), FakeContext(),
                Args(), "radio", "mobile"), "com.example.tv", "")
check("mobile: a phone that does not answer at all -> the phone, not the app",
      "phone did not answer" in reason and "not installed" not in reason,
      reason[:110])

# --------------------------------------------------------------------------

failed = [name for name, ok, _ in RESULTS if not ok]
print()
print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
if failed:
    print("FAILED: " + "; ".join(failed))
    sys.exit(1)
