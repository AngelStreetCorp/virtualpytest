#!/usr/bin/env python3
"""
Mobile adapter — the Android PHONE platform for the content-surface suite.

Platform facts this adapter is built on (verified live on the mobile
app, device model `android_mobile`, userinterface `stb_android_mobile`):

* The navigation tree models the app's screens, not its content. The nodes are
  home, ENTRY, live, live_fullscreen, home_tvguide, tvguide_livetv, home_saved,
  home_replay, home_movies, home_profile and settings — there is NO node per
  programme, per title or per radio station, and NO radio node at all.
* Every edge in that tree is `action_type: remote`, `command: click_element`
  with an `element_id`. So the phone is driven through the remote controller's
  element clicking (uiautomator dump + tap / click), not through IR keys.
* A phone has no media element to inspect, so playback is confirmed the only
  honest way: the SCREEN MOTION probe (`_harness.motion_probe` ->
  `ZapExecutor.detect_real_motion`). The frame-to-frame change is the verdict.

Three things this adapter refuses to do, because they are how a benchmark gets
invalidated:

1. It never reports a product defect for something the platform could not do.
   A phone that is not reachable over ADB, an app that is not installed, a
   navigation that timed out — those are `infra`.
2. It never reports a product defect for a surface that is not in this UI.
   There is no radio node in the mobile tree, so radio is a DISCOVERY step: if
   no radio source can be reached, the case is SKIP / `coverage`. A surface
   that IS in the tree and still cannot be opened is the opposite: the surface
   is there and it did not work, so that is a product defect.
3. It never lets an exception escape. An exception that reaches the runner is
   classified by the harness as `infra`, which would misattribute a product bug.
   Every error is caught here and returned as a CaseOutcome whose cause says
   who is to blame: `exception_cause` splits a programming error in this file
   (infra) from an application-level error (product).
4. It never reads "the picture did not move" as "the content did not play" on
   an audio-only surface. A radio station is a static logo with sound, and the
   phone carries no audio analysis, so that case can only ever SKIP / `infra`.

The runtime iteration loop is the prior art of the STB content scripts
(`test_scripts/tv/_content_play.py` on the unmerged `task80-stb-content-scripts`
branch): the catalogue has to be walked at RUNTIME, and the honest claim from a
run is "I iterated N items with motion-validated playback" — never "I played
every item available on the device".

Underscore-prefixed on purpose: `is_discoverable_script_ref` hides it from the
RunTests picker. It is not a runnable script.
"""

import asyncio
import inspect
import os
import re
import time

from test_scripts.content._harness import (
    Adapter,
    CaseOutcome,
    CAUSE_COVERAGE,
    CAUSE_INFRA,
    CAUSE_PRODUCT,
    capture,
    exception_cause,
    motion_probe,
    navigate_to,
    press_key,
    sleep,
    surface_failure,
    tree_id_for,
)


# --------------------------------------------------------------------------
# label vocabulary
#
# The phone UI is text-driven (uiautomator dump), so the labels below are what
# the adapter recognises. Both the English and the German wording of the app is
# listed, because the account language is a device setting, not a constant.
# --------------------------------------------------------------------------

# Chrome of the app shell: the bottom navigation, the header, the buttons that
# are never a content row. A candidate whose label is in here is skipped.
_CHROME_LABELS = frozenset({
    "home", "startseite", "start", "carousel",
    "live", "live tv", "fernsehen", "tv", "tvb",
    "tv guide", "tvguide", "tv programm", "programm", "guide", "epg",
    "replay", "catchup", "mediathek",
    "movies", "movie", "movies & series", "filme & serien", "filme", "serien",
    "vod", "recordings", "saved", "aufnahmen", "aufzeichnung", "aufnahme",
    "profile", "profil", "settings", "einstellungen", "shop", "tv shop", "apps",
    "search", "suche", "back", "zurück", "menu", "more", "mehr", "info",
    "share", "teilen", "close", "schließen", "schliessen", "cancel",
    "abbrechen", "ok", "yes", "no", "ja", "nein", "loading",
    "play", "play arrow", "abspielen", "pause", "stop", "skip", "next",
    "weiter", "previous", "zurückspringen", "volume", "lautstärke", "settings icon",
})

# The control that starts playback (an icon on a programme page, mostly).
_PLAY_KEYWORDS = ("play", "abspielen", "ansehen", "watch", "▶", "▷")
_PLAY_EXACT = ("▶", "▷", "play", "play arrow", "play_arrow", "start playback")

# The control that starts a recording.
_RECORD_KEYWORDS = ("record", "aufnehmen", "aufnahme", "aufzeichnung", "recorder")
_RECORD_EXACT = ("rec", "recording", "aufnahme starten", "record sendung")

# The app's own surface labels: used to recognise the TV app when its
# package name is not known (the package is not written in this repository).
_APP_SURFACE_LABELS = (
    "replay", "tv guide", "tvguide", "tv programm", "aufnahmen", "recordings",
    "filme & serien", "movies & series", "programm", "radio", "live",
)

# The app's own guest bypass. The login screen offers a way in without an
# account, and the suite uses it: a guest session is what the app gives, and
# the content surfaces are reachable without a credential.
_SKIP_LOGIN_LABELS = (
    "skip login", "skip sign in", "skip registration", "skip the login",
    "anmeldung überspringen", "anmelden überspringen", "als gast fortfahren",
    "continue as guest",
)

# Android's own permission dialog ("Allow <app> to send you notifications?").
# It belongs to the system and sits on top of the app's first screen, so
# nothing of the app is reachable until it is answered.
_PERMISSION_DIALOG_MARKERS = (
    "send you notifications", "notifications?", "benachrichtigung",
)
_PERMISSION_DENY_LABELS = (
    "don't allow", "don’t allow", "dont allow", "nicht erlauben", "ablehnen",
    "deny", "nicht zulassen",
)
_PERMISSION_ALLOW_LABELS = ("allow", "erlauben", "zulassen")


# The app's own sign-in prompt on the pages that play content. When the app
# says this, it refuses to play for this session: a session problem, never a
# defect of the product. The same words the web app publishes.
SIGN_IN_PHRASES = (
    "please sign in with your account to play",
    "sign in with your account to play",
    "sign in with your access data to play",
    "sign in to play this content",
    "please sign in with your account",
    "melde dich bitte mit deinen zugangsdaten an",
    "anmeldung",
    "sign in",
    "log in",
    "se connecter",
    "accedi",
)


class MobileAdapter(Adapter):
    """Content-surface mechanics for an Android phone.

    Every case returns a CaseOutcome. The adapter never prints a result line
    and never builds the summary — `_harness.run_suite` owns both.
    """

    platform = "mobile"

    def __init__(self):
        # Set by prepare() when the platform itself cannot run the cases. The
        # cases then report it as infra instead of blaming the product.
        self._infra_reason = ""
        self._app_ready = False
        # True when the suite itself used the app's guest bypass. The app
        # then plays nothing for that session, and a refusal is the session,
        # never a defect of the product.
        self._guest_session = False

    # ------------------------------------------------------------------
    # arguments
    # ------------------------------------------------------------------

    @staticmethod
    def _max_items(ctx):
        try:
            return max(1, int(ctx.arg("max_items", 3) or 3))
        except (TypeError, ValueError):
            return 3

    @staticmethod
    def _play_seconds(ctx):
        try:
            return max(1.0, float(ctx.arg("play_seconds", 12) or 12))
        except (TypeError, ValueError):
            return 12.0

    @staticmethod
    def _settle_s(ctx):
        try:
            return max(0.0, float(ctx.arg("settle_ms", 800) or 800) / 1000.0)
        except (TypeError, ValueError):
            return 0.8

    @staticmethod
    def _record_wait_s(ctx):
        try:
            return max(1.0, float(ctx.arg("record_wait_s", 45) or 45))
        except (TypeError, ValueError):
            return 45.0

    @staticmethod
    def _poll_s(ctx):
        try:
            return max(1.0, float(ctx.arg("record_poll_s", 5) or 5))
        except (TypeError, ValueError):
            return 5.0

    @staticmethod
    def _number(ctx, name, default):
        """A number from the run's arguments, with a default."""
        try:
            return float(ctx.arg(name, default) or default)
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def _keywords(ctx, name, default):
        """A comma separated list of keywords, with a default."""
        raw = ctx.arg(name, None)
        if not raw:
            raw = ",".join(default)
        return [part.strip().lower() for part in str(raw).split(",") if part.strip()]

    # ------------------------------------------------------------------
    # platform mechanics
    # ------------------------------------------------------------------

    def _remote(self, ctx):
        return ctx.controller("remote")

    def _command(self, ctx, command, params=None):
        """Send one command to the phone's remote controller.

        Returns (ok, detail, payload). The android_mobile controller is
        synchronous; an awaitable result is still handled, so the adapter also
        works on a controller whose execute_command is a coroutine.
        """
        remote = self._remote(ctx)
        if remote is None:
            return False, "the phone has no remote controller", {}
        try:
            result = remote.execute_command(command, params or {})
        except Exception as exc:                                   # noqa: BLE001
            return False, f"the remote command '{command}' raised: {exc}", {}
        if inspect.isawaitable(result):
            try:
                result = asyncio.run(result)
            except Exception as exc:                               # noqa: BLE001
                return False, f"the remote command '{command}' raised: {exc}", {}
        if not isinstance(result, dict):
            result = {"success": bool(result)}
        ok = bool(result.get("success", False))
        return ok, (result.get("error") or ""), result

    @staticmethod
    def _normalize_element(element):
        """One UI element as a plain dict, whatever the controller returned."""
        if isinstance(element, dict):
            get = element.get
            raw = {
                "text": get("text"),
                "content_desc": get("content_desc") or get("contentDesc"),
                "resource_id": get("resource_id") or get("resourceId"),
                "class_name": get("class_name") or get("className"),
                "bounds": get("bounds"),
                "clickable": bool(get("clickable", False)),
                "under_clickable": get("under_clickable"),
                "id": get("id") if get("id") is not None else get("element_id"),
            }
        else:
            def attr(name, default=None):
                value = getattr(element, name, default)
                return default if value is None else value

            raw = {
                "text": attr("text", ""),
                "content_desc": attr("content_desc", attr("contentDesc", "")),
                "resource_id": attr("resource_id", ""),
                "class_name": attr("class_name", attr("className", "")),
                "bounds": attr("bounds"),
                "clickable": bool(attr("clickable", False)),
                "under_clickable": attr("under_clickable"),
                "id": attr("id"),
            }
        return {
            "text": str(raw["text"] or "").strip(),
            "content_desc": str(raw["content_desc"] or "").strip(),
            "resource_id": str(raw["resource_id"] or "").strip(),
            "class_name": str(raw["class_name"] or "").strip(),
            "bounds": raw["bounds"],
            "clickable": bool(raw["clickable"]),
            "under_clickable": raw["under_clickable"],
            "id": raw["id"],
        }

    def _dump(self, ctx):
        """Read the current screen. Returns (ok, elements, detail)."""
        remote = self._remote(ctx)
        if remote is None:
            return False, [], "the phone has no remote controller"
        dump = getattr(remote, "dump_elements", None)
        if callable(dump):
            try:
                success, elements, error = dump()
            except Exception as exc:                               # noqa: BLE001
                return False, [], f"the UI dump raised: {exc}"
            if not success:
                return False, [], f"the UI dump failed: {error or 'unknown error'}"
            return True, [self._normalize_element(e) for e in (elements or [])], ""
        # Fallback for a controller whose dump only exists as a command.
        ok, detail, payload = self._command(ctx, "dump_elements", {})
        if not ok:
            return False, [], detail or "the UI dump failed"
        return True, [self._normalize_element(e) for e in (payload.get("elements") or [])], ""

    def _screen_size(self, ctx):
        """(width, height) of the live screen, or None."""
        remote = self._remote(ctx)
        if remote is None:
            return None
        for getter in ("get_orientation", "get_device_resolution"):
            fn = getattr(remote, getter, None)
            if not callable(fn):
                continue
            try:
                size = fn()
            except Exception:                                      # noqa: BLE001
                size = None
            if isinstance(size, dict) and size.get("width") and size.get("height"):
                return int(size["width"]), int(size["height"])
        return None

    # -- element helpers -------------------------------------------------

    @staticmethod
    def _label(element):
        """The element's own name: its content description, then its text.

        The platform's dump fills an empty field with the placeholder
        `<no text>` / `<no content-desc>`, and a placeholder is not a name.
        The platform prints the name with the content description first; this
        reads it the same way, so a button that carries its name in the
        description ("Skip login. Button") is found — with the text read
        first, the placeholder would win and the name would be lost.
        """
        for key in ("content_desc", "text"):
            value = str(element.get(key) or "").strip()
            if value and not value.startswith("<no "):
                return value
        return ""

    @staticmethod
    def _normalize_text(value):
        value = str(value or "").strip().lower()
        value = value.replace("…", "").replace("...", "")
        value = re.sub(r"\s+", " ", value)
        return value.strip(" ·•-:–—|")

    @staticmethod
    def _bounds_center(bounds):
        """The centre of an element's bounds, or None."""
        if bounds is None:
            return None
        if isinstance(bounds, dict):
            left = bounds.get("left")
            top = bounds.get("top")
            right = bounds.get("right")
            bottom = bounds.get("bottom")
            if None in (left, top, right, bottom):
                return None
            return (int((int(left) + int(right)) / 2), int((int(top) + int(bottom)) / 2))
        if isinstance(bounds, (list, tuple)) and len(bounds) == 4:
            try:
                left, top, right, bottom = (int(v) for v in bounds)
            except (TypeError, ValueError):
                return None
            return ((left + right) // 2, (top + bottom) // 2)
        if isinstance(bounds, str):
            match = re.search(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]", bounds)
            if match:
                x1, y1, x2, y2 = (int(v) for v in match.groups())
                return ((x1 + x2) // 2, (y1 + y2) // 2)
        return None

    @staticmethod
    def _key(element):
        """A stable identity for an element, so it is tried only once."""
        for value in (element.get("resource_id"), element.get("content_desc"),
                      element.get("text")):
            if value:
                return MobileAdapter._normalize_text(value)
        center = MobileAdapter._bounds_center(element.get("bounds"))
        return f"@{center}" if center else ""

    def _candidates(self, elements, size):
        """The elements that can be a content row on a list screen.

        The phone list is a vertical feed; the app's own chrome (the bottom
        navigation bar, the header buttons) must not be tapped. Clickable
        rows come first, because a phone card is usually a clickable container
        with the title as a child view.
        """
        height = size[1] if size else 0
        candidates = []
        for index, element in enumerate(elements):
            label = self._label(element)
            if not label or len(label) < 2:
                continue
            normalized = self._normalize_text(label)
            if not normalized or normalized in _CHROME_LABELS:
                continue
            center = self._bounds_center(element.get("bounds"))
            if center and height and center[1] > height * 0.92:
                continue          # the bottom navigation bar of the app
            candidates.append((index, element))
        candidates.sort(key=lambda pair: (
            0 if (pair[1].get("clickable") or pair[1].get("under_clickable")) else 1,
            pair[0],
        ))
        return [element for _, element in candidates]

    def _find_by_keywords(self, elements, keywords, exact=()):
        """The first element whose label contains one of the keywords."""
        for element in elements:
            label = self._normalize_text(self._label(element))
            if not label:
                continue
            if label in exact:
                return element
            for keyword in keywords:
                if keyword and keyword in label:
                    return element
        return None

    def _find_exact(self, elements, labels, clickable_only=False):
        """The first element whose label IS one of `labels`, or starts with it.

        The app publishes its labels with the widget's role attached — the
        guest bypass reads "Skip login. Button", not "Skip login" — so a
        plain equality match misses the very control we are after. The
        platform's own search prefers an exact match and falls back to the
        label's start; this does the same, and an exact match still wins.

        `clickable_only` keeps a title that merely starts with the same word
        ("Allow <app> to send you notifications?") from being taken for the
        button.
        """
        wanted = {self._normalize_text(label) for label in labels}
        started = None
        for element in elements:
            label = self._normalize_text(self._label(element))
            if not label:
                continue
            if clickable_only and not element.get("clickable"):
                continue
            if label in wanted:
                return element
            if started is None and any(label.startswith(w) for w in wanted):
                started = element
        return started

    # -- actions ----------------------------------------------------------

    def _tap(self, ctx, element):
        """Open an element: tap its centre, fall back to a click by label."""
        label = self._label(element)
        center = self._bounds_center(element.get("bounds"))
        if center:
            ok, detail, _ = self._command(ctx, "tap_coordinates",
                                          {"x": int(center[0]), "y": int(center[1])})
            if ok:
                return True, f"tapped '{label}' at {center[0]},{center[1]}"
            if label:
                ok, detail, _ = self._command(ctx, "click_element", {"element_id": label})
                if ok:
                    return True, f"clicked '{label}'"
                return False, detail or f"could not open '{label}'"
            return False, detail or "the element has no coordinates and no label"
        if label:
            ok, detail, _ = self._command(ctx, "click_element", {"element_id": label})
            if ok:
                return True, f"clicked '{label}'"
            return False, detail or f"could not open '{label}'"
        return False, "the element has no text and no coordinates"

    def _tap_label(self, ctx, label):
        ok, detail, _ = self._command(ctx, "click_element", {"element_id": label})
        return ok, detail or (f"clicked '{label}'" if ok else f"could not click '{label}'")

    def _go_back(self, ctx):
        """One BACK press. The list is one level below the player."""
        ok, detail = press_key(ctx, "BACK", settle=self._settle_s(ctx))
        if ok:
            return True, "back"
        # The controller may refuse the key even when the device would accept
        # it; the command form is the fallback.
        ok, detail = self._command(ctx, "press_key", {"key": "BACK"})
        if ok:
            sleep(ctx, self._settle_s(ctx))
            return True, "back"
        return False, detail or "the BACK key was refused"

    # -- playback probe ---------------------------------------------------

    def _sign_in_prompt(self, ctx) -> str:
        """The app's own sign-in prompt, when the screen carries one.

        The app answers a session that covers the catalogue with its sign-in
        prompt on the screens that play content ("Please sign in with your
        account to play this content."). When that is there, the content does
        not play because the app refuses to play it for this session — a
        session problem, never a defect of the product.

        Returns the phrase that was found, or "".
        """
        ok, elements, _detail = self._dump(ctx)
        if not ok:
            return ""
        text = " ".join(self._normalize_text(self._label(e)) for e in elements)
        for phrase in SIGN_IN_PHRASES:
            if phrase in text:
                return phrase
        return ""

    def _probe(self, ctx):
        """(has_verdict, playing, detail) from the screen-motion probe.

        `has_verdict` is False when the probe could not run at all (no capture
        on this phone, or the detector raised). That is a platform problem and
        must never be reported as "the content did not play".
        """
        probe = motion_probe(ctx)
        playing = bool(probe.get("playing"))
        change = probe.get("change")
        detail = str(probe.get("detail") or "")
        if playing:
            return True, True, detail
        if change is not None:
            return True, False, detail
        low = detail.lower()
        if "no result" in low or "no verdict" in low or "raised" in low:
            return False, False, detail
        return True, False, detail

    # ------------------------------------------------------------------
    # attribution
    # ------------------------------------------------------------------

    # Markers that say the PLATFORM could not do the job, not that the app
    # behaved wrongly.
    _INFRA_MARKERS = (
        "no navigation executor", "navigation tree load failed", "timed out",
        "timeout", "not connected", "offline", "adb", "device not found",
        "unreachable", "lease", "connection refused", "ssh", "host is down",
        "no screenshot", "no capture",
    )

    @classmethod
    def _classify_nav_failure(cls, detail):
        """CAUSE_INFRA when the platform failed, CAUSE_COVERAGE otherwise.

        A navigation failure that is not a platform problem means the surface
        is not reachable in this UI — a coverage gap, not a defect.
        """
        low = (detail or "").lower()
        for marker in cls._INFRA_MARKERS:
            if marker in low:
                return CAUSE_INFRA
        return CAUSE_COVERAGE

    def _guard(self, ctx):
        """The outcome every case returns when the platform itself is down."""
        if self._infra_reason:
            return CaseOutcome.skipped(f"infra: {self._infra_reason}", cause=CAUSE_INFRA)
        return None

    def _surface_failure(self, ctx, case_label, node_label, detail):
        """The outcome for a surface that could not be opened.

        A platform problem (the phone is gone, the tree does not load) is
        infra. A node that IS in the tree and still could not be opened is a
        product failure: the surface is there and it did not work. A node
        that is absent from the tree is a coverage gap: this UI has no such
        surface.
        """
        if self._classify_nav_failure(detail) == CAUSE_INFRA:
            return CaseOutcome.skipped(
                f"infra: the platform could not reach the {case_label} surface "
                f"(navigation to '{node_label}' failed: {detail})", cause=CAUSE_INFRA)
        return surface_failure(
            ctx, node_label, detail,
            reason=f"the {case_label} surface could not be reached in the mobile app "
                   f"(navigation to '{node_label}' failed: {detail})")

    # ------------------------------------------------------------------
    # prepare
    # ------------------------------------------------------------------

    def _status_detail(self, ctx):
        """None when the phone answers, else why it does not."""
        remote = self._remote(ctx)
        getter = getattr(remote, "get_status", None)
        if not callable(getter):
            return None
        try:
            status = getter()
        except Exception as exc:                                   # noqa: BLE001
            return f"the status check raised: {exc}"
        if isinstance(status, dict):
            if status.get("success"):
                return None
            return status.get("error") or "the device is not in the ADB device list"
        return None

    def _app_package(self, ctx):
        """The package of the TV app, or None when it cannot be identified.

        The package is never written in this repository: pass `--app_package`, or
        set `VPT_TV_APP_HINT` to a keyword of the app name shown on the phone.
        When neither is given, the TREE itself answers: the entry edge of a
        mobile tree carries the `launch_app` action of the app it drives, and
        that is the platform's own answer, read at run time.
        """
        package = ctx.arg("app_package")
        if package:
            return package
        hint = str(ctx.arg("app_name_hint", "")
                   or os.environ.get("VPT_TV_APP_HINT", "") or "").lower()
        if hint:
            ok, _detail, payload = self._command(ctx, "get_installed_apps", {})
            if ok:
                for app in payload.get("apps") or []:
                    if not isinstance(app, dict):
                        continue
                    name = str(app.get("app_name") or "").lower()
                    pkg = str(app.get("package_name") or "").lower()
                    if hint in name or hint in pkg:
                        return app.get("package_name")
        return self._app_package_from_tree(ctx)

    def _app_package_from_tree(self, ctx):
        """The app package, read from the tree's own launch action.

        The graph of a mobile UI carries the app it drives: the default retry
        actions of its edges are `close_app` and `launch_app`, and the launch
        action names the package. Reading it here keeps the app identity in
        the platform's data instead of in this file.
        """
        executor = getattr(ctx.device, "navigation_executor", None)
        if executor is None:
            return None
        try:
            if not tree_id_for(ctx):
                return None
        except Exception as exc:                                   # noqa: BLE001
            ctx.log(f"the tree could not be loaded to find the app: {exc}")
            return None
        graph = getattr(executor, "unified_graph", None)
        if graph is None:
            return None
        try:
            edges = list(graph.edges(data=True))
        except Exception:                                          # noqa: BLE001
            return None
        for _source, _target, data in edges:
            for action_set in (data.get("action_sets") or []):
                actions = list(action_set.get("actions") or [])
                actions += list(action_set.get("retry_actions") or [])
                for action in actions:
                    if not isinstance(action, dict):
                        continue
                    if str(action.get("command") or "") not in ("launch_app", "open_app"):
                        continue
                    package = str((action.get("params") or {}).get("package") or "")
                    if package:
                        return package
        return None

    def _app_on_screen(self, ctx):
        """True when the screen already shows the app's own surface.

        The app publishes its labels with the widget's role attached ("TV
        Guide. Button"), so a surface is recognised by the label's start,
        the way the platform's own search recognises it.
        """
        ok, elements, _detail = self._dump(ctx)
        if not ok:
            return False
        wanted = {self._normalize_text(label) for label in _APP_SURFACE_LABELS}
        for element in elements:
            label = self._normalize_text(self._label(element))
            if not label:
                continue
            if label in wanted:
                return True
            if any(label.startswith(surface) for surface in wanted):
                return True
        return False

    def _dismiss_permission_dialog(self, ctx):
        """Answer Android's own permission dialog, if it is on the screen.

        The dialog belongs to the system, not to the app, and it sits on top
        of the app's first screen. Until it is answered nothing of the app
        is reachable, and the tree's first check cannot see the app's
        surface at all. The answer is a system choice, never a credential.

        Returns (answered, detail).
        """
        ok, elements, detail = self._dump(ctx)
        if not ok:
            return False, detail or "the screen could not be read"
        text = " ".join(self._normalize_text(self._label(e)) for e in elements)
        if not any(marker in text for marker in _PERMISSION_DIALOG_MARKERS):
            return False, "no permission dialog on the screen"
        # "Don't allow" first: the suite asks no notification of the app.
        for labels, clickable_only in ((_PERMISSION_DENY_LABELS, False),
                                       (_PERMISSION_ALLOW_LABELS, True)):
            button = self._find_exact(elements, labels, clickable_only=clickable_only)
            if button is not None:
                answered, detail = self._tap(ctx, button)
                if answered:
                    return True, f"answered the permission dialog ({detail})"
                return False, detail
        return False, "the permission dialog has no button to answer"

    def _skip_login(self, ctx):
        """Use the app's own guest bypass when the login screen is up.

        The app offers a way in without an account ("Skip login"). The suite
        uses it: the content surfaces are reachable as a guest, and a
        credential never belongs in a test script.

        Returns (used, detail).
        """
        ok, elements, detail = self._dump(ctx)
        if not ok:
            return False, detail or "the screen could not be read"
        bypass = self._find_exact(elements, _SKIP_LOGIN_LABELS)
        if bypass is None:
            return False, "the app does not ask for a login"
        used, detail = self._tap(ctx, bypass)
        if used:
            self._guest_session = True
        return used, detail

    def prepare(self, ctx):
        """Bring the app to the foreground, if it can be brought.

        Returns cleanly in every case: each case reports the problem itself,
        so a phone without the app is an infra skip and not a crash.
        """
        self._infra_reason = ""
        self._app_ready = False

        remote = self._remote(ctx)
        if remote is None:
            self._infra_reason = ("the phone has no remote controller "
                                  "(no ADB remote attached to this device)")
            return

        status_detail = self._status_detail(ctx)
        if status_detail:
            self._infra_reason = f"the phone is not reachable over ADB ({status_detail})"
            return

        package = self._app_package(ctx)
        if not package:
            if self._app_on_screen(ctx):
                # The app is running but its package name is not in the
                # installed-app list we can see: carry on, the app is up.
                self._app_ready = True
                return
            self._infra_reason = ("the TV app could not be identified on this phone "
                                  "(no app name hint was given and the tree carries "
                                  "no launch action for it)")
            return

        ok, detail, _payload = self._command(ctx, "launch_app", {"package": package})
        if not ok:
            self._infra_reason = self._launch_failure(ctx, package, detail)
            return
        sleep(ctx, self._settle_s(ctx))
        # The app needs a moment to draw its own surface. The tree's route
        # verifies the screen it lands on with no timeout of its own, so the
        # app has to be UP before the tree drives it — otherwise the
        # verification reads the launcher that was still on the screen.
        if not self._wait_for_app(ctx):
            ctx.log("the TV app did not come to the foreground in time")
        self._app_ready = True

    def _wait_for_app(self, ctx) -> bool:
        """Wait until the app's own surface is on the screen.

        The app is up when one of its own surfaces is readable (the TV Guide,
        the recordings, the catalogue). Returns False when it did not come up
        in time — the case then says so instead of blaming the product.

        Two things stand between the launch and that surface, and both are
        answered on the way: Android's own permission dialog and the app's
        login screen. They are asked again on every poll, because the app
        may put the login screen up after the first answer.
        """
        limit = max(1.0, self._number(ctx, "app_ready_wait_s", 20))
        poll = max(0.5, self._number(ctx, "app_ready_poll_s", 2.0))
        waited = 0.0
        while waited < limit:
            # The dialog and the login screen are answered BEFORE the app is
            # judged ready: while either of them is up, the app's own surface
            # is not on the screen yet.
            answered, detail = self._dismiss_permission_dialog(ctx)
            if answered:
                ctx.log(detail)
            used, detail = self._skip_login(ctx)
            if used:
                ctx.log(f"the app's own bypass was used ({detail})")
            if self._app_on_screen(ctx):
                ctx.log(f"the TV app is on the screen after {waited:.0f}s")
                return True
            sleep(ctx, poll)
            waited += poll
        return False

    def _launch_failure(self, ctx, package, detail) -> str:
        """Why the app could not be started, said as precisely as we can.

        The platform's launch error is often empty, so the installed-app list
        is asked: a package that is not installed is a lab fact (the phone has
        no TV app), a package that IS installed is a platform fact (the launch
        was refused). Neither is a product defect.
        """
        installed = self._is_installed(ctx, package)
        if installed is False:
            if not self._phone_answers(ctx):
                # the list came back empty because the phone itself did not
                # answer: that is a lab fact about the phone, not about the app
                return ("the phone did not answer (the app list came back empty "
                        "and the screen could not be read)")
            return ("the TV app is not installed on this phone (the package the "
                    "tree drives is not in the installed-app list)")
        if installed is True:
            return (f"the TV app is installed but could not be launched "
                    f"({detail or 'the controller gave no reason'})")
        if not self._phone_answers(ctx):
            # The phone answered neither the app list nor the screen: it is
            # not reachable at all (a cable that is down, a debugging prompt
            # nobody accepted). That is a fact about the phone, and saying it
            # as such keeps the app out of it.
            return ("the phone did not answer (the app list came back without "
                    "an app list and the screen could not be read)")
        return f"the TV app could not be launched ({detail or 'unknown error'})"

    def _phone_answers(self, ctx) -> bool:
        """True when the phone still reads its screen."""
        ok, _elements, _detail = self._dump(ctx)
        return ok

    def _is_installed(self, ctx, package):
        """True / False when the phone answered, None when it did not.

        The controller answers `get_installed_apps` with `success: False` when
        the list is EMPTY — an answer, not a failure. Only a payload without
        an `apps` list at all means the phone did not answer.
        """
        _ok, _detail, payload = self._command(ctx, "get_installed_apps", {})
        apps = payload.get("apps") if isinstance(payload, dict) else None
        if not isinstance(apps, list):
            return None
        wanted = str(package or "").lower()
        for app in apps:
            if not isinstance(app, dict):
                continue
            if str(app.get("package_name") or "").lower() == wanted:
                return True
        return False

    # ------------------------------------------------------------------
    # the runtime catalogue walk
    # ------------------------------------------------------------------

    def _walk_and_play(self, ctx, node_label, case_label):
        """Open a list surface, walk it at runtime, play one item.

        PASS as soon as one item really plays. FAIL (product) when items were
        reachable but none of them started. A surface that is not in the tree
        is a SKIP (coverage); a surface that IS in the tree and could not be
        opened is a FAIL (product).
        """
        ok, detail = navigate_to(ctx, node_label)
        if not ok:
            return self._surface_failure(ctx, case_label, node_label, detail)

        play_seconds = self._play_seconds(ctx)
        max_items = self._max_items(ctx)
        tried = set()
        attempts = []

        for _ in range(max_items):
            dumped, elements, dump_detail = self._dump(ctx)
            if not dumped:
                return CaseOutcome.skipped(
                    f"infra: the phone screen could not be read on the {case_label} list "
                    f"({dump_detail})", cause=CAUSE_INFRA)

            candidates = [e for e in self._candidates(elements, self._screen_size(ctx))
                          if self._key(e) not in tried]
            if not candidates:
                # The list is empty, or we are no longer on it: put the app
                # back on the list and look once more before giving up.
                recovered = self._recover_list(ctx, node_label)
                if not recovered:
                    break
                dumped, elements, dump_detail = self._dump(ctx)
                if not dumped:
                    return CaseOutcome.skipped(
                        f"infra: the phone screen could not be read on the {case_label} list "
                        f"({dump_detail})", cause=CAUSE_INFRA)
                candidates = [e for e in self._candidates(elements, self._screen_size(ctx))
                              if self._key(e) not in tried]
                if not candidates:
                    break

            element = candidates[0]
            tried.add(self._key(element))
            label = self._label(element)
            opened, open_detail = self._tap(ctx, element)
            if not opened:
                attempts.append({"item": label, "opened": False, "detail": open_detail})
                self._go_back(ctx)
                continue

            sleep(ctx, play_seconds)
            has_verdict, playing, probe_detail = self._probe(ctx)
            if playing:
                capture(ctx, f"{ctx.case}-{case_label}-playing")
                attempts.append({"item": label, "opened": True, "motion": True,
                                 "detail": probe_detail})
                return CaseOutcome.passed(
                    f"{case_label} played: '{label}' started playback ({probe_detail})",
                    evidence={"node": node_label, "item": label, "attempts": attempts})

            if not has_verdict:
                # The probe cannot measure this phone: the platform problem,
                # never the product.
                attempts.append({"item": label, "opened": True, "motion": None,
                                 "detail": probe_detail})
                return CaseOutcome.skipped(
                    f"infra: the screen-motion probe could not run on this phone, so no "
                    f"playback verdict was possible ({probe_detail})", cause=CAUSE_INFRA)

            # The item opened but nothing played: it may be a detail page with
            # a play control.
            played, play_detail = self._try_play_control(ctx, play_seconds)
            if played:
                attempts.append({"item": label, "opened": True, "motion": True,
                                 "detail": play_detail})
                capture(ctx, f"{ctx.case}-{case_label}-playing")
                return CaseOutcome.passed(
                    f"{case_label} played: '{label}' started playback ({play_detail})",
                    evidence={"node": node_label, "item": label, "attempts": attempts})

            attempts.append({"item": label, "opened": True, "motion": False,
                             "detail": probe_detail})
            # The app may say why it plays nothing: "Please sign in with your
            # account to play this content." That is the session, and no
            # other item will play either.
            prompt = self._sign_in_prompt(ctx)
            if prompt:
                attempts[-1]["sign_in_prompt"] = prompt
                break
            self._go_back(ctx)

        if not attempts:
            return CaseOutcome.skipped(
                f"coverage gap: the {case_label} list on '{node_label}' exposes no item "
                f"the adapter could open", cause=CAUSE_COVERAGE,
                evidence={"node": node_label})

        if not any(attempt.get("opened") for attempt in attempts):
            # Not one item could even be opened: the platform refused the
            # action, so the product was never exercised.
            return CaseOutcome.skipped(
                f"infra: the phone could not open any of the {len(attempts)} {case_label} "
                f"item(s) on '{node_label}' (last detail: "
                f"{attempts[-1].get('detail') or 'no detail'})", cause=CAUSE_INFRA,
                evidence={"node": node_label, "attempts": attempts})

        prompt = next((a.get("sign_in_prompt") for a in attempts
                       if a.get("sign_in_prompt")), "")
        if prompt:
            # The app itself says why: it wants an account to play this.
            return CaseOutcome.failed(
                f"infra: {len(attempts)} {case_label} item(s) on '{node_label}' were "
                f"reachable but none of them started playback — the app asks for a "
                f"sign-in to play this content ({prompt}): the session of this run "
                f"covers the catalogue, not the playback",
                cause=CAUSE_INFRA,
                evidence={"node": node_label, "attempts": attempts,
                          "session": "guest", "sign_in_prompt": prompt})

        if self._guest_session:
            # The suite itself used the app's guest bypass, so the session
            # plays nothing: the app offers the playback to a signed-in user
            # only. That is the session, never a defect of the product.
            return CaseOutcome.failed(
                f"infra: {len(attempts)} {case_label} item(s) on '{node_label}' were "
                f"reachable but none of them started playback (last probe: "
                f"{attempts[-1].get('detail') or 'no verdict'}) — the session of this run "
                f"is a guest session (the app's own bypass was used), and the app offers "
                f"the playback to a signed-in user only",
                cause=CAUSE_INFRA, evidence={"node": node_label, "attempts": attempts,
                                             "session": "guest"})

        return CaseOutcome.failed(
            f"product: {len(attempts)} {case_label} item(s) on '{node_label}' were reachable "
            f"but none of them started playback "
            f"(last probe: {attempts[-1].get('detail') or 'no verdict'})",
            cause=CAUSE_PRODUCT, evidence={"node": node_label, "attempts": attempts})

    def _recover_list(self, ctx, node_label):
        """Put the app back on the list surface. True when it worked."""
        ok, _detail = navigate_to(ctx, node_label)
        if not ok:
            return False
        sleep(ctx, self._settle_s(ctx))
        return True

    def _try_play_control(self, ctx, play_seconds):
        """Look for a play control on the current screen and use it.

        Returns (played, detail).
        """
        dumped, elements, dump_detail = self._dump(ctx)
        if not dumped:
            return False, f"the screen could not be read ({dump_detail})"
        control = self._find_by_keywords(elements, _PLAY_KEYWORDS, exact=_PLAY_EXACT)
        if control is None:
            return False, "the screen shows no play control"
        label = self._label(control)
        opened, open_detail = self._tap(ctx, control)
        if not opened:
            return False, f"the play control '{label}' could not be used ({open_detail})"
        sleep(ctx, play_seconds)
        has_verdict, playing, probe_detail = self._probe(ctx)
        if playing:
            return True, f"the play control '{label}' started playback ({probe_detail})"
        if not has_verdict:
            return False, f"the screen-motion probe could not run ({probe_detail})"
        return False, f"the play control '{label}' did not start playback ({probe_detail})"

    # ------------------------------------------------------------------
    # the four cases
    # ------------------------------------------------------------------

    def run_replay(self, ctx):
        """Open the replay catalogue, start one programme, confirm playback."""
        guard = self._guard(ctx)
        if guard is not None:
            return guard
        try:
            return self._walk_and_play(ctx, "home_replay", "replay")
        except Exception as exc:                                   # noqa: BLE001
            cause = exception_cause(exc)
            ctx.log(f"the replay case raised while walking the catalogue: {exc}")
            return CaseOutcome.failed(
                f"{cause}: the replay case raised while walking the catalogue: "
                f"{type(exc).__name__}", cause=cause)

    def run_vod(self, ctx):
        """Open the movies & series catalogue, start one title, confirm playback."""
        guard = self._guard(ctx)
        if guard is not None:
            return guard
        try:
            return self._walk_and_play(ctx, "home_movies", "VOD")
        except Exception as exc:                                   # noqa: BLE001
            cause = exception_cause(exc)
            ctx.log(f"the VOD case raised while walking the catalogue: {exc}")
            return CaseOutcome.failed(
                f"{cause}: the VOD case raised while walking the catalogue: "
                f"{type(exc).__name__}", cause=cause)

    def run_radio(self, ctx):
        """DISCOVERY: find a radio surface, then play it.

        The mobile navigation tree has no radio node, so radio is looked for at
        runtime on the screens that can carry one (the home screen, the TV
        guide, the live surface). No radio source in this UI is a COVERAGE gap
        — a skip, never a product defect.
        """
        guard = self._guard(ctx)
        if guard is not None:
            return guard
        try:
            return self._run_radio_discovery(ctx)
        except Exception as exc:                                   # noqa: BLE001
            cause = exception_cause(exc)
            ctx.log(f"the radio case raised during the discovery: {exc}")
            return CaseOutcome.failed(
                f"{cause}: the radio case raised during the discovery: "
                f"{type(exc).__name__}", cause=cause)

    def _run_radio_discovery(self, ctx):
        nodes = [n.strip() for n in
                 str(ctx.arg("radio_probe_nodes", "home,home_tvguide,tvguide_livetv,live") or "").split(",")
                 if n.strip()]
        keywords = self._keywords(ctx, "radio_keywords", ("radio",))
        play_seconds = self._play_seconds(ctx)
        looked = []
        failure = None

        for node in nodes:
            ok, detail = navigate_to(ctx, node)
            if not ok:
                looked.append(f"{node} (unreachable: {detail})")
                # The node is either absent from the tree (this UI has no such
                # screen) or present and broken. Only the second one is a
                # product defect.
                outcome = self._surface_failure(ctx, f"'{node}'", node, detail)
                if outcome.cause == CAUSE_PRODUCT and failure is None:
                    failure = outcome
                continue
            dumped, elements, dump_detail = self._dump(ctx)
            if not dumped:
                looked.append(f"{node} (screen unreadable: {dump_detail})")
                continue
            match = self._find_by_keywords(elements, keywords)
            if match is None:
                looked.append(f"{node} (no radio entry)")
                continue

            label = self._label(match)
            opened, open_detail = self._tap(ctx, match)
            if not opened:
                return CaseOutcome.skipped(
                    f"infra: the radio entry '{label}' on '{node}' was found but the phone "
                    f"could not act on it ({open_detail})", cause=CAUSE_INFRA)

            sleep(ctx, play_seconds)
            has_verdict, playing, probe_detail = self._probe(ctx)
            if playing:
                capture(ctx, f"{ctx.case}-radio-playing")
                return CaseOutcome.passed(
                    f"radio played: '{label}' started playback ({probe_detail})",
                    evidence={"node": node, "item": label, "looked": looked})
            if not has_verdict:
                return CaseOutcome.skipped(
                    f"infra: the screen-motion probe could not run on this phone, so no "
                    f"playback verdict was possible ({probe_detail})", cause=CAUSE_INFRA)

            played, play_detail = self._try_play_control(ctx, play_seconds)
            if played:
                capture(ctx, f"{ctx.case}-radio-playing")
                return CaseOutcome.passed(
                    f"radio played: '{label}' started playback ({play_detail})",
                    evidence={"node": node, "item": label, "looked": looked})

            # The picture did not move. On a radio station that is NOT a
            # verdict: the station is a static logo with sound, and this phone
            # carries no audio analysis to read. The case cannot conclude, so
            # it never blames the product for it.
            return CaseOutcome.skipped(
                f"infra: the radio entry '{label}' on '{node}' was opened but the screen did "
                f"not move; a radio station is a static picture and this phone carries no "
                f"audio analysis, so the playback cannot be concluded ({probe_detail})",
                cause=CAUSE_INFRA, evidence={"node": node, "item": label, "looked": looked})

        if failure is not None:
            failure.evidence = {"looked": looked}
            return failure
        return CaseOutcome.skipped(
            f"coverage gap: no radio surface exists in the mobile app "
            f"(looked on: {', '.join(looked) if looked else 'no node'})",
            cause=CAUSE_COVERAGE, evidence={"looked": looked})

    def run_recording(self, ctx):
        """Record a live programme, check it is listed, then play it back.

        Three steps in one case. The reason names the step that broke.
        """
        guard = self._guard(ctx)
        if guard is not None:
            return guard
        try:
            return self._run_recording(ctx)
        except Exception as exc:                                   # noqa: BLE001
            cause = exception_cause(exc)
            ctx.log(f"the recording case raised: {exc}")
            return CaseOutcome.failed(
                f"{cause}: the recording case raised {type(exc).__name__}", cause=cause)

    def _run_recording(self, ctx):
        # -- step 0: what the saved list looks like BEFORE the recording ---
        ok, detail = navigate_to(ctx, "home_saved")
        if not ok:
            return self._surface_failure(ctx, "saved list", "home_saved", detail)
        dumped, elements, dump_detail = self._dump(ctx)
        if not dumped:
            return CaseOutcome.skipped(
                f"infra: the phone screen could not be read on the saved list "
                f"({dump_detail})", cause=CAUSE_INFRA)
        baseline = {self._normalize_text(self._label(e))
                    for e in self._candidates(elements, self._screen_size(ctx))}

        # -- step 1: start a live programme and trigger the record action ---
        started, reason, record_info = self._trigger_record(ctx)
        if not started:
            cause = record_info.get("cause")
            if cause == CAUSE_PRODUCT:
                return CaseOutcome.failed(reason, cause=CAUSE_PRODUCT)
            if cause == CAUSE_COVERAGE:
                return CaseOutcome.skipped(reason, cause=CAUSE_COVERAGE)
            return CaseOutcome.skipped(reason, cause=CAUSE_INFRA)

        # -- step 2: the recording must show up in the saved list ----------
        # Back to the saved list first: after step 1 the app is on the live
        # surface, and the listing has to be read where the recordings live.
        ok, detail = navigate_to(ctx, "home_saved")
        if not ok:
            return self._surface_failure(ctx, "saved list", "home_saved", detail)
        wait_s = self._record_wait_s(ctx)
        listed, entry_label, listing_detail = self._await_listing(ctx, baseline, record_info)
        if not listed:
            return CaseOutcome.failed(
                f"product: step 2 (listing) failed: the recording started from "
                f"'{record_info.get('control')}' never appeared in 'home_saved' within "
                f"{int(wait_s)}s", cause=CAUSE_PRODUCT,
                evidence={"baseline": sorted(baseline), "detail": listing_detail})

        # -- step 3: the recording must PLAY BACK --------------------------
        played, play_detail = self._play_recording(ctx, entry_label)
        if played:
            capture(ctx, f"{ctx.case}-recording-playing")
            return CaseOutcome.passed(
                f"recording passed: '{entry_label}' is listed in 'home_saved' and plays back "
                f"({play_detail})",
                evidence={"recording": entry_label, "listed_in": "home_saved"})
        if play_detail.startswith("infra:"):
            return CaseOutcome.skipped(play_detail, cause=CAUSE_INFRA)
        return CaseOutcome.failed(
            f"product: step 3 (playback) failed: the recording '{entry_label}' is listed in "
            f"'home_saved' but does not play back ({play_detail})",
            cause=CAUSE_PRODUCT, evidence={"recording": entry_label})

    def _trigger_record(self, ctx):
        """Open a live surface and press the record control.

        Returns (started, reason, info). `info['cause']` says who is to blame
        when it did not start: coverage when the app has no record control at
        all, infra when the platform could not press it, product when a node
        that IS in the tree could not be opened.
        """
        nodes = [n.strip() for n in
                 str(ctx.arg("record_nodes", "live,home_tvguide,tvguide_livetv") or "").split(",")
                 if n.strip()]
        keywords = self._keywords(ctx, "record_keywords", _RECORD_KEYWORDS)
        settle = self._settle_s(ctx)
        failure = None

        for node in nodes:
            ok, detail = navigate_to(ctx, node)
            if not ok:
                # The node is either absent from the tree (this UI has no such
                # screen) or present and broken. Only the second one is a
                # product defect.
                outcome = self._surface_failure(ctx, f"'{node}'", node, detail)
                if outcome.cause == CAUSE_PRODUCT and failure is None:
                    failure = outcome
                continue
            dumped, elements, dump_detail = self._dump(ctx)
            if not dumped:
                continue
            control = self._find_by_keywords(elements, keywords, exact=_RECORD_EXACT)
            if control is None:
                continue
            label = self._label(control)
            titles = self._surface_titles(elements)
            opened, open_detail = self._tap(ctx, control)
            if not opened:
                return False, (f"infra: the record control '{label}' on '{node}' was found but "
                               f"the phone could not act on it ({open_detail})"), {"cause": CAUSE_INFRA}
            sleep(ctx, settle)
            return True, "", {"node": node, "control": label, "titles": titles}

        if failure is not None:
            return False, failure.reason, {"cause": CAUSE_PRODUCT}
        return False, ("coverage gap: the mobile app shows no record control on any of "
                       f"{', '.join(nodes)}"), {"cause": CAUSE_COVERAGE}

    @staticmethod
    def _surface_titles(elements):
        """The plausible programme titles of the current screen."""
        titles = []
        for element in elements:
            label = MobileAdapter._normalize_text(element.get("text"))
            if len(label) >= 4 and label not in _CHROME_LABELS:
                titles.append(label)
        # The longest first: a full title matches before a fragment of it.
        titles.sort(key=len, reverse=True)
        return titles

    def _await_listing(self, ctx, baseline, record_info):
        """Wait for the recording to be listed in the saved list.

        Returns (listed, entry_label, detail).
        """
        wait_s = self._record_wait_s(ctx)
        poll_s = self._poll_s(ctx)
        deadline = time.time() + wait_s
        titles = record_info.get("titles") or []
        last_entries = []
        last_refresh = time.time()

        while True:
            dumped, elements, dump_detail = self._dump(ctx)
            if dumped:
                candidates = self._candidates(elements, self._screen_size(ctx))
                entries = []
                for element in candidates:
                    raw = self._label(element)
                    label = self._normalize_text(raw)
                    if label and label not in [e["norm"] for e in entries]:
                        entries.append({"norm": label, "raw": raw})
                last_entries = [e["raw"] for e in entries]

                # The recorded programme's own title is the strongest match.
                match = self._match_title(entries, titles)
                if match:
                    return True, match, f"the recording '{match}' is listed"

                # Otherwise: an entry that was not in the list before.
                fresh = [e["raw"] for e in entries if e["norm"] not in baseline]
                if fresh:
                    return True, fresh[0], f"a new entry '{fresh[0]}' is listed"
            else:
                last_entries = [f"<the screen could not be read: {dump_detail}>"]

            if time.time() >= deadline:
                return False, None, (f"the saved list still shows {last_entries} after "
                                     f"{int(wait_s)}s")

            # Refresh the list now and then: the saved list is loaded when the
            # screen is entered, so a plain re-read would never see a
            # recording that arrived later.
            if time.time() - last_refresh >= max(poll_s * 3, 10.0):
                last_refresh = time.time()
                self._recover_list(ctx, "home")
                self._recover_list(ctx, "home_saved")
            sleep(ctx, poll_s)

    @staticmethod
    def _match_title(entries, titles):
        """The raw label of the entry that carries one of the recorded titles."""
        for title in titles:
            if len(title) < 4:
                continue
            for entry in entries:
                label = entry["norm"]
                if title in label or (len(label) >= 8 and label in title):
                    return entry["raw"]
        return None

    def _play_recording(self, ctx, entry_label):
        """Select the listed recording and confirm it plays back.

        Returns (played, detail). A detail that starts with "infra:" means the
        platform could not do it, not the product.
        """
        dumped, elements, dump_detail = self._dump(ctx)
        if not dumped:
            return False, f"infra: the phone screen could not be read on the saved list ({dump_detail})"
        wanted = self._normalize_text(entry_label)
        entry = None
        for element in self._candidates(elements, self._screen_size(ctx)):
            if self._normalize_text(self._label(element)) == wanted:
                entry = element
                break
        if entry is None:
            entry = self._find_by_keywords(elements, [wanted]) if wanted else None
        if entry is None:
            return False, f"the listed recording '{entry_label}' could not be found again"

        opened, open_detail = self._tap(ctx, entry)
        if not opened:
            return False, f"infra: the listed recording '{entry_label}' could not be opened ({open_detail})"

        sleep(ctx, self._play_seconds(ctx))
        has_verdict, playing, probe_detail = self._probe(ctx)
        if playing:
            return True, probe_detail
        if not has_verdict:
            return False, f"infra: the screen-motion probe could not run on this phone ({probe_detail})"

        played, play_detail = self._try_play_control(ctx, self._play_seconds(ctx))
        if played:
            return True, play_detail
        if play_detail.startswith("the screen-motion probe could not run"):
            return False, f"infra: {play_detail}"
        return False, f"the recording did not start playing ({probe_detail})"
