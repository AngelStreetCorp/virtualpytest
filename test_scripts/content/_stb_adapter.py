#!/usr/bin/env python3
"""
STB-remote platform adapter for the content-surface test suite.

The adapter owns the STB mechanics: the remote keys, the navigation
tree labels and the motion probe that tells "the stream really plays" from
"the box is showing a still frame".

It never prints a result line and never builds a summary:
`test_scripts/content/_harness.run_suite` does that. Every case method
returns a `CaseOutcome` and swallows its own product-facing errors, because
an exception that escapes to the runner is classified `infra` by the harness
and would misattribute a product defect. A CAUGHT exception is attributed by
`exception_cause`: a programming error in this file (a NameError, a changed
API) is `infra`, anything else is `product`.

A surface that is in the tree and still cannot be opened is a PRODUCT
failure, not a coverage gap. `surface_failure` tells the two apart: a node
that is absent from the tree is a coverage gap (this UI has no such
surface), a node that is in the tree and failed to open is a defect.

Platform facts this adapter is built on (stb_tv tree, read live on
2026-10-23):

  * the radio app is IR-only: `apps_radio` is the app tile under `apps`,
    `radio_home` is the app's own home page;
  * `replay` is the catch-up list, `movies` the VOD catalogue, `recordings`
    the recordings list, `live` the live channel;
  * the tree models NO per-item node for a station / programme / title, so
    the catalogue has to be walked at runtime with the remote keys
    (TASK-80, branch task80-stb-content-scripts, commit a6e14152c);
  * the keys the remote controllers accept are the keymap names -- `OK`,
    `BACK`, `DOWN`, `UP`, `HOME`, `RECORD` -- and NOT `KEY_OK` & friends:
    backend_host/src/controllers/remote/infrared.py refuses any name that is
    not in ir_conf/<type>.json (stb.json) and bluetooth.py does the same with
    its ble_conf profile (the vendor keymap file). The TASK-80 scripts used `KEY_OK` /
    `KEY_BACK` / `KEY_DOWN`, which those controllers reject.

Playback is confirmed with the motion probe (the STB has no media element to
inspect): two frames of the screen are compared and a frame change above the
threshold counts as "playing". On a surface that is still while it plays
(radio album art) the probe can only report what the screen does, so the
reason strings say so instead of claiming more than was measured. The radio
case therefore asks the audio probe as well: a radio station is a static
logo with sound, so only the audio reading can say whether it played.
"""

import os
import re
import sys
import time

# Add project root to path so the helper imports work from anywhere.
# The virtual-script converter rewrites this block (it only ever reads
# `project_root`, never `current_dir`), so keep the canonical shape.
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from test_scripts.content._harness import (  # noqa: E402
    Adapter,
    CaseContext,
    CaseOutcome,
    CAUSE_COVERAGE,
    CAUSE_INFRA,
    CAUSE_PRODUCT,
    audio_probe,
    capture,
    exception_cause,
    motion_probe,
    navigate_to,
    press_key,
    sleep,
    surface_failure,
)


class StbAdapter(Adapter):
    """The TV set-top box driven with its remote (IR or BLE)."""

    platform = "stb"

    # -- the tree labels (stb_tv, verified live on 2026-10-23) --------------
    DEFAULT_RADIO_NODES = ("apps_radio", "radio_home")
    DEFAULT_REPLAY_NODES = ("replay",)
    # The tree's own path into a catch-up asset: open the asset, play its
    # stream. Used as a second chance when the runtime walk finds nothing.
    DEFAULT_REPLAY_ASSET_NODES = ("replay_asset_stream", "replay_asset")
    DEFAULT_VOD_NODES = ("movies", "home_movies")
    DEFAULT_RECORDINGS_NODES = ("recordings", "home_recodings")
    DEFAULT_LIVE_NODES = ("live",)

    # -- the remote keys (the names the IR / BLE keymaps carry) -------------
    DEFAULT_SELECT_KEY = "OK"
    DEFAULT_BACK_KEY = "BACK"
    DEFAULT_NEXT_KEY = "DOWN"
    DEFAULT_RECORD_KEY = "RECORD"

    def __init__(self):
        self._ocr_ready = None          # None = not probed yet, else bool
        self._pytesseract = None
        self._cv2 = None

    # ------------------------------------------------------------------
    # argument helpers (every wait and timeout is an argument)
    # ------------------------------------------------------------------

    def _nodes(self, ctx: CaseContext, name: str, default):
        """The node labels to try for a surface, as a tuple.

        The default is the verified stb_tv label; `--stb_<x>_nodes` (a comma
        separated list) overrides it for another STB UI.
        """
        raw = ctx.arg(name, "")
        if not raw:
            return tuple(default)
        parts = raw if isinstance(raw, (list, tuple)) else str(raw).split(",")
        names = tuple(str(part).strip() for part in parts if str(part).strip())
        return names or tuple(default)

    def _seconds(self, ctx: CaseContext, name: str, default):
        """An argument read as a number of seconds (never negative)."""
        try:
            return max(0.0, float(ctx.arg(name, default)))
        except (TypeError, ValueError):
            return float(default)

    def _count(self, ctx: CaseContext, name: str, default):
        """An argument read as a whole number (at least one)."""
        try:
            return max(1, int(float(ctx.arg(name, default))))
        except (TypeError, ValueError):
            return int(default)

    def _settle(self, ctx: CaseContext) -> float:
        """The pause after a key press (the suite's `--settle_ms` by default)."""
        default = self._seconds(ctx, "settle_ms", 800) / 1000.0
        return self._seconds(ctx, "stb_key_settle_s", default)

    def _key(self, ctx: CaseContext, name: str, default: str) -> str:
        """The name of a remote key, as the controllers spell it."""
        return str(ctx.arg(name, default) or default)

    # ------------------------------------------------------------------
    # platform mechanics
    # ------------------------------------------------------------------

    def _open_surface(self, ctx: CaseContext, nodes):
        """Navigate to the first reachable node of `nodes`.

        Returns (ok, node, detail). `detail` carries every failure so the
        case can say why the surface was not reached.
        """
        detail = ""
        for node in nodes:
            ok, nav_detail = navigate_to(ctx, node)
            if ok:
                ctx.log(f"on '{node}'")
                return True, node, ""
            detail = f"{node}: {nav_detail}" if not detail else f"{detail}; {node}: {nav_detail}"
            ctx.log(f"could not reach '{node}': {nav_detail}")
        return False, "", detail

    def _surface_failure(self, ctx: CaseContext, nodes, detail: str, reason: str,
                         evidence=None):
        """The outcome for a surface that could not be opened.

        A node that IS in the tree and still could not be opened is a product
        failure: the surface is there and it did not work. A node that is
        absent from the tree is a coverage gap: this UI has no such surface.
        """
        outcome = None
        for node in nodes:
            outcome = surface_failure(ctx, node, detail, reason=reason)
            if outcome.cause == CAUSE_PRODUCT:
                break
        if outcome is None:
            outcome = surface_failure(ctx, "", detail, reason=reason)
        if evidence:
            outcome.evidence = evidence
        return outcome

    def _radio_tile_on_screen(self, ctx: CaseContext, path=None):
        """Is a radio tile on the screen right now?

        The tree's route to the radio app can fail while the radio app sits
        right there on the box: the tree's reference picture for the tile is
        stale, so the focus never lands on it. Reading the screen's own text
        tells the two apart — the surface is present (the tile is visible) or
        it is not.

        The tile carries the same word in the app's German and English
        layouts, so the match does not depend on the profile language.

        The app store draws its tiles in, so a frame can be empty while the
        next one is not: the screen is read more than once before the answer
        is "no". The text of the last frame is returned as well, so the row
        can say what the screen did show.

        Returns (found, matched_line, frame_path). A missing OCR stack is
        reported as "not found": the frame simply proves nothing then.
        """
        frames = []
        gap = self._seconds(ctx, "stb_radio_tile_gap_s", 2.0)
        if path:
            frames.append(path)
        else:
            for attempt in range(3):
                frame = self._capture(ctx, f"radio_tile_{attempt}")
                if frame:
                    frames.append(frame)
                if attempt < 2:
                    sleep(ctx, gap)
        seen = ""
        for frame in frames:
            lines = self._screen_lines(frame, 0.0)
            if not lines:
                continue
            seen = seen or "; ".join(lines[:6])
            for line in lines:
                for word in re.split(r"[^\w]+", line):
                    if word.strip() == "radio":
                        return True, line, frame
        return False, seen, (frames[-1] if frames else None)

    def _probe_audio(self, ctx: CaseContext):
        """Is there sound on the box right now?

        The motion probe cannot say anything about an audio-only surface: a
        radio station is a static logo, so "the picture did not move" says
        nothing about the sound. The audio probe reads the capture monitor's
        own per-frame analysis. It never raises: a probe that cannot run
        returns `audible: None`, which means "no reading", never "silence".
        """
        try:
            audio = audio_probe(ctx)
        except Exception as exc:                                   # noqa: BLE001
            ctx.log(f"the audio probe raised: {exc}")
            return {"audible": None, "level_db": None, "frames": 0,
                    "detail": f"the audio probe raised: {type(exc).__name__}"}
        return audio if isinstance(audio, dict) else {
            "audible": None, "level_db": None, "frames": 0,
            "detail": "the audio probe returned no reading"}

    def _probe_playback(self, ctx: CaseContext, retries: int):
        """Ask the motion probe whether something is playing.

        The probe is retried: the first pair of frames can land on a still
        moment of a stream that is running.
        """
        detail = ""
        gap = self._seconds(ctx, "stb_probe_gap_s", 1.5)
        for attempt in range(max(1, retries)):
            probe = motion_probe(ctx)
            detail = probe.get("detail", "")
            if probe.get("playing"):
                return {"playing": True, "detail": detail}
            if attempt + 1 < max(1, retries):
                sleep(ctx, gap)
        return {"playing": False, "detail": detail}

    def _walk_list(self, ctx: CaseContext, max_items: int):
        """Walk the runtime list and play the first row that really moves.

        The catalogue is not in the tree, so the list is walked with the
        remote: the select key opens the row, the back key returns to the
        list, the next key moves to the next row. Returns a dict that says
        what was tried and why it stopped.

        The audio probe runs on every row whose picture did not move: a row
        that is still may be a radio station (a static logo with sound), so
        the sound decides. The video rows keep the picture as their proof.
        """
        select_key = self._key(ctx, "stb_select_key", self.DEFAULT_SELECT_KEY)
        back_key = self._key(ctx, "stb_back_key", self.DEFAULT_BACK_KEY)
        next_key = self._key(ctx, "stb_next_key", self.DEFAULT_NEXT_KEY)
        settle = self._settle(ctx)
        play_s = self._seconds(ctx, "play_seconds", 12)
        item_settle_s = self._seconds(ctx, "stb_item_settle_s", 3.0)
        list_settle_s = self._seconds(ctx, "stb_list_settle_s", 2.0)
        retries = self._count(ctx, "stb_probe_retries", 2)

        result = {
            "items_tried": 0,
            "played": False,
            "item_index": None,
            "detail": "",
            "probe_detail": "",
            "transport_error": False,
            "audio": {},
            "audio_audible": False,
            "audio_index": None,
        }

        for index in range(max_items):
            result["items_tried"] = index + 1
            ctx.log(f"item {index + 1}/{max_items}: selecting with '{select_key}'")

            ok, detail = press_key(ctx, select_key, settle=settle)
            if not ok:
                result["detail"] = f"the remote refused '{select_key}': {detail}"
                result["transport_error"] = True
                return result

            sleep(ctx, item_settle_s + play_s)
            probe = self._probe_playback(ctx, retries)
            result["probe_detail"] = probe.get("detail", "")
            if probe.get("playing"):
                result["played"] = True
                result["item_index"] = index
                return result

            # The picture did not move. Ask the audio while the item is still
            # displayed: on an audio-only surface (radio) the picture is a
            # static logo and only the sound proves the playback.
            audio = self._probe_audio(ctx)
            if audio.get("audible"):
                # The reading that proves the playback is kept: a later silent
                # row does not take that verdict away.
                result["audio_audible"] = True
                result["audio_index"] = index
                result["audio"] = audio
            elif not result.get("audio_audible"):
                result["audio"] = audio

            # Not playing: back to the list, then the next row.
            back_ok, back_detail = press_key(ctx, back_key, settle=settle)
            if not back_ok:
                result["detail"] = f"the remote refused '{back_key}': {back_detail}"
                result["transport_error"] = True
                return result
            sleep(ctx, list_settle_s)

            if index + 1 < max_items:
                next_ok, next_detail = press_key(ctx, next_key, settle=settle)
                if not next_ok:
                    result["detail"] = f"the remote refused '{next_key}': {next_detail}"
                    result["transport_error"] = True
                    return result
                sleep(ctx, list_settle_s)

        result["detail"] = f"none of the {result['items_tried']} rows showed motion"
        return result

    def _tree_playback(self, ctx: CaseContext, nodes):
        """Play through the tree's own asset path.

        The replay tree knows `replay_asset` -> `replay_asset_stream`: the
        first is the catch-up asset, the second plays its stream. Used as a
        second chance when the runtime walk found nothing.
        """
        play_s = self._seconds(ctx, "play_seconds", 12)
        item_settle_s = self._seconds(ctx, "stb_item_settle_s", 3.0)
        retries = self._count(ctx, "stb_probe_retries", 2)

        for node in nodes:
            ok, detail = navigate_to(ctx, node)
            if not ok:
                ctx.log(f"tree path '{node}' not reachable: {detail}")
                continue
            sleep(ctx, item_settle_s + play_s)
            probe = self._probe_playback(ctx, retries)
            if probe.get("playing"):
                return {"played": True, "node": node, "detail": probe.get("detail", "")}
        return {"played": False, "node": "", "detail": "no tree asset path played"}

    # ------------------------------------------------------------------
    # screen reading (the recordings list has no node per entry)
    # ------------------------------------------------------------------

    def _capture(self, ctx: CaseContext, label: str):
        """Take a screenshot and return its path -- or None.

        Only a NEW frame counts: `capture` hands back the last screenshot of
        the run, and comparing a stale frame with a fresh one would invent a
        difference that never happened.
        """
        before = len(getattr(ctx.context, "screenshot_paths", None) or [])
        path = capture(ctx, label)
        after = getattr(ctx.context, "screenshot_paths", None) or []
        if len(after) <= before:
            return None
        return path

    def _load_image(self, path):
        """Read a captured frame, or None when it cannot be read."""
        if not path:
            return None
        try:
            from shared.src.lib.utils.cv2_io import imread
        except Exception:                                        # noqa: BLE001
            return None
        try:
            return imread(path)
        except Exception:                                        # noqa: BLE001
            return None

    def _ocr_module(self):
        """pytesseract, or None when the OCR stack is not installed."""
        if self._ocr_ready is None:
            try:
                import pytesseract
                self._pytesseract = pytesseract
                self._ocr_ready = True
            except Exception:                                    # noqa: BLE001
                self._ocr_ready = False
        return self._pytesseract if self._ocr_ready else None

    def _cv2_module(self):
        """cv2, or None when OpenCV is not installed."""
        if self._cv2 is None:
            try:
                import cv2
                self._cv2 = cv2
            except Exception:                                    # noqa: BLE001
                self._cv2 = False
        return self._cv2 or None

    def _screen_lines(self, path, top_pct: float):
        """The text lines of the frame, or None when OCR is unavailable.

        Only the lower part of the frame is read (`top_pct` is skipped): the
        tab bar and the rotating hero sit at the top and would add lines
        that have nothing to do with the list.
        """
        pytesseract = self._ocr_module()
        cv2 = self._cv2_module()
        image = self._load_image(path)
        if pytesseract is None or cv2 is None or image is None:
            return None
        try:
            region = image[int(image.shape[0] * top_pct):, :, :]
            if region.size == 0:
                return None
            gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
            raw = pytesseract.image_to_string(gray, config="--psm 6")
        except Exception:                                        # noqa: BLE001
            return None
        lines = []
        for line in str(raw or "").splitlines():
            cleaned = re.sub(r"\s+", " ", line).strip().lower()
            if len(cleaned) >= 3:
                lines.append(cleaned)
        return lines

    def _frame_diff(self, path, other_path, top_pct: float):
        """Percent of pixels that differ between two frames (list area only).

        None when the two frames cannot be compared.
        """
        cv2 = self._cv2_module()
        first = self._load_image(path)
        second = self._load_image(other_path)
        if cv2 is None or first is None or second is None:
            return None
        try:
            if first.shape != second.shape:
                second = cv2.resize(second, (first.shape[1], first.shape[0]))
            top = int(first.shape[0] * top_pct)
            one = cv2.cvtColor(first[top:, :, :], cv2.COLOR_BGR2GRAY)
            two = cv2.cvtColor(second[top:, :, :], cv2.COLOR_BGR2GRAY)
            if one.size == 0 or two.size == 0:
                return None
            changed = float((cv2.absdiff(one, two) > 25).mean() * 100.0)
        except Exception:                                        # noqa: BLE001
            return None
        return changed

    # ------------------------------------------------------------------
    # the four cases
    # ------------------------------------------------------------------

    def run_radio(self, ctx: CaseContext) -> CaseOutcome:
        """Open the radio app and play one of its stations."""
        try:
            nodes = self._nodes(ctx, "stb_radio_nodes", self.DEFAULT_RADIO_NODES)
            max_items = self._count(ctx, "max_items", 3)

            opened = False
            node = ""
            detail = ""
            for candidate in nodes:
                ok, nav_detail = navigate_to(ctx, candidate)
                if ok:
                    opened, node = True, candidate
                    ctx.log(f"on '{candidate}'")
                    break
                detail = (f"{candidate}: {nav_detail}" if not detail
                          else f"{detail}; {candidate}: {nav_detail}")
                ctx.log(f"could not reach '{candidate}': {nav_detail}")
                # The screen is asked HERE, right after the route failed: the
                # app store is still on the screen, and a radio tile that IS
                # there means the surface is present and the TREE could not
                # reach it (a stale reference picture, a layout that moved
                # the tile). That is never a defect of the product.
                found, matched, _frame = self._radio_tile_on_screen(ctx)
                if found:
                    evidence = {"nodes": list(nodes),
                                "radio_tile_on_screen": True,
                                "radio_tile_text": matched}
                    return CaseOutcome.failed(
                        f"infra: the radio surface could not be opened ({detail}) — the "
                        f"Radio app IS on this box's app store (the screen shows "
                        f"'{matched}'), but the tree's route for '{candidate}' does not "
                        f"reach it: the tree's reference picture is stale for this "
                        f"layout. That is a gap in the tree, not a defect of the product",
                        cause=CAUSE_INFRA, evidence=evidence)
            if not opened:
                # The node is either absent from the tree (this box has no
                # radio surface: a coverage gap) or present and broken (a
                # product defect). `surface_failure` decides which.
                return self._surface_failure(
                    ctx, nodes, detail,
                    reason=f"the radio surface could not be opened ({detail})",
                    evidence={"nodes": list(nodes)})

            walk = self._walk_list(ctx, max_items)
            evidence = {"surface": node, "items_tried": walk["items_tried"]}
            if walk.get("transport_error"):
                return CaseOutcome.skipped(
                    f"the radio remote did not answer: {walk['detail']}",
                    cause=CAUSE_INFRA, evidence=evidence)
            if walk["played"]:
                evidence["played_item"] = walk["item_index"]
                evidence["probe"] = walk["probe_detail"]
                return CaseOutcome.passed(
                    f"radio station {walk['item_index'] + 1} of {max_items} played "
                    f"({walk['probe_detail']})",
                    evidence=evidence)
            evidence["probe"] = walk["probe_detail"]

            # The picture did not move. On a radio station that is NOT a
            # verdict: the station is a static logo with sound. The audio
            # probe is the signal that decides.
            audio = walk.get("audio") or {}
            evidence["audio"] = audio
            if audio.get("audible") is True:
                evidence["played_item"] = walk.get("audio_index")
                return CaseOutcome.passed(
                    f"radio station {int(walk.get('audio_index') or 0) + 1} of {max_items} "
                    f"played: the audio was measured at {audio.get('level_db')} dB "
                    f"({audio.get('detail')})",
                    evidence=evidence)
            if audio.get("audible") is False:
                return CaseOutcome.failed(
                    f"{walk['items_tried']} radio stations were reachable but none played: "
                    f"the audio was measured as absent ({audio.get('detail')})",
                    cause=CAUSE_PRODUCT, evidence=evidence)
            return CaseOutcome.skipped(
                "the radio surface is a static picture and the screen did not move; the "
                "capture carried no audio reading, so the playback cannot be concluded "
                f"({audio.get('detail')})",
                cause=CAUSE_INFRA, evidence=evidence)
        except Exception as exc:                                   # noqa: BLE001
            cause = exception_cause(exc)
            ctx.log(f"the radio case raised: {exc}")
            return CaseOutcome.failed(
                f"{cause}: the radio case raised {type(exc).__name__}", cause=cause)

    def run_replay(self, ctx: CaseContext) -> CaseOutcome:
        """Open the catch-up list and play one of its programmes."""
        try:
            nodes = self._nodes(ctx, "stb_replay_nodes", self.DEFAULT_REPLAY_NODES)
            max_items = self._count(ctx, "max_items", 3)

            opened, node, detail = self._open_surface(ctx, nodes)
            if not opened:
                return self._surface_failure(
                    ctx, nodes, detail,
                    reason=f"the replay surface could not be opened ({detail})",
                    evidence={"nodes": list(nodes)})

            walk = self._walk_list(ctx, max_items)
            evidence = {"surface": node, "items_tried": walk["items_tried"]}
            if walk.get("transport_error"):
                return CaseOutcome.skipped(
                    f"the replay remote did not answer: {walk['detail']}",
                    cause=CAUSE_INFRA, evidence=evidence)
            if walk["played"]:
                evidence["played_item"] = walk["item_index"]
                evidence["probe"] = walk["probe_detail"]
                return CaseOutcome.passed(
                    f"replay programme {walk['item_index'] + 1} of {max_items} played "
                    f"({walk['probe_detail']})",
                    evidence=evidence)

            # Second chance: the tree's own asset path (replay_asset ->
            # replay_asset_stream) plays a catch-up asset without a walk.
            fallback = self._tree_playback(
                ctx, self._nodes(ctx, "stb_replay_asset_nodes", self.DEFAULT_REPLAY_ASSET_NODES))
            evidence["probe"] = walk["probe_detail"]
            if fallback.get("played"):
                evidence["played_node"] = fallback.get("node")
                evidence["probe"] = fallback.get("detail")
                return CaseOutcome.passed(
                    f"a replay programme played through the tree path "
                    f"'{fallback.get('node')}' ({fallback.get('detail')})",
                    evidence=evidence)
            evidence["audio"] = walk.get("audio") or {}
            return self._no_playback_outcome(walk, evidence, "replay programme", max_items)
        except Exception as exc:                                   # noqa: BLE001
            cause = exception_cause(exc)
            ctx.log(f"the replay case raised: {exc}")
            return CaseOutcome.failed(
                f"{cause}: the replay case raised {type(exc).__name__}", cause=cause)

    def _no_playback_outcome(self, walk, evidence, subject: str, max_items: int):
        """The verdict when the picture never moved.

        A still picture is not a failure verdict. The capture can be static
        while the sound plays — a radio station is a still logo, and a video
        can sit in a small player — so the SOUND decides:

        * sound measured present -> it played;
        * sound measured absent  -> a product defect (the surface was reached
          and nothing came out of it);
        * no audio reading at all -> the playback cannot be concluded, which
          is infra, never a defect.
        """
        audio = walk.get("audio") or {}
        if audio.get("audible") is True:
            evidence["played_item"] = walk.get("audio_index")
            return CaseOutcome.passed(
                f"{subject} {int(walk.get('audio_index') or 0) + 1} of {max_items} played: "
                f"the audio was measured at {audio.get('level_db')} dB "
                f"({audio.get('detail')})",
                evidence=evidence)
        if audio.get("audible") is False:
            return CaseOutcome.failed(
                f"{walk['items_tried']} {subject}s were reachable but none played: the audio "
                f"was measured as absent ({audio.get('detail')})",
                cause=CAUSE_PRODUCT, evidence=evidence)
        return CaseOutcome.skipped(
            f"the screen did not move on the {subject} surface and the capture carried no "
            f"audio reading, so the playback cannot be concluded "
            f"({audio.get('detail')})",
            cause=CAUSE_INFRA, evidence=evidence)

    def run_vod(self, ctx: CaseContext) -> CaseOutcome:
        """Open the VOD catalogue and play one of its titles."""
        try:
            nodes = self._nodes(ctx, "stb_vod_nodes", self.DEFAULT_VOD_NODES)
            max_items = self._count(ctx, "max_items", 3)

            opened, node, detail = self._open_surface(ctx, nodes)
            if not opened:
                return self._surface_failure(
                    ctx, nodes, detail,
                    reason=f"the VOD surface could not be opened ({detail})",
                    evidence={"nodes": list(nodes)})

            walk = self._walk_list(ctx, max_items)
            evidence = {"surface": node, "items_tried": walk["items_tried"]}
            if walk.get("transport_error"):
                return CaseOutcome.skipped(
                    f"the VOD remote did not answer: {walk['detail']}",
                    cause=CAUSE_INFRA, evidence=evidence)
            if walk["played"]:
                evidence["played_item"] = walk["item_index"]
                evidence["probe"] = walk["probe_detail"]
                return CaseOutcome.passed(
                    f"VOD title {walk['item_index'] + 1} of {max_items} played "
                    f"({walk['probe_detail']})",
                    evidence=evidence)
            evidence["probe"] = walk["probe_detail"]
            evidence["audio"] = walk.get("audio") or {}
            return self._no_playback_outcome(walk, evidence, "VOD title", max_items)
        except Exception as exc:                                   # noqa: BLE001
            cause = exception_cause(exc)
            ctx.log(f"the VOD case raised: {exc}")
            return CaseOutcome.failed(
                f"{cause}: the VOD case raised {type(exc).__name__}", cause=cause)

    def run_recording(self, ctx: CaseContext) -> CaseOutcome:
        """Record a live programme, find it in the list, play it back.

        Three steps in one case, because each of them alone would prove
        nothing: a recording that is listed but does not play back is a
        failure, and a recording that never appears is a failure too.

        The rule that keeps this honest: a missing listing is a product defect
        only when the recording was PROVEN to exist. When the RECORD key left
        no trace at all — the list did not change and nothing on screen said a
        recording had started — the test cannot claim the product dropped a
        recording that was never requested. That case is a coverage gap (this
        surface may offer no recording affordance for the IR key), never a
        confirmed defect.
        """
        try:
            recordings_nodes = self._nodes(ctx, "stb_recordings_nodes",
                                           self.DEFAULT_RECORDINGS_NODES)
            live_nodes = self._nodes(ctx, "stb_live_nodes", self.DEFAULT_LIVE_NODES)
            # The list of a set-top box refreshes on its own pace: 45s was too
            # short on the lab boxes (the listing showed up a minute later), and
            # a listing that is not seen in time is not a dropped recording.
            wait_s = self._seconds(ctx, "record_wait_s", 120)
            poll_s = self._seconds(ctx, "stb_record_poll_s", 10.0)
            top_pct = self._seconds(ctx, "stb_record_list_top_pct", 0.25)
            settle = self._settle(ctx)
            record_key = self._key(ctx, "stb_record_key", self.DEFAULT_RECORD_KEY)

            evidence = {"steps": []}

            # -- step 0: the baseline of the recordings list ------------------
            base_ok, base_node, base_detail = self._open_surface(ctx, recordings_nodes)
            baseline_path = None
            baseline_lines = None
            if base_ok:
                baseline_path = self._capture(ctx, "recording-list-before")
                baseline_lines = self._screen_lines(baseline_path, top_pct)
            evidence["baseline"] = {"node": base_node, "frame": bool(baseline_path)}
            if not base_ok:
                ctx.log(f"the recordings list is not reachable yet: {base_detail}")

            # -- step 1: a live programme, then RECORD -------------------------
            live_ok, live_node, live_detail = self._open_surface(ctx, live_nodes)
            if not live_ok:
                evidence["steps"].append("no live programme")
                outcome = self._surface_failure(
                    ctx, live_nodes, live_detail,
                    reason=f"the live surface could not be opened ({live_detail})")
                outcome.evidence = evidence
                return outcome
            sleep(ctx, self._seconds(ctx, "stb_live_settle_s", 8.0))

            record_ok, record_detail = press_key(ctx, record_key, settle=settle)
            if not record_ok:
                evidence["steps"].append("record key refused")
                return CaseOutcome.skipped(
                    f"the remote refused '{record_key}', so nothing was recorded "
                    f"({record_detail})",
                    cause=CAUSE_INFRA, evidence=evidence)
            sleep(ctx, self._seconds(ctx, "stb_record_settle_s", 4.0))
            self._capture(ctx, "recording-after-record")
            evidence["steps"].append("recorded")
            evidence["live_node"] = live_node

            # -- step 2: is the recording listed? ------------------------------
            listed, how, listed_path, signal = self._wait_for_listing(
                ctx, recordings_nodes, baseline_path, baseline_lines, wait_s, poll_s, top_pct)
            evidence["listing"] = how
            evidence["listing_signal"] = signal
            evidence["listing_frame"] = bool(listed_path)
            if not listed:
                evidence["steps"].append("not listed")
                if signal == "surface":
                    # The recordings list could not be opened at all: the node
                    # is either absent from the tree (a coverage gap) or
                    # present and broken (a product defect).
                    outcome = self._surface_failure(
                        ctx, recordings_nodes, how,
                        reason=f"step 2 (listing): {how}")
                    outcome.evidence = evidence
                    return outcome
                if signal == "no-baseline":
                    # The list was readable but there was no baseline to compare
                    # it with: the test could not exercise the step.
                    return CaseOutcome.skipped(
                        f"step 2 (listing): cannot conclude whether the recording appeared "
                        f"({how})",
                        cause=CAUSE_COVERAGE, evidence=evidence)
                if signal == "none":
                    # No signal at all: that is the platform, not the product.
                    return CaseOutcome.skipped(
                        f"step 2 (listing): cannot conclude whether the recording appeared "
                        f"({how})",
                        cause=CAUSE_INFRA, evidence=evidence)
                # The list was readable and it did not change. The RECORD key was
                # sent, but NOTHING proves that a recording was ever requested
                # on this surface: the app showed no recording confirmation and
                # neither the recorded nor the planned part of the list moved.
                # A recording that was never requested proves nothing about the
                # product, so this is NOT a product defect: the surface may
                # offer no recording affordance for the IR key (a product
                # decision), and the test cannot judge the product here.
                return CaseOutcome.skipped(
                    f"step 2 (listing): the recordings list did not change within "
                    f"{wait_s:.0f}s after the RECORD key ({how}) — the test cannot "
                    f"establish that a recording was requested on this surface, so "
                    f"it cannot say the product dropped it: the live surface may "
                    f"offer no recording affordance for the IR key (a product "
                    f"decision, not a confirmed defect)",
                    cause=CAUSE_COVERAGE, evidence=evidence)
            evidence["steps"].append("listed")

            # -- step 3: does it play back? -----------------------------------
            played, play_detail = self._play_recording(ctx)
            evidence["playback"] = play_detail
            if not played:
                # "no motion and no audio reading" is not a verdict: the test
                # could not measure the playback. Only a measured silence (or
                # a transport that answered) makes it a defect.
                if "no audio reading" in play_detail:
                    evidence["steps"].append("playback cannot be concluded")
                    return CaseOutcome.skipped(
                        f"step 3 (playback): the recording is listed, but the playback "
                        f"cannot be concluded ({play_detail})",
                        cause=CAUSE_INFRA, evidence=evidence)
                evidence["steps"].append("does not play back")
                return CaseOutcome.failed(
                    f"step 3 (playback): the recording is listed but does not play back "
                    f"({play_detail})",
                    cause=CAUSE_PRODUCT, evidence=evidence)
            evidence["steps"].append("plays back")
            return CaseOutcome.passed(
                f"recorded a live programme, found it in the recordings list ({how}) "
                f"and played it back",
                evidence=evidence)
        except Exception as exc:                                   # noqa: BLE001
            cause = exception_cause(exc)
            ctx.log(f"the recording case raised: {exc}")
            return CaseOutcome.failed(
                f"{cause}: the recording case raised {type(exc).__name__}", cause=cause)

    # ------------------------------------------------------------------
    # the recording case, step by step
    # ------------------------------------------------------------------

    def _wait_for_listing(self, ctx: CaseContext, nodes, baseline_path,
                           baseline_lines, wait_s: float, poll_s: float,
                           top_pct: float):
        """Wait for the recording to show up in the recordings list.

        Returns (listed, how, frame_path, signal). The list is opened once and
        then polled: the wait is bounded by `wait_s`. The signal is "surface"
        when the list could not be opened at all, "text" / "pixels" when the
        list was read, "no-baseline" when there was nothing to compare the
        list with and "none" when no frame could be read.
        """
        opened, node, detail = self._open_surface(ctx, nodes)
        if not opened:
            # The list itself could not be opened: the listing cannot be
            # judged. The caller tells a missing surface (a coverage gap)
            # from a broken one (a product defect).
            return False, f"the recordings list could not be opened ({detail})", None, "surface"

        deadline = time.monotonic() + wait_s
        how = "the recordings list never changed"
        signal = "text"
        path = None
        while True:
            path = self._capture(ctx, "recording-list-after")
            listed, how, signal = self._is_listed(ctx, path, baseline_path,
                                                  baseline_lines, top_pct)
            if listed:
                return True, how, path, signal
            if time.monotonic() >= deadline:
                return False, how, path, signal
            sleep(ctx, min(poll_s, max(0.0, deadline - time.monotonic())))

    def _is_listed(self, ctx: CaseContext, path, baseline_path, baseline_lines,
                   top_pct: float):
        """Is there a new entry in the recordings list?

        The primary signal is the text of the list area: a line the baseline
        did not have means an entry appeared. When OCR is not available the
        fallback is the pixel difference over the same area. Returns
        (listed, how, signal) where `how` says which signal decided and
        `signal` is "text", "pixels", "no-baseline" or "none".
        """
        if not path:
            return False, "no frame of the recordings list could be captured", "none"

        lines = self._screen_lines(path, top_pct)
        if lines is not None:
            if baseline_lines is None:
                # The list is readable but there is nothing to compare it with:
                # without a baseline "new" cannot be claimed.
                return False, ("the recordings list could not be compared with a "
                               "baseline (no frame of the list before the recording)"), \
                    "no-baseline"
            new_lines = [line for line in lines if line not in baseline_lines]
            if new_lines:
                return True, f"a new entry appeared in the list: '{new_lines[0][:60]}'", "text"
            return False, "the list still shows the same entries as before the recording", "text"

        difference = self._frame_diff(path, baseline_path, top_pct)
        if difference is None:
            return False, ("the recordings list could not be compared "
                           "(no OCR and no readable baseline frame)"), "none"
        threshold = self._seconds(ctx, "stb_record_diff_pct", 2.0)
        if difference >= threshold:
            return True, (f"the list area changed by {difference:.1f}% of its pixels "
                          f"after the recording"), "pixels"
        return False, (f"the list area did not change after the recording "
                       f"({difference:.1f}% of pixels, threshold {threshold:.1f}%)"), "pixels"

    def _play_recording(self, ctx: CaseContext):
        """Select the recording and confirm that it plays back.

        The newest recording is the first row of the list, so the first try
        selects it. If that does not play, the next row is tried as well.
        """
        select_key = self._key(ctx, "stb_select_key", self.DEFAULT_SELECT_KEY)
        back_key = self._key(ctx, "stb_back_key", self.DEFAULT_BACK_KEY)
        next_key = self._key(ctx, "stb_next_key", self.DEFAULT_NEXT_KEY)
        settle = self._settle(ctx)
        play_s = self._seconds(ctx, "play_seconds", 12)
        item_settle_s = self._seconds(ctx, "stb_item_settle_s", 3.0)
        list_settle_s = self._seconds(ctx, "stb_list_settle_s", 2.0)
        retries = self._count(ctx, "stb_probe_retries", 2)

        for attempt in range(2):
            if attempt:
                # Leave the player and move to the next recording.
                press_key(ctx, back_key, settle=settle)
                sleep(ctx, list_settle_s)
                press_key(ctx, next_key, settle=settle)
                sleep(ctx, list_settle_s)

            ok, detail = press_key(ctx, select_key, settle=settle)
            if not ok:
                return False, f"the remote refused '{select_key}': {detail}"
            sleep(ctx, item_settle_s + play_s)
            probe = self._probe_playback(ctx, retries)
            if probe.get("playing"):
                return True, f"recording {attempt + 1} played back ({probe['detail']})"
            # The picture did not move. A recording can play with a still
            # picture, so the sound decides — without an audio reading the
            # playback cannot be concluded at all.
            audio = self._probe_audio(ctx)
            if audio.get("audible") is True:
                return True, (f"recording {attempt + 1} played back: the audio was measured "
                              f"at {audio.get('level_db')} dB ({audio.get('detail')})")
            if audio.get("audible") is False:
                return False, (f"the recording played with the sound measured as absent "
                               f"({audio.get('detail')})")
            return False, ("no recording in the list showed motion after OK and the capture "
                           f"carried no audio reading ({audio.get('detail')})")
        return False, "no recording in the list showed motion after OK"

    # ------------------------------------------------------------------
    # optional run lifecycle
    # ------------------------------------------------------------------

    def prepare(self, ctx: CaseContext) -> None:
        """Start from a known screen and check the remote is there."""
        try:
            remote = ctx.controller("remote")
            ctx.log(f"device {getattr(ctx.device, 'device_name', '')} "
                    f"({getattr(ctx.device, 'device_model', '')}), "
                    f"remote: {'yes' if remote else 'no'}")
            if remote is None:
                ctx.note("the device has no remote controller")
                return
            # The operator's rule: a run starts from Home (STB_UI_OPERATOR.md
            # §1). Best effort: every case navigates to its own surface.
            ok, detail = navigate_to(ctx, "home")
            if not ok:
                ctx.log(f"could not reach 'home': {detail}")
        except Exception as exc:                                   # noqa: BLE001
            ctx.log(f"prepare failed: {exc}")

    def finish(self, ctx: CaseContext) -> None:
        """Leave the box in a sane state (no player left open)."""
        try:
            press_key(ctx, self._key(ctx, "stb_back_key", self.DEFAULT_BACK_KEY),
                      settle=self._settle(ctx))
        except Exception as exc:                                   # noqa: BLE001
            ctx.log(f"finish failed: {exc}")
