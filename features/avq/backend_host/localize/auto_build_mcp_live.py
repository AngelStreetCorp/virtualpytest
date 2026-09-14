#!/usr/bin/env python3
"""Build a fresh, depth-bounded STB graph from MCP captures.

This runner deliberately does not use an exported fixture, an existing navigation tree,
localize(), or the paid DOM generator.  Device observations come from MCP only.  The
production fingerprint is computed locally from each captured image.  DOM analysis is a
file handoff: a Codex sub-agent inspects ``captures/*.png`` and writes ``dom/*.json``.

The command is resumable because a screen's DOM is required before its outgoing keys can
be explored:

    # Fresh HOME capture and first DOM job
    python3 features/avq/backend_host/localize/auto_build_mcp_live.py init --run-dir /tmp/blestb-depth1

    # After a sub-agent has written the requested dom/*.json files
    python3 features/avq/backend_host/localize/auto_build_mcp_live.py explore --run-dir /tmp/blestb-depth1

    python3 features/avq/backend_host/localize/auto_build_mcp_live.py status --run-dir /tmp/blestb-depth1

``explore`` may create more DOM jobs.  Analyze those images and run it again until status
reports ``complete``.  Every probe repositions by MCP ``goto home`` plus the freshly
discovered path, captures that source for verification, then sends exactly one discovery key.
"""

from __future__ import annotations

import argparse
import base64
import difflib
import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import cv2
import numpy as np
import requests
import urllib3


# Lab defaults — every one overridable per-invocation (CLI flag) or per-machine (env).
# Ladder C: a run against any other server/host/device needs only flags, no edits.
DEFAULT_MCP_URL = os.getenv("VPT_MCP_URL", "https://rpitest.angelstreet.io/server/mcp")
DEFAULT_HOST = os.getenv("VPT_BUILD_HOST", "host3")
DEFAULT_DEVICE = os.getenv("VPT_BUILD_DEVICE", "device4")
DEFAULT_DEVICE_NAME = os.getenv("VPT_BUILD_DEVICE_NAME", "blestbv1+")
DEFAULT_UI = os.getenv("VPT_BUILD_UI", "example_tv")
STATE_VERSION = 1
EXIT_MORE_WORK = 10   # explore exit code: a frontier remains — re-invoke to continue

_RUN_START = time.time()


def _ts() -> str:
    """Wall clock + elapsed-since-process-start, for profiling where a live run spends time."""
    return f"[{time.strftime('%H:%M:%S')} +{time.time() - _RUN_START:5.0f}s]"
# Exploration priority: DIVE first (OK opens the focused item's screen), then sweep focus
# (RIGHT/LEFT/DOWN/UP). BACK is NOT a discovery probe — it is the return-to-parent mechanism
# (offline back-stack: OK pushes, BACK pops). goto-home is used ONLY once, at init.
PROBE_ORDER = ("OK", "RIGHT", "LEFT", "DOWN", "UP")
DPAD_KEYS = {"UP", "DOWN", "LEFT", "RIGHT"}
DOM_KEYS = {"OK", *DPAD_KEYS, "BACK"}


class LiveBuildError(RuntimeError):
    pass


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _find_auth(config_path: Optional[str]) -> str:
    explicit = os.getenv("VPT_MCP_AUTHORIZATION", "").strip()
    if explicit:
        return explicit if explicit.lower().startswith("bearer ") else f"Bearer {explicit}"
    key = os.getenv("VPT_MCP_KEY", "").strip()
    if key:
        return f"Bearer {key}"

    candidates: List[Path] = []
    if config_path:
        candidates.append(Path(config_path).expanduser())
    candidates.extend([
        Path.cwd() / ".mcp.json",
        Path(__file__).resolve().parents[4] / ".mcp.json",
        Path.home() / "virtualpytest" / ".mcp.json",
    ])
    for path in candidates:
        if not path.exists():
            continue
        config = _load_json(path)
        auth = (((config.get("mcpServers") or {}).get("virtualpytest") or {})
                .get("headers") or {}).get("Authorization")
        if auth:
            return str(auth)
    raise LiveBuildError(
        "No MCP bearer credential found. Set VPT_MCP_KEY or pass --mcp-config."
    )


class MCPClient:
    def __init__(self, url: str, authorization: str, verify_tls: bool = False):
        self.url = url
        self.headers = {
            "Authorization": authorization,
            "Content-Type": "application/json",
            "User-Agent": "curl/8.7.1",
        }
        self.verify_tls = verify_tls
        # goto_home is the ONE expensive reposition primitive (full Entry->home recipe,
        # ~9-26s). Counting its invocations is how a run proves it is NOT goto-storming:
        # the 2026-07-18 fix collapsed validation from 58 gotos to a handful, and the
        # certification report surfaces this count so the collapse is verifiable.
        self.goto_count = 0
        if not verify_tls:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def call(self, tool: str, params: Dict[str, Any], timeout: int = 240) -> Dict[str, Any]:
        t0 = time.time()
        response = requests.post(
            self.url,
            headers=self.headers,
            json={"tool": tool, "params": params},
            timeout=timeout,
            verify=self.verify_tls,
        )
        # Timestamped device-call profiling: every MCP round-trip is a ~seconds-scale wait, so
        # this is where a live run spends its time. `keys=[...]` for an action makes the press
        # sequence visible so a slow/re-anchor step is obvious in the log.
        keys = "+".join(str((a.get("params") or {}).get("key", "")) for a in (params.get("actions") or []))
        print(f"{_ts()} MCP {tool}{f'[{keys}]' if keys else ''} {time.time() - t0:.1f}s")
        if not response.ok:
            raise LiveBuildError(f"MCP {tool} HTTP {response.status_code}: {response.text[:500]}")
        body = response.json()
        if body.get("isError"):
            text = next((c.get("text") for c in body.get("content", [])
                         if c.get("type") == "text"), "unknown MCP error")
            raise LiveBuildError(f"MCP {tool} failed: {text}")
        return body

    def goto_home(self, host: str, device: str, ui_name: str,
                  timeout: int = 240, include_screenshot: bool = False) -> Dict[str, Any]:
        """Reliable reset-to-root: MCP-navigate the saved tree's `home` node.

        Raises LiveBuildError on MCP failure, so callers are gated on a successful goto.
        Preferred over a raw HOME keypress, which toggles TV<->menu on this STB. With
        include_screenshot the response carries the resulting home frame inline.

        Poll-timeout tolerance: the MCP tool polls the async navigation for a fixed
        60s and reports "timed out" even though the host keeps executing the action
        sequence and its verification. A timeout is therefore NOT a failure verdict —
        wait out the remainder and let the caller confirm the landing state by
        fingerprint (which every caller of this method does anyway).
        """
        self.goto_count += 1
        try:
            return self.call("navigate_to_node", {
                "host_name": host,
                "device_id": device,
                "userinterface_name": ui_name,
                "target_node_label": "home",
                "include_screenshot": include_screenshot,
            }, timeout=timeout)
        except LiveBuildError as exc:
            if "timed out" not in str(exc).lower():
                raise
            print("    goto_home poll timed out — navigation continues on host; "
                  "waiting 25s for it to finish before the caller's fingerprint check")
            time.sleep(25)
            return {"timed_out": True}

    def image_bytes(self, body: Dict[str, Any]) -> bytes:
        image = next((c for c in body.get("content", []) if c.get("type") == "image"), None)
        if image and image.get("data"):
            return base64.b64decode(image["data"])

        # Some deployed MCP servers return the capture URL but fail to inline the image
        # block.  The stream/capture route is intentionally auth-exempt, so retain MCP as
        # the capture primitive and download the exact URL it returned.
        text = "\n".join(
            str(c.get("text") or "") for c in body.get("content", [])
            if c.get("type") == "text"
        )
        match = re.search(r"Screenshot URL:\s*(https?://\S+)", text)
        if match:
            response = requests.get(
                match.group(1), headers={"User-Agent": "curl/8.7.1"},
                timeout=30, verify=self.verify_tls,
            )
            if response.ok and response.content:
                return response.content
            raise LiveBuildError(
                f"MCP screenshot URL returned HTTP {response.status_code}: {match.group(1)}"
            )
        raise LiveBuildError("MCP response did not include a screenshot image or URL")


def _device_payload(body: Dict[str, Any]) -> Dict[str, Any]:
    text = next((c.get("text") for c in body.get("content", [])
                 if c.get("type") == "text"), "{}")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LiveBuildError("get_device_info returned non-JSON text") from exc


def _validate_target(client: MCPClient, host: str, device: str, name: str) -> None:
    payload = _device_payload(client.call("get_device_info", {}))
    match = next((d for d in payload.get("devices", [])
                  if d.get("host_name") == host and d.get("device_id") == device), None)
    if not match:
        raise LiveBuildError(f"Target {host}/{device} was not returned by get_device_info")
    if str(match.get("device_name", "")).lower() != name.lower():
        raise LiveBuildError(
            f"Refusing wrong device: expected {name!r}, got {match.get('device_name')!r}"
        )
    if match.get("status") != "online":
        raise LiveBuildError(f"Target is not online: {match.get('status')}")

    actions = client.call("list_actions", {"host_name": host, "device_id": device})
    remote = (actions.get("device_action_types") or {}).get("remote") or []
    available = {
        str((a.get("params") or {}).get("key", "")).upper()
        for a in remote if a.get("command") == "press_key"
    }
    missing = ({"HOME", "BACK", "UP", "DOWN", "LEFT", "RIGHT", "OK"} - available)
    if missing:
        raise LiveBuildError(f"Target remote does not expose required keys: {sorted(missing)}")


DPAD_SETTLE_MS = 1000      # focus moves (UP/DOWN/LEFT/RIGHT) settle fast (~1s is enough;
                           # was 2000 — measured 2026-07-17 as pure waste on tab/row moves)
SCREEN_SETTLE_MS = 5000    # screen changes (OK / BACK) — 5s. A menu<->screen transition (settings
                           # -> home) can take >3s to render; at 3s the BACK probe captured the
                           # source mid-transition, read it as "still on the screen", and pressed a
                           # spurious 2nd BACK — which at VALIDATE time exits the menu root to live
                           # TV (fail_wrong_screen on settings/profile BACK, 2026-07-18). 5s lets the
                           # true post-BACK screen render so the recorded press count is accurate.


def _settle_for(key: str) -> int:
    return SCREEN_SETTLE_MS if str(key).upper() in ("OK", "BACK") else DPAD_SETTLE_MS


def _actions(keys: Iterable[str]) -> List[Dict[str, Any]]:
    # Per-key wait so the inline screenshot is captured only after that key's screen settles:
    # D-pad = 1s, OK/BACK = 5s.
    return [{"command": "press_key", "params": {"key": k, "wait_time": _settle_for(k)}}
            for k in keys]


CAPTURE_RETRIES = 3        # attempts for a KEYLESS capture before giving up
CAPTURE_RETRY_WAIT_S = 4.0 # the observed outage window is ~1-2 min of ffmpeg restart, but a single
                           # restart clears in seconds; 3 x 4s covers it without stalling the run.

# Capture faults that are TRANSIENT — the AV pipeline is mid-restart (the ffmpeg watchdog recycles
# the encoder) and the next frame request succeeds. Measured 2026-07-19: a ~90s window killed a
# 24-round explore (rc=2) AND certified 5 edges SOURCE UNREACHABLE, because neither path retried.
# Both signatures below are the SAME fault surfacing at two layers: the host returns no frame
# (controller returned None), or returns a body with neither an inline image nor a URL.
_TRANSIENT_CAPTURE = (
    "controller returned none",
    "failed to take temporary screenshot",
    "did not include a screenshot image or url",
)


def _is_transient_capture(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(sig in text for sig in _TRANSIENT_CAPTURE)


def _capture_frame(client: MCPClient, host: str, device: str) -> bytes:
    """Keyless capture with retry. Safe to retry: it presses nothing, so re-running it cannot
    move the device. fast=True — we compute our OWN fingerprint from these bytes, so the
    server/host must skip their (double) fingerprint+OCR + the 0.5s settle."""
    for attempt in range(CAPTURE_RETRIES):
        try:
            return client.image_bytes(client.call("capture_screenshot", {
                "host_name": host,
                "device_id": device,
                "fast": True,
            }))
        except LiveBuildError as exc:
            if not _is_transient_capture(exc) or attempt == CAPTURE_RETRIES - 1:
                raise
            print(f"    transient capture fault ({exc}) — retry "
                  f"{attempt + 1}/{CAPTURE_RETRIES - 1} in {CAPTURE_RETRY_WAIT_S:.0f}s")
            time.sleep(CAPTURE_RETRY_WAIT_S)
    raise LiveBuildError("unreachable")  # loop either returns or raises


def _execute_capture(
    client: MCPClient,
    *,
    host: str,
    device: str,
    keys: List[str],
) -> bytes:
    if keys:
        # Execute the actions and take the RESULTING frame inline from the SAME response
        # (include_screenshot=true) — one round-trip, and the image is exactly the post-action
        # screen (server captures after the key's per-kind wait_time settles).
        # NEVER retry the ACTION on a capture fault: the host presses the keys and THEN grabs the
        # frame, so a capture-stage failure means the keys already landed. Re-sending them would
        # double-press (a 2nd BACK exits the menu root to live TV — the exact desync the
        # late-render guard exists to prevent). Recover with a KEYLESS re-capture instead: the
        # device is already on the post-action screen, so a plain frame grab is what we want.
        try:
            body = client.call("execute_device_action", {
                "host_name": host,
                "device_id": device,
                "actions": _actions(keys),
                "include_screenshot": True,
                # We compute our own fingerprint — skip the host-side fingerprint/settle (~2s/press).
                "fast_screenshot": True,
            })
            return client.image_bytes(body)
        except LiveBuildError as exc:
            if not _is_transient_capture(exc):
                raise
            print(f"    transient capture fault after {'+'.join(keys)} ({exc}) — "
                  f"keys landed; re-capturing without re-pressing")
            time.sleep(CAPTURE_RETRY_WAIT_S)
            return _capture_frame(client, host, device)
    # ~sub-second vs a 6-14s keyless capture (2026-07-17 profiling; ~13 keyless captures per run).
    return _capture_frame(client, host, device)


def _image_helpers_class():
    helper_path = (Path(__file__).resolve().parents[4] / "backend_host" / "src" / "controllers" /
                   "verification" / "image_helpers.py")
    spec = importlib.util.spec_from_file_location("auto_build_image_helpers", helper_path)
    if not spec or not spec.loader:
        raise LiveBuildError(f"Cannot load fingerprint helper: {helper_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ImageHelpers


_GRAPH_REPORT = None


def _graph_report():
    """Load the SAME report renderer the offline test uses (graph_report.py), so the live
    HTML report is identical in shape — no parallel renderer."""
    global _GRAPH_REPORT
    if _GRAPH_REPORT is None:
        path = (Path(__file__).resolve().parents[2] / "lib" / "auto_builder" / "graph_report.py")
        spec = importlib.util.spec_from_file_location("auto_build_graph_report", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _GRAPH_REPORT = module
    return _GRAPH_REPORT


_DOM_OVERLAY_FN = None


def _dom_overlay_fn():
    """Reuse the production overlay renderer (dom_generator.render_dom_overlay) — the same
    function that draws the <stem>_dom.jpg for the Edit-node DOM tab. OpenAI is lazy-imported
    inside generate_dom, so loading this module standalone pulls no paid deps."""
    global _DOM_OVERLAY_FN
    if _DOM_OVERLAY_FN is None:
        path = (Path(__file__).resolve().parents[4] / "backend_host" / "src" / "services" / "ai_exploration" /
                "dom_generator.py")
        spec = importlib.util.spec_from_file_location("auto_build_dom_generator", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _DOM_OVERLAY_FN = module.render_dom_overlay
    return _DOM_OVERLAY_FN


DIALOG_MIN_H = 0.042        # heading glyph height as a fraction of frame height
DIALOG_CENTER = (0.30, 0.70)  # heading line midpoint must sit in this x range (of the frame)
DIALOG_DIM_RATIO = 0.55     # surround must be this much darker than the plate to count as modal


def _dialog_plate(image) -> Optional[Any]:
    """Bounding box (x, y, w, h) of a MODAL plate — a lighter panel over a DIMMED page — or
    None when the frame is not a dialog.

    The dimming is what makes this specific. Height/centring alone cannot separate a dialog
    heading from a big centred app tile: measured, the apps grid's 'youtube'/'max' tiles are
    0.043-0.068 of frame height, right on top of the 0.046-0.060 that dialog headings measure.
    A modal, though, always darkens the page behind it, so the plate is materially brighter
    than its surround; the undimmed apps grid is not."""
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 40, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for c in contours:
        x, y, bw, bh = cv2.boundingRect(c)
        if bw < 0.25 * w or bh < 0.15 * h or (bw * bh) > 0.80 * (w * h):
            continue
        cx, cy = (x + bw / 2) / w, (y + bh / 2) / h
        if not (0.30 <= cx <= 0.70 and 0.20 <= cy <= 0.85):
            continue
        if best is None or bw * bh > best[2] * best[3]:
            best = (x, y, bw, bh)
    if best is None:
        return None
    x, y, bw, bh = best
    inside = float(gray[y:y + bh, x:x + bw].mean())
    surround = gray.copy()
    surround[y:y + bh, x:x + bw] = 0
    outside = float(surround[surround > 0].mean()) if (surround > 0).any() else 0.0
    return best if outside < DIALOG_DIM_RATIO * inside else None


def _dialog_heading(image_path: Path) -> str:
    """The heading of a MODAL dialog ('high contrast', 'enter pin code'), or '' when the
    frame is not a dialog.

    The shared fingerprint only OCRs the TOP BAND (`_band_tokens`) and takes `title` from a
    narrow far-LEFT crop, so a modal's own heading never reaches it: every stb3 settings
    dialog therefore carries title='settings' (the page header behind it) and they all
    collapsed onto one node (2026-07-18). This reads the text the top band cannot see.

    Deliberately narrow so it stays EMPTY on content screens: a heading must be big
    (>= DIALOG_MIN_H of frame height — dialog headings render larger than the page title)
    AND horizontally centred. tvguide's programme names are small and left-aligned inside
    grid cells, so it yields '' there and those screens keep their title-only identity.
    Computed here rather than in image_helpers so FINGERPRINT_VERSION — and every Localize
    /verification consumer of it — is untouched."""
    image = cv2.imread(str(image_path))
    if image is None:
        return ""
    h, w = image.shape[:2]
    plate = _dialog_plate(image)
    if plate is None:
        return ""                       # not a modal -> no heading, identity unchanged
    px, py, pw, ph = plate
    x0 = px / w
    crop = image[py:py + int(ph * 0.55), px:px + pw]    # heading sits in the plate's top half
    if crop.size == 0:
        return ""
    helper = _image_helpers_class()(None, None)
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    # The dialog panel is a LIGHTER grey plate over a dimmed page. Threshold to the bright
    # plate text first: without it tesseract locks onto the dimmed page rows showing through
    # (the 'high contrast' heading OCR'd as nothing while background rows scored conf>90).
    # Then upscale, as _title_text does — tesseract is markedly better on enlarged glyphs.
    g = cv2.createCLAHE(2.5, (8, 8)).apply(g)
    _, g = cv2.threshold(g, 165, 255, cv2.THRESH_BINARY)
    scale = 2.0
    g = cv2.resize(g, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    lines: Dict[Any, List[Any]] = {}
    for row in helper._tesseract(g, "tsv").splitlines()[1:]:
        c = row.split("\t")
        if len(c) < 12:
            continue
        try:
            bx, by, bw, bh, conf = int(c[6]), int(c[7]), int(c[8]), int(c[9]), float(c[10])
        except ValueError:
            continue
        bx, bw, bh = bx / scale, bw / scale, bh / scale     # back to source-crop pixels
        tok = re.sub(r"[^0-9A-Za-zÀ-ÿ]", "", c[11]).lower()
        if conf < 60 or len(tok) < 2 or bh < DIALOG_MIN_H * h:
            continue
        lines.setdefault((c[2], c[3], c[4]), []).append((bx, bx + bw, bh, tok))
    best, best_h = "", 0.0
    for parts in lines.values():
        parts.sort()
        mid = (min(p[0] for p in parts) + max(p[1] for p in parts)) / 2.0
        mid_frac = (x0 * w + mid) / w
        if not (DIALOG_CENTER[0] <= mid_frac <= DIALOG_CENTER[1]):
            continue
        tall = max(p[2] for p in parts)
        if tall > best_h:
            best, best_h = " ".join(p[3] for p in parts), float(tall)
    return best[:48]


def _fingerprint(image_path: Path) -> Dict[str, Any]:
    image = cv2.imread(str(image_path))
    if image is None:
        raise LiveBuildError(f"Captured image is unreadable: {image_path}")
    fp = _image_helpers_class()(None, None).compute_fingerprint(image)
    if not fp or not fp.get("dhash"):
        raise LiveBuildError(f"Fingerprint failed for {image_path}")
    # Modal identity, which the shared fingerprint cannot express (see _dialog_heading).
    fp["modal"] = _dialog_plate(image) is not None
    fp["dialog"] = _dialog_heading(image_path) if fp["modal"] else ""
    if fp["modal"]:
        print(f"[@fingerprint] modal dialog={fp['dialog']!r}")
    return fp


def _fingerprint_bytes(raw: bytes) -> Dict[str, Any]:
    """Fingerprint raw image bytes WITHOUT writing a numbered capture — used by the dynamic-screen
    stability probe, whose second frame is throwaway."""
    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise LiveBuildError("Stability-probe image is unreadable")
    fp = _image_helpers_class()(None, None).compute_fingerprint(image)
    if not fp or not fp.get("dhash"):
        raise LiveBuildError("Stability-probe fingerprint failed")
    return fp


def _hamming(a: str, b: str) -> int:
    if not a or not b or len(a) != len(b):
        return 9999
    return (int(a, 16) ^ int(b, 16)).bit_count()


def _is_committed(focus: Dict[str, Any]) -> Optional[bool]:
    """On a commit strip, True when the underline sits on the BOLD/selected tab (a resting,
    content-bearing pane) vs a transient hover. None when the frame carries no selected_x
    (older fingerprints / non-strip screens) — callers then ignore the flag."""
    sx = (focus or {}).get("selected_x")
    if sx is None or focus.get("x") is None:
        return None
    return abs(float(focus["x"]) - float(sx)) <= 0.03


def _committed_flag_agrees(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """Two nav focuses agree on committed-status. When either lacks selected_x, don't veto."""
    ca, cb = _is_committed(a), _is_committed(b)
    return ca is None or cb is None or ca == cb


def _demote_ring_focus(fp: Dict[str, Any], depth: int) -> Dict[str, Any]:
    """Drop selected_x from a DEPTH-0 nav focus before it becomes a node.

    The root home ring does NOT reflow — each tab sits at a fixed underline x, so a tab's
    identity is its x alone. selected_x there is only hero-commit LAG (the hero art catches
    up to the focused tab a beat late; a dive-BACK leaves the tab you entered 'committed',
    a plain ring-hover leaves Home committed). That lag is NOT a navigational distinction:
    OK dives into the FOCUSED tab either way. Keeping selected_x split home_moviesseries into
    a committed node + an uncommitted phantom (home_moviesseries_2) that FORKED the RIGHT ring
    so _ring_order never closed -> empty ring -> validation goto-stormed and every reverse
    action set went source_unreachable (perf_depth1, 2026-07-18). Strips (depth>=1) KEEP
    selected_x — there tabs reflow and the committed flag IS the identity."""
    if depth != 0 or not fp:
        return fp
    f = (fp or {}).get("focus") or {}
    if f.get("kind") == "nav" and "selected_x" in f:
        fp = dict(fp)
        f = dict(f)
        f.pop("selected_x", None)
        fp["focus"] = f
    return fp


def _focus_agrees(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    a, b = a or {}, b or {}
    if a.get("kind") != b.get("kind"):
        return False
    if a.get("kind") == "nav":
        # 0.025, NOT 0.06: the stb3 icon cluster (settings gear x=0.895, profile person
        # x=0.932) sits only 0.037 apart, so 0.06 read profile as "still settings" — that
        # certified settings--RIGHT-->search on a retry double-press (2026-07-16 audit).
        # Measured same-item x jitter across estimators/frames is <=0.005.
        # Discriminate commit-strip states by the COMMITTED FLAG (is the underline on the
        # BOLD/selected tab?), NOT by the exact selected tab. A hover shares focus_x AND
        # title with its committed pane (ham=24, false-merged as no-op 2026-07-17) so they
        # must split — but "hover System while Profiles shows" and "hover System while Info
        # shows" are the SAME navigational state (RIGHT/LEFT/OK do the same thing), so keying
        # on exact selected_x blew hovers up O(tabs²) (29+ nodes climbing, 2026-07-17). The
        # committed flag splits hover-vs-committed while merging equivalent hovers → O(tabs).
        # Only enforced when both carry selected_x (older fingerprints don't).
        if not _committed_flag_agrees(a, b):
            return False
        return (abs(float(a.get("x") or 0) - float(b.get("x") or 0)) <= 0.025 and
                abs(float(a.get("width") or 0) - float(b.get("width") or 0)) <= 0.10)
    if a.get("kind") == "row":
        # A focused pane row is a POSITION (bar y) within the COMMITTED pane. The pane it
        # belongs to matters (a row in System vs a row in Profiles differ), so key on the
        # committed selected tab here — unlike hovers, a row IS a resting state on one pane.
        sa, sb = a.get("selected_x"), b.get("selected_x")
        if sa is not None and sb is not None and abs(float(sa) - float(sb)) > 0.03:
            return False
        return abs(float(a.get("y") or 0) - float(b.get("y") or 0)) <= 0.04
    if a.get("kind") == "button":
        # An accent chip (hero 'Watch') is CHROME: its text and position are stable while
        # the artwork behind it rotates. Fuzzy label equality absorbs OCR jitter; geometry
        # is a real fallback here (unlike box) because the chip does not ride content.
        la = str(a.get("label") or "").strip().lower()
        lb = str(b.get("label") or "").strip().lower()
        if la and lb and (la == lb or difflib.SequenceMatcher(None, la, lb).ratio() >= 0.8):
            return True
        return (abs(float(a.get("x") or 0) - float(b.get("x") or 0)) <= 0.08 and
                abs(float(a.get("y") or 0) - float(b.get("y") or 0)) <= 0.08)
    if a.get("kind") == "box":
        # Equal labels confirm the same focused element OUTRIGHT: a box focus is authored
        # from the DOM bbox (tile + caption, center low) on one side but CV-detected from
        # the highlight border (tile only, center high) on the other — the SAME focused
        # tile measures ~0.17 apart in y (stb3 apps/netflix, 2026-07-16), so geometry
        # across the two estimators false-negatives. UNEQUAL labels prove nothing: the CV
        # side OCRs garbage on non-text focus targets (stb3 search input read as
        # '( am 7 wh …'), so inequality falls through to geometry rather than vetoing.
        la = str(a.get("label") or "").strip().lower()
        lb = str(b.get("label") or "").strip().lower()
        if la and lb and la == lb:
            return True
        return (abs(float(a.get("x") or 0) - float(b.get("x") or 0)) <= 0.08 and
                abs(float(a.get("y") or 0) - float(b.get("y") or 0)) <= 0.08)
    return True


DIALOG_BODY_MAX = 24    # center-region ham above which two BOX-focused screens are different
                        # dialogs. Measured on the stb3 settings corpus (2026-07-18): the SAME
                        # dialog re-captured = 0 bits; DISTINCT dialogs = 41-104. 24 sits in that
                        # gap with ~17 bits of margin on the tight side.


def _region_ham(a: Dict[str, Any], b: Dict[str, Any], key: str) -> int:
    """Hamming distance between one named region of two fingerprints, or -1 when either
    side lacks it (older fingerprints predate `regions`; callers must treat -1 as
    'unknown' and never as evidence of difference)."""
    ra, rb = (a.get("regions") or {}), (b.get("regions") or {})
    if key not in ra or key not in rb:
        return -1
    return _hamming(ra[key], rb[key])


def _same_screen(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    fa, fb = a.get("focus") or {}, b.get("focus") or {}
    ka, kb = fa.get("kind"), fb.get("kind")
    # A (near-)pixel-identical frame IS the same screen, before any focus reasoning: the sibling
    # discriminator (the underline/highlight) is itself pixels — while DOM-authored focus sits up
    # to 0.036 off the CV detector on the SAME frame (ham=0, measured 2026-07-16), which no
    # geometry tolerance can absorb without also merging the 0.037-apart icon cluster.
    # EXCEPTION: two nav underlines at clearly different x CANNOT be the same screen no matter how
    # close the pixels — when the rotating hero COINCIDES across two captures, distinct siblings
    # measured ham=2 (home vs settings-focused, live 2026-07-17: the thin underline is nearly
    # invisible to the 16x16 dHash), which false-merged settings into home and desynced the DFS.
    # 0.06 is far beyond the 0.036 estimator skew, so real same-tab pairs always pass the gate.
    nav_contradiction = (fa.get("kind") == "nav" and fb.get("kind") == "nav"
                         and abs(float(fa.get("x") or 0) - float(fb.get("x") or 0)) > 0.06)
    if _hamming(a.get("dhash", ""), b.get("dhash", "")) <= 2 and not nav_contradiction:
        return True
    # NAV focus is the SIBLING discriminator and is strict both ways: same-title siblings sit
    # just 5-11 dHash bits apart, so disagreeing underlines => different sibling, and an
    # underline on exactly ONE side also vetoes — nav rows share one title ('q home tv'), so
    # title equality proves nothing there, and a CV-missed underline is exactly how
    # home_settings--RIGHT-->home_search FALSE-PASSED while the box sat on the unmapped
    # profile icon (2026-07-16).
    if ka == "nav" and kb == "nav":
        if not _focus_agrees(fa, fb):
            return False
    # ROW focus (a focused pane row) is strict both ways ON STATIC SCREENS, like nav:
    # same bar position in the same committed pane confirms; anything else (different
    # row / different pane / row vs nav) is a different state — this is what keeps
    # settings pane positions from merging back into the tab strip (2026-07-17). On a
    # DYNAMIC screen the bar rides content (the tvguide focused program cell moves with
    # channel/time), so a disagreement proves nothing and falls through to title.
    elif ka == "row" and kb == "row":
        if _focus_agrees(fa, fb):
            return True
        if not (a.get("dynamic") or b.get("dynamic")):
            return False
    elif (ka == "nav") != (kb == "nav") or (ka == "row") != (kb == "row"):
        return False
    # BOX focus confirms identity only through an equal non-empty label (same element
    # focused). Its GEOMETRY neither vetoes nor confirms: every measured box-vs-box
    # disagreement was estimator or content noise, not a different screen — DOM bbox vs CV
    # border on the SAME tile (dy~0.17), OCR garbage labels on the search input, tvguide's
    # box riding rotating program cells / the PiP (2026-07-16) — and near-position boxes on
    # DIFFERENT screens are just as possible. The one same-title-different-body case
    # (settings tabs) has NAV focus and is handled above + at the probe site
    # (_ok_entered_new_screen). Distinct box screens carry distinct titles, so the
    # dHash/title checks below still discriminate.
    elif ka == "box" and kb == "box":
        la = str(fa.get("label") or "").strip().lower()
        lb = str(fb.get("label") or "").strip().lower()
        if la and lb and la == lb:
            return True
        # A MODAL/dialog renders OVER a titled page, so its OCR title is the PAGE header
        # ('settings') for EVERY settings dialog — the dialog's own heading never becomes the
        # title. The title fallback at the bottom therefore merged the profile picker, the
        # HDMI-resolution chooser and the diagnostics panel into ONE node with 6 contradictory
        # BACK parents, which read as a "non-returnable dive" (2026-07-18). The dialog BODY is
        # the identity: same dialog re-captured = 0 bits of center-region drift, distinct
        # dialogs = 41-104. Veto here, BEFORE the title fallback.
        # Deliberately scoped to box-vs-box: the screens that genuinely need title-only
        # identity (home's rotating hero, tvguide's EPG) carry nav/row/none focus, not box,
        # so their dHash self-drift is untouched by this.
        if _region_ham(a, b, "center") > DIALOG_BODY_MAX:
            return False
    # BUTTON focus (accent chip, e.g. the hero 'Watch'): the chip is stable chrome, so an
    # agreeing chip confirms identity outright — this is what keeps the DOWN-from-nav state
    # ONE canonical node (home_watch) while the hero behind it rotates the full-frame dHash.
    # A disagreeing chip proves nothing (OCR/position noise) and falls through to title.
    elif ka == "button" and kb == "button":
        if _focus_agrees(fa, fb):
            return True
    if _hamming(a.get("dhash", ""), b.get("dhash", "")) <= 8:
        return True
    # dHash cannot separate these alone: a dynamic screen (live PiP/clock) drifts from ITSELF far
    # more than distinct siblings differ — home self-drifts ~80 bits, tvguide ~36, vs only 5-11
    # bits between siblings — so no single threshold works. An identical non-empty title confirms
    # the same screen for ANY focus kind, including dynamic content screens (tvguide, kind none).
    # NOTE: this deliberately also returns True for an OK that swaps a same-title body (settings
    # tabs). That is handled at the probe site (_ok_entered_new_screen), not here, because this
    # predicate is ALSO what keeps home/tvguide from splitting on revisit — see the probe loop.
    # A MODAL's heading is the explicit statement of which dialog this is, and the shared
    # fingerprint cannot see it (top-band OCR + far-left title crop), so every settings dialog
    # arrives here as title='settings'. Two DIFFERENT headings are two different screens —
    # checked before the title fallback, and independent of focus kind, because the CV often
    # reports focus 'none' on a dialog (the PIN pad is not a detected box), which is exactly
    # how 'high contrast' and 'enter pin code' merged past a box-scoped check (2026-07-18).
    # Screens with no dialog heading ('' — tvguide's small left-aligned cells, home) are
    # unaffected and keep their title-only identity.
    da = str(a.get("dialog") or "").strip()
    db = str(b.get("dialog") or "").strip()
    if da and db and not _titles_match(da, db):
        return False
    # Once EITHER side is a modal, the page title behind it says nothing about which dialog
    # this is, so the dialog BODY decides. This is scoped to modals rather than to box focus
    # because a dialog often reports focus 'none' and often has no heading text at all (the
    # profile picker is a bare list) — the box-scoped and heading-based checks each leave a
    # hole the other cannot close, and 'profile picker vs enter pin' fell through both.
    # Same dialog re-captured measures 0 bits here; distinct dialogs 41-104.
    if (a.get("modal") or b.get("modal")) and _region_ham(a, b, "center") > DIALOG_BODY_MAX:
        return False
    ta = re.sub(r"\W+", " ", str(a.get("title") or "").lower()).strip()
    tb = re.sub(r"\W+", " ", str(b.get("title") or "").lower()).strip()
    return _titles_match(ta, tb)


def _norm_title(fp: Dict[str, Any]) -> str:
    return re.sub(r"\W+", " ", str((fp or {}).get("title") or "").lower()).strip()


def _titles_match(ta: str, tb: str) -> bool:
    """Near-identity title equality, absorbing OCR glyph jitter.

    OCR reads decorative glyphs unstably — the search magnifier on the stb3 home nav row
    OCRs as 'q' on one frame and 'qq' on the next of the SAME screen ('q home tv' vs
    'qq home tv', anchor false-negative 2026-07-16; 'tv' also reads as 'iv' — one char
    in a 9-char title is ratio 0.889). On dynamic screens the title is the ONLY
    discriminator left (dHash self-drifts ~80 bits), so strict equality strands the
    anchor. 0.85 keeps real screens apart with huge margin: the closest DISTINCT titles
    in the stb3 corpus measure 0.556 ('recordings' vs 'settings'); observed same-screen
    jitter measures 0.889-0.947."""
    if not ta or not tb:
        return False
    return ta == tb or difflib.SequenceMatcher(None, ta, tb).ratio() >= 0.85


def _same_family(a: Dict[str, Any], b: Dict[str, Any], loose: int = 20) -> bool:
    """Same screen FAMILY (sibling), ignoring focus — decides sibling vs new-screen(leaf).

    Title is the primary signal: moving focus along a menu keeps the same screen title, while
    diving into a new screen changes it. The rotating hero/PiP makes the full-frame dHash
    unreliable on these menus, so dHash within a looser bound is only the fallback when a
    title is missing on either side.
    """
    ta, tb = _norm_title(a), _norm_title(b)
    if ta and tb:
        return _titles_match(ta, tb)
    return _hamming(a.get("dhash", ""), b.get("dhash", "")) <= loose


def _ok_entered_new_screen(node_fp: Dict[str, Any], result_fp: Dict[str, Any], key: str) -> bool:
    """True when OK committed a same-title content change on a STATIC source — the settings-tab case
    (focus parked on the tab strip, body swaps Profiles list -> Accessibility list, dHash gap ~40).

    _same_screen/_same_family match such frames by their shared title ("settings") and would call
    the OK a no-op (then an overlay), dropping it and stranding the device. But a STATIC screen does
    not drift (settings self-drift ~0 vs home ~80), so a dHash gap past the same-screen bound is a
    REAL new screen reached by OK — an explicit leaf. Gated on the source being static so dynamic
    screens (home/tvguide), whose dHash is noise and whose same-title OK is a genuine overlay, keep
    their existing title-based handling. The `dynamic` bit is stamped at capture time
    (_stamp_dynamic); reliable in the static direction, which is all this needs."""
    return (str(key).upper() == "OK"
            and not node_fp.get("dynamic")
            and _hamming(node_fp.get("dhash", ""), result_fp.get("dhash", "")) > 8)


def _ok_lateral_select(node_fp: Dict[str, Any], result_fp: Dict[str, Any], key: str) -> bool:
    """OK that SELECTS a tab on the SAME nav bar (settings tab commit) rather than diving
    into a new menu — so it stays at the SAME depth (a lateral sibling / new committed-pane
    state), it does NOT add a level.

    The discriminator (arbitrator's, verified on real frames 2026-07-17): an OK is a tab
    select iff BEFORE and AFTER both show a nav underline on the SAME-titled bar. A genuine
    dive loses the tab strip or changes the title — measured: settings tab commit stays
    nav/'settings'→nav/'settings' (lateral), while home→apps goes nav→box/'apps' and
    home→tvguide goes nav→row/'tv guide' (dives). Without this, _ok_entered_new_screen
    forced every tab commit to a depth+1 leaf, producing a tangled chain instead of a flat
    6-tab strip."""
    fa = node_fp.get("focus") or {}
    fb = result_fp.get("focus") or {}
    return (str(key).upper() == "OK"
            and fa.get("kind") == "nav" and fb.get("kind") == "nav"
            and _titles_match(_norm_title(node_fp), _norm_title(result_fp)))


def _is_home_menu(fp: Dict[str, Any]) -> bool:
    """Conservative live HOME recognition; avoids toggling an already-open HOME menu."""
    focus = fp.get("focus") or {}
    title = re.sub(r"\W+", " ", str(fp.get("title") or "").lower()).strip()
    return focus.get("kind") == "nav" and "home" in title


BLACK_FRAME_WAIT_S = 10        # extra settle when a capture is still a black/loading frame
BLACK_FRAME_RETRIES = 2
RECOVERY_SETTLE_S = 20         # home re-render is slow when climbing out of a heavy app (Netflix)
BACK_RETRIES = 2               # a keyboard/modal eats the 1st BACK; the 2nd returns to the parent
DYNAMIC_PROBE_WAIT_S = 0.5     # gap between the two stability frames that detect a dynamic screen
DYNAMIC_DRIFT_BITS = 8         # self-drift above this => screen is dynamic (dHash untrustworthy)
LATE_RENDER_WAIT_S = 3         # second look before re-pressing a press that read as "no effect"


def _stamp_dynamic(fp: Dict[str, Any], client: "MCPClient", run_dir: Path, state: Dict[str, Any],
                   *, host: str, device: str) -> Dict[str, Any]:
    """Tag fp['dynamic'] by re-grabbing the SAME screen after a short gap and measuring self-drift.
    A static screen (settings panel, frozen clock) reproduces its dHash exactly (~0 bits); a dynamic
    screen (home video tile + live rails ~80 bits, tvguide PiP ~36 bits) drifts well past the
    threshold. _same_screen trusts the dHash only between two static screens, so this bit is what
    lets an OK that swaps a settings tab read as a real new screen while home/tvguide stay one node.
    Skips black/loading frames (no stable image to compare)."""
    if _is_black_frame(fp):
        fp["dynamic"] = False
        return fp
    time.sleep(DYNAMIC_PROBE_WAIT_S)
    raw2 = _execute_capture(client, host=host, device=device, keys=[])
    fp2 = _fingerprint_bytes(raw2)
    fp["dynamic"] = _hamming(fp.get("dhash", ""), fp2.get("dhash", "")) > DYNAMIC_DRIFT_BITS
    return fp


def _is_black_frame(fp: Dict[str, Any]) -> bool:
    """A uniform (all-zero dHash) frame — a black/loading screen, e.g. an app still launching.
    Such a capture carries no real screen, so callers wait and re-grab instead of recording it."""
    dh = str(fp.get("dhash") or "")
    return bool(dh) and set(dh) <= {"0"}


def _settled_capture(client: "MCPClient", run_dir: Path, state: Dict[str, Any], prefix: str,
                     *, host: str, device: str, keys: List[str]) -> Tuple[str, Dict[str, Any]]:
    """Capture the post-key frame; if it is a black/loading screen (an app still launching) wait
    BLACK_FRAME_WAIT_S and re-grab the current frame, up to BLACK_FRAME_RETRIES, overwriting the
    same capture id. Returns (screenshot_path, fingerprint)."""
    raw = _execute_capture(client, host=host, device=device, keys=keys)
    cap_id = _next_id(state, "next_capture", prefix)
    shot, fp = _write_capture(run_dir, cap_id, raw, state)
    tries = 0
    while _is_black_frame(fp) and tries < BLACK_FRAME_RETRIES:
        tries += 1
        print(f"  [black frame] {shot} is a loading/black screen — waiting {BLACK_FRAME_WAIT_S}s "
              f"and recapturing ({tries}/{BLACK_FRAME_RETRIES})")
        time.sleep(BLACK_FRAME_WAIT_S)
        raw = _execute_capture(client, host=host, device=device, keys=[])
        shot, fp = _write_capture(run_dir, cap_id, raw, state)   # overwrite the same capture id
    _stamp_dynamic(fp, client, run_dir, state, host=host, device=device)
    return shot, fp


def _recover_position(client: "MCPClient", run_dir: Path, state: Dict[str, Any],
                      target: Dict[str, Any], stuck_id: str) -> str:
    """A dive did not reverse with BACK (e.g. OK launched an external app like Netflix, which
    swallows BACK). Climb out with a BOUNDED 3-rung ladder, exactly once per stuck step — no retry
    loop: rung 1 = the BACK the caller already tried and that failed; rung 2 = the HOME key; rung 3
    = MCP goto-home. Reset DFS position to the root and continue from home. Raises only if rung 3
    also fails. The recovery presses are NOT discovery, so they do not consume max_iterations
    (recorded with result 'recover', which _walk_steps excludes). Returns the root node id."""
    root = next(n for n in state["nodes"].values() if not n.get("path"))
    host, device = target["host_name"], target["device_id"]
    # rung 2: HOME key. Coming back from a heavy app (Netflix) the home re-render is slow, so give
    # it RECOVERY_SETTLE_S before deciding the key did not reach home (avoids a transitional frame
    # being read as "HOME key failed" and escalating to goto-home unnecessarily).
    _execute_capture(client, host=host, device=device, keys=["HOME"])
    time.sleep(RECOVERY_SETTLE_S)
    shot, fp = _settled_capture(client, run_dir, state, "recover", host=host, device=device, keys=[])
    via = "HOME"
    if not _is_home_menu(fp):
        # rung 3: MCP goto-home, same generous settle before the final verdict.
        client.goto_home(host, device, state["userinterface_name"])
        time.sleep(RECOVERY_SETTLE_S)
        shot, fp = _settled_capture(client, run_dir, state, "recover", host=host, device=device, keys=[])
        via = "goto-home"
        if not _is_home_menu(fp):
            raise LiveBuildError(
                f"Recovery from {stuck_id} failed: neither HOME key nor goto-home reached the HOME "
                f"menu; evidence kept at {shot}."
            )
    state["probes"].append({"source": stuck_id, "key": via, "result": "recover",
                            "target": root["node_id"], "screenshot": shot})
    print(f"{stuck_id}: BACK did not return (non-returnable dive) — recovered to HOME via {via}")
    return root["node_id"]


def _write_capture(run_dir: Path, capture_id: str, raw: bytes,
                   state: Optional[Dict[str, Any]] = None) -> Tuple[str, Dict[str, Any]]:
    path = run_dir / "captures" / f"{capture_id}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    shot = str(path.resolve())
    fp = _refine_button_focus(state, shot, _fingerprint(path))
    return shot, _refine_selection_focus(shot, fp)


BUTTON_FILL_MIN = 0.4   # measured on the stb3 hero 'Watch' chip: 0.58 focused vs 0.000 not

# Commit-strip signals (settings-style tab rows; measured live 2026-07-17):
# The SELECTED pane's tab renders BOLD WHITE while the others are gray — so
# (selected tab, focused tab) identifies every strip state: hovering a tab moves only
# the underline (content stays the selected pane), OK COMMITS it (bold + content swap),
# DOWN drops focus onto a pane ROW (wide red bar well below the nav band).
SEL_BAND = (0.06, 0.17)     # tab-text band (home row y~0.075-0.105, settings tabs ~0.13-0.155)
SEL_X_MAX = 0.85            # exclude the white clock / status icons on the right
SEL_BRIGHT = 220            # bold-white text threshold (unselected tabs are gray)
SEL_MIN_W, SEL_MAX_W = 20, 0.20   # a text run, not a stray glint / whole-band artifact
ROW_BAND_TOP = 0.20         # a focused-row bar lives BELOW the nav band
ROW_MIN_W = 0.25            # spans a table row (settings row bar measures ~0.60w)
ROW_MAX_H = 14              # a bar, not a tile/border


def _selected_tab_x(image) -> Optional[float]:
    """x-center (0..1) of the BOLD (selected) tab's text run in the tab band, or None."""
    h, w = image.shape[:2]
    band = cv2.cvtColor(image[int(SEL_BAND[0] * h):int(SEL_BAND[1] * h), :int(SEL_X_MAX * w)],
                        cv2.COLOR_BGR2GRAY)
    mask = (band > SEL_BRIGHT).astype(np.uint8)
    cols = mask.sum(axis=0)
    runs, start = [], None
    gap = 0
    for x in range(len(cols)):
        if cols[x] > 0:
            if start is None:
                start = x
            gap = 0
        elif start is not None:
            gap += 1
            if gap > 12:                       # word gaps stitch; tab gaps split
                runs.append((start, x - gap))
                start = None
    if start is not None:
        runs.append((start, len(cols) - 1))
    best = None
    for x0, x1 in runs:
        if not (SEL_MIN_W <= (x1 - x0) <= SEL_MAX_W * w):
            continue
        weight = int(cols[x0:x1 + 1].sum())
        if best is None or weight > best[0]:
            best = (weight, (x0 + x1) / 2.0 / w)
    return round(best[1], 3) if best else None


def _refine_selection_focus(screenshot: str, fp: Dict[str, Any]) -> Dict[str, Any]:
    """Commit-strip refinement (builder-local, production code untouched):

    - focus kind 'row': a wide accent bar BELOW the nav band = a focused pane row
      (settings 'Change connection type' measured y=0.29, width 0.60w) — the CV
      detector reads these frames as 'none', which let the cached family DOM stamp a
      nav focus on them and reconcile merged the state away (2026-07-17).
    - 'selected_x' on nav/row focus: the bold tab. Hover moves the underline while the
      content stays the SELECTED pane, and OK commits — without selected_x the
      pre-commit and post-commit frames share focus+title and false-merged
      (settings System: ham=24 yet judged no-op).
    """
    focus = fp.get("focus") or {}
    image = None
    if focus.get("kind") in (None, "none", "box"):
        image = cv2.imread(screenshot)
        if image is not None:
            h, w = image.shape[:2]
            red = _image_helpers_class()(None, None)._accent_mask(image)
            below = red[int(ROW_BAND_TOP * h):, :]
            bar = cv2.morphologyEx(below, cv2.MORPH_CLOSE,
                                   cv2.getStructuringElement(cv2.MORPH_RECT, (15, 3)))
            cnts, _ = cv2.findContours(bar, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            best = None
            for c in cnts:
                x, y, bw, bh = cv2.boundingRect(c)
                if bw < ROW_MIN_W * w or bh > ROW_MAX_H:
                    continue
                if best is None or bw > best[2]:
                    best = (x, y, bw, bh)
            if best is not None:
                x, y, bw, bh = best
                focus = {"kind": "row",
                         "x": round((x + bw / 2) / w, 2),
                         "y": round((int(ROW_BAND_TOP * h) + y + bh / 2) / h, 2)}
                fp["focus"] = focus
    if focus.get("kind") in ("nav", "row"):
        if image is None:
            image = cv2.imread(screenshot)
        if image is not None:
            sel = _selected_tab_x(image)
            if sel is not None:
                focus["selected_x"] = sel
    return fp


def _refine_button_focus(state: Optional[Dict[str, Any]], screenshot: str,
                         fp: Dict[str, Any]) -> Dict[str, Any]:
    """DOM-guided focus refinement — the hero action chip (home_watch) state.

    The CV focus estimator has no prior and misreads a focused hero chip every way at once
    (the red customer wordmark as a nav underline at x=0.123 — within nav tolerance of
    home's real 0.139 — a box riding the rotating hero, or nothing; 2026-07-16 corpus:
    3 bogus DOWN->root edges + 1 phantom node). The authored DOMs already DECLARE such
    chips (type='button' + bbox), so instead of hunting we check: a declared chip that is
    accent-FILLED in this frame is the real focus. The chip swaps gray->red at near-equal
    luminance, so the gray dHash layers cannot see the state (measured: 47-bit same-state
    region drift vs 35-bit across) while the accent mask reads 0.58 vs 0.000 — binary.
    The family-title guard means a frame from a DIFFERENT screen (a tvguide dive with red
    chrome of its own) can never false-fire; no OCR, no contour hunting, no new detector.
    """
    if not state or not fp or not fp.get("title"):
        return fp
    image = None
    seen_doms = set()
    for node in state.get("nodes", {}).values():
        dom_path = node.get("dom")
        if not dom_path or dom_path in seen_doms or not node.get("fingerprint"):
            continue
        seen_doms.add(dom_path)
        if not _titles_match(_norm_title(fp), _norm_title(node["fingerprint"])):
            continue
        dom = _load_json(Path(dom_path))
        for el in dom.get("focusable_elements") or []:
            bbox = el.get("bbox") or []
            if el.get("type") != "button" or len(bbox) != 4:
                continue
            if image is None:
                image = cv2.imread(screenshot)
                if image is None:
                    return fp
            h, w = image.shape[:2]
            x, y, bw, bh = [float(v) for v in bbox]
            crop = image[int(y * h):int((y + bh) * h), int(x * w):int((x + bw) * w)]
            if crop.size == 0:
                continue
            mask = _image_helpers_class()(None, None)._accent_mask(crop)
            fill = cv2.countNonZero(mask) / float(mask.size)
            if fill >= BUTTON_FILL_MIN:
                fp["focus"] = {
                    "kind": "button",
                    "x": round(x + bw / 2, 2),
                    "y": round(y + bh / 2, 2),
                    "label": str(el.get("label") or el.get("id") or "").lower(),
                }
                print(f"  [button focus] declared chip '{fp['focus']['label']}' is accent-filled "
                      f"({fill:.2f}) — overriding CV focus")
                return fp
    return fp


def _sanitize_label(value: str) -> str:
    label = re.sub(r"[^a-z0-9]+", "_", (value or "screen").lower()).strip("_")
    return label[:48] or "screen"


_ROLE_PREFIX = re.compile(r"^(nav|btn|button|tab|menu|item|card|tile|icon)_")
_ROLE_SUFFIX = re.compile(r"_(nav|btn|button|tab|menu|item|card|tile|icon)$")
_FILLER = {"screen", "page", "top", "navigation", "nav", "focused", "menu", "view",
           # prepositions/connectors: screen_summary is a sentence, and letting its 2nd
           # token into the 2-token base produced 'settingswith'/'recordingsshowing'
           "with", "showing", "using", "your", "of", "and", "to", "for", "in", "on", "a", "the"}


def _element_short(elem_id: str) -> str:
    """Focused-element id without its UI-role prefix/suffix OR internal underscores:
    nav_tv_guide -> tvguide, accessibility_tab -> accessibility (role words carry no user
    meaning — the arbitrator reads screen title + element only). '_' is reserved for the
    parent_child join in _derive_label."""
    e = (elem_id or "").strip().lower()
    e = _ROLE_SUFFIX.sub("", _ROLE_PREFIX.sub("", e))
    return (e or "el").replace("_", "")


def _screen_base(dom: Dict[str, Any]) -> str:
    """Short base name for a screen from its summary: filler words dropped, first 2 tokens, then
    underscores removed so the screen name is ONE token ('tv guide' -> 'tvguide'). The '_' is the
    parent_child separator only, so a screen/child name must never contain it."""
    toks = [t for t in _sanitize_label(dom.get("screen_summary") or "").split("_")
            if t and t not in _FILLER]
    return ("".join(toks[:2])
            or _sanitize_label(dom.get("screen_summary") or "").replace("_", "")
            or "screen")


def _derive_label(state: Dict[str, Any], node: Dict[str, Any], dom: Dict[str, Any]) -> str:
    """Readable name from the DOM + parent context (replaces summary+focused double-count).

    - root / screen (new family) -> the screen's own base (home; tv_guide; suchen_search)
    - focus sibling              -> "<subtree_family>_<element>"  (nav_search under home -> home_search)

    Sibling vs new-screen comes from the stored `kind` (set by family classification), NOT
    from the key. Falls back to the entry key only for older runs without `kind`.
    """
    focused_id = dom.get("focused_element_id") or ""
    focused_element = next(
        (e for e in dom.get("focusable_elements", []) if e.get("id") == focused_id), {}
    )
    # Asset titles are volatile and must never become navigation labels. A content screen has
    # category nodes plus at most one generic dynamic node. A BUTTON is exempt: its id is
    # stable chrome even when its OK plays rotating content (the hero 'Watch' -> home_watch).
    elem = ("content" if focused_element.get("ok_action") == "dynamic"
            and focused_element.get("type") != "button" else _element_short(focused_id))
    parent_id = entry_key = None
    for e in state["edges"]:
        if e["target"] == node["node_id"] and not e.get("reverse"):
            parent_id, entry_key = e["source"], e["key"]
            break
    kind = node.get("kind")
    if kind == "root" or not node.get("path"):       # root screen
        base = _screen_base(dom)
        return base if elem in (base, "home", "el") else f"{base}_{elem}"
    is_sibling = (kind == "sibling") if kind else (entry_key != "OK")
    if not is_sibling:                                # new screen (leaf)
        # The user-facing name of an OK-dive screen IS the menu item it was entered from
        # (home_settings -> settings) — that's what the arbitrator reads in the tree. The
        # vision pass's screen_summary is a SENTENCE, so its 2nd token leaked prepositions
        # into labels (settingswith, searchwith, recordingsshowing; 2026-07-16). The
        # summary stays the fallback for dives whose parent has no item name to inherit.
        parent_label = (state["nodes"].get(parent_id) or {}).get("label") or ""
        if entry_key == "OK" and "_" in parent_label:
            return parent_label.split("_", 1)[1].replace("_", "")
        return _screen_base(dom)
    # focus sibling: share the subtree's family base + this element
    family_node = state["nodes"].get(node.get("subtree_root")) or state["nodes"].get(parent_id)
    family = ((family_node or {}).get("label") or _screen_base(dom)).split("_")[0]
    return family if elem in (family, "el") else f"{family}_{elem}"


def _focus_from_dom(dom: Dict[str, Any]) -> Dict[str, Any]:
    """Convert sub-agent visual focus into the production fingerprint focus shape.

    The screenshot focus detector can be confused by red hero artwork.  Once the DOM has
    been visually reviewed, its focused bbox is the stronger sibling discriminator.
    """
    focused = dom.get("focused_element_id")
    element = next((e for e in dom.get("focusable_elements", [])
                    if e.get("id") == focused), None)
    bbox = (element or {}).get("bbox") or []
    if len(bbox) != 4:
        return {"kind": "none"}
    x, y, width, height = [float(v) for v in bbox]
    if (element or {}).get("type") in ("nav_item", "tab"):
        return {
            "kind": "nav",
            "x": round(x + width / 2, 3),
            "width": round(width, 3),
        }
    if (element or {}).get("type") == "button":
        return {
            "kind": "button",
            "x": round(x + width / 2, 2),
            "y": round(y + height / 2, 2),
            "label": str((element or {}).get("label") or "").lower(),
        }
    return {
        "kind": "box",
        "x": round(x + width / 2, 2),
        "y": round(y + height / 2, 2),
        "label": str((element or {}).get("label") or "").lower(),
    }


def _snap_focus_to_dom(dom: Dict[str, Any], capture_fp: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Re-point a REUSED family DOM's focused_element_id at THIS node's production focus.

    Siblings on one screen (the home nav row) share a single DOM and differ only by which element
    is focused. A cached DOM's focused_element_id came from a DIFFERENT capture, so inheriting it
    makes every sibling claim the same focus -> they become _same_screen and merge away (Bug B:
    the whole nav row collapses to one node). Instead we snap focus to the focusable element whose
    center is nearest this node's PRODUCTION focus. Content screens (focus kind none) have no
    geometric focus to snap, so their authored focus is kept. Returns a shallow copy.
    """
    prod = (capture_fp or {}).get("focus") or {}
    kind = prod.get("kind")
    if kind not in ("nav", "box", "button") or prod.get("x") is None:
        return dom
    px, py = float(prod["x"]), prod.get("y")
    best_id, best_d = None, 1e9
    for element in dom.get("focusable_elements") or []:
        bbox = element.get("bbox") or []
        if len(bbox) != 4 or not element.get("id"):
            continue
        element_is_nav = element.get("type") in ("nav_item", "tab")
        # Never snap a production nav highlight to a content box merely because their x centers
        # are close (TV Shop Categories and the first poster are a real example). Likewise, box
        # focus must not snap back onto the category row.
        if (kind == "nav") != element_is_nav:
            continue
        dist = abs((float(bbox[0]) + float(bbox[2]) / 2) - px)
        if kind in ("box", "button") and py is not None:
            dist += abs((float(bbox[1]) + float(bbox[3]) / 2) - float(py))
        if dist < best_d:
            best_id, best_d = element["id"], dist
    # Nav items sit ~0.1 apart, so a real hit is well inside 0.12; a far "nearest" means the
    # production focus did not land on a listed element -> keep the authored focus rather than
    # snapping to something wrong.
    if best_id is None or best_d > (0.12 if kind == "nav" else 0.25):
        return dom
    if best_id == dom.get("focused_element_id"):
        return dom
    snapped = dict(dom)
    snapped["focused_element_id"] = best_id
    return snapped


def _dom_job(run_dir: Path, node: Dict[str, Any]) -> None:
    output = run_dir / "dom" / f"{node['node_id']}.json"
    job = run_dir / "dom_jobs" / f"{node['node_id']}.json"
    if output.exists() or job.exists():
        return
    schema = {
        "screen_summary": "short screen name",
        "screen_type": "nav_row | content | overlay | app_launcher | keyboard | dialog | player | other",
        "focused_element_id": "id of the visibly focused element or null",
        "focus_confidence": 0.0,
        "focusable_elements": [{
            "index": 0, "id": "stable_snake_case", "type": "nav_item",
            "label": "short semantic label", "text_found": "exact visible text",
            "bbox": [0.0, 0.0, 0.0, 0.0], "focused": True, "confidence": 0.0,
            "ok_action": "screen | overlay | external | dynamic | activate",
        }],
        "navigation": {
            "stable_snake_case": {
                "LEFT": None, "RIGHT": None, "UP": None, "DOWN": None,
                "OK": "open", "BACK": "back",
            }
        },
    }
    _atomic_json(job, {
        "job_type": "codex_subagent_dom_analysis",
        "node_id": node["node_id"],
        "screenshot": node["screenshot"],
        "output": str(output.resolve()),
        "instructions": [
            "Inspect only this fresh screenshot; do not read fixtures or existing graph data.",
            "Write strict JSON to output using the supplied schema.",
            "Include only remote-focusable elements and normalized [x,y,w,h] boxes.",
            "Set focused_element_id from the visible highlight, not from prior expectations.",
            "Navigation values are another element id, 'open', 'back', or null.",
            "Every focusable element must have all LEFT/RIGHT/UP/DOWN/OK/BACK keys.",
            "Classify screen_type (the kind of screen this is).",
            "For EACH element set ok_action = what pressing OK on it does: 'screen' opens a new "
            "in-UI screen or category (navigable, BACK returns); 'overlay' opens an in-screen popup "
            "that keeps this screen's title; 'external' launches a SEPARATE app (Netflix, Disney+, "
            "...); 'dynamic' plays a content asset (a movie/show/recording tile -> a player); "
            "'activate' is a toggle/text-input with no navigation. On a content/browse screen, the "
            "category tabs (Discover/Movies/Series/...) are 'screen'. Represent all visible "
            "posters/assets as AT MOST ONE generic element named 'content' (or 'asset') with "
            "ok_action='dynamic'; never use movie/show/recording titles as element ids or labels. "
            "Explore categories, never individual dynamic content.",
        ],
        "schema_example": schema,
    })


# --------------------------------------------------------------------------------------
# Persistent DOM cache — author a screen's DOM ONCE ever; reuse it for any later node whose
# fingerprint matches (this run or a future run). Keyed by the captured fingerprint so the
# match uses the production focus (consistent across runs). Kills re-authoring the same
# screens, the multi-minute gaps, and the screensaver they trigger.
# --------------------------------------------------------------------------------------
def _dom_cache_dir(run_dir: Path) -> Path:
    d = run_dir.parent / "_dom_cache"           # shared across all runs under live_runs/
    d.mkdir(parents=True, exist_ok=True)
    return d


def _dom_cache_lookup(run_dir: Path, fp: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Family-keyed reuse: siblings on one screen share a single DOM and differ only by focus, so
    match by FAMILY (title-first) — not by focus — and return the MOST COMPLETE entry. A sibling
    thus reuses the full nav row instead of a truncated focus-specific capture; the caller snaps
    focused_element_id onto this node's production focus (_snap_focus_to_dom)."""
    idx = _dom_cache_dir(run_dir) / "index.json"
    if not fp or not idx.exists():
        return None
    best, best_n = None, -1
    for e in _load_json(idx):
        if not _same_family(e.get("fingerprint") or {}, fp):
            continue
        p = _dom_cache_dir(run_dir) / e["dom_file"]
        if not p.exists():
            continue
        dom = _load_json(p)
        n = len(dom.get("focusable_elements") or [])
        if n > best_n:
            best, best_n = dom, n
    return best


def _dom_cache_save(run_dir: Path, fp: Optional[Dict[str, Any]],
                    dom: Dict[str, Any], label: Optional[str]) -> None:
    """One DOM per screen FAMILY. If a same-family entry exists, upgrade it in place only when this
    capture is more complete (more focusable elements) — never add a second focus-specific copy,
    which is what fragmented the home nav row into truncated, mislabeled siblings."""
    if not fp:
        return
    d = _dom_cache_dir(run_dir)
    idx = d / "index.json"
    entries = _load_json(idx) if idx.exists() else []
    n_new = len(dom.get("focusable_elements") or [])
    new_summary = _sanitize_label(dom.get("screen_summary") or "")
    for e in entries:
        if _same_family(e.get("fingerprint") or {}, fp):
            existing = _load_json(d / e["dom_file"]) if (d / e["dom_file"]).exists() else {}
            # Only upgrade with a DOM of the SAME screen (matching screen_summary). Title-family
            # alone is too coarse — an overlay or a mis-assigned DOM can share the title yet be a
            # different screen; without this guard a larger wrong DOM (e.g. home content) silently
            # overwrites the canonical family entry and poisons every later lookup.
            same_screen_kind = (new_summary == _sanitize_label(existing.get("screen_summary") or ""))
            if same_screen_kind and n_new > len(existing.get("focusable_elements") or []):
                _atomic_json(d / e["dom_file"], dom)
                e["fingerprint"], e["label"] = fp, label
                _atomic_json(idx, entries)
            return
    fid = f"dom_{len(entries):04d}.json"
    _atomic_json(d / fid, dom)
    entries.append({"fingerprint": fp, "label": label, "dom_file": fid})
    _atomic_json(idx, entries)


def _validate_dom(dom: Dict[str, Any], source: Path) -> Dict[str, Any]:
    elements = dom.get("focusable_elements")
    navigation = dom.get("navigation")
    if not isinstance(elements, list) or not isinstance(navigation, dict):
        raise LiveBuildError(f"Invalid DOM {source}: focusable_elements/navigation missing")
    ids = {str(e.get("id")) for e in elements if e.get("id")}
    focused = dom.get("focused_element_id")
    # A read-only panel (stb3's settings > info diagnostics page) legitimately has NO focusable
    # control and therefore nothing focused. `None not in set()` is unconditionally true, so the
    # check below rejected that valid state and — because it RAISES — aborted the whole explore
    # round (rc=2, depth-2 cut short 2026-07-18). Accept the empty/none pairing explicitly.
    if focused is None and not ids:
        return dom
    if focused not in ids:
        raise LiveBuildError(f"Invalid DOM {source}: focused_element_id is not an element")
    for element_id in ids:
        nav = navigation.get(element_id)
        if not isinstance(nav, dict) or not DOM_KEYS.issubset(nav):
            raise LiveBuildError(f"Invalid DOM {source}: incomplete navigation for {element_id}")
        # Coerce instead of crash: weaker vision models (qwen fallback) leak the
        # ok_action vocabulary ('dynamic', 'screen', ...) into navigation targets.
        # OK-slot leakage means "pressing OK does something" -> 'open'; a leaked
        # directional target is unusable -> null. Log so DOM quality stays visible.
        for k, v in list(nav.items()):
            if v is not None and v not in ids and v not in ("open", "back"):
                nav[k] = "open" if k == "OK" else None
                print(f"  [dom sanitize] {source.name} {element_id}.{k}: "
                      f"coerced unknown target {v!r} -> {nav[k]!r}")
    return dom


def _auto_dom(run_dir: Path, node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Author a screen DOM inline via the shared vision generator (ladder B).

    Uses services/ai_exploration/dom_generator.generate_dom (schema v2: includes
    ok_action + screen_type). Returns the DOM dict, or None on ANY failure —
    caller then falls back to the manual sub-agent job file, so this path can
    never make the builder less capable than before it existed.
    """
    shot = node.get("screenshot")
    if not shot:
        return None
    img = Path(shot)
    if not img.is_absolute():
        img = run_dir / shot
    if not img.exists():
        print(f"  [dom AUTO] {node['node_id']}: screenshot missing ({img}) — falling back")
        return None
    try:
        gen_path = (Path(__file__).resolve().parents[4] / "backend_host" / "src" / "services" /
                    "ai_exploration" / "dom_generator.py")
        spec = importlib.util.spec_from_file_location("auto_build_dom_generator", gen_path)
        if not spec or not spec.loader:
            raise LiveBuildError(f"Cannot load dom generator: {gen_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.generate_dom(str(img))
    except Exception as exc:
        print(f"  [dom AUTO] {node['node_id']}: generation failed ({exc}) — "
              f"falling back to sub-agent job")
        return None


def _ingest_doms(run_dir: Path, state: Dict[str, Any]) -> int:
    count = 0
    used_labels = {n.get("label") for n in state["nodes"].values() if n.get("dom")}
    for node in state["nodes"].values():
        if node.get("dom") or node.get("terminal"):
            continue   # terminal external-app leaves are never entered, so they need no DOM
        path = run_dir / "dom" / f"{node['node_id']}.json"
        if not path.exists():
            # Reuse a previously-authored DOM for the same screen+focus if we have one cached;
            # only fall back to a (slow, token-heavy) sub-agent job on a genuine cache miss.
            capture_fp = node.get("capture_fp") or node.get("fingerprint")
            cached = _dom_cache_lookup(run_dir, capture_fp)
            if cached is not None:
                # Reuse the family DOM but swap focus to THIS sibling's element (keep DOM,
                # change focus) — so siblings stay distinct instead of all inheriting the
                # cached focus.
                cached = _snap_focus_to_dom(cached, capture_fp)
                _atomic_json(path, cached)
                print(f"  [dom CACHE HIT] {node['node_id']} — reused family DOM, "
                      f"focus snapped to {cached.get('focused_element_id')!r}")
            else:
                # Ladder B: genuine cache miss — author the DOM inline via the vision
                # model (dom_generator schema v2 carries ok_action/screen_type parity
                # with the sub-agent job). Falls back to the manual sub-agent file
                # handoff when disabled (init --no-auto-dom) or on any failure, so a
                # missing OPENAI key degrades to the old workflow instead of aborting.
                generated = _auto_dom(run_dir, node) if state.get("auto_dom", True) else None
                if generated is None:
                    _dom_job(run_dir, node)
                    continue
                _atomic_json(path, generated)
                print(f"  [dom AUTO] {node['node_id']} — authored inline via "
                      f"{(generated.get('_dom_meta') or {}).get('model', 'vision model')}")
        dom = _validate_dom(_load_json(path), path)
        base = _derive_label(state, node, dom)
        label, suffix = base, 2
        while label in used_labels:
            label, suffix = f"{base}_{suffix}", suffix + 1
        used_labels.add(label)
        node["label"] = label
        node["dom"] = str(path.resolve())
        # Fingerprint focus must stay in the CV estimator's coordinate system: live checks
        # compare CV-vs-stored, and the DOM-authored center sits up to 0.036 off the CV
        # reading of the SAME frame (nav has no label to bridge estimators — that skew
        # false-failed node_0009 at validation, 2026-07-16). Keep the captured CV focus;
        # the DOM value fills in only when the detector found nothing (red-artwork case).
        # 'row' included: a focused pane row must NEVER inherit the cached family DOM's
        # nav focus — that stamp is exactly what let reconcile merge pane states back
        # into the tab strip (settings, 2026-07-17).
        if (node["fingerprint"].get("focus") or {}).get("kind") not in ("nav", "box", "button", "row"):
            node["fingerprint"]["focus"] = _focus_from_dom(dom)
        focused = dom.get("focused_element_id")
        cand = [k for k in PROBE_ORDER
                if (dom.get("navigation", {}).get(focused) or {}).get(k)]
        print(f"  [dom generated] {node['node_id']} -> {path}")
        print(f"     label={label!r} focused={focused!r} "
              f"focusable={len(dom.get('focusable_elements', []))} "
              f"focus={node['fingerprint']['focus']} candidates={cand}")
        # Cache it (keyed by the CAPTURED fingerprint) so this screen is never authored again.
        _dom_cache_save(run_dir, node.get("capture_fp"), dom, label)
        count += 1
    if count:
        _reconcile_nodes(state)
    return count


def _collapse_settled_hovers(state: Dict[str, Any]) -> int:
    """Absorb SETTLED commit-strip hover nodes into compound <DIR>+OK edges, in-place, during
    exploration — so the frontier shrinks and the run converges instead of accreting reflow
    hover variants (a strip's tab x reflows with the bold tab, so 'hover Profiles while Info
    shows' and '…while Accessibility shows' are DIFFERENT content = different nodes; they pile
    up, 2026-07-17).

    A hover H (nav, underline NOT on the bold tab) whose OK lands on a committed pane C on the
    SAME titled bar is transient — replace P--DIR-->H--OK-->C with P--[DIR,OK]-->C and drop H.
    STRICTLY lateral (spares the home ring, whose OK dives). NEVER collapses the node the device
    is physically on (current / back_stack) — those are removed only once the DFS has moved on."""
    nodes, edges = state["nodes"], state["edges"]
    occupied = {state.get("current"), *(state.get("back_stack") or [])}

    def is_hover(nid):
        f = (nodes.get(nid, {}).get("fingerprint") or {}).get("focus") or {}
        return f.get("kind") == "nav" and _is_committed(f) is False

    def committed_pane(nid):
        f = (nodes.get(nid, {}).get("fingerprint") or {}).get("focus") or {}
        return f.get("kind") == "nav" and _is_committed(f) is True

    removed, new_edges = set(), []
    for H in list(nodes):
        if H in occupied or not is_hover(H):
            continue
        ok_out = [e for e in edges if e["source"] == H and not e.get("reverse") and e["key"] == "OK"]
        if len(ok_out) != 1:
            continue                                   # OK not probed yet — wait, don't drop it
        C = ok_out[0]["target"]
        if not (committed_pane(C) and _titles_match(_norm_title(nodes[H]["fingerprint"]),
                                                    _norm_title(nodes[C]["fingerprint"]))):
            continue
        inbound = [e for e in edges if e["target"] == H and not e.get("reverse")
                   and e["key"] in ("RIGHT", "LEFT", "DOWN", "UP")]
        for ib in inbound:
            if ib["source"] not in (H, C):
                new_edges.append({"source": ib["source"], "key": ib["key"],
                                  "keys": [ib["key"], "OK"], "target": C,
                                  "observed_capture": ok_out[0].get("observed_capture"),
                                  "strip": True})
        removed.add(H)

    if not removed:
        return 0
    state["edges"] = [e for e in edges
                      if e["source"] not in removed and e["target"] not in removed] + new_edges
    state["probes"] = [p for p in state["probes"]
                       if p.get("source") not in removed and p.get("target") not in removed]
    for H in removed:
        nodes.pop(H, None)
    return len(removed)


def _reconcile_nodes(state: Dict[str, Any]) -> None:
    """Merge observations that become identical after their sub-agent DOMs arrive."""
    node_ids = list(state["nodes"])
    replacements: Dict[str, str] = {}
    for i, left_id in enumerate(node_ids):
        if left_id in replacements or left_id not in state["nodes"]:
            continue
        left = state["nodes"][left_id]
        if not left.get("dom"):
            continue
        for right_id in node_ids[i + 1:]:
            if right_id in replacements or right_id not in state["nodes"]:
                continue
            right = state["nodes"][right_id]
            if not right.get("dom") or not _same_screen(left["fingerprint"], right["fingerprint"]):
                continue
            replacements[right_id] = left_id
            left["tried"] = list(dict.fromkeys([*left.get("tried", []),
                                                 *right.get("tried", [])]))
            if len(right.get("path", [])) < len(left.get("path", [])):
                left["path"] = right["path"]
            left["depth"] = min(left["depth"], right["depth"])
            left.setdefault("alternate_observations", []).append({
                "screenshot": right["screenshot"],
                "fingerprint": right["fingerprint"],
                "dom": right["dom"],
            })

    if not replacements:
        return
    for edge in state["edges"]:
        edge["source"] = replacements.get(edge["source"], edge["source"])
        edge["target"] = replacements.get(edge["target"], edge["target"])
    # A probe whose destination merged into its source was a same-state observation, not
    # a graph edge.  Keep the audit probe and remove the self edge.
    state["edges"] = [e for e in state["edges"] if e["source"] != e["target"]]
    for probe in state["probes"]:
        if probe.get("target") in replacements:
            probe["target"] = replacements[probe["target"]]
        if probe.get("source") in replacements:
            probe["source"] = replacements[probe["source"]]
        if probe.get("target") == probe.get("source"):
            probe["result"] = "no-op"
            probe["target"] = None
    # The physical-position pointers reference node ids too. A merge that removes the node the
    # device is currently AT (or a parent on the return stack) must follow it to the survivor,
    # or the next explore reads a ghost id and dead-stops on `if not node: break`.
    if state.get("current") in replacements:
        state["current"] = replacements[state["current"]]
    if state.get("back_stack"):
        remapped: List[str] = []
        for nid in (replacements.get(b, b) for b in state["back_stack"]):
            if not remapped or remapped[-1] != nid:   # collapse dupes two merged parents create
                remapped.append(nid)
        # A return point equal to where we now stand is no longer a parent to BACK to.
        if remapped and remapped[-1] == state.get("current"):
            remapped.pop()
        state["back_stack"] = remapped
    for old_id in replacements:
        state["nodes"].pop(old_id, None)


def _candidate_keys(node: Dict[str, Any]) -> List[str]:
    dom = _load_json(Path(node["dom"]))
    focused = dom.get("focused_element_id")
    nav = (dom.get("navigation") or {}).get(focused) or {}
    # Probe in PROBE_ORDER priority (OK dive first, then focus sweep). BACK/HOME are never
    # discovery probes — BACK returns to the parent, HOME is only the initial position.
    keys = [key for key in PROBE_ORDER if nav.get(key)]
    # DOWN from a nav-row item lands on the hero's action BUTTON (the red 'Watch') — stable
    # chrome, modeled as its own sibling (home_watch) via the 'button' focus kind, so it IS
    # probed. What is NOT a screen is the dynamic content zone one level further (rails of
    # rotating assets — measured live on stb3, 2026-07-16: content-dependent frames that
    # produced bogus edges and a phantom 'moviedetail' node). Any probe whose DECLARED
    # target element is a dynamic non-button (a card/tile of rotating assets) is dropped.
    # A nav-row item ALWAYS gets LEFT/RIGHT probes: a null row-neighbor in the authored map
    # means "the model didn't see one", not "no move" — profile.RIGHT=null left the stb3 home
    # ring OPEN, and chained certification lost its ring walk entirely (offline rebuild,
    # 2026-07-16). A genuine end-of-row press just records a harmless no-op.
    if (node.get("fingerprint", {}).get("focus") or {}).get("kind") == "nav":
        keys += [k for k in ("LEFT", "RIGHT") if k not in keys]
    elements = {e.get("id"): e for e in dom.get("focusable_elements") or []}

    def _dynamic_card(target_id):
        el = elements.get(target_id) or {}
        return el.get("ok_action") == "dynamic" and el.get("type") != "button"

    return [k for k in keys if not _dynamic_card(nav.get(k))]


def _focused_element(node: Dict[str, Any]) -> Dict[str, Any]:
    dom = _load_json(Path(node["dom"]))
    fid = dom.get("focused_element_id")
    return next((e for e in dom.get("focusable_elements", []) if e.get("id") == fid), {})


def _ok_action(node: Dict[str, Any]) -> str:
    """How OK behaves on this node's focused element, per the sub-agent's classification:
    'screen'   -> opens a child screen (real dive, depth+1)
    'overlay'  -> opens an in-screen popup that keeps the same title (skip, same screen)
    'external' -> launches a SEPARATE app (Netflix, Disney+, ...) (terminal leaf, never entered)
    'activate'/'' -> a toggle/input/no navigation.
    This makes overlay and app-launcher handling deterministic from the DOM — no fingerprint
    threshold, and no real press into a popup or external app (so no black frame / recovery)."""
    return str(_focused_element(node).get("ok_action") or "").lower()


def _focused_label(node: Dict[str, Any]) -> str:
    el = _focused_element(node)
    return str(el.get("label") or el.get("text_found") or el.get("id") or "app")


def _ancestor_chain(state: Dict[str, Any], node_id: str) -> List[str]:
    """root -> node_id list of node ids, following each node's unique observed parent edge."""
    chain, seen, cur = [node_id], {node_id}, node_id
    while True:
        parent = next((e["source"] for e in state["edges"]
                       if e["target"] == cur and e["source"] not in seen), None)
        if parent is None:
            break
        chain.append(parent); seen.add(parent); cur = parent
    return list(reversed(chain))


def _back_stack_for(state: Dict[str, Any], node_id: str) -> List[str]:
    """Reconstruct the DFS return stack for a node after a path-replay: the parent of each OK-dive
    (a 'screen'/'external' kind change) along its ancestor chain — exactly what BACK pops."""
    chain = _ancestor_chain(state, node_id)
    return [chain[i - 1] for i in range(1, len(chain))
            if state["nodes"][chain[i]].get("kind") in ("screen", "external")]


def _resolve_scope(state: Dict[str, Any], under: Optional[str]) -> Optional[List[str]]:
    """--under NODE -> the node ids of that node's subtree (itself + every node whose path
    extends its path). Accepts a label or a node_id. None = unscoped. This is what lets a
    later session deepen ONE subtree (settings, replay, ...) without re-walking the home
    ring: everything outside the scope is simply never probed or validated."""
    if not under:
        return None
    root_node = next((n for nid, n in state["nodes"].items()
                      if nid == under or str(n.get("label") or "").lower() == under.lower()), None)
    if root_node is None:
        known = ", ".join(sorted(str(n.get("label")) for n in state["nodes"].values()))
        raise LiveBuildError(f"--under {under!r} matches no node. Known labels: {known}")
    base = list(root_node.get("path") or [])
    return [nid for nid, n in state["nodes"].items()
            if list(n.get("path") or [])[:len(base)] == base]


def _in_scope(state: Dict[str, Any], nid: str) -> bool:
    scope = state.get("_scope")
    return scope is None or nid in scope


def _next_frontier(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """An authored, non-terminal, expandable node that still has untried candidate keys. Prefer the
    shortest path (cheapest replay). This is what lets one run cover subtrees the back-stack can no
    longer reach (e.g. stranded by an app-launch recovery). Honors the --under scope."""
    best = None
    for n in state["nodes"].values():
        if n.get("terminal") or not n.get("dom") or n["depth"] >= state["max_depth"]:
            continue
        if not _in_scope(state, n["node_id"]):
            continue
        if not [k for k in _candidate_keys(n) if k not in n.get("tried", [])]:
            continue
        if best is None or len(n.get("path", [])) < len(best.get("path", [])):
            best = n
    return best


def _self_anchor_home(client: "MCPClient", run_dir: Path, state: Dict[str, Any],
                      target: Dict[str, Any]) -> bool:
    """Reposition to the RUN'S OWN root using its captured fingerprint — no dependency
    on any pre-existing tree.

    The old goto_home anchored on the production tree's `home` node, whose reference
    (home_red.jpg) assumes focus is ON the Home nav item; the home screen keeps its
    last focus after a HOME keypress, so that goto fails with score 0.000 whenever
    focus sits elsewhere — blocking validation of a NEW graph on a defect in the OLD
    one. We hold the root fingerprint from init; anchor on that instead:
    HOME → check; HOME again (TV<->menu toggle) → check; BACK ladder → check.
    Falls back to the production goto only as a last resort.
    """
    host, device = target["host_name"], target["device_id"]
    root = next((n for n in state["nodes"].values() if not n.get("path")), None)
    root_fp = (root or {}).get("fingerprint")
    if not root_fp:
        return False

    # Focus-reset recipe from the run's OWN root DOM: HOME returns to the home screen
    # but keeps the last focus; the fingerprint focus-layer rightly rejects that. Flood
    # LEFT to the leftmost nav item, then RIGHT-step to the root's focused element —
    # both counts derived from the captured DOM, no layout knowledge hardcoded.
    focus_reset: List[str] = []
    try:
        dom = json.loads(Path(root["dom"]).read_text(encoding="utf-8")) if root.get("dom") else {}
        nav = dom.get("navigation") or {}
        focused = dom.get("focused_element_id")
        if focused and nav:
            leftmost, steps, seen = focused, 0, {focused}
            while nav.get(leftmost, {}).get("LEFT") and nav[leftmost]["LEFT"] not in seen:
                leftmost = nav[leftmost]["LEFT"]
                seen.add(leftmost)
            cur, k = leftmost, 0
            while cur != focused and k < len(nav):
                cur = nav.get(cur, {}).get("RIGHT")
                if not cur:
                    break
                k += 1
            if cur == focused:
                flood = min(len(nav) + 2, 12)
                focus_reset = ["LEFT"] * flood + ["RIGHT"] * k
    except Exception:
        pass

    attempts = [[], ["HOME"], ["HOME"], ["BACK", "BACK"]]
    if focus_reset:
        attempts.append(focus_reset)
    for keys in attempts:
        try:
            _shot, fp = _settled_capture(client, run_dir, state, "anchor",
                                         host=host, device=device, keys=keys)
            if _same_screen(root_fp, fp):
                return True
        except (LiveBuildError, OSError, ValueError):
            continue
    # No goto here: this IS the rescue for a failed goto (_replay_to runs goto first).
    return False


def _replay_to(client: "MCPClient", run_dir: Path, state: Dict[str, Any],
               target: Dict[str, Any], node: Dict[str, Any]) -> bool:
    """Physically reposition to `node`: reach the run's root, replay its path keys, verify
    arrival by fingerprint. Rooting order (arbitrator ruling 2026-07-16): the saved tree's
    goto-home FIRST (as it was), and on its failure the run's OWN root-fingerprint anchor
    as rescue — the rescue references nothing but this run's captured truth. Path keys only
    ever traverse in-UI screens (external tiles are terminal, never on a frontier path), so
    replay never launches an app. Returns True on verified arrival."""
    host, device = target["host_name"], target["device_id"]
    root = next((n for n in state["nodes"].values() if not n.get("path")), None)
    root_fp = (root or {}).get("fingerprint")
    # Validation exercises the CREATED artifact's own Entry->home recipe (--goto-ui);
    # rescue is FORBIDDEN there (arbitrator ruling 2026-07-16): the rescue masked an
    # absent/broken goto for a whole session at ~20s of anchor-ladder per edge — a
    # failed goto on the created UI is a certification finding, not noise to absorb.
    # Build/explore keeps the rescue as its PRIMARY anchor: the UI under construction
    # does not exist yet, so there is nothing of "what was created" to exercise.
    no_rescue = bool(state.get("_no_rescue"))
    goto_ok = False
    try:
        client.goto_home(host, device, state.get("_goto_ui") or state["userinterface_name"])
        time.sleep(SCREEN_SETTLE_MS / 1000.0)
        goto_ok = True
    except (LiveBuildError, OSError, ValueError) as exc:
        print(f"    goto_home FAILED ({str(exc)[:90]})"
              + (" — no rescue, unreachable" if no_rescue else " — self-anchor rescue"))
        if no_rescue:
            return False
    # A goto that RETURNS is not a goto that ARRIVED (poll-timeout returns normally):
    # always verify arrival at the root fingerprint with one keyless capture.
    if root_fp:
        if goto_ok:
            _shot, fp = _settled_capture(client, run_dir, state, "anchor",
                                         host=host, device=device, keys=[])
            if not _same_screen(root_fp, fp):
                if no_rescue:
                    print(f"    goto_home returned but did not arrive at root — no rescue, see {_shot}")
                    return False
                if not _self_anchor_home(client, run_dir, state, target):
                    return False
        elif not _self_anchor_home(client, run_dir, state, target):
            return False
    elif not goto_ok:
        return False
    # STEPWISE-VERIFIED replay: dead windows eat keys mid-path, and a blind RIGHTx5
    # ends up positions short with no way to tell. Every intermediate position along a
    # path is itself a node in the run (its fingerprint is known), so verify after each
    # key and re-press once on no-effect — same guard as explore/validate presses.
    by_path = {tuple(n.get("path") or []): n for n in state["nodes"].values()
               if n.get("fingerprint")}
    path = list(node.get("path") or [])
    for i, key in enumerate(path, 1):
        expected = by_path.get(tuple(path[:i]))
        _shot, fp = _settled_capture(client, run_dir, state, "replay",
                                     host=host, device=device, keys=[key])
        if expected is not None and not _same_screen(expected["fingerprint"], fp):
            prev = by_path.get(tuple(path[:i - 1]))
            # Eaten-press retries: bursts of consecutive eats are real (measured on the
            # BLE box); budget 2 re-presses per step, and LOG each so an unreachable
            # verdict is always explainable from the run log + saved frames.
            for r in (1, 2):
                if prev is None or not _same_screen(prev["fingerprint"], fp):
                    break   # not sitting on the previous position -> off-path, not an eat
                # A "no effect" reading can be a slow render racing the settle capture,
                # not an eaten press — IR never drops (fleet truth), and re-pressing a
                # press that DID land overshoots the sibling row (edge 3/19 2026-07-16:
                # RIGHT re-press walked home->apps past tvguide). Look again before
                # re-pressing; only a still-unmoved frame earns the re-press.
                time.sleep(LATE_RENDER_WAIT_S)
                _shot, fp = _settled_capture(client, run_dir, state, "replay",
                                             host=host, device=device, keys=[])
                if _same_screen(expected["fingerprint"], fp):
                    break   # the first press landed late; do not re-press
                if not _same_screen(prev["fingerprint"], fp):
                    break   # moved somewhere else entirely -> off-path, not an eat
                print(f"    replay step {i}/{len(path)} ({key}): no effect "
                      f"(still at {prev.get('label') or 'prev'}) — re-press {r}/2, see {_shot}")
                _shot, fp = _settled_capture(client, run_dir, state, "replay",
                                             host=host, device=device, keys=[key])
            if not _same_screen(expected["fingerprint"], fp):
                print(f"    replay ABORT at step {i}/{len(path)} ({key}): expected "
                      f"{expected.get('label') or '?'}, frame {_shot}")
                # A commit-strip pane path (…RIGHT, OK) strands here on the tab cache —
                # fall back to the bounded repeat_until-style re-anchor.
                return (_reanchor_strip(client, run_dir, state, target, node)
                        or _reanchor_row(client, run_dir, state, target, node))
    _shot, fp = _settled_capture(client, run_dir, state, "replay", host=host, device=device, keys=[])
    if bool(node.get("fingerprint")) and _same_screen(node["fingerprint"], fp):
        return True
    # Commit-strip pane / pane row: the rigid path replay strands on the tab (or row) cache;
    # fall back to the bounded repeat_until-style re-anchor (the way stb_tv navigates).
    return (_reanchor_strip(client, run_dir, state, target, node)
            or _reanchor_row(client, run_dir, state, target, node))


STRIP_WALK_MAX = 7      # bound on the repeat_until-style walk (stb3 has 6 settings tabs)


def _reanchor_strip(client: "MCPClient", run_dir: Path, state: Dict[str, Any],
                    target: Dict[str, Any], node: Dict[str, Any]) -> bool:
    """Re-anchor to a COMMITTED strip pane by a bounded repeat_until-style walk — the way
    stb_tv navigates — instead of the rigid exact-path replay that strands on the tab cache.

    The strip remembers its last committed tab, so entering settings lands on an arbitrary
    pane and the fixed 'RIGHT×n then OK' replay never arrives. Instead: enter the strip
    (family-loose), RIGHT to the CLAMPED end + OK, then LEFT+OK one tab at a time, checking
    the target fingerprint after each commit — up to STRIP_WALK_MAX. Builder-side (the pane
    isn't in the DB during a build, so the host's repeat_until-on-node can't be used)."""
    host, device = target["host_name"], target["device_id"]
    gf = (node.get("fingerprint") or {}).get("focus") or {}
    if gf.get("selected_x") is None or _is_committed(gf) is not True:
        return False                                     # only committed strip panes
    # strip root = the SHORTEST-path node on the same titled bar carrying selected_x
    root = None
    for n in state["nodes"].values():
        f = (n.get("fingerprint") or {}).get("focus") or {}
        if f.get("selected_x") is None or f.get("kind") != "nav":
            continue
        if _titles_match(_norm_title(n["fingerprint"]), _norm_title(node["fingerprint"])):
            if root is None or len(n.get("path") or []) < len(root.get("path") or []):
                root = n
    if root is None or not root.get("path"):
        return False
    parent = next((n for n in state["nodes"].values()
                   if list(n.get("path") or []) == list(root["path"])[:-1]), None)
    if parent is None or not _replay_to(client, run_dir, state, target, parent):
        return False
    _shot, fp = _settled_capture(client, run_dir, state, "strip",
                                 host=host, device=device, keys=[list(root["path"])[-1]])
    if not _same_family(root["fingerprint"], fp):
        print(f"    strip entry landed off-family — see {_shot}")
        return False
    # MOUNT the tab row: entering a strip can land with focus down in the pane ROWS (the row
    # cursor persists), where RIGHT/LEFT/OK navigate rows, not tabs — the walk then never returns
    # to a committed pane (settings landed on a 'Match frame rate' ROW, live 2026-07-17). UP mounts
    # the nav row (measured); press it until focus is a nav underline before walking tabs.
    for _ in range(ROW_WALK_MAX):
        if (fp.get("focus") or {}).get("kind") == "nav":
            break
        _shot, fp = _settled_capture(client, run_dir, state, "strip",
                                     host=host, device=device, keys=["UP"])
    if (fp.get("focus") or {}).get("kind") != "nav":
        print(f"    strip entry could not mount the tab row — see {_shot}")
        return False
    if _same_screen(node["fingerprint"], fp):
        return True
    # RIGHT to the clamped end (focus stops moving), then OK to commit it
    prevx = ((fp.get("focus") or {}).get("x"))
    for _ in range(STRIP_WALK_MAX):
        _shot, fp = _settled_capture(client, run_dir, state, "strip",
                                     host=host, device=device, keys=["RIGHT"])
        curx = (fp.get("focus") or {}).get("x")
        if curx is not None and prevx is not None and abs(float(curx) - float(prevx)) <= 0.01:
            break
        prevx = curx
    _shot, fp = _settled_capture(client, run_dir, state, "strip",
                                 host=host, device=device, keys=["OK"])
    if _same_screen(node["fingerprint"], fp):
        return True
    # walk LEFT+OK one pane at a time until the target committed pane matches
    for _ in range(STRIP_WALK_MAX):
        _shot, fp = _settled_capture(client, run_dir, state, "strip",
                                     host=host, device=device, keys=["LEFT", "OK"])
        if _same_screen(node["fingerprint"], fp):
            print(f"    strip re-anchor to {node.get('label')}: confirmed ({_shot})")
            return True
    print(f"    strip re-anchor to {node.get('label')}: not found in {STRIP_WALK_MAX} steps ({_shot})")
    return False


ROW_WALK_MAX = 12       # bound on the DOWN row-walk (settings System has ~7 rows)


def _reanchor_row(client: "MCPClient", run_dir: Path, state: Dict[str, Any],
                  target: Dict[str, Any], node: Dict[str, Any]) -> bool:
    """Re-anchor to a pane ROW state (focus kind 'row') by a bounded DOWN-walk — rows are the
    vertical mirror of the tab strip. Measured 2026-07-17: DOWN moves the row bar down
    (y 0.31→0.62) and CLAMPS at the bottom; the row carries selected_x (the committed pane
    behind it) and its bar y, both reflow-free — so identity is exact.

    Reach the row's committed PANE first (via the tab re-anchor), then press DOWN up to
    ROW_WALK_MAX, confirming each step by FULL-FRAME identity — the CV loses the row bar on
    ~95% of looks at these panes, so the bar's y is not a usable confirmation signal (see the
    loop). The stored `focus.y`/`selected_x` are still the walk's TARGET and its pane key."""
    host, device = target["host_name"], target["device_id"]
    gf = (node.get("fingerprint") or {}).get("focus") or {}
    if gf.get("kind") != "row" or gf.get("selected_x") is None or gf.get("y") is None:
        return False
    # the pane this row belongs to = the committed pane whose selected_x matches
    pane = None
    for n in state["nodes"].values():
        f = (n.get("fingerprint") or {}).get("focus") or {}
        if f.get("kind") == "nav" and _is_committed(f) is True \
                and abs(float(f.get("selected_x") or -9) - float(gf["selected_x"])) <= 0.03:
            pane = n
            break
    if pane is None or not _reanchor_strip(client, run_dir, state, target, pane):
        return False
    # DOWN from the pane (nav focus) until the target row bar y matches
    goal_y = float(gf["y"])

    # PREFERRED: dead-reckon the row INDEX and step exactly that far. Neither of the two
    # signals a walk could confirm on is trustworthy at these panes:
    #   - focus.y  — the CV loses the row bar on ~95% of looks (2026-07-19 depth-2 run: 35
    #                'row' vs 664 'none'), so a y-gated walk almost never confirms and burns
    #                its whole budget. This is where all 13 `source_unreachable` came from.
    #   - dHash    — sibling rows can be ~1 bit apart when a row change moves ONLY the bar
    #                (the System pane; the synthetic row_reanchor fixture models exactly this),
    #                so full-frame identity happily confirms on the WRONG row.
    # But the device behaviour IS deterministic and was measured: from the committed pane
    # (nav focus) each DOWN steps exactly one row and CLAMPS at the bottom. So the row's
    # position among its pane's known rows gives the press count outright — no confirmation
    # signal needed to GET there, only to sanity-check afterwards.
    pane_ys = sorted({round(float(((n.get("fingerprint") or {}).get("focus") or {}).get("y")), 3)
                      for n in state["nodes"].values()
                      if ((n.get("fingerprint") or {}).get("focus") or {}).get("kind") == "row"
                      and ((n.get("fingerprint") or {}).get("focus") or {}).get("y") is not None
                      and abs(float(((n.get("fingerprint") or {}).get("focus") or {})
                                    .get("selected_x", -9)) - float(gf["selected_x"])) <= 0.03})
    if round(goal_y, 3) in pane_ys:
        idx = pane_ys.index(round(goal_y, 3))
        _shot, fp = None, None
        for _ in range(idx + 1):                      # nav row (pos -1) -> row idx
            _shot, fp = _settled_capture(client, run_dir, state, "row",
                                         host=host, device=device, keys=["DOWN"])
        if fp is not None and _same_screen(node["fingerprint"], fp):
            print(f"    row re-anchor to {node.get('label')}: confirmed at index {idx} ({_shot})")
            return True
        # Landed but the frame disagrees — fall through to the bounded walk below rather than
        # trusting dead reckoning blind (the pane's row set may be only partly discovered).
        # Re-anchor first: the walk below assumes it starts on the committed pane, and we are
        # now `idx` rows into it.
        print(f"    row re-anchor to {node.get('label')}: index {idx} did not confirm — walking")
        if not _reanchor_strip(client, run_dir, state, target, pane):
            return False

    prev_y = prev_dhash = None
    for _ in range(ROW_WALK_MAX):
        _shot, fp = _settled_capture(client, run_dir, state, "row",
                                     host=host, device=device, keys=["DOWN"])
        f = fp.get("focus") or {}
        # Confirm by FULL-FRAME identity, NOT by the CV reporting a row. On stb3 settings panes
        # the row detector loses the bar on ~95% of looks (measured over the 2026-07-19 depth-2
        # run: 35 'row' vs 664 'none' across frames that DO sometimes report one), so gating the
        # confirmation on kind == 'row' failed the walk almost every time — it burned all
        # ROW_WALK_MAX steps and returned False, which is where all 13 `source_unreachable`
        # verdicts came from. Full-frame identity is safe for a pane row *here* because a row
        # change swaps the whole right-hand detail panel, not just a thin underline: the closest
        # sibling-row pair in this corpus is 7 dHash bits apart and 0 of 39 within-pane pairs
        # fall inside the <=2 same-screen bound, so _same_screen cannot confuse two rows.
        # (_same_screen already subsumes the old kind=='row' + y-match test: that test could only
        # confirm when it ALSO passed _same_screen, so goal_y is now just the walk's target.)
        if _same_screen(node["fingerprint"], fp):
            print(f"    row re-anchor to {node.get('label')}: confirmed ({_shot})")
            return True
        cy = f.get("y")
        if cy is not None and prev_y is not None and abs(float(cy) - float(prev_y)) <= 0.005:
            break                                    # clamped at the bottom, target not here
        # Clamp detection must ALSO work when the CV reports no focus: with kind='none' the y
        # test above is dead (cy is None), so a walk that had already hit the bottom kept
        # pressing DOWN into an unchanging screen for the full budget. An identical frame after
        # a DOWN means the bar cannot move any further.
        if prev_dhash is not None and _hamming(fp.get("dhash", ""), prev_dhash) == 0:
            break
        prev_y, prev_dhash = cy, fp.get("dhash")
    print(f"    row re-anchor to {node.get('label')}: not found in {ROW_WALK_MAX} steps ({_shot})")
    return False


def _ring_order(state: Dict[str, Any]) -> List[str]:
    """Sibling ring [node_id, ...] in RIGHT order among the depth-0 NAV tabs.

    Primary: follow the run's own observed RIGHT edges into a closed cycle. Fallback: when the
    RIGHT edges don't close (a stray/duplicate node, an unprobed RIGHT), the home row is still a
    wrapping ring whose tabs DON'T reflow, so order them by underline x — a POSITION order the
    stepwise-verified walk in _position_to confirms landing-by-landing anyway. A single broken
    RIGHT edge used to empty the ring, which crippled every reposition into a goto (2026-07-18)."""
    row = {nid: n for nid, n in state["nodes"].items()
           if n.get("fingerprint") and n.get("depth") == 0
           and ((n["fingerprint"].get("focus") or {}).get("kind") == "nav")}
    succ = {e["source"]: e["target"] for e in state["edges"]
            if e["key"] == "RIGHT" and e["source"] in row and e["target"] in row}
    if succ:
        start = next(iter(succ))
        ring, cur = [start], succ.get(start)
        while cur and cur != start and cur not in ring:
            ring.append(cur)
            cur = succ.get(cur)
        if cur == start and len(ring) == len(row):
            return ring
    # positional fallback: tabs are fixed-x on a wrapping ring
    return [nid for nid, _ in sorted(
        row.items(),
        key=lambda kv: float((kv[1]["fingerprint"].get("focus") or {}).get("x") or 0))]


def _identify_node(state: Dict[str, Any], fp: Dict[str, Any]) -> Optional[str]:
    """Which certified node is the device on right now? None when nothing matches."""
    for nid, n in state["nodes"].items():
        if n.get("fingerprint") and _same_screen(n["fingerprint"], fp):
            return nid
    return None


def _position_to(client: "MCPClient", run_dir: Path, state: Dict[str, Any],
                 target: Dict[str, Any], node: Dict[str, Any]) -> bool:
    """Chain-aware repositioning to `node` using ONLY certified artifacts — no rescue,
    no blind floods (the nav row is a RING: floods rotate, they never park; measured
    2026-07-16). One keyless capture identifies the current node by certified
    fingerprint; if it's already the goal we chained for free (the previous pass's
    verified end-state IS this edge's precondition). Otherwise walk the sibling ring
    stepwise-verified along the shorter direction, and pay the created UI's own
    Entry->home goto only when genuinely lost (dive screen / unidentifiable frame).
    Every miss is a loud failure."""
    host, device = target["host_name"], target["device_id"]
    goal = node["node_id"]
    ring = _ring_order(state)

    _shot, fp = _settled_capture(client, run_dir, state, "chain",
                                 host=host, device=device, keys=[])
    at = _identify_node(state, fp)
    if at == goal:
        return True
    if goal not in ring:
        # Off-ring goal (hero button / dive screen / pane row): the ring walk cannot reach it
        # and a goto would only waste ~10s before failing. Fail FAST so the caller routes to
        # _replay_to (non-reverse source) or the paired-forward re-establish (reverse action
        # set) — the localization/replay paths by which an off-ring node is actually reachable.
        return False

    for attempt in (1, 2):
        if at is None or at not in ring or goal not in ring:
            if attempt == 2:
                break
            try:
                client.goto_home(host, device,
                                 state.get("_goto_ui") or state["userinterface_name"])
                time.sleep(SCREEN_SETTLE_MS / 1000.0)
            except (LiveBuildError, OSError, ValueError) as exc:
                print(f"    goto_home FAILED ({str(exc)[:90]}) — no rescue, unreachable")
                return False
            _shot, fp = _settled_capture(client, run_dir, state, "chain",
                                         host=host, device=device, keys=[])
            at = _identify_node(state, fp)
            # Home has a third state: menu visible with focus DOWN in the content zone
            # (no underline) — entered by DOWN edges and sometimes by HOME itself. No
            # node matches it (siblings require their underline). UP mounts the nav row
            # deterministically (measured 2026-07-16), which turns the frame back into a
            # certified sibling. Two UPs max (hero zone -> row is one, rails need two).
            if at is None and ring:
                root_title = _norm_title(state["nodes"][ring[0]].get("fingerprint") or {})
                for _ in range(2):
                    if not _titles_match(_norm_title(fp), root_title):
                        break
                    _shot, fp = _settled_capture(client, run_dir, state, "chain",
                                                 host=host, device=device, keys=["UP"])
                    at = _identify_node(state, fp)
                    if at is not None:
                        break
            if at == goal:
                return True
            if at is None or at not in ring:
                why = ("unidentifiable frame" if at is None
                       else f"'{state['nodes'][at].get('label')}' is not on the sibling ring"
                            + (" (ring empty — row never closed)" if not ring else ""))
                print(f"    {why} after goto — no rescue, see {_shot}")
                return False
        if goal not in ring:
            print(f"    goal {goal} is off the sibling ring and unreachable by walking")
            return False
        # walk the shorter way around the ring, verifying each landing
        n = len(ring)
        i, j = ring.index(at), ring.index(goal)
        key, steps = (("RIGHT", (j - i) % n) if (j - i) % n <= (i - j) % n
                      else ("LEFT", (i - j) % n))
        ok = True
        for _step in range(steps):
            nxt = ring[(ring.index(at) + (1 if key == "RIGHT" else -1)) % n]
            _shot, fp = _settled_capture(client, run_dir, state, "chain",
                                         host=host, device=device, keys=[key])
            if not _same_screen(state["nodes"][nxt]["fingerprint"], fp):
                time.sleep(LATE_RENDER_WAIT_S)           # late render? look again
                _shot, fp = _settled_capture(client, run_dir, state, "chain",
                                             host=host, device=device, keys=[])
                if not _same_screen(state["nodes"][nxt]["fingerprint"], fp):
                    at = _identify_node(state, fp)        # drifted — re-anchor once
                    ok = False
                    break
            at = nxt
        if ok and at == goal:
            return True
    print(f"    positioning to {goal} failed after goto + verified walk")
    return False


def _jump_to_frontier(client: "MCPClient", run_dir: Path, state: Dict[str, Any],
                      target: Dict[str, Any], max_tries: int = 8) -> Tuple[Optional[str], List[str]]:
    """Reposition to the next unfinished frontier via path-replay so the run never blocks on a
    single stuck/awaiting-DOM node. Retires frontiers that prove unreachable. Returns
    (current_id, back_stack), or (None, []) when nothing reachable remains."""
    for _ in range(max_tries):
        frontier = _next_frontier(state)
        if frontier is None:
            return None, []
        if _replay_to(client, run_dir, state, target, frontier):
            print(f"replayed to {frontier['node_id']} "
                  f"(path {'+'.join(frontier.get('path') or []) or 'HOME'}) to continue")
            return frontier["node_id"], _back_stack_for(state, frontier["node_id"])
        f = state["nodes"][frontier["node_id"]]   # unreachable -> retire so we don't loop on it
        f["tried"] = list(dict.fromkeys([*f.get("tried", []), *_candidate_keys(f)]))
        print(f"replay to {frontier['node_id']} failed (unreachable); retired it")
    return None, []


def _new_state(args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mcp_url": args.mcp_url,
        "target": {
            "host_name": args.host,
            "device_id": args.device,
            "device_name": args.device_name,
        },
        "userinterface_name": args.ui_name,
        "max_depth": args.max_depth,
        # Global cap on total discovery keypresses (walk steps) across the whole run; 0 =
        # unlimited. Handy for tests: stop after 1-2 steps regardless of explore invocations.
        "max_iterations": args.max_iterations,
        "settle_ms": args.settle_ms,
        "auto_dom": not getattr(args, "no_auto_dom", False),
        "nodes": {},
        "edges": [],
        "probes": [],
        "next_node": 1,
        "next_capture": 1,
    }


def _next_id(state: Dict[str, Any], field: str, prefix: str) -> str:
    value = int(state[field])
    state[field] = value + 1
    return f"{prefix}_{value:04d}"


def _find_node(state: Dict[str, Any], fp: Dict[str, Any]) -> Optional[str]:
    for node_id, node in state["nodes"].items():
        if node.get("fingerprint") and _same_screen(node["fingerprint"], fp):
            return node_id   # terminal external nodes carry no fingerprint — never match
    return None


def _state_path(run_dir: Path) -> Path:
    return run_dir / "state.json"


def _save_state(run_dir: Path, state: Dict[str, Any]) -> None:
    _atomic_json(_state_path(run_dir), state)
    _write_report(run_dir, state)
    try:
        _emit_html_report(run_dir, state)
    except Exception as exc:  # a report glitch must never abort a live run
        print(f"(html report skipped: {exc})")


def _build_result(run_dir: Path, state: Dict[str, Any],
                  key_of: Dict[str, str]) -> Dict[str, Any]:
    """Adapt live probes into the offline builder `result` shape so html_report renders the
    same Walk + Steps sections. Per-step timing (t(s)) comes from the capture file mtimes —
    no schema change needed, and it works for old runs too. depth-skips sent no key, skipped."""
    caps = run_dir / "captures"

    def mtime(p: Optional[str]) -> Optional[float]:
        try:
            return os.path.getmtime(p) if p else None
        except OSError:
            return None

    all_t = [t for t in (mtime(str(caps / f)) for f in os.listdir(caps))
             if t] if caps.exists() else []
    t0 = min(all_t) if all_t else None

    def rel(shot: Optional[str]) -> Optional[float]:
        mt = mtime(shot)
        return round(mt - t0, 1) if (mt and t0) else None

    def clock(shot: Optional[str]) -> Optional[str]:
        mt = mtime(shot)
        return time.strftime("%H:%M:%S", time.localtime(mt)) if mt else None

    sent = [p for p in state["probes"] if p.get("result") != "depth-skip"]
    walk = []
    for p in sent:
        moved = p["result"] != "no-op"
        walk.append({
            "seq": len(walk) + 1, "key": p["key"],
            "from": key_of.get(p["source"], p["source"]),
            "to": (key_of.get(p["target"], p["target"]) if (moved and p.get("target"))
                   else "(no change)"),
            "moved": moved, "t": rel(p.get("screenshot")),
            "clock": clock(p.get("screenshot")),
            "shot": p.get("screenshot"),   # the inline frame returned by the action
        })
    order: List[str] = []
    by_src: Dict[str, List[Dict[str, Any]]] = {}
    for p in sent:
        by_src.setdefault(p["source"], []).append(p)
        if p["source"] not in order:
            order.append(p["source"])
    steps = []
    for si, src in enumerate(order, 1):
        ps = by_src[src]
        steps.append({
            "step": si, "node": key_of.get(src, src), "via": "",
            "t_start_s": rel(ps[0].get("screenshot")) or 0,
            "presses": len(ps),
            "new_nodes": sum(1 for p in ps if p["result"] == "new"),
            "transitions": [{"keys": p["key"],
                             "dst": (key_of.get(p.get("target"), p.get("target"))
                                     if p.get("target") else "(no change)"),
                             "new": p["result"] == "new"} for p in ps],
        })
    return {
        "walk": walk, "steps": steps, "presses": len(sent),
        "nodes": len(state["nodes"]), "edges": len(state["edges"]),
        "iterations": len(steps),
        "duration_ms": round((max(all_t) - t0) * 1000, 1) if (all_t and t0) else 0,
    }


def _emit_html_report(run_dir: Path, state: Dict[str, Any]) -> Path:
    """Render report.html using the offline graph_report.html_report renderer (reused, not
    reforked). We only ADAPT the live state into the node/edge shape it already expects:
    node['data'] = {screenshot, fingerprint, dom(dict), dom_image}; edge action_sets carry the
    key. Screenshots inline from captures/; the DOM-overlay column shows the rendered overlay
    when present (same placeholder behaviour as offline otherwise)."""
    gr = _graph_report()
    # Unique, readable display key per node (prefer the sub-agent label; node_id until DOM lands).
    key_of: Dict[str, str] = {}
    used: set = set()
    for nid, n in state["nodes"].items():
        base = n.get("label") or nid
        key, i = base, 2
        while key in used:
            key, i = f"{base}__{i}", i + 1
        used.add(key)
        key_of[nid] = key

    nodes: Dict[str, Dict[str, Any]] = {}
    for nid, n in state["nodes"].items():
        dom: Dict[str, Any] = {}
        dom_image = n.get("dom_image")
        if n.get("dom") and Path(n["dom"]).exists():
            dom = _load_json(Path(n["dom"]))
            # Draw the _dom.jpg from the DOM JSON we already have (reused production renderer),
            # so the report's DOM-overlay column is populated — not just a placeholder.
            overlay = run_dir / "dom_overlays" / f"{nid}_dom.jpg"
            if not overlay.exists() and n.get("screenshot") and Path(n["screenshot"]).exists():
                try:
                    _dom_overlay_fn()(n["screenshot"], dom, str(overlay))
                    print(f"  [dom image generated] {overlay}")
                except Exception as exc:
                    print(f"  (dom overlay skipped for {nid}: {exc})")
            if overlay.exists():
                dom_image = str(overlay)
                n["dom_image"] = dom_image  # persists on the next state save
        nodes[key_of[nid]] = {
            "node_id": key_of[nid], "label": key_of[nid], "node_type": "screen",
            "data": {
                "type": "external" if n.get("terminal") else "screen",
                "is_root": not n.get("path"), "depth": n.get("depth"),
                "screenshot": n.get("screenshot"),
                "fingerprint": n.get("fingerprint") or {},
                "dom": dom,
                "dom_image": dom_image,
            },
        }
    edges: Dict[str, Dict[str, Any]] = {}
    for i, e in enumerate(state["edges"]):
        s, t = key_of.get(e["source"]), key_of.get(e["target"])
        if not s or not t:
            continue
        edges[f"{s}__{t}__{i}"] = {
            "source_node_id": s, "target_node_id": t,
            "action_sets": [{"actions": [{"params": {"key": e["key"]}}]}],
        }

    root = next((key_of[nid] for nid, n in state["nodes"].items() if not n.get("path")), None)
    tree = gr.text_tree(nodes, edges, root=root or next(iter(nodes), ""))
    result = _build_result(run_dir, state, key_of)
    tgt = state["target"]
    title = (f"{tgt['device_name']} live build "
             f"({tgt['host_name']}/{tgt['device_id']} · {state.get('userinterface_name')})")
    html = gr.html_report(nodes, edges, str(run_dir / "captures"),
                          title=title, tree_text=tree, result=result,
                          dom_dir=str(run_dir / "dom_overlays"))
    out = run_dir / "report.html"
    out.write_text(html)
    return out


def _write_report(run_dir: Path, state: Dict[str, Any]) -> None:
    lines = [
        f"target: {state['target']['host_name']}/{state['target']['device_id']} "
        f"({state['target']['device_name']})",
        f"userinterface: {state.get('userinterface_name')}",
        f"max depth: {state['max_depth']}  ·  "
        f"max iterations: {state.get('max_iterations') or 'unlimited'}",
        f"nodes / observed edges / probes: {len(state['nodes'])} / "
        f"{len(state['edges'])} / {len(state['probes'])}",
        "",
        "NODES",
    ]
    for node in state["nodes"].values():
        lines.append(
            f"{node['node_id']:10} depth={node['depth']} "
            f"label={node.get('label') or '(awaiting DOM)'} path={'+'.join(node['path']) or 'HOME'}"
        )
    lines.extend(["", "OBSERVED EDGES"])
    for edge in state["edges"]:
        src = state["nodes"][edge["source"]]
        dst = state["nodes"][edge["target"]]
        lines.append(
            f"{src.get('label') or edge['source']} --{edge['key']}--> "
            f"{dst.get('label') or edge['target']}"
        )
    lines.extend(["", "PROBES"])
    for probe in state["probes"]:
        lines.append(
            f"{probe['source']} {probe['key']:5} {probe['result']:8} "
            f"{probe.get('target') or '-'}"
        )
    (run_dir / "report.txt").write_text("\n".join(lines) + "\n")


def cmd_init(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    state_path = _state_path(run_dir)
    if state_path.exists() and not args.force:
        raise LiveBuildError(f"Run already exists: {state_path}; use --force to replace it")
    if args.force and run_dir.exists():
        # Never recursively delete user data.  A force-init replaces only generated state;
        # old captures remain available for audit under their unique capture names.
        for sub in ("dom_jobs", "dom"):
            (run_dir / sub).mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    client = MCPClient(args.mcp_url, _find_auth(args.mcp_config), args.verify_tls)
    _validate_target(client, args.host, args.device, args.device_name)
    state = _new_state(args)

    # Reliable positioning, layered (arbitrator ruling 2026-07-16): the saved tree's
    # goto-home FIRST (as it was); if it fails (e.g. its reference was captured on a
    # different box variant — per-model reference caveat), fall back to checking the
    # CURRENT frame: if the box already shows a home menu (one HOME toggle allowed),
    # the precondition is met and the build proceeds self-contained.
    try:
        client.goto_home(args.host, args.device, state["userinterface_name"])
        time.sleep(SCREEN_SETTLE_MS / 1000.0)
    except LiveBuildError as exc:
        print(f"goto home failed ({str(exc)[:110]}) — checking current frame instead")
    screenshot, fp = _settled_capture(client, run_dir, state, "initial",
                                      host=args.host, device=args.device, keys=[])
    if not _is_home_menu(fp):
        _execute_capture(client, host=args.host, device=args.device, keys=["HOME"])
        time.sleep(SCREEN_SETTLE_MS / 1000.0)
        screenshot, fp = _settled_capture(client, run_dir, state, "initial",
                                          host=args.host, device=args.device, keys=[])
    if not _is_home_menu(fp):
        raise LiveBuildError(
            f"Not on a recognized HOME menu (goto failed and one HOME toggle didn't reach "
            f"one). Put the device on its home menu and re-run init; evidence at {screenshot}"
        )
    node_id = _next_id(state, "next_node", "node")
    fp = _demote_ring_focus(fp, 0)   # root ring: identity is underline x, not hero-commit lag
    state["nodes"][node_id] = {
        "node_id": node_id,
        "label": None,
        "kind": "root",
        "subtree_root": node_id,
        "depth": 0,
        "path": [],
        "screenshot": screenshot,
        "fingerprint": fp,
        "capture_fp": dict(fp),   # stable copy (production focus) — DOM-cache key

        "dom": None,
        "tried": [],
    }
    # Physical traversal state: we are AT the root, with an empty return stack. From here on
    # the device is moved only by probe keys and BACK — goto-home is never used again.
    state["current"] = node_id
    state["back_stack"] = []
    _dom_job(run_dir, state["nodes"][node_id])
    _save_state(run_dir, state)
    print(f"Initialized fresh live run at {run_dir}")
    print(f"Root screenshot: {screenshot}")
    print(f"DOM job: {run_dir / 'dom_jobs' / (node_id + '.json')}")
    return 0


def _walk_steps(state: Dict[str, Any]) -> int:
    """Discovery presses that count toward max_iterations. Excludes no-ops, depth-skips, and
    recovery climbs (BACK->HOME->goto-home) — recovery is overhead to get unstuck after a
    non-returnable dive, not forward exploration, so it must not consume the iteration budget."""
    return sum(1 for p in state["probes"]
               if p.get("result") not in ("no-op", "recover", "depth-skip"))


def cmd_explore(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    state = _load_json(_state_path(run_dir))
    if state.get("version") != STATE_VERSION:
        raise LiveBuildError(f"Unsupported state version: {state.get('version')}")
    ingested = _ingest_doms(run_dir, state)
    if ingested:
        print(f"Ingested {ingested} sub-agent DOM file(s)")

    # Scoped / deepened exploration: --under expands only ONE subtree; --max-depth raises
    # the run's depth cap (never lowers — shallower nodes are already final). Combined they
    # deepen e.g. settings to depth 4 without re-walking the home ring. Scope is
    # per-invocation: cleared when --under is absent.
    if getattr(args, "max_depth", 0):
        if args.max_depth > state["max_depth"]:
            print(f"max_depth {state['max_depth']} -> {args.max_depth}")
            state["max_depth"] = args.max_depth
    scope = _resolve_scope(state, getattr(args, "under", None))
    if scope is not None:
        state["_scope"] = scope
        print(f"scoped to {len(scope)} node(s) under {args.under!r}")
    else:
        state.pop("_scope", None)

    target = state["target"]
    client = MCPClient(
        state["mcp_url"], _find_auth(args.mcp_config), args.verify_tls
    )
    _validate_target(client, target["host_name"], target["device_id"], target["device_name"])
    actions_done = 0
    max_iter = state.get("max_iterations") or 0          # cap on walk steps (moves); 0 = off
    root = next((n for n in state["nodes"].values() if not n.get("path")), None)
    if not root:
        raise LiveBuildError("Run state has no root node")
    current_id = state.get("current") or root["node_id"]
    back_stack = list(state.get("back_stack") or [])

    while actions_done < args.max_actions:
        if max_iter and _walk_steps(state) >= max_iter:
            print(f"Reached max_iterations={max_iter} walk steps; stopping.")
            break

        node = state["nodes"].get(current_id)
        if not node:
            break
        # A non-expandable leaf (depth == max_depth) is only ever BACKed out of — it has no
        # candidate keys to read, so it needs no DOM (an app-launch leaf we recover from never
        # gets one). Only block on a missing DOM when the node is actually expandable.
        expandable = node["depth"] < state["max_depth"]
        if expandable and not node.get("dom"):
            # current is a cache-miss screen we can't explore inside without an authored DOM. Don't
            # block the whole run on that handoff — jump to another reachable frontier (the nav-row
            # sweep and app tiles are all cache hits / annotated). The dom_job remains pending for
            # optional later authoring of this screen's interior.
            actions_done += 1
            current_id, back_stack = _jump_to_frontier(client, run_dir, state, target)
            if current_id is None:
                break  # nothing else reachable; stop (pending DOM jobs remain for the user)
            state["current"], state["back_stack"] = current_id, back_stack
            _save_state(run_dir, state)
            continue

        # Next untried candidate — only while `current` is expandable. We dive exactly ONE
        # level: a node is expanded while depth < max_depth, so its OK reveals a depth+1
        # screen, but that screen is itself a non-expandable leaf (we don't go inside it).
        probe_key = None
        if expandable and _in_scope(state, current_id):
            # Skip OK ONLY on the home root (the depth-0 nav screen): OK on the focused home tab
            # just re-enters home, so we sweep the nav row first (RIGHT) and OK from a focused
            # sibling. Deeper content screen-roots (tvguide, apps, ...) are NOT skipped — there OK
            # is exactly the dive to the next depth (e.g. a tvguide program -> its detail screen).
            is_home_root = not node.get("path")
            for k in _candidate_keys(node):
                if k in node["tried"]:
                    continue
                if k == "OK" and is_home_root:
                    node["tried"].append(k)
                    continue
                probe_key = k
                break

        if probe_key is None:
            # `current` is exhausted / a non-expandable leaf -> BACK to the parent. goto-home is
            # used ONLY at init; the return path is the back-stack (OK pushed, BACK pops).
            if not back_stack:
                # Back-stack empty, but the tree may still hold stranded frontier nodes (a recovery
                # discards the stack; the nav-row sweep also lives behind already-tried edges).
                # Reposition to the nearest unfinished node via path-replay so ONE run can cover the
                # whole tree and consume its max_iterations. Replay/goto-home are not discovery, so
                # they don't count toward max_iterations (only the probes that follow do).
                actions_done += 1
                current_id, back_stack = _jump_to_frontier(client, run_dir, state, target)
                if current_id is None:
                    break  # genuinely nothing reachable left to explore
                state["current"], state["back_stack"] = current_id, back_stack
                _save_state(run_dir, state)
                continue
            parent_id = back_stack[-1]
            parent = state["nodes"][parent_id]
            # Some screens consume the first BACK on an in-screen dismiss rather than navigating:
            # a search screen opens an on-screen keyboard, so BACK #1 closes the keyboard (still on
            # the same screen) and BACK #2 actually returns to the parent. Verified live via MCP on
            # `suchen`. So press BACK up to BACK_RETRIES times, checking for the parent after each,
            # before treating the dive as non-returnable and recovering.
            shot = fp = None
            reached = False
            for attempt in range(BACK_RETRIES):
                raw = _execute_capture(client, host=target["host_name"],
                                       device=target["device_id"], keys=["BACK"])
                shot, fp = _write_capture(run_dir, _next_id(state, "next_capture", "back"), raw, state)
                if _same_screen(parent["fingerprint"], fp):
                    reached = True
                    break
                # If BACK landed us back on `current` (unchanged), it dismissed an in-screen layer
                # (the keyboard) — keep going. If it landed somewhere else entirely, stop retrying.
                if not _same_screen(state["nodes"][current_id]["fingerprint"], fp):
                    break
                # Late-render guard (mirrors the same guard in replay/validate): a BACK that
                # DID navigate but rendered after the settle capture reads as "still here", and
                # the extra BACK below gets baked into the reverse edge's key list. At VALIDATE
                # time that surplus BACK exits the menu root to live TV — settings/profile
                # flapped between 1 and 2 presses run-to-run this way (2026-07-18). Look again
                # before re-pressing; only a parent that STILL hasn't appeared earns a 2nd BACK.
                time.sleep(LATE_RENDER_WAIT_S)
                raw = _execute_capture(client, host=target["host_name"],
                                       device=target["device_id"], keys=[])
                shot, fp = _write_capture(run_dir, _next_id(state, "next_capture", "back"), raw, state)
                if _same_screen(parent["fingerprint"], fp):
                    reached = True
                    break
            if not reached:
                # BACK did not land on the parent — a non-returnable dive (e.g. an app launch that
                # swallows BACK). Recover to HOME (HOME key, then goto-home) and continue from root
                # instead of crashing.
                current_id = _recover_position(client, run_dir, state, target, current_id)
                back_stack = []
                actions_done += 1
                state["current"], state["back_stack"] = current_id, back_stack
                _save_state(run_dir, state)
                continue
            state["probes"].append({"source": current_id, "key": "BACK",
                                    "result": "back", "target": parent_id, "screenshot": shot})
            # This verified return IS the dive's backward direction — record it as a `reverse`
            # edge so the push pairs it into the DB edge's backward action set and validation
            # certifies it. Without this, every dive edge shipped with an empty backward set
            # even though BACK was exercised and fingerprint-checked right here (gap found by
            # the arbitrator on stb3_autobuild, 2026-07-16). `reverse` edges are invisible to
            # partition/layout (push skips them in _build_out) — they only fill action_sets[1].
            presses = attempt + 1
            if not any(e.get("reverse") and e["source"] == current_id and e["target"] == parent_id
                       for e in state["edges"]):
                state["edges"].append({"source": current_id, "key": "BACK",
                                       **({"keys": ["BACK"] * presses} if presses > 1 else {}),
                                       "target": parent_id, "observed_capture": shot,
                                       "reverse": True})
            print(f"{current_id} --BACK--> {parent_id}"
                  + (f" ({presses} presses)" if presses > 1 else ""))
            back_stack.pop()
            current_id = parent_id
            actions_done += 1
            state["current"], state["back_stack"] = current_id, back_stack
            _save_state(run_dir, state)
            continue

        # HYBRID CLASSIFICATION: consult the screen's authored DOM for what OK does on the focused
        # element, and handle overlays / external apps WITHOUT pressing — we never leave the menu,
        # so there is no popup to dismiss, no app launch, no black frame, and no recovery.
        if probe_key == "OK":
            action = _ok_action(node)
            if action == "overlay":
                node["tried"].append("OK")
                state["probes"].append({"source": current_id, "key": "OK", "result": "no-op",
                                        "target": None, "screenshot": None})
                _save_state(run_dir, state)
                print(f"{current_id} --OK--> overlay per DOM ('{_focused_label(node)}'); skipped")
                continue
            if action == "dynamic":
                # The focused node already represents the screen's one generic content/asset
                # target. Do not add a second terminal child for OK; that produced pairs such as
                # replay_content -> content and let volatile asset titles leak into the graph.
                node["tried"].append("OK")
                actions_done += 1
                state["probes"].append({"source": current_id, "key": "OK", "result": "dynamic",
                                        "target": None, "screenshot": None})
                _save_state(run_dir, state)
                print(f"{current_id} --OK--> dynamic content skipped (node is the terminal content target)")
                continue
            if action == "external":
                # Terminal, never entered: 'external' launches a separate app (Netflix), 'dynamic'
                # apps do not belong in the navigation graph and do not BACK cleanly, so record the
                # terminal app edge without launching it.
                node["tried"].append("OK")
                actions_done += 1
                lbl = _focused_label(node)
                term_id = _next_id(state, "next_node", "node")
                state["nodes"][term_id] = {
                    "node_id": term_id, "label": _sanitize_label(lbl) or action,
                    "kind": action, "subtree_root": term_id, "depth": node["depth"] + 1,
                    "path": [*node["path"], "OK"], "screenshot": None, "fingerprint": None,
                    "capture_fp": None, "dom": None, "tried": [], "terminal": True,
                    "external_app": lbl,
                }
                state["edges"].append({"source": current_id, "key": "OK", "target": term_id,
                                       "observed_capture": None})
                state["probes"].append({"source": current_id, "key": "OK", "result": action,
                                        "target": term_id, "screenshot": None})
                _save_state(run_dir, state)
                print(f"{current_id} --OK--> launches external app '{lbl}' (terminal, not entered)")
                continue

        # We are physically AT `current` (DFS keeps us in sync) — press the probe key directly.
        # No reposition, no goto-home. Black/loading frames (an app launching) wait and recapture.
        screenshot, fp = _settled_capture(client, run_dir, state, "capture",
                                          host=target["host_name"], device=target["device_id"],
                                          keys=[probe_key])
        node["tried"].append(probe_key)
        actions_done += 1

        # Press-verify-retry: the UI app has input-dead windows (screensaver kicking in,
        # occasional app reload — observed live 2026-07-16 as an EN→DE language flip with
        # a press that never took effect). The key is delivered fine (transport ACKs);
        # the app just wasn't listening. If the frame is unchanged, retry ONCE so a dead
        # window doesn't get recorded as a structural no-op (which silently prunes real
        # siblings/dives from the graph). A genuine dead key stays a no-op on the retry.
        if _same_screen(node["fingerprint"], fp):
            # First: LOOK AGAIN without pressing — a slow render means the press DID act
            # and re-pressing would move twice (corrupting the edge as a 2-step jump).
            time.sleep(SCREEN_SETTLE_MS / 1000.0)
            screenshot, fp = _settled_capture(client, run_dir, state, "capture",
                                              host=target["host_name"], device=target["device_id"],
                                              keys=[])
            if _same_screen(node["fingerprint"], fp):
                # Still unchanged after a generous second look → the press fell into an
                # input-dead window (screensaver / app reload — observed live 2026-07-16
                # as an EN→DE language flip with a press that never took effect). The key
                # is delivered fine (transport ACKs); the app wasn't listening. Re-press
                # once; a genuinely dead key stays a no-op on the retry.
                print(f"    frame unchanged after {probe_key} (late-render ruled out) — "
                      f"input-dead window suspected, re-pressing once")
                screenshot, fp = _settled_capture(client, run_dir, state, "capture",
                                                  host=target["host_name"], device=target["device_id"],
                                                  keys=[probe_key])
                actions_done += 1

        print(f"[probe] {current_id} --{probe_key}-->  dhash={fp.get('dhash','')[:12]}… "
              f"focus={fp.get('focus')} title={fp.get('title')!r}")

        # An OK on a tab strip SELECTS a tab (lateral, same depth) when before & after share
        # the same nav bar; only otherwise does a same-title static OK enter a new screen.
        # lateral wins: it makes the settings tabs a FLAT sibling strip, not a depth chain.
        lateral = _ok_lateral_select(node["fingerprint"], fp, probe_key)
        ok_new_screen = _ok_entered_new_screen(node["fingerprint"], fp, probe_key) and not lateral

        if _same_screen(node["fingerprint"], fp) and not ok_new_screen:
            state["probes"].append({"source": current_id, "key": probe_key,
                                    "result": "no-op", "target": None, "screenshot": screenshot})
            _save_state(run_dir, state)
            print(f"{current_id} --{probe_key}--> no change")
            continue

        # Classify by FINGERPRINT FAMILY (not the key): same family = focus sibling, same depth
        # & subtree; different family = a new screen (leaf), one level deeper, its own subtree.
        # An OK that entered a new static screen is always a leaf (never a focus sibling/overlay).
        # NOTE: this is a guess from the frame alone. When the probe lands on an ALREADY-KNOWN
        # node it is overridden below by that node's recorded classification, which is authoritative.
        is_sibling = (_same_family(node["fingerprint"], fp) and not ok_new_screen) or lateral

        # An OK that stays in the SAME family did not navigate to a child screen — it opened an
        # in-screen overlay/popup that keeps the parent's title (e.g. the tvguide program options
        # with its 'live schauen' button). By design we treat that as the same screen and do NOT
        # branch a node into it. The device is now physically ON the overlay, so dismiss it with
        # BACK to restore position at `current`, record a no-op, and move on.
        # A lateral tab SELECT is a real new state we keep (a committed pane) — it is NOT an
        # overlay to dismiss. Only a same-family OK that ISN'T a tab select is the tvguide-
        # style popup we back out of.
        if probe_key == "OK" and is_sibling and not lateral:
            raw_back = _execute_capture(client, host=target["host_name"],
                                        device=target["device_id"], keys=["BACK"])
            bshot, bfp = _write_capture(run_dir, _next_id(state, "next_capture", "back"), raw_back, state)
            if not _same_screen(node["fingerprint"], bfp):
                _save_state(run_dir, state)
                raise LiveBuildError(
                    f"OK on {current_id} opened a same-family overlay that BACK did not dismiss "
                    f"back to the screen; evidence kept at {bshot}."
                )
            state["probes"].append({"source": current_id, "key": "OK", "result": "no-op",
                                    "target": None, "screenshot": screenshot})
            _save_state(run_dir, state)
            print(f"{current_id} --OK--> same-family overlay; dismissed with BACK (skipped)")
            continue
        existing = _find_node(state, fp)
        if existing:
            target_id, result = existing, "existing"
            # A node we have ALREADY classified is not re-classified from the frame heuristic:
            # trust what it was recorded as. `is_sibling` is a guess derived from family/dHash,
            # and it disagrees with the record whenever a screen is reachable by more than one
            # key — on stb3 a settings pane row is activated by RIGHT (its '>' chevron) exactly
            # as by OK, but `_ok_entered_new_screen` is gated on key == "OK", so the RIGHT
            # landing read as a same-family SIBLING while the node itself was recorded a
            # depth-2 SCREEN by the OK that discovered it. The sibling reading skips the
            # back_stack push below, leaving `current` on the child with back_stack[-1] still
            # pointing at a stale ancestor — the next BACK "did not return" and burned a ~90s
            # goto-home. That was the sole cause of every non-returnable dive measured on
            # 2026-07-19 (3 in depth2_settings_0719_0022, 1 in _0117), and it is NOT specific to
            # modals: the frame need not carry a dialog plate (profiles2: modal=False).
            known = state["nodes"][target_id]
            known_dive = (known.get("kind") == "screen"
                          and int(known.get("depth") or 0) > int(node.get("depth") or 0))
            if known_dive and is_sibling:
                print(f"  [dive] {probe_key} reaches {target_id} — recorded as a depth-"
                      f"{known.get('depth')} screen, not a focus sibling; pushing a return point")
            is_sibling = not known_dive
        else:
            target_id = _next_id(state, "next_node", "node")
            if is_sibling:
                kind, ndepth, subtree = "sibling", node["depth"], node.get("subtree_root") or current_id
            else:
                kind, ndepth, subtree = "screen", node["depth"] + 1, target_id
            nfp = _demote_ring_focus(fp, ndepth)   # root ring: drop hero-commit lag (see helper)
            state["nodes"][target_id] = {
                "node_id": target_id, "label": None, "kind": kind,
                "subtree_root": subtree, "depth": ndepth,
                "path": [*node["path"], probe_key], "screenshot": screenshot,
                "fingerprint": nfp, "capture_fp": dict(nfp), "dom": None, "tried": [],
            }
            # DOM is resolved by _ingest_doms (cache hit = instant reuse; miss = sub-agent job).
            result = "new"
            print(f"  [new node] {target_id} {kind} depth={ndepth}")

        # The nav row KEEPS LAST FOCUS (stb3 truth): UP from a hero-chip state (button focus)
        # returns to WHICHEVER sibling you came DOWN from — validated live 2026-07-17 when
        # `watch --UP--> home` false-failed after a DOWN from tvguide. So UP from a button
        # state is never a forward edge to one node: it is the BACKWARD direction of every
        # `sibling --DOWN--> chip` pair (recorded below with the DOWN), same shape as
        # dive-BACK. A DOWN into a button state likewise records its paired reverse UP.
        src_button = (node.get("fingerprint", {}).get("focus") or {}).get("kind") == "button"
        tgt_button = (state["nodes"][target_id].get("fingerprint") or {}).get("focus", {}).get("kind") == "button"

        def _pair_reverse(src, tgt, key):
            if not any(e.get("reverse") and e["source"] == src and e["target"] == tgt
                       for e in state["edges"]):
                state["edges"].append({"source": src, "key": key, "target": tgt,
                                       "observed_capture": screenshot, "reverse": True})

        if probe_key == "UP" and src_button:
            _pair_reverse(current_id, target_id, "UP")     # measured pair (entered from target)
        else:
            state["edges"].append({"source": current_id, "key": probe_key, "target": target_id,
                                   "observed_capture": screenshot})
            if probe_key == "DOWN" and tgt_button:
                _pair_reverse(target_id, current_id, "UP")  # paired reverse; certified at validate
        state["probes"].append({"source": current_id, "key": probe_key,
                                "result": result, "target": target_id, "screenshot": screenshot})
        # Advance physical position: a focus sibling just moves us onto it (same screen); an
        # OK-dive into a new family pushes a return point (BACK pops it later).
        if not is_sibling:
            back_stack.append(current_id)
        current_id = target_id
        state["current"], state["back_stack"] = current_id, back_stack
        _save_state(run_dir, state)
        print(f"{node['node_id']} --{probe_key}--> {target_id} ({result})")
        if result == "new":
            break  # wait for the new node's DOM (handoff)

    _ingest_doms(run_dir, state)
    dropped = _collapse_settled_hovers(state)      # shrink the frontier: absorb settled tab hovers
    if dropped:
        print(f"[strip] collapsed {dropped} settled tab-hover node(s) into DIR+OK edges")
    _save_state(run_dir, state)
    return _print_status(run_dir, state)


def _print_status(run_dir: Path, state: Dict[str, Any]) -> int:
    waiting = [n["node_id"] for n in state["nodes"].values()
               if not n.get("dom") and not n.get("terminal")]
    remaining = []
    for node in state["nodes"].values():
        if not node.get("dom"):
            continue
        if node["depth"] >= state["max_depth"]:   # non-expandable leaf (we don't go inside it)
            continue
        if not _in_scope(state, node["node_id"]):  # scoped run: out-of-scope frontiers don't count
            continue
        keys = [k for k in _candidate_keys(node) if k not in node["tried"]]
        if keys:
            remaining.append({"node": node["node_id"], "keys": keys})
    max_iter = state.get("max_iterations") or 0
    steps = _walk_steps(state)             # same counter the explore cap uses (excludes recovery)
    capped = bool(max_iter and steps >= max_iter)
    complete = capped or (not waiting and not remaining)
    print(
        f"nodes={len(state['nodes'])} edges={len(state['edges'])} "
        f"probes={len(state['probes'])} steps={steps}"
        f"{f'/{max_iter}' if max_iter else ''} max_depth={state['max_depth']}"
    )
    status = ('capped' if capped else 'complete' if complete
              else 'waiting-for-dom' if waiting else 'ready')
    print(f"status={status}")
    if waiting:
        print(f"DOM jobs pending: {', '.join(waiting)}")
        print(f"Have a Codex sub-agent process: {run_dir / 'dom_jobs'}")
    if remaining:
        print("Ready probes: " + ", ".join(f"{x['node']}:{'/'.join(x['keys'])}" for x in remaining))
    print(f"Report (txt):  {run_dir / 'report.txt'}")
    print(f"Report (html): {run_dir / 'report.html'}")
    # Exit code drives loop-until-complete: 0 = complete/capped (stop), EXIT_MORE_WORK = a
    # frontier remains, so a driver should re-invoke `explore`. This is what makes rows get
    # DISCOVERED — a re-anchor round adds no probe, so a probe-count-stall check stops too early.
    return 0 if complete else EXIT_MORE_WORK


def cmd_status(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    state = _load_json(_state_path(run_dir))
    _ingest_doms(run_dir, state)
    _save_state(run_dir, state)  # always refresh report.txt / report.html from current state
    return _print_status(run_dir, state)


def cmd_validate(args: argparse.Namespace) -> int:
    """Ladder A (GOAL-02): the create→validate oracle.

    For every discovered edge, physically replay to its SOURCE (goto-home + path
    keys + fingerprint-confirmed arrival, the `_replay_to` primitive), press the
    edge key once, and confirm the result frame matches the TARGET node's stored
    fingerprint. Every claim the builder made is thereby re-earned live:

      pass                edge pressed, destination fingerprint confirmed
      fail                edge pressed, landed on a DIFFERENT screen
      source_unreachable  could not even reposition to the source (path rot)
      skipped_external    target is a terminal external-app tile (never entered
                          by design — see explore's external handling)
      skipped_no_fp       target carries no fingerprint to confirm against

    Results are written to state['validation'] (keyed "source|key|target", with
    checked_at + screenshot) and summarized in validation.txt. Exit code 1 when
    any edge fails or any source is unreachable, so agents/CI can gate on it.
    Nodes are implicitly confirmed too: a 'pass' on an inbound edge IS a live
    fingerprint confirmation of that node.
    """
    run_dir = Path(args.run_dir).expanduser().resolve()
    state = _load_json(_state_path(run_dir))
    if state.get("version") != STATE_VERSION:
        raise LiveBuildError(f"Unsupported state version: {state.get('version')}")

    target = state["target"]
    host, device = target["host_name"], target["device_id"]
    client = MCPClient(state["mcp_url"], _find_auth(args.mcp_config), args.verify_tls)
    _validate_target(client, host, device, target["device_name"])

    # Certification exercises the created artifact end-to-end: goto runs against the
    # PUSHED UI (--goto-ui, e.g. stb3_autobuild) so its Entry->home recipe is under test
    # too, and rescue anchoring is disabled — a goto miss is a finding, not noise.
    state["_no_rescue"] = True
    if args.goto_ui:
        state["_goto_ui"] = args.goto_ui

    nodes = state["nodes"]
    edges = list(state["edges"])
    scope = _resolve_scope(state, getattr(args, "under", None))
    if scope is not None:
        edges = [e for e in edges if e["source"] in scope and e["target"] in scope]
        print(f"scoped to {len(edges)} edge(s) under {args.under!r}")
    if args.only_failed:
        prev = state.get("validation") or {}
        edges = [e for e in edges
                 if prev.get(f"{e['source']}|{e['key']}|{e['target']}", {}).get("status")
                 not in ("pass", "pass_on_retry", "skipped_external", "skipped_no_fp")]
    if args.max_edges:
        edges = edges[: args.max_edges]

    results: Dict[str, Dict[str, Any]] = state.get("validation") or {}
    counts = {"pass": 0, "fail_no_effect": 0, "fail_wrong_screen": 0,
              "source_unreachable": 0, "skipped_external": 0, "skipped_no_fp": 0}
    # Repositioning cost roll-up (the fix's proof): total goto-home resets paid, how many
    # edges needed one, how many were reached free (chain/ring-walk), and total repo seconds.
    repo = {"gotos": 0, "goto_edges": 0, "free_edges": 0, "seconds": 0.0}
    started = time.time()
    _val_goto0 = client.goto_count

    # CHAINED ordering (arbitrator ruling 2026-07-16): a pass is a fingerprint-verified
    # proof of where the device now stands, so the next edge should start there — the
    # goto tax is only paid on chain breaks. Greedy tour: prefer an edge whose source is
    # the previous edge's target, then the nearest ring source; row edges (LEFT/RIGHT)
    # before dives (OK/DOWN) so the walk stays on the ring as long as possible.
    # Correctness never depends on this ordering — _position_to verifies every start.
    ring = _ring_order(state)
    ring_pos = {nid: k for k, nid in enumerate(ring)}
    pending, ordered = list(edges), []
    cur: Optional[str] = None
    while pending:
        here = [e for e in pending if e["source"] == cur]
        if here:
            # A `reverse` UP pairs with the DOWN just validated (nav row keeps last focus):
            # it is only measurable straight after arriving via ITS sibling, so it outranks
            # everything; then row moves; then dives.
            prev = ordered[-1] if ordered else None
            pick = min(here, key=lambda e: (
                0 if (e.get("reverse") and prev is not None and e["target"] == prev["source"])
                else 1 if e["key"] in ("LEFT", "RIGHT") else 2))
        elif cur in ring_pos and any(e["source"] in ring_pos for e in pending):
            n = len(ring)
            pick = min((e for e in pending if e["source"] in ring_pos),
                       key=lambda e: min((ring_pos[e["source"]] - ring_pos[cur]) % n,
                                         (ring_pos[cur] - ring_pos[e["source"]]) % n))
        else:
            pick = pending[0]
        pending.remove(pick)
        ordered.append(pick)
        cur = pick["target"]
    edges = ordered

    print(f"Validating {len(edges)} edge(s) on {host}/{device} "
          f"(ui={state['userinterface_name']}, chained order, ring={len(ring)})")

    for i, edge in enumerate(edges, 1):
        src_id, key, dst_id = edge["source"], edge["key"], edge["target"]
        press_keys = list(edge.get("keys") or [key])   # reverse edges may need BACK x2 (keyboard)
        edge_key = f"{src_id}|{key}|{dst_id}"
        src, dst = nodes.get(src_id), nodes.get(dst_id)
        entry: Dict[str, Any] = {
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "screenshot": None,
        }

        if dst is None or not dst.get("fingerprint"):
            # External tiles are recorded as OK-edges to fingerprint-less terminal
            # nodes on purpose (never entered). Anything else without a fingerprint
            # is unconfirmable — say so rather than fake a pass.
            status = ("skipped_external" if dst is not None and dst.get("kind") == "external"
                      else "skipped_no_fp")
            entry["status"] = status
            counts[status] += 1
            results[edge_key] = entry
            print(f"[{i}/{len(edges)}] {src_id} --{key}--> {dst_id}: {status}")
            continue

        _repo_t0 = time.time()
        _repo_g0 = client.goto_count
        try:
            reached = src is not None and _position_to(client, run_dir, state, target, src)
            if not reached and src is not None and edge.get("reverse"):
                # A reverse edge's PRECONDITION is its paired forward edge (the nav row
                # keeps last focus: UP returns to the sibling you came DOWN from, BACK to
                # the screen you dove from). When the chain didn't arrive via that pair
                # (--only-failed reruns), re-establish it: position to the pair's parent
                # (on the ring), traverse the certified forward edge, confirm arrival.
                fwd = next((f for f in state["edges"] if not f.get("reverse")
                            and f["source"] == dst_id and f["target"] == src_id), None)
                if fwd is not None and dst is not None and dst.get("fingerprint") \
                        and (_position_to(client, run_dir, state, target, dst)
                             or _replay_to(client, run_dir, state, target, dst)):
                    _shot0, fp0 = _settled_capture(client, run_dir, state, "validate",
                                                   host=host, device=device,
                                                   keys=list(fwd.get("keys") or [fwd["key"]]))
                    reached = bool(src.get("fingerprint")) and _same_screen(src["fingerprint"], fp0)
            if not reached and src is not None and not edge.get("reverse"):
                # Off-ring source (dive screen / any depth>=2 node): the certified
                # stepwise path replay is the fallback the ring walk cannot cover.
                reached = _replay_to(client, run_dir, state, target, src)
        except (LiveBuildError, OSError, ValueError) as exc:
            # goto_home / MCP hiccups must cost ONE edge, not the whole run
            # (first live run lost all results to exactly this).
            print(f"[{i}/{len(edges)}] {src_id} --{key}--> {dst_id}: positioning error ({exc})")
            reached = False
        # Reposition cost per edge: seconds spent reaching the source and how many
        # goto-home resets it took (0 = free chain/ring-walk; >0 = a full recipe was paid).
        # These roll up into validation_summary.reposition so the report proves the run is
        # NOT goto-storming (the whole point of the 2026-07-18 fix).
        entry["reposition_s"] = round(time.time() - _repo_t0, 1)
        entry["gotos"] = client.goto_count - _repo_g0
        repo["seconds"] += entry["reposition_s"]
        repo["gotos"] += entry["gotos"]
        # Only edges we actually REACHED count as free/goto — an unreachable edge that
        # fast-fails off-ring spends 0 gotos but was NOT "reached free"; conflating the two
        # would hide a source_unreachable behind a rosy "reached free" tally.
        if reached:
            repo["goto_edges" if entry["gotos"] else "free_edges"] += 1
        if not reached:
            entry["status"] = "source_unreachable"
            counts["source_unreachable"] += 1
            results[edge_key] = entry
            state["validation"] = results
            if not args.benchmark:
                _save_state(run_dir, state)   # incremental — crash loses at most one edge
            print(f"[{i}/{len(edges)}] {src_id} --{key}--> {dst_id}: SOURCE UNREACHABLE")
            continue

        # BLE remotes drop presses (~measured 50% at short waits; see
        # AI_USERINTERFACE_BENCHMARKS). One retry distinguishes "transport noise"
        # from "the graph is wrong": a drop leaves us ON the source screen, so
        # retry only in that case, and record the retry honestly.
        status = None
        for attempt in (1, 2):
            try:
                shot, fp = _settled_capture(client, run_dir, state, "validate",
                                            host=host, device=device, keys=press_keys)
            except (LiveBuildError, OSError, ValueError) as exc:
                # A transient MCP/controller hiccup must cost ONE edge, not the run
                # (a single failed press_key aborted 8 remaining edges, 2026-07-17).
                print(f"    press error on attempt {attempt} ({str(exc)[:90]})")
                if attempt == 1:
                    continue
                status = "press_error"
                break
            entry["screenshot"] = shot
            if _same_screen(dst["fingerprint"], fp):
                status = "pass" if attempt == 1 else "pass_on_retry"
                break
            if src.get("fingerprint") and _same_screen(src["fingerprint"], fp) and attempt == 1:
                # Late-render guard (same as replay): look again before re-pressing —
                # a press that landed but rendered after the settle capture would
                # otherwise be re-pressed and overshoot, indicting a correct edge.
                time.sleep(LATE_RENDER_WAIT_S)
                shot, fp = _settled_capture(client, run_dir, state, "validate",
                                            host=host, device=device, keys=[])
                entry["screenshot"] = shot
                if _same_screen(dst["fingerprint"], fp):
                    status = "pass"
                    break
                if not _same_screen(src["fingerprint"], fp):
                    break   # moved somewhere else -> real wrong-screen, not an eat
                print(f"    still on source after {key} — likely dropped press, retrying once")
                continue
            break
        if status is None:
            # Distinguish the two failure classes: only fail_wrong_screen indicts the
            # graph; fail_no_effect means the press never acted (device/transport).
            still_on_source = bool(src.get("fingerprint")) and _same_screen(src["fingerprint"], fp)
            status = "fail_no_effect" if still_on_source else "fail_wrong_screen"
        entry["status"] = status
        counts[status] = counts.get(status, 0) + 1
        icon = {"pass": "✅", "pass_on_retry": "✅(retry)"}.get(status, "❌ FAIL")
        extra = "" if status.startswith("pass") else f" (landed on a different screen; see {shot})"
        print(f"[{i}/{len(edges)}] {src_id} --{key}--> {dst_id}: {icon}{extra}")
        results[edge_key] = entry
        state["validation"] = results
        if not args.benchmark:
            _save_state(run_dir, state)

    state["validation"] = results
    if args.benchmark:
        print("[benchmark] verdicts NOT persisted (timing run)")
    repo["seconds"] = round(repo["seconds"], 1)
    state["validation_summary"] = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_s": round(time.time() - started, 1),
        "edges_checked": len(edges),
        "reposition": repo,
        **counts,
    }
    if not args.benchmark:
        _save_state(run_dir, state)

    lines = [f"VALIDATION — {state['userinterface_name']} on {host}/{device}",
             f"checked {len(edges)} edge(s) in {state['validation_summary']['duration_s']}s",
             f"repositioning: {repo['gotos']} goto-home reset(s) across {repo['goto_edges']} "
             f"edge(s); {repo['free_edges']} reached free (chain/ring-walk); "
             f"{repo['seconds']}s total in repositioning",
             ""]
    lines += [f"  {k}: {v}" for k, v in counts.items()]
    bad = ("fail_no_effect", "fail_wrong_screen", "source_unreachable", "press_error")
    lines += (["", "failures:"] if any(counts.get(k) for k in bad) else [])
    for ek, r in results.items():
        if r.get("status") in bad:
            lines.append(f"  {ek}: {r['status']} ({r.get('screenshot') or 'no frame'})")
    if not args.benchmark:
        (run_dir / "validation.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))

    # The certification report is part of the run's deliverable: generated and uploaded
    # (7-day presigned link) after EVERY validation pass, so the verdict is always
    # reviewable without shell access. Failure evidence is inlined base64.
    if not args.benchmark:
        try:
            _upload_report(run_dir, _certification_report_html(run_dir, state))
        except Exception as exc:                                 # noqa: BLE001
            print(f"[report] generation failed ({exc}) — validation verdicts unaffected")

    return 1 if any(counts.get(k) for k in bad) else 0


def _certification_report_html(run_dir: Path, state: Dict[str, Any]) -> Path:
    """Self-contained certification report: build summary + per-edge verdict table +
    failure evidence INLINED as base64 JPEG (data URIs, never signed URLs — links rot,
    the report must stand alone)."""
    import base64 as _b64
    nodes = state["nodes"]

    def _lbl(nid):
        return (nodes.get(nid) or {}).get("label") or nid

    def _thumb(path):
        img = cv2.imread(str(path)) if path and os.path.exists(str(path)) else None
        if img is None:
            return ""
        h, w = img.shape[:2]
        scale = 640.0 / max(w, 1)
        img = cv2.resize(img, (640, max(1, int(h * scale))))
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return ("<img src='data:image/jpeg;base64," + _b64.b64encode(buf).decode() +
                "' style='max-width:640px'>") if ok else ""

    v = state.get("validation") or {}
    summary = state.get("validation_summary") or {}
    _repo = summary.get("reposition") or {}
    counts: Dict[str, int] = {}
    for e in v.values():
        counts[e.get("status") or "?"] = counts.get(e.get("status") or "?", 0) + 1
    bad = ("fail_no_effect", "fail_wrong_screen", "source_unreachable", "press_error")
    rows, fails = [], []
    for ek, r in sorted(v.items()):
        src, key, dst = ek.split("|")
        status = r.get("status") or "?"
        color = "#2e7d32" if status.startswith("pass") else "#c62828"
        _gt = r.get("gotos")
        _repo_cell = ("" if r.get("reposition_s") is None
                      else f"{r.get('reposition_s')}s"
                      + (f" · <b style='color:#c62828'>{_gt} goto</b>" if _gt else " · walk"))
        rows.append(f"<tr><td>{_lbl(src)}</td><td><code>{key}</code></td><td>{_lbl(dst)}</td>"
                    f"<td style='color:{color}'>{status}</td><td>{_repo_cell}</td>"
                    f"<td>{r.get('checked_at') or ''}</td></tr>")
        if status in bad:
            fails.append(f"<h3>{_lbl(src)} --{key}--> {_lbl(dst)}: {status}</h3>"
                         + _thumb(r.get("screenshot")))
    rev = sum(1 for e in state["edges"] if e.get("reverse"))
    html = f"""<!doctype html><html><head><meta charset='utf-8'>
<title>Certification — {state['userinterface_name']}</title>
<style>body{{font-family:sans-serif;margin:24px}}table{{border-collapse:collapse}}
td,th{{border:1px solid #ccc;padding:4px 10px;font-size:13px}}</style></head><body>
<h1>Auto-build certification — {state['userinterface_name']}</h1>
<p>run: <code>{run_dir.name}</code> · device: {state['target']['host_name']}/{state['target']['device_id']}
({state['target']['device_name']}) · generated {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}</p>
<h2>Build</h2>
<p>{len(nodes)} nodes · {len(state['edges'])} edges ({rev} reverse) · {len(state['probes'])} probes ·
init {state.get('created_at')}</p>
<h2>Certification</h2>
<p>checked {summary.get('edges_checked', len(v))} edge(s) in {summary.get('duration_s', '?')}s (last pass) ·
verdicts: {' · '.join(f"{k}={n}" for k, n in sorted(counts.items()))}</p>
<p>repositioning: <b>{_repo.get('gotos', '?')}</b> goto-home reset(s) across {_repo.get('goto_edges', '?')} edge(s) ·
{_repo.get('free_edges', '?')} reached free (chain/ring-walk) · {_repo.get('seconds', '?')}s total</p>
<table><tr><th>source</th><th>key</th><th>target</th><th>status</th><th>reposition</th><th>checked</th></tr>
{''.join(rows)}</table>
{'<h2>Failure evidence</h2>' + ''.join(fails) if fails else '<p><b>No failures.</b></p>'}
</body></html>"""
    out = run_dir / "certification_report.html"
    out.write_text(html, encoding="utf-8")
    return out


def _upload_report(run_dir: Path, html_path: Path) -> Optional[str]:
    """Upload the run's reports to object storage with 7-day presigned links: the
    certification report AND the exploration report (report.html — the graph/DOM view,
    already self-contained base64, regenerated on every save). Import bootstrap mirrors
    push_autobuild_to_db (repo root on sys.path); requires MINIO_*/R2 creds in the
    environment. Never raises — a report upload must not fail a run."""
    try:
        repo = Path(__file__).resolve().parents[4]
        if str(repo) not in sys.path:
            sys.path.insert(0, str(repo))
        from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils, MAX_R2_PRESIGN_EXPIRY
        cf = get_cloudflare_utils()
        targets = [("certification", html_path)]
        exploration = run_dir / "report.html"
        if exploration.exists():
            targets.append(("exploration", exploration))
        url = None
        for kind, local in targets:
            key = f"reports/{run_dir.name}_{kind}.html"
            result = cf.upload_files([{"local_path": str(local), "remote_path": key,
                                       "content_type": "text/html"}], auto_delete_cold=False)
            if not (isinstance(result, dict) and result.get("uploaded_count")):
                print(f"[report] upload FAILED for {key}: {result}")
                continue
            link = (cf.generate_presigned_url(key, expires_in=MAX_R2_PRESIGN_EXPIRY) or {}).get("url")
            print(f"[report] {kind} uploaded: {key}\n[report] {kind} link (7 days): {link}")
            if kind == "certification":
                url = link
        return url
    except Exception as exc:                                     # noqa: BLE001
        print(f"[report] upload skipped ({exc})")
        return None


def cmd_report(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    state = _load_json(_state_path(run_dir))
    html_path = _certification_report_html(run_dir, state)
    print(f"[report] written: {html_path}")
    if not args.no_upload:
        _upload_report(run_dir, html_path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fresh blestbv1+ MCP exploration with sub-agent DOM handoff"
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--run-dir", required=True)
    common.add_argument("--mcp-config", help="Config used only to read Authorization")
    common.add_argument("--verify-tls", action="store_true",
                        help="Enable CA verification (off for the current lab endpoint)")

    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", parents=[common])
    init.add_argument("--mcp-url", default=DEFAULT_MCP_URL)
    init.add_argument("--host", default=DEFAULT_HOST)
    init.add_argument("--device", default=DEFAULT_DEVICE)
    init.add_argument("--device-name", default=DEFAULT_DEVICE_NAME)
    init.add_argument("--ui-name", default=DEFAULT_UI,
                      help="Saved userinterface whose 'home' node MCP goto targets")
    init.add_argument("--max-depth", type=int, default=1)
    init.add_argument("--max-iterations", type=int, default=0,
                      help="Global cap on total walk steps (discovery keypresses); 0 = unlimited")
    init.add_argument("--settle-ms", type=int, default=3500)
    init.add_argument("--no-auto-dom", action="store_true",
                      help="Disable inline vision DOM authoring; use the manual "
                           "sub-agent dom_jobs file handoff for every cache miss")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)

    explore = sub.add_parser("explore", parents=[common])
    explore.add_argument("--max-actions", type=int, default=20,
                         help="Maximum new discovery probes in this invocation")
    explore.add_argument("--under", default=None, metavar="NODE",
                         help="Scope exploration to the subtree rooted at NODE (label or "
                              "node_id) — deepen one menu without re-walking the rest")
    explore.add_argument("--max-depth", type=int, default=0,
                         help="Raise the run's depth cap for this and later invocations "
                              "(0 = keep; combine with --under for deep subtree builds)")
    explore.set_defaults(func=cmd_explore)

    status = sub.add_parser("status", parents=[common])
    status.set_defaults(func=cmd_status)

    validate = sub.add_parser("validate", parents=[common],
                              help="Replay every edge live and fingerprint-confirm its "
                                   "destination (the create→validate oracle)")
    validate.add_argument("--max-edges", type=int, default=0,
                          help="Validate at most N edges this invocation (0 = all)")
    validate.add_argument("--only-failed", action="store_true",
                          help="Re-check only edges that are not already 'pass' from a "
                               "previous validate run")
    validate.add_argument("--benchmark", action="store_true",
                          help="Timing run: execute normally but never persist verdicts or "
                               "validation.txt (a benchmark clobbered certified verdicts once)")
    validate.add_argument("--goto-ui", default=None, metavar="UI_NAME",
                          help="Run goto-home against this (pushed) userinterface so its "
                               "Entry→home recipe is certified too (e.g. stb3_autobuild). "
                               "Default: the run's explored UI.")
    validate.add_argument("--under", default=None, metavar="NODE",
                          help="Scope to the subtree rooted at NODE (label or node_id): only "
                               "edges whose source AND target are in that subtree are checked")
    validate.set_defaults(func=cmd_validate)

    report = sub.add_parser("report", parents=[common],
                            help="(Re)generate the certification report and upload it "
                                 "(7-day presigned link). Runs automatically after validate.")
    report.add_argument("--no-upload", action="store_true")
    report.set_defaults(func=cmd_report)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except (LiveBuildError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
