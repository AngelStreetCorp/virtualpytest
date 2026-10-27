"""Per-frame screen identification for the monitoring overlay (Localize).

The capture monitor already decodes every frame for freeze/blackscreen. This
adds a cheap (~few ms) "where am I?" identification on top, throttled to ~1/sec,
written into the per-frame JSON as `localize` so the frontend overlay can show
the current node the same way it shows freeze.

It is OPT-IN per device: only runs when `DEVICE{N}_USERINTERFACE` is set in the
host `.env` (the same var the controller/scripts already use for navigation
defaults). When unset, `localize_frame()` returns None and no field is written.

Unlike `NavigationExecutor.localize()` this runs in the standalone vpt-monitor-img
process, so it loads node fingerprints straight from the DB (base `data.fingerprint`,
no variant resolution) and uses ONLY the deterministic dHash + focus layers — it
does NOT run the title-translation layer (a network/LLM call), which is too heavy
for a per-second loop. The result is the single best candidate by confidence, or
"unknown" when nothing is recognized — which is all the overlay needs.
"""

import logging
import os
from collections import deque
import queue
import re
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from shared.src.lib.utils.phase_timing import (
    t0 as _phase_t0,
    log_duration as _log_duration,
)
from shared.src.lib.utils import cv2_io
from shared.src.lib.utils.localize_verdict import (
    SLOW_LIVE_MIN_PCT, SLOW_LIVE_PAIR_KINDS,
    MOTION_SIZE, after_match, cell_mask, is_live_node, live_verdict, motion_shape, signal_verdict, unknown_verdict,
    verdict_from_match)

logger = logging.getLogger("capture_monitor")

# How long a UI's loaded fingerprint set is reused before re-querying the DB.
# Lets a re-fingerprint (backfill / Reset fingerprint) be picked up without a
# monitor restart, without querying the DB on every frame.
_FP_TTL_SECONDS = 300
# Stand-in userinterface name of a device with no screen tree (profile `mobile`): zero fingerprinted nodes, no DB lookup.
NO_TREE = "__no_tree__"

# identify_screen runs on EVERY captured frame (~5 fps), forever. A `⏱` line per
# frame is ~5 lines/s = 300 lines/min of pure noise in execution.txt, which is the
# BUG-0093 shape (per-cycle logging on the realtime path). So the monitor logs its
# identify_screen timing on VERDICT CHANGE only, plus this heartbeat so a long
# stable stretch still leaves one sample per interval instead of silence:
# 5 lines/s -> 1 line / 30 s = 0.033 lines/s, a 30x reduction; a real screen
# change still gets its own line, and it is the same event _record_change logs.
_IDENTIFY_LOG_HEARTBEAT_SECONDS = 30.0

# Same BUG-0093 shape for the motion gate: a frame-localized log line on every
# skip would still be ~5 lines/s when motion is sustained. Log on gate-decision
# CHANGE only, plus a heartbeat so a long live stretch still leaves one sample.
_GATE_LOG_HEARTBEAT_SECONDS = 30.0

IDENTIFY_SCREEN_PHASE = 'localize.identify_screen'

# Which matcher layer answered. This path only ever calls the deterministic
# dHash/focus matcher (identify_screen, no title translation, no CV/model), so it
# is always 'rule'. 'cv' and 'model' are RESERVED so the overlay can label a future
# tier without changing the payload shape — never emitted from this path.
IDENTIFY_TIER_RULE = 'rule'
IDENTIFY_TIERS = ('rule', 'cv', 'model')

# The six abstain doors of identify_screen (docs/agent/navigation/FINGERPRINT.md)
# keyed by the reason string the matcher itself returns. We MAP the string it
# already produced — the reason is never re-derived here, so the overlay cannot
# disagree with the matcher about WHY it abstained.
#
# Doors 4 (title disambiguation), 5 (dHash fallback narrowing) and 6 (confidence
# floor) do not set `reason` on identify_screen yet, so no string exists to map
# and they fall through to DOOR_UNKNOWN until that worker lands them. Add the
# needle to this tuple (in door order) when it does — never guess a substring.
_ABSTAIN_DOOR_REASONS = (
    ('1', 'low-content frame'),                                    # door 1, nothing to recognise
    ('2', 'nav underline matched no node'),                         # door 2, NAV path fail-safe
    ('3', 'nav underline far from chrome'),                         # door 3, spurious underline
    # 4 title disambiguation — reason not emitted by identify_screen yet
    # 5 dHash fallback narrowing — reason not emitted by identify_screen yet
    # 6 confidence floor — reason not emitted by identify_screen yet
    ('7', 'operator negative'),                                     # door 7, an operator's "not this screen" (TASK-104)
)

# No candidate AND no recognisable reason string (e.g. identify_screen returned
# empty with no reason, or a reason string added upstream before this table is
# extended). An abstain is NORMAL behaviour, not a fault — hence the name.
DOOR_UNKNOWN = 'unknown'


# --- Motion gate (1 Hz localize loop) ------------------------------------------
# A localized match on a live TV / moving carousel is wasted CPU: the picture has
# no node on it, and the answer will be 'unknown' for as long as the motion lasts.
# This gate lets the localize loop SKIP identify_screen on a motion frame and
# serve a cached verdict instead, with a small transition tail that forces a fresh
# matcher call once the picture has settled, so a flip back to a recognisable
# screen (channel changed, carousel stopped) is caught within ~1.5 s.
#
# Motion shape → gate decision:
#   'full'              → SKIP, reason 'live'     (full-frame distributed motion; 'motion'
#                                                  unless the last LIVE_WINDOW ticks all moved)
#   'band'              → SKIP, reason 'motion'   (carousel / horizontal strip)
#   'minor' & pct > 1%  → SKIP, reason 'motion'   (small but persistent change)
#   'static' / 'box'    → RUN                     (drawn screen / PiP)
#   'minor' & pct <= 1% → RUN                     (sub-floor twitch)
#   None / no kind      → RUN                     (defensive default)
#
# The fused 'state' on the motion dict (set by capture_monitor._fuse_motion_state,
# values: blackscreen | no_signal | static | ui | motion | live) is the more
# authoritative input when it is present. 'live' here is the same name as the raw
# 'full' kind but it's the FUSED state — held behind a sustain window in
# _motion_gatekeeper, so the gate is intentionally sticky on it.
GATE_LIVE = 'live'
GATE_MOTION = 'motion'
GATE_MINOR_PCT_FLOOR = 1.0          # pct above which a 'minor' shape is treated as motion
# How long, after a transition from motion→static (or live→ui), the next localize
# tick is FORCED to call identify_screen regardless of the gate. Matches the
# _motion_gatekeeper CONFIRM window: by 1.5 s the new state is fully shown and
# any matcher run from then on is a settled-screen read.
GATE_TRANSITION_FORCE_SECONDS = 1.5


def gate_motion_decision(motion: Optional[dict]) -> Optional[str]:
    """Pure: should the localize loop skip identify_screen on this frame, and why?

    Returns one of `GATE_LIVE` / `GATE_MOTION` (skip + reason) or `None` (run the
    matcher). The rule:

      - `motion.state == 'live'` (the fused value held behind a sustain window)
        OR `motion.kind == 'full'`              → 'live'  (see `live_by_window` for the
                                                   per-device window the loop applies on top)
      - `motion.kind == 'band'`                  → 'motion'
      - `motion.kind == 'minor'` and pct > 1.0   → 'motion'
      - `motion.kind in {'static', 'box'}`       → None
      - `motion.kind == 'minor'` and pct <= 1.0  → None
      - anything else (no motion dict, missing
        'kind', non-numeric pct, …)              → None (defensive)

    Pure: never raises, never mutates. `pct` is read with a tolerant coercion so
    a motion dict that lost its type (e.g. a freshly JSON-decoded number) does
    not crash the 1 Hz loop — the gate defaults to "run the matcher" instead.
    """
    if not isinstance(motion, dict):
        return None
    state = motion.get('state')
    # Detector blackscreen / no_signal outrank a leftover 'full' motion dict: while
    # blackscreen is ongoing, freeze (and therefore motion) is skipped, so kind can
    # stay 'full' from the last live frame. That must not keep the live gate closed
    # or the badge stays on "live" for hours of a black picture (vpt-mf1 stbv1).
    if state in ('blackscreen', 'no_signal'):
        return None
    if state == 'live':
        return GATE_LIVE
    kind = motion.get('kind')
    if kind == 'full':
        return GATE_LIVE
    if kind == 'band':
        return GATE_MOTION
    if kind == 'minor':
        try:
            pct = float(motion.get('pct', 0.0) or 0.0)
        except (TypeError, ValueError):
            return None
        if pct > GATE_MINOR_PCT_FLOOR:
            return GATE_MOTION
        return None
    # 'static' / 'box' / anything missing → let the matcher run.
    return None


# Live needs the motion to LAST, as on the Localize button (one full pair and no still pair over
# ~1 s): a single raw 'full' frame also happens on a menu with a hero trailer behind it (stb-<operator>
# home: static / box / full frames alternate). The fused 'state' cannot tell them apart — it read
# 'ui' on a live SRF 1 channel too (2026-10-15). So the loop keeps the last LIVE_WINDOW raw kinds
# per device: 'live' only when none of them was still; otherwise the frame is plain motion (skip,
# keep the cached screen). TASK-107 goal 6.
LIVE_WINDOW = 3


def live_by_window(kinds) -> bool:
    """Pure: the last LIVE_WINDOW raw motion kinds show sustained motion (none 'static')."""
    kinds = list(kinds)[-LIVE_WINDOW:]
    return len(kinds) == LIVE_WINDOW and 'static' not in kinds and 'full' in kinds


# --- Settled screens under motion (TASK-159 step 6, opt-in per device) -----------------------------
# A splash with drifting words, or a TV guide behind a moving preview, moves enough for the live gate to answer
# `live` before the matcher or the screen memory ever sees it. A LIVE VIDEO changes its dHash every second; such a
# screen keeps its dHash. With DEVICE{N}_LOCALIZE_SETTLED=1 a frame the gate would skip is still sent to the matcher
# (and, when unknown, to the screen registry) once its picture has stayed the same for SETTLED_HOLD_S, then again every
# SETTLED_REFRESH_S. Every other class, and every device without the flag, keeps today's gate.
SETTLED_MAX_BITS = 24       # of 256: drifting words flip a few bits, a video scene flips most of them
SETTLED_HOLD_S = 3.0
SETTLED_REFRESH_S = 5.0


def settled_decision(state: Optional[Dict[str, Any]], dhash: Optional[str], now: float) -> Tuple[Dict[str, Any], bool]:
    """Pure: ``(new_state, force)``. ``state`` = ``{'dhash', 'since', 'last_force'}`` of the previous tick (None at
    first). ``force`` is True when the picture has been the same for SETTLED_HOLD_S and the matcher has not been forced
    for SETTLED_REFRESH_S."""
    from shared.src.lib.utils.image_hash import dhash_hamming
    if not dhash:
        return {"dhash": None, "since": now, "last_force": 0.0}, False
    if not state or not state.get("dhash") or dhash_hamming(dhash, state["dhash"]) > SETTLED_MAX_BITS:
        return {"dhash": dhash, "since": now, "last_force": 0.0}, False
    state = dict(state)
    if now - state["since"] >= SETTLED_HOLD_S and now - state.get("last_force", 0.0) >= SETTLED_REFRESH_S:
        state["last_force"] = now
        return state, True
    return state, False


# --- Unchanged-frame skip (TASK-115) ------------------------------------------
# A calm live channel (a news studio: the presenter moves, the background is still) alternates between
# full-frame motion (live) and ticks the matcher cannot name (abstain -> unknown, badge hidden; stb4
# NDR 2026-10-19). An abstain is no evidence the box left live: keep `live` for LIVE_HOLD_SECONDS after the
# last real live reading, and let only a positive answer (a node, an overlay, a signal state) end it.
LIVE_HOLD_SECONDS = 20.0
# Cues that the picture is playing video, used ONLY when the matcher named nothing (so a menu with a hero trailer,
# which the matcher names, never turns live):
#   - slow live: the last LIVE_WINDOW raw kinds are minor/full and every pct >= SLOW_LIVE_MIN_PCT
#     (same numbers as localize_verdict.SLOW_LIVE_*: a presenter measures 2.8-5.3 %);
#   - audio: the frame JSON says audio present with mean volume above AUDIO_PLAYING_DB, and the picture is not static.
AUDIO_PLAYING_DB = -50.0


def slow_live_by_window(kinds, pcts) -> bool:
    """Pure: sustained minor / full motion of at least SLOW_LIVE_MIN_PCT over the last LIVE_WINDOW ticks."""
    kinds, pcts = list(kinds)[-LIVE_WINDOW:], list(pcts)[-LIVE_WINDOW:]
    if len(kinds) < LIVE_WINDOW or len(pcts) < LIVE_WINDOW:
        return False
    try:
        return (all(k in SLOW_LIVE_PAIR_KINDS for k in kinds)
                and min(float(p) for p in pcts) >= SLOW_LIVE_MIN_PCT)
    except (TypeError, ValueError):
        return False


def audio_playing(audio, motion) -> bool:
    """Pure: `audio` = (present, mean_volume_db) from the frame JSON; true when sound is playing and the picture moves."""
    try:
        present, db = audio
        moving = isinstance(motion, dict) and motion.get("kind") not in (None, "static")
        return bool(present) and db is not None and float(db) > AUDIO_PLAYING_DB and moving
    except (TypeError, ValueError):
        return False


def hold_live(verdict: Dict[str, Any], live_seen_at: Optional[float], now: float, playing: bool = False) -> bool:
    """Pure: True when a matcher `verdict` that named nothing (unknown, or an unnamed known screen) should
    be replaced by `live`: live was read within LIVE_HOLD_SECONDS, or a playback cue (`playing`: slow live
    window or audio) holds now."""
    if verdict.get("kind") == "unknown":
        pass
    elif not (verdict.get("kind") == "known_screen" and (verdict.get("evidence") or {}).get("named") is False):
        return False
    if playing:
        return True
    return live_seen_at is not None and now - live_seen_at <= LIVE_HOLD_SECONDS


# On a still menu the motion gate lets every 1 Hz tick through, so identify_screen ran ~60x/min
# for the same picture. The loop keeps the 320x180 grey thumbnail of the frame last sent to the
# matcher, per device; a new frame with NO changed cell against it (motion_shape's own thresholds:
# pixel > 12, cell > 4 % on the 4x4 grid) serves the cached verdict instead. ONE changed cell
# re-runs the matcher: an app-grid focus move changes one tile (~3 dHash bits — why a dHash gate
# was rejected, TASK-107 §10). The matcher still runs once per UNCHANGED_REFRESH_SECONDS on a
# still screen, so a change below the cell floor is caught within that bound.
GATE_UNCHANGED = 'unchanged'
UNCHANGED_REFRESH_SECONDS = 30.0


def motion_thumb(img):
    """320x180 grey thumbnail of a BGR frame — the same scaling measure_motion uses."""
    import cv2
    return cv2.cvtColor(cv2.resize(img, MOTION_SIZE, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)


def changed_cells(prev_thumb, thumb):
    """Pure: 4x4 bool mask of the cells of `thumb` that changed against `prev_thumb` (None when
    either is missing or the shapes differ)."""
    import cv2
    if prev_thumb is None or thumb is None or prev_thumb.shape != thumb.shape:
        return None
    return cell_mask(cv2.absdiff(prev_thumb, thumb))


def frame_unchanged(prev_thumb, thumb) -> bool:
    """Pure: True when `thumb` has no changed 4x4 cell against `prev_thumb` (None -> False)."""
    changed = changed_cells(prev_thumb, thumb)
    return changed is not None and not changed.any()


# --- Moving-box skip (TASK-115 §5) ---------------------------------------------
# A menu with a looping hero trailer (stb-<operator> home) changes cells on every tick, so the unchanged
# skip never fires there. A cell is MOVING when it changed tick-to-tick on the last
# MOVING_BOX_TICKS ticks in a row (a trailer does; a focus move changes a tile once, then holds).
# A frame is skipped when every cell changed against the last matched frame is moving now AND was
# already moving at that matcher run: the change is the trailer that was playing when the matcher
# last named this screen. Anything else re-runs the matcher on that tick:
#   - a focus move (one tile, changed once, not moving);
#   - a change outside the box (menu focus, a popup larger than the box, a dimmed background);
#   - a popup / frozen frame covering the box: its cells stop changing, so they are no longer
#     moving on the next tick (caught within ~2 s);
#   - a box larger than MOVING_BOX_MAX_CELLS (that is live video: the motion gate's job).
# Blind spot: a change confined to the box's cells while the trailer keeps playing in those same
# cells is served the cached verdict until MOVING_BOX_REFRESH_SECONDS since the last run.
GATE_MOVING_BOX = 'moving_box'
MOVING_BOX_TICKS = 3
MOVING_BOX_MAX_CELLS = 8
MOVING_BOX_REFRESH_SECONDS = 20.0


def moving_box_skip(changed, moving_now, moving_at_match) -> bool:
    """Pure: True when the changed cells lie inside the box that is moving now and was already
    moving at the last matcher run (see the rule above). Any None / empty input -> False."""
    if changed is None or moving_now is None or moving_at_match is None or not changed.any():
        return False
    box = moving_now & moving_at_match
    if int(moving_at_match.sum()) > MOVING_BOX_MAX_CELLS:
        return False
    return not (changed & ~box).any()


def abstain_door(reason: Optional[str]) -> str:
    """`reason` -> the door that produced it: '1'..'6', else `DOOR_UNKNOWN`.

    Substring match, in door order, so a reason the matcher decorates (v6 appends
    ' +v6crop' to it) still resolves, and so the longest-lived token in the string
    wins. Returns `DOOR_UNKNOWN` for an empty/unrecognised reason — never raises.
    """
    try:
        text = (reason or '').strip().lower()
        if not text:
            return DOOR_UNKNOWN
        for door, needle in _ABSTAIN_DOOR_REASONS:
            if needle.lower() in text:
                return door
        return DOOR_UNKNOWN
    except Exception:
        return DOOR_UNKNOWN


def identify_screen_verdict(result: Dict[str, Any]) -> str:
    """`'matched:<node_id>'` / `'abstain:<state>'` -- the part worth a log line when it changes."""
    cands = result.get('candidates') or []
    if cands:
        return f"matched:{cands[0].get('node_id')}"
    return f"abstain:{result.get('state') or 'unknown'}"


def identify_screen_detail(result: Dict[str, Any]) -> str:
    """One-line summary of an identify_screen() result, for a ⏱ line.

    `matched  node=<node_id> conf=<c> excl=<excluded>/<total>`
    `abstain  state=<state|unknown> excl=<excluded>/<total>`

    Identical to the copy in navigation_executor.py (deliberately duplicated: this
    runs in the standalone vpt-monitor-img process, which must not import the navigation
    stack). Keep the two in step.
    """
    try:
        cands = result.get('candidates') or []
        excl = f"{result.get('excluded_count', 0)}/{result.get('total', 0)}"
        if cands:
            top = cands[0]
            return f"matched  node={top.get('node_id')} conf={top.get('confidence', 0)} excl={excl}"
        return f"abstain  state={result.get('state') or 'unknown'} excl={excl}"
    except Exception:
        return 'identify_screen result unreadable'



class MonitorLocalizer:
    """Loads node fingerprints per userinterface and identifies live frames.

    All state is cached per device/UI; everything is best-effort and wrapped so
    a failure can never break frame processing (callers get None on any error).
    """

    def __init__(self, team_id: Optional[str] = None):
        if not team_id:
            from shared.src.lib.utils.app_utils import DEFAULT_TEAM_ID
            team_id = DEFAULT_TEAM_ID
        self.team_id = team_id
        # TASK-159: a sighting is counted per transition INTO a screen, never per tick. device_id -> the screen id
        # (or None) the device is on now; and device_id -> [fingerprint, consecutive unknown ticks] of the unknown
        # picture waiting to settle before it is registered as unknown_N.
        self._on_screen: Dict[str, Optional[str]] = {}
        self._reg_limit: Dict[str, int] = {}            # device_id -> new rows per hour (0 = registry off)
        self._settled_flag: Dict[str, bool] = {}        # device_id -> DEVICE{N}_LOCALIZE_SETTLED (opt-in)
        self._settled: Dict[str, Dict[str, Any]] = {}   # device_id -> settled_decision state
        # flicker guard (BUG-0746): two near-identical rows the matcher alternates between are not 100 transitions
        self._known_counted: Dict[Tuple[str, str], float] = {}  # (device_id, screen_id) -> last counted (monotonic)
        self._unsettled: Dict[str, list] = {}
        self._registering: Dict[str, bool] = {}              # a registration thread is running for the device
        self._reg_result: Dict[str, Optional[str]] = {}      # mailbox: the id the thread registered/matched
        self._reg_times: Dict[str, deque] = {}               # monotonic times of the device's recent new rows
        # device_id -> (userinterface_name, variant) or None (disabled). Both read
        # from the host .env (DEVICE{N}_USERINTERFACE / DEVICE{N}_VARIANT); variant
        # defaults to 'base' when unset — the same convention scripts/goto use.
        self._ui_by_device: Dict[str, Optional[tuple]] = {}
        # userinterface_name -> {'ts': float, 'node_fps': [...]}
        self._fps_by_ui: Dict[str, Dict[str, Any]] = {}
        # userinterface_name -> {'ts': float, 'ui': <record>} — TTL-cached
        # side-channel for the userinterface row (id, name, company, is_media).
        # Loaded inside `_load_node_fps` so the 1 Hz loop does not pay a
        # second DB roundtrip for the company / is_media passthrough.
        self._ui_meta_by_name: Dict[str, Dict[str, Any]] = {}
        self._helpers = None  # lazy ImageHelpers (only when first enabled device seen)
        # device_id -> last logged verdict signature (node label / state / 'unknown'),
        # so the forensic trail only fires on an actual verdict CHANGE, not per frame.
        self._last_sig: Dict[str, str] = {}
        # BUG-0675: match_runs pushes run on their own thread. A Redis connect timeout is ~26 s
        # (host without a local Redis); inline it froze the one localize worker, so the badge
        # kept the verdict from before the last matcher run for that long.
        # device_id -> wall clock of the last real live reading (see hold_live).
        self._live_seen: Dict[str, float] = {}
        self._match_run_q: "queue.Queue" = queue.Queue(maxsize=32)
        self._match_run_thread: Optional[threading.Thread] = None
        # device_id -> (last emitted localize.identify_screen signature, its wall clock),
        # and the number of frames folded into that last line. Same per-frame noise
        # problem as _last_sig, solved the same way (TASK-68 row 6).
        self._identify_state: Dict[str, tuple] = {}
        # device_id -> last MATCHER verdict (no gate_skip), kept so the motion gate can
        # serve a cached node when it skips identify_screen. Updated on every matcher
        # run; never carries gate_skip itself.
        self._last_match: Dict[str, Dict[str, Any]] = {}
        # device_id -> {'prev': state, 'current': state, 'since': float} for transition
        # tracking. When the fused motion state moves from 'live'/'motion' to
        # 'static'/'ui' and stays for >= GATE_TRANSITION_FORCE_SECONDS, the next call
        # forces a fresh matcher run regardless of the gate (otherwise a settled
        # screen after a carousel would keep showing the pre-motion verdict forever).
        self._motion_state: Dict[str, Dict[str, Any]] = {}
        # device_id -> (last gate decision, its wall clock, frames folded since then).
        # Same BUG-0093 throttling shape as _identify_state: log on CHANGE, plus
        # _GATE_LOG_HEARTBEAT_SECONDS.
        self._gate_log_state: Dict[str, tuple] = {}
        # device_id -> deque of recent motion.pct values (oldest first, newest last),
        # bounded to LOADED_CONVERGED_FRAMES. screen_state_cv.loaded() consumes this
        # as a window — a single float always returns 'unknown' (line 267), and a
        # raw std-dev proxy also returns 'unknown' (line 269, window not filled).
        # The monitor collects one pct per captured frame (~5 fps), so even a
        # 5-frame window fills in 1 second and the abstain period after a screen
        # change is short enough to not matter on the per-second overlay.
        # device_id -> (grey thumbnail of the frame last sent to the matcher, its wall clock).
        # See frame_unchanged / UNCHANGED_REFRESH_SECONDS.
        self._matched_thumb: Dict[str, tuple] = {}
        # device_id -> (grey thumbnail of the previous tick, 4x4 int array: ticks in a row each
        # cell changed tick-to-tick). See moving_box_skip.
        self._tick_motion: Dict[str, tuple] = {}
        self._pct_window: Dict[str, deque] = {}
        # device_id -> the last LIVE_WINDOW raw motion kinds (see live_by_window).
        self._kind_window: Dict[str, deque] = {}

    def _get_helpers(self):
        if self._helpers is None:
            from backend_host.src.controllers.verification.image_helpers import ImageHelpers
            # captures_path / av_controller are unused by the matching methods we call.
            self._helpers = ImageHelpers(None, None)
        return self._helpers

    def _device_env(self, device_id: str, suffix: str) -> str:
        """Value of DEVICE{N}_<suffix> (N as in _resolve_ui; HOST_<suffix> for the host desktop), or ''."""
        n = None
        m = re.match(r"device(\d+)$", device_id or "")
        if m:
            n = m.group(1)
        elif device_id and device_id != "host":
            try:
                from shared.src.lib.utils.storage_path_utils import get_device_info_from_capture_folder
                index = get_device_info_from_capture_folder(device_id).get("device_index")
                n = str(index) if index else None
            except Exception:
                n = None
        prefix = f"DEVICE{n}" if n is not None else ("HOST" if device_id == "host" else None)
        return (os.getenv(f"{prefix}_{suffix}") or "").strip().lower() if prefix else ""

    def _settled_enabled(self, device_id: str) -> bool:
        """DEVICE{N}_LOCALIZE_SETTLED is truthy: opt-in, default off."""
        if device_id not in self._settled_flag:
            self._settled_flag[device_id] = self._device_env(device_id, "LOCALIZE_SETTLED") in ("1", "true", "yes", "on")
        return self._settled_flag[device_id]

    def _registry_limit(self, device_id: str) -> int:
        """New unknown_N rows allowed per hour for this device: DEVICE{N}_SCREEN_REGISTRY=off -> 0 (games, drones: no
        registry); DEVICE{N}_SCREEN_MAX_NEW_PER_HOUR=<n> raises or lowers the default MAX_NEW_PER_HOUR."""
        if device_id not in self._reg_limit:
            if self._device_env(device_id, "SCREEN_REGISTRY") in ("0", "off", "false", "no"):
                limit = 0
            else:
                raw = self._device_env(device_id, "SCREEN_MAX_NEW_PER_HOUR")
                limit = int(raw) if raw.isdigit() else self.MAX_NEW_PER_HOUR
            self._reg_limit[device_id] = limit
        return self._reg_limit[device_id]

    def _settled_force(self, device_id: str, frame_path: str) -> bool:
        """True when this gated frame is a settled screen (see SETTLED_*): the caller runs the matcher on it."""
        try:
            from shared.src.lib import screen_memory
            fp = screen_memory.fingerprint_frame(cv2_io.imread(frame_path))
            state, force = settled_decision(self._settled.get(device_id), fp["dhash"] if fp else None, time.time())
            self._settled[device_id] = state
            return force
        except Exception as e:
            logger.debug(f"[localize] settled check failed for {device_id}: {e}")
            return False

    def _resolve_ui(self, device_id: str) -> Optional[tuple]:
        """Map device_id ('device4') -> (DEVICE4_USERINTERFACE, DEVICE4_VARIANT), cached.

        A device with no userinterface gets the default tree-less one (NO_TREE): Localize still answers signal /
        live, and names a still frame from the device's screen memory (known screen #id, its verdict) or says
        unknown. ``host`` reads HOST_USERINTERFACE; DEVICE5 and up arrive as their capture folder ('capture5').
        Variant defaults to 'base' when DEVICE{N}_VARIANT is unset — same as scripts/goto.
        """
        if device_id in self._ui_by_device:
            return self._ui_by_device[device_id]
        resolved = None
        m = re.match(r"device(\d+)$", device_id or "")
        n = m.group(1) if m else None
        if n is None and device_id and device_id != "host":
            from shared.src.lib.utils.storage_path_utils import get_device_info_from_capture_folder
            index = get_device_info_from_capture_folder(device_id).get("device_index")
            n = str(index) if index else None
        if n is not None or device_id == "host":
            prefix = f"DEVICE{n}" if n is not None else "HOST"
            val = os.getenv(f"{prefix}_USERINTERFACE")
            ui = (val.strip() if val and val.strip() else None) or NO_TREE
            var = (os.getenv(f"{prefix}_VARIANT") or "base").strip() or "base"
            resolved = (ui, var)
        self._ui_by_device[device_id] = resolved
        if resolved:
            logger.info(f"[localize] Enabled for {device_id} → userinterface "
                        f"'{resolved[0]}' variant '{resolved[1]}'")
        return resolved

    def _load_node_fps(self, userinterface_name: str) -> List[Dict[str, Any]]:
        """Fingerprinted+verified nodes for a UI (base data.fingerprint), TTL-cached."""
        if userinterface_name == NO_TREE:
            return []
        cached = self._fps_by_ui.get(userinterface_name)
        if cached and (time.time() - cached["ts"]) < _FP_TTL_SECONDS:
            return cached["node_fps"]

        node_fps: List[Dict[str, Any]] = []
        live_node: Optional[Dict[str, Any]] = None
        # Side-channel: cache the userinterface record alongside the fingerprints
        # so the per-frame payload can carry `userinterface_company` and the
        # Tier-2 `playback` arm can answer on `is_media` without a second DB
        # roundtrip on the 1 Hz loop. Cached together with node_fps (same TTL,
        # same invalidation lifetime); a separate dict keeps the fingerprint
        # code untouched. None when the UI is unknown or the DB lookup failed
        # — `userinterface_company` is then omitted from the per-frame payload
        # and `is_media` defaults to None (the safe default).
        ui_record: Optional[Dict[str, Any]] = None
        try:
            from shared.src.lib.database.userinterface_db import get_userinterface_by_name
            from shared.src.lib.database.navigation_trees_db import (
                get_root_tree_for_interface,
                get_complete_tree_hierarchy,
            )
            from shared.src.lib.utils.navigation_graph import resolve_node_variant

            ui = get_userinterface_by_name(userinterface_name, self.team_id)
            if not ui or not ui.get("id"):
                logger.warning(f"[localize] Unknown userinterface '{userinterface_name}'")
            else:
                ui_record = ui
                root = get_root_tree_for_interface(ui["id"], self.team_id)
                if root and root.get("id"):
                    hier = get_complete_tree_hierarchy(root["id"], self.team_id)
                    if hier.get("success"):
                        seen_ids = set()
                        for tree in hier.get("all_trees_data", []):
                            for raw in tree.get("nodes", []):
                                # IDENTICAL candidate rule to NavigationExecutor.localize:
                                # base variant-resolve (respects hidden_in_base) + a dHash,
                                # dedup by node_id (parent-reference rows recur). Localize is
                                # FINGERPRINT-based — a node with a stored fingerprint is
                                # recognizable on its own, so do NOT require a hand-authored
                                # verification (that gate wrongly dropped fingerprint-only nodes
                                # like the app-grid tiles, so the overlay mislabeled e.g. a
                                # Netflix-focused frame as apps_oneplus — the nearest *verified*
                                # tile — while the Localize popover correctly kept apps_netflix).
                                node = resolve_node_variant(raw, None)
                                if (node.get("__variant_state") or {}).get("active") is False:
                                    continue
                                nid = node.get("node_id")
                                if not nid or nid in seen_ids:
                                    continue
                                if live_node is None and is_live_node(node.get("label")):
                                    live_node = {"node_id": nid, "label": node.get("label") or nid}
                                fp = node.get("__fingerprint")
                                if fp and fp.get("dhash"):
                                    seen_ids.add(nid)
                                    node_fps.append({
                                        "node_id": nid,
                                        "label": node.get("label") or nid,
                                        "fingerprint": fp,
                                    })
            logger.info(f"[localize] Loaded {len(node_fps)} fingerprinted node(s) for '{userinterface_name}'")
        except Exception as e:
            logger.warning(f"[localize] Failed to load fingerprints for '{userinterface_name}': {e}")

        # Cache even an empty result so we don't hammer the DB on a misconfigured UI.
        self._fps_by_ui[userinterface_name] = {"ts": time.time(), "node_fps": node_fps,
                                               "live_node": live_node}
        # Best-effort cache of the userinterface record (id, name, company,
        # is_media). `company` is the opt-in metadata the per-frame payload
        # carries; `is_media` drives the Tier-2 `playback` arm. See
        # _screen_state and the gate log for the same record.
        self._ui_meta_by_name[userinterface_name] = {"ts": time.time(), "ui": ui_record}
        return node_fps

    def _after_match(self, verdict: Dict[str, Any], img, node_fps: List[Dict[str, Any]], helpers,
                       device_id: str, motion: Optional[dict] = None) -> Dict[str, Any]:
        """Cascade steps 4-5b (overlay over a node or on an abstain, screen memory) after the matcher,
        as the button runs them (localize_verdict.after_match). Never raises: a failure keeps the
        verdict it was given. Slow live (5b) needs per-pair kinds, which this per-frame motion dict
        does not carry: the monitor reads live from its fused window in the gate above."""
        if verdict.get("kind") not in ("node", "unknown"):
            return verdict
        try:
            from shared.src.lib.database.screen_fingerprints_db import known_screen_lookup
            scope = f"{os.getenv('HOST_NAME', '')}/{device_id}"
            out = after_match(verdict, img, node_fps, helpers, known_screen_lookup(self.team_id, scope),
                              motion=motion if isinstance(motion, dict) else None)
            try:
                self._track_screen(device_id, scope, out, img)
            except Exception as e:   # registry bookkeeping must never cost the frame its verdict
                logger.warning(f"[localize] screen registry bookkeeping failed for {scope}: {e}")
            return out
        except Exception as e:
            logger.debug(f"[localize] after_match failed for {device_id}: {e}")
            return verdict

    KNOWN_RECOUNT_S = 600.0
    SETTLE_SECONDS = 5.0   # an unknown picture must stay the same this long before it is registered (wall clock: on a frozen
                           # screen the 'unchanged' gate skips ticks, the matcher only re-reads it every UNCHANGED_REFRESH_SECONDS)
    MAX_NEW_PER_HOUR = 12   # new unknown_N rows per device and hour: a runaway source is logged and skipped

    def _track_screen(self, device_id: str, scope: str, verdict: Dict[str, Any], img=None) -> None:
        """TASK-159: Localize is the only creator of screen rows. A known unclassified screen gets one sighting per
        transition into it (BUG-0662, BUG-0746: never per tick); a picture that stays unknown for SETTLE_SECONDS seconds
        in a row is registered as the device's next ``unknown_N``. DB writes run in a daemon thread so the 1 Hz loop
        never waits on them."""
        kind = verdict.get("kind")
        ev = verdict.get("evidence") or {}
        registered = self._reg_result.pop(device_id, None)   # the thread only leaves its result; this loop applies it
        if registered:
            self._on_screen[device_id] = registered   # the registration was this episode's sighting
            self._registering.pop(device_id, None)
        if kind == "known_screen" and ev.get("screen_id"):
            self._unsettled.pop(device_id, None)
            sid = ev["screen_id"]
            if self._registering.pop(device_id, None):
                self._on_screen[device_id] = sid   # the row the thread just made: its creation was the sighting
                return
            if self._on_screen.get(device_id) == sid:
                return
            self._on_screen[device_id] = sid
            now = time.monotonic()
            last = self._known_counted.get((device_id, sid))
            if ev.get("verdict") in (None, "unknown") and (last is None or now - last >= self.KNOWN_RECOUNT_S):
                self._known_counted[(device_id, sid)] = now
                import threading
                from shared.src.lib.database.screen_fingerprints_bump import bump_known_screen_sighting
                threading.Thread(target=bump_known_screen_sighting,
                                 kwargs={"team_id": self.team_id, "screen_id": sid, "frame": img}, daemon=True).start()
            return
        if kind != "unknown":
            self._on_screen[device_id] = None
            self._unsettled.pop(device_id, None)
            return
        from shared.src.lib import screen_memory
        fp = screen_memory.fingerprint_frame(img)
        if not fp:
            self._unsettled.pop(device_id, None)
            return
        pending = self._unsettled.get(device_id)
        now = time.monotonic()
        if not (pending and screen_memory.match_screen(fp, [pending[0]])):
            self._unsettled[device_id] = [fp, now, False]
            return
        if pending[2] or now - pending[1] < self.SETTLE_SECONDS or self._registering.get(device_id):
            return
        pending[2] = True   # registered for this stay: a frozen screen is one registration
        limit = self._registry_limit(device_id)
        if limit == 0:
            return   # DEVICE{N}_SCREEN_REGISTRY=off: this source (game, drone camera) does not use the registry
        recent = self._reg_times.setdefault(device_id, deque(maxlen=limit))
        if len(recent) == recent.maxlen and now - recent[0] < 3600:
            logger.warning(f"[localize] {scope}: {limit} new unknown screens in the last hour, not registering more")
            return
        recent.append(now)
        self._registering[device_id] = True
        # TASK-162: store the fingerprint blob, not just the {dhash, region_center} identity. The
        # matcher reads v/dhash/regions/crop/focus (localize_verdicts_db.SAMPLE_KEYS), all of
        # which are computed without OCR, so this costs no tesseract subprocess in the 1 Hz loop.
        # Before this, every row the monitor registered had fingerprint = NULL: named, but never
        # fingerprinted. Computed here (the loop thread), not in the daemon thread below.
        v6 = None
        try:
            v6 = self._get_helpers().compute_fingerprint(img, ocr=False)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[localize] {scope}: v6 fingerprint failed ({e}); registering with identity only")
        import threading
        threading.Thread(target=self._register_unknown, args=(device_id, scope, fp, img, v6), daemon=True).start()

    def _register_unknown(self, device_id: str, scope: str, fp: Dict[str, str], img,
                          v6: Optional[Dict[str, Any]] = None) -> None:
        """Daemon thread: register the settled picture and leave the id in the mailbox (``_reg_result``); the 1 Hz loop
        applies it, so this thread never writes the device's episode state."""
        hit = None
        try:
            from shared.src.lib.database.screen_fingerprints_bump import _thumb_uri
            from shared.src.lib.database.screen_fingerprints_db import register_screen
            hit = register_screen(self.team_id, scope, fp, fingerprint=v6,
                                  sample_image_path=_thumb_uri(img))
            if hit:
                logger.info(f"[localize] {scope}: screen {hit.get('label')} ({'new' if hit['is_new'] else 'seen'})")
        except Exception as e:
            logger.debug(f"[localize] register unknown failed for {scope}: {e}")
        finally:
            if hit:
                self._reg_result[device_id] = hit["id"]
            else:
                self._registering.pop(device_id, None)

    def _live_node(self, userinterface_name: str) -> Optional[Dict[str, Any]]:
        """The UI's node flagged `live: true` ({node_id, label}), from the fingerprint cache."""
        self._load_node_fps(userinterface_name)
        return (self._fps_by_ui.get(userinterface_name) or {}).get("live_node")

    def _ui_meta(self, userinterface_name: str) -> Dict[str, Any]:
        """Return the cached userinterface record (with `company` and `is_media`),
        or {} on miss/error.

        The 1 Hz localize loop must not stall on a DB lookup; the record is
        loaded by `_load_node_fps` and TTL-cached here alongside the
        fingerprints. Returns an empty dict when the row is missing (the
        caller then omits `userinterface_company` from the payload and
        passes `is_media=None` to `scv.playback`) and NEVER raises — a DB
        failure on metadata is a no-op, not a crash.
        """
        try:
            cached = self._ui_meta_by_name.get(userinterface_name)
            if cached and (time.time() - cached["ts"]) < _FP_TTL_SECONDS:
                return cached.get("ui") or {}
            return {}
        except Exception as e:
            logger.debug(f"[localize] _ui_meta lookup failed for {userinterface_name}: {e}")
            return {}

    def localize_frame(self, device_id: str, frame_path: str, motion: Optional[dict] = None,
                       audio: Optional[tuple] = None, foreground: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """`_localize_frame`, then on a tree-less phone (profile `mobile`) the foreground app names the screen: kind `app`,
        label = the app name (foreground_app.py). A black screen / no signal still wins."""
        out = self._localize_frame(device_id, frame_path, motion=motion, audio=audio)
        try:
            ui = self._ui_by_device.get(device_id)
            if out is not None and foreground and ui and ui[0] == NO_TREE and (out.get("verdict") or {}).get("kind") != "signal":
                from monitor.foreground_app import app_label
                label = app_label(foreground)
                out = dict(out, node=label, confidence=1.0,
                           verdict={"kind": "app", "node_id": None, "label": label, "confidence": 1.0,
                                    "evidence": {"package": foreground, "motion": motion if isinstance(motion, dict) else None}},
                           kind="app")
                out.pop("gate_skip", None)
        except Exception as e:
            logger.debug(f"[localize] app verdict failed for {device_id}: {e}")
        return out

    def _localize_frame(self, device_id: str, frame_path: str,
                        motion: Optional[dict] = None, audio: Optional[tuple] = None) -> Optional[Dict[str, Any]]:
        """Identify the screen in `frame_path` for `device_id`.

        Returns None when the feature is disabled for this device (no env var) or
        on any error. When enabled, returns:
            {'node': <label>|None, 'confidence': <0..1>, 'excluded': int, 'total': int,
             'tier': 'rule',
             'reason'?: str, 'door'?: '1'..'6'|'unknown',
             'state'?: 'no_signal'|'blackscreen', 'state_label'?: str,
             'gate_skip'?: 'live'|'motion',
             'loaded'?: 'yes'|'no'|'unknown',     # Tier 2, only on a fresh matcher run
             'overlay'?: 'none'|'popup'|'tooltip'|'keyboard'|'notification'|'unknown',
             'playback'?: 'playing'|'paused'|'stopped'|'not_applicable'|'unknown',
             'error'?: 'none'|'visible'|'unknown'}
        `node` is None when nothing is recognized (overlay shows "unknown"), or the
        named `state`/`state_label` for a capture-side no-signal / black state.

        `reason`/`door` are the DIAGNOSIS, so an operator can tell a confident match
        from a guess and see WHY it abstained: `reason` is identify_screen's own
        string, passed through untouched, and `door` is the abstain door mapped from
        it. Both appear only when identify_screen produced them (so a match with no
        abstain carries neither), which also keeps the per-frame payload small.
        `tier` names the layer that answered — always IDENTIFY_TIER_RULE here.

        `gate_skip` is set on motion-gated frames (live TV / moving carousel): the
        matcher is skipped, the verdict is the cached `last_match` node with
        confidence 0, and a fresh matcher call is forced on the next tick after a
        motion→static transition tail (GATE_TRANSITION_FORCE_SECONDS) so a settled
        screen is recognised within ~1.5 s. See `gate_motion_decision` for the rule.

        `loaded` / `overlay` / `playback` / `error` are the Tier-2 screen-state
        fields from `shared.src.lib.ai.screen_state_cv.screen_state`. They are
        ADDITIVE: present on a fresh matcher run (the gate must be open to even
        read the image, so a `gate_skip` payload carries none of them) and
        absent on a gate-skip payload. Order of priority for the overlay display
        is documented in FINGERPRINT.md.

        `userinterface_company` is the userinterface's free-text brand label
        (e.g. 'brand_a', 'brand_b', 'brand_c'). Absent when the row has none
        (NULL = unknown company, treated as today). On a fresh matcher run it
        is also passed as an extra keyword to `screen_state_cv.error` so brand
        text on screen becomes a 'visible' answer; a `gate_skip` payload
        carries the cached `userinterface_company` for the same reason it
        carries the cached `node`. `is_media` is the userinterface's
        media-surface flag (NULL when the editor has not decided; TRUE for
        channels / streaming / HDMI; FALSE for app grids / settings / games).
        The monitor passes it through to `screen_state_cv.playback` so the
        arm answers 'playing' / 'paused' / 'stopped' on TRUE,
        'not_applicable' on FALSE, and abstains to 'unknown' on NULL (today's
        behaviour).
        """
        resolved = self._resolve_ui(device_id)
        if not resolved:
            return None
        userinterface_name, _variant = resolved
        # Maintain the per-device motion.pct window that screen_state_cv.loaded()
        # consumes. The window is bounded; on a new device_id a fresh deque is
        # created. Push None to None to keep cadence if motion is missing — the
        # deque length still grows, but loaded() refuses None values and abstains,
        # which is the right behaviour when the motion detector has nothing yet.
        if device_id not in self._pct_window:
            from collections import deque as _dq
            self._pct_window[device_id] = _dq(maxlen=8)  # LOADED_CONVERGED_FRAMES == 5; 8 leaves headroom
        win = self._pct_window[device_id]
        settled_tick = False   # this tick is an opt-in read of a settled screen under motion (SETTLED_*)
        if isinstance(motion, dict):
            try:
                win.append(float(motion.get("pct")))
            except (TypeError, ValueError):
                win.append(None)
        try:
            # Free the window when the device is gone (best-effort GC).
            pass  # no idle eviction needed: deques are tiny, one per device_id
            # Motion gate: when the frame is sustained live / carousel / minor-motion,
            # skip identify_screen and serve the cached matcher verdict instead. The
            # motion dict is the same one _fuse_motion_state already attached to
            # analysis_data, so the gate sees both the raw shape (kind/pct) and the
            # fused state (live/ui/static/motion/blackscreen/no_signal). The pure
            # decision function is unit-tested; this call site only does the
            # bookkeeping (cache hit, log throttle, transition force-tail).
            # Cascade step 1 (signal) before the live gate. The detector already named
            # blackscreen / no_signal on this frame; do not skip to live on a stale
            # full-motion dict from before the picture went black.
            if isinstance(motion, dict) and motion.get('state') in ('blackscreen', 'no_signal'):
                state = motion['state']
                helpers = self._get_helpers()
                label = ((helpers.SPECIAL_STATE_LABELS.get(state) if helpers else None) or state)
                verdict = signal_verdict(state, label)
                self._kind_window.pop(device_id, None)
                return {
                    'node': None,
                    'confidence': 1.0,
                    'tier': IDENTIFY_TIER_RULE,
                    'state': state,
                    'state_label': label,
                    'verdict': verdict,
                    'kind': verdict['kind'],
                }
            gate_reason = gate_motion_decision(motion) if motion is not None else None
            kinds = self._kind_window.setdefault(device_id, deque(maxlen=LIVE_WINDOW))
            if isinstance(motion, dict):
                kinds.append(motion.get('kind'))
            if gate_reason == GATE_LIVE and motion.get('state') != 'live' and not live_by_window(kinds):
                gate_reason = GATE_MOTION
            force_match = self._update_motion_state(device_id, motion)
            if gate_reason and not force_match and self._settled_enabled(device_id):
                settled_tick = force_match = self._settled_force(device_id, frame_path)
            playing = slow_live_by_window(kinds, win) or audio_playing(audio, motion)
            if gate_reason and not force_match:
                cached = self._last_match.get(device_id)
                # Live needs no cached match: full-frame motion IS the answer (TASK-104).
                if cached is not None or gate_reason == GATE_LIVE:
                    cached = cached or {}
                    out = {
                        "gate_skip": gate_reason,
                        "node": cached.get("node"),
                        # confidence is 0 on a gate_skip: we did not measure this frame
                        # (the match is from an earlier, possibly pre-motion tick).
                        "confidence": 0.0,
                        "tier": IDENTIFY_TIER_RULE,
                    }
                    # Carry the small set of stable fields from the cached verdict so
                    # the overlay does not blank on a sustained motion stretch.
                    for k in ("state", "state_label", "userinterface_company"):
                        if k in cached:
                            out[k] = cached[k]
                    # v3 verdict (TASK-104): full-frame motion IS the answer (live), and the
                    # tree's live node names it; a carousel keeps the cached verdict.
                    if gate_reason == GATE_LIVE:
                        live = self._live_node(userinterface_name)
                        verdict = live_verdict(motion, live)
                        self._live_seen[device_id] = time.time()
                        if live:
                            out["node"] = live["label"]
                    else:
                        verdict = cached.get("verdict") or unknown_verdict()
                        if hold_live(verdict, self._live_seen.get(device_id), time.time(), playing):
                            live = self._live_node(userinterface_name)
                            verdict = live_verdict(motion, live)
                            self._live_seen[device_id] = time.time()
                            if live:
                                out["node"] = live["label"]
                    out["verdict"] = verdict
                    out["kind"] = verdict["kind"]
                    self._log_gate_skip(device_id, gate_reason, force_match=False)
                    return out
                # No cache on a carousel / minor-motion frame (very first frame is gated):
                # fall through and run the matcher so we have SOMETHING to serve next time.

            # NOTE: non-base variants fall back to base fingerprints here — the
            # standalone monitor does not do variant-override resolution (the enable
            # log records the configured variant). All current devices run 'base'.
            node_fps = self._load_node_fps(userinterface_name)
            if not node_fps:
                # UI lookup failed (Unknown userinterface / DB unavailable / no fingerprints
                # for this team). The Tier-2 cascade does NOT need fingerprints — it
                # answers from frame + motion + company alone — so we still run it and
                # merge the new fields into the early-exit payload. Otherwise the per-frame
                # JSON silently drops the new gate_skip / loaded / overlay / playback /
                # error fields whenever the matcher can't run, which is exactly when
                # operators most want to see them. The image-load + Tier-2 calls below
                # are cheap (~few ms); cv2 is already imported further up the call chain
                # via the matcher on a successful run, so the import here is duplicate
                # but harmless.
                import cv2 as _cv2
                _img = cv2_io.imread(frame_path)
                if _img is None:
                    return None
                _tier2 = self._screen_state(_img, motion, company=None, device_id=device_id)
                # The verdict still answers signal without fingerprints (live was the gate above).
                _helpers = self._get_helpers()
                _state = _helpers.classify_special_state(_img) if _helpers else None
                _verdict = (signal_verdict(_state, _helpers.SPECIAL_STATE_LABELS.get(_state)) if _state
                            else self._after_match(unknown_verdict({'reason': 'no fingerprinted nodes'}),
                                                     _img, [], _helpers, device_id, motion))
                if hold_live(_verdict, self._live_seen.get(device_id), time.time(), playing):
                    self._live_seen[device_id] = time.time()
                    _verdict = live_verdict(motion if isinstance(motion, dict) else None, self._live_node(userinterface_name))
                _out = {"node": None, "confidence": 0.0, "excluded": 0, "total": 0,
                        "verdict": _verdict, "kind": _verdict["kind"]}
                if _state:
                    _out["state"] = _state
                    _out["state_label"] = _verdict["label"]
                if _tier2:
                    _out.update(_tier2)
                return _out

            import cv2
            img = cv2_io.imread(frame_path)
            if img is None:
                return None

            # Unchanged-frame skip: the same picture as the last matcher run answers the same.
            # Not on a forced tick (the settle tail must re-read) nor past the refresh bound.
            # Moving-box skip: the only change is the trailer that was already playing (§5).
            thumb = motion_thumb(img)
            moving_now = self._update_tick_motion(device_id, thumb)
            prev = self._matched_thumb.get(device_id)
            cached = self._last_match.get(device_id)
            if cached is not None and prev is not None:
                age = time.time() - prev[1]
                changed = changed_cells(prev[0], thumb)
                if (not force_match and changed is not None and not changed.any()
                        and age < UNCHANGED_REFRESH_SECONDS):
                    self._log_gate_skip(device_id, GATE_UNCHANGED, force_match=False)
                    return dict(cached)
                # Also on a forced settle tick: on a trailer screen the trailer's own cuts make the
                # motion -> still edges (~6/min on stb-<operator> home), so an edge whose only change is
                # that box carries no news. A still screen keeps its one forced re-read (above).
                if age < MOVING_BOX_REFRESH_SECONDS and not settled_tick and moving_box_skip(changed, moving_now, prev[2]):
                    self._log_gate_skip(device_id, GATE_MOVING_BOX, force_match=False)
                    return dict(cached)
            self._matched_thumb[device_id] = (thumb, time.time(), moving_now)

            helpers = self._get_helpers()

            # Run identify_screen on every CHANGED frame — the exact same method (and node set)
            # NavigationExecutor.localize (the Localize button / MCP) runs, with NOTHING
            # in front of it, so the overlay verdict is byte-for-byte the popover's.
            # (We deliberately do NOT gate this on a full-frame dHash-delta: that is a
            # MOTION signal, not a screen-identity one. On the app grid a tile-to-tile
            # focus move is only ~3 bits — below any motion threshold — so a dHash gate
            # would freeze the verdict on the previous tile, e.g. show apps_netflix while
            # Disney is focused. Correctness over the ~1/sec matcher cost.)
            # v3 cascade (TASK-104), same order as NavigationExecutor.localize: a signal
            # state answers before the matcher runs. (Live is the gate above.)
            state = helpers.classify_special_state(img)
            if state:
                result = {"candidates": [], "excluded_count": 0, "total": len(node_fps), "state": state,
                          "state_label": helpers.SPECIAL_STATE_LABELS.get(state)}
            else:
                _started = _phase_t0()
                result = helpers.identify_screen(img, node_fps)
                # Time it as its own phase (TASK-68 row 6) — but rate-limited, because
                # this runs on every frame. The matcher and its result are untouched.
                self._log_identify_screen(device_id, _started, result)
                # A low-confidence single answer is kept only when Jev confirms it (cached per node + frame,
                # rate-capped), else "unknown": the same function NavigationExecutor.localize calls.
                from backend_host.src.controllers.verification.jev_second_opinion import confirm_low_confidence
                confirm_low_confidence(helpers, img, node_fps, result, team_id=self.team_id,
                                       cache_key=userinterface_name)
            verdict = self._after_match(verdict_from_match(result), img, node_fps, helpers, device_id, motion)
            held_live = None
            # a settled screen read on purpose (opt-in) must not be replaced by the "live was seen a moment ago" hold
            if not settled_tick and hold_live(verdict, self._live_seen.get(device_id), time.time(), playing):
                self._live_seen[device_id] = time.time()
                held_live = self._live_node(userinterface_name)
                verdict = live_verdict(motion if isinstance(motion, dict) else None, held_live)

            cands = result.get("candidates") or []
            top = cands[0] if cands else None
            reason = result.get("reason")
            out = {
                "node": top["label"] if top else None,
                "confidence": top["confidence"] if top else 0.0,
                "excluded": result.get("excluded_count", 0),
                "total": result.get("total", len(node_fps)),
                # Which layer answered — 'rule' on this path, always.
                "tier": IDENTIFY_TIER_RULE,
                "verdict": verdict,
                "kind": verdict["kind"],
            }
            if verdict["kind"] == "live" and held_live:
                out["node"] = held_live["label"]
            # Diagnosis: identify_screen's own reason, verbatim, plus the door it maps
            # to. Emitted whenever the matcher produced a reason (an abstain today);
            # a match without one carries neither, so the payload stays small.
            if reason:
                out["reason"] = reason
                out["door"] = abstain_door(reason)
            if result.get("state"):
                out["state"] = result["state"]
                out["state_label"] = result.get("state_label")
            # Userinterface metadata: `company` is the brand label an editor
            # typed in (NULL = unknown). Surfaced in the per-frame payload for
            # downstream consumers and as a brand-aware extra keyword to the
            # Tier-2 `error` arm (see _screen_state). `is_media` is the
            # media-surface flag the Tier-2 `playback` arm consumes. Both
            # are best-effort: a missing row or a DB error just leaves the
            # payload without metadata and Tier-2 falls back to None.
            ui_meta = self._ui_meta(userinterface_name)
            company = ui_meta.get("company") if isinstance(ui_meta, dict) else None
            is_media = ui_meta.get("is_media") if isinstance(ui_meta, dict) else None
            if company:
                out["userinterface_company"] = company
            # Tier 2 (screen_state_cv) — only on a fresh matcher run, so the four
            # fields inherit the same "we actually looked at this frame" guarantee
            # the matcher verdict has. Lazy import like ImageHelpers above, so a
            # device without the dependency still loads.
            tier2 = self._screen_state(
                img, motion,
                company=company,
                is_media=is_media,
                device_id=device_id,
            )
            if tier2:
                out.update(tier2)
            # Mirror the matcher verdict (no gate_skip) for the next gate_skip to serve.
            self._last_match[device_id] = dict(out)
            self._record_change(device_id, frame_path, out, reason)
            # If the gate would have skipped this frame but the transition force-tail
            # overrode it, log the override so the trail shows the matcher ran on a
            # tail tick (otherwise the saved line is the only sign the gate let it through).
            if gate_reason and force_match:
                self._log_gate_skip(device_id, gate_reason, force_match=True)

            # BUG-0565: enqueue one match_runs entry per settled-screen matcher run.
            # The Redis-backed worker (vpt-match-runs-writer.service) is what
            # actually writes to the DB; the monitor never blocks on Supabase.
            #  - Same-verdict runs on a stable screen go to the steady-state
            #    channel (worker throttles to ~1 row / 10s per device).
            #  - Verdicts changing go to the `change` channel (every change
            #    lands — that's the input to v_node_transitions).
            #  - unknown / low_confidence hits go to the `alert` channel
            #    (every hit bumps the screen_fingerprints counter).
            try:
                self._enqueue_match_run_async(device_id, userinterface_name, result, dict(out), frame_path)
            except Exception as e:
                logger.debug(f"[localize] match_runs enqueue failed for {device_id}: {e}")

            return out
        except Exception as e:
            logger.warning(f"[localize] localize_frame failed for {device_id}: {e}")
            return None

    def _screen_state(self, img, motion: Optional[dict],
                      company: Optional[str] = None,
                      is_media: Optional[bool] = None,
                      device_id: Optional[str] = None) -> Optional[Dict[str, str]]:
        """Run the Tier-2 screen_state_cv cascade and return the four ADDITIVE fields
        ready to merge into the per-frame `localize` payload.

        `company` is the userinterface's free-text brand label (e.g. 'brand_a',
        'brand_b', 'brand_c'). When set, it is passed as an extra keyword to
        the `error` arm so a frame with a matching brand token is more likely to
        be flagged as 'visible' (a 'BRAND_A' token on a brand_a userinterface is
        a strong splash / login candidate). When None, behaviour is unchanged —
        no extra keyword, no extra answer, exactly the same payload as before
        the metadata existed. screen_state_cv is treated as a read-only consumer
        (the test suite and the constants live there), so the company-aware
        re-check is done by calling `scv.error()` separately with the extended
        keyword list and merging the result.

        `is_media` is the userinterface's media-surface flag (TRUE / FALSE /
        None). TRUE makes `scv.playback` answer 'playing' / 'paused' /
        'stopped' from the freeze-detector's own moving signal; FALSE makes
        it answer 'not_applicable' (the surface is not a player); None is
        today's behaviour — the arm abstains to 'unknown' because the
        monitor had no way to say "this is / is not media". As a side effect,
        a media surface (is_media=True) skips the OCR pass: broadcast slates
        cannot bear an error keyword, so the Tesseract call would burn cycles
        for no new information.

        Returns None on any failure (import error, missing module, malformed
        inputs) so the call site can fall back to the no-Tier-2 payload without
        an extra try/except. Lazy import of `shared.src.lib.ai.screen_state_cv`:
        a device that does not have it (e.g. a minimal install) still produces
        a valid matcher verdict and just leaves the Tier-2 fields absent. Same
        shape as `ImageHelpers` (line ~156-161): one lazy import, one helper,
        never raised.
        """
        try:
            from shared.src.lib.ai import screen_state_cv as scv
        except Exception as e:
            logger.debug(f"[localize] screen_state_cv unavailable, Tier 2 fields omitted: {e}")
            return None
        try:
            current_pct = None
            window_pct = None
            if isinstance(motion, dict):
                # motion.pct is "% of the frame that changed" (see detector.py).
                try:
                    current_pct = float(motion.get("pct"))
                except (TypeError, ValueError):
                    current_pct = None
                # The windowed series lives in the localizer (one deque per device_id)
                # — see localize_frame() — so loaded() can answer 'yes'/'no' on a
                # filled window and 'unknown' while the window is filling.
                win = self._pct_window.get(device_id)
                if win:
                    # Drop None entries so loaded() doesn't refuse the window on a gap.
                    window_pct = [v for v in win if v is not None]
            # Per-row inputs: `is_media` flows from the userinterface
            # metadata (the editor's media-surface flag); `tokens` comes
            # from the OCR pass; `audio_silence_seconds` is still unwired
            # in the standalone monitor (no AVQ call here) — pass None
            # rather than guess. Each Tier-2 arm abstains honestly on its
            # own missing input, so a missing `tokens` row still lets
            # `error` answer 'none' (which is the SAFE answer on an empty
            # token stream — see the docstring).
            #
            # Call the four arms separately instead of scv.screen_state(): loaded()
            # wants a SEQUENCE (line 267, "if not isinstance(changed_pct, (list, tuple))
            # return 'unknown'"), while playback() wants a single value (line 519,
            # _num(change) returns None on a sequence). The bundle's `changed_pct`
            # parameter can't satisfy both, so the only honest answer is to drive
            # each arm with the right shape.
            out: Dict[str, str] = {}
            try:
                if window_pct is not None:
                    out["loaded"] = scv.loaded(window_pct)
                else:
                    out["loaded"] = "unknown"
            except Exception as e:
                logger.debug(f"[localize] scv.loaded failed, leaving 'unknown': {e}")
                out["loaded"] = "unknown"
            try:
                out["overlay"] = scv.overlay(img)
            except Exception as e:
                logger.debug(f"[localize] scv.overlay failed, leaving 'unknown': {e}")
                out["overlay"] = "unknown"
            try:
                # `is_media` is the userinterface's media-surface flag (TRUE /
                # FALSE / None). When set it lets playback answer
                # 'playing' / 'paused' / 'stopped' or 'not_applicable'; when
                # None (the safe default) playback abstains to 'unknown' and
                # the payload shape is identical to today.
                out["playback"] = scv.playback(is_media, current_pct)
            except Exception as e:
                logger.debug(f"[localize] scv.playback failed, leaving 'unknown': {e}")
                out["playback"] = "unknown"
            try:
                # OCR pass for the `error` arm: a frame carries text. Tesseract
                # is expensive (~hundreds of ms per frame), so we (a) lazy-
                # import it (a host that never feeds a non-None `is_media`
                # UI still loads) and (b) throttle on `is_media is not True`
                # — a confirmed media broadcast cannot bear an error keyword,
                # so the broadcast slates won't burn OCR cycles. On any other
                # UI (is_media=False or None) the OCR runs and `error()` gets a
                # chance to answer 'visible' / 'none' / 'unknown' instead of
                # abstaining on every frame.
                tokens: Optional[Sequence[Any]] = None
                if is_media is not True:
                    try:
                        import pytesseract  # local import — see docstring
                        # --psm 6 = 'assume a single uniform block of text',
                        # which is what an error splash looks like (one
                        # centred paragraph). Cheaper than the full TSV and
                        # enough to populate the keyword token stream.
                        raw = pytesseract.image_to_string(img, config='--psm 6')
                        tokens = raw.split() if raw else ()
                    except Exception as e:
                        logger.debug(f"[localize] pytesseract OCR failed, error() abstains: {e}")
                        tokens = None
                out["error"] = scv.error(tokens)
            except Exception as e:
                logger.debug(f"[localize] scv.error failed, leaving 'unknown': {e}")
                out["error"] = "unknown"
            # Company passthrough: re-check `error` with the company name as an
            # extra keyword. The default keyword set is the well-known
            # 'error' / 'failed' / 'warning' family (see ERROR_KEYWORDS in
            # screen_state_cv); the company name is a brand label, not an
            # error term, so it lives in its own list and ONLY widens the
            # match. Opt-in: when company is None, the default run is the
            # only run, and the answer is unchanged. We re-use the OCR
            # token stream from the default run (no second Tesseract call)
            # so a brand-specific frame ('Brand_a  ERROR  503' for example)
            # can also be flagged; on a media surface `tokens` is None and
            # the re-check still abstains — same as today.
            company_norm = (company or "").strip().lower() or None
            if company_norm:
                try:
                    keywords = list(scv.ERROR_KEYWORDS) + [company_norm]
                    out["error"] = scv.error(tokens, keywords=keywords)
                except Exception as e:
                    logger.debug(f"[localize] company-aware error() failed, default kept: {e}")
            return out
        except Exception as e:
            logger.debug(f"[localize] screen_state_cv failed, Tier 2 fields omitted: {e}")
            return None

    def _log_identify_screen(self, device_id: str, started: float, result: Dict[str, Any]) -> None:
        """Emit `⏱ localize.identify_screen` for one frame — on CHANGE, else on the heartbeat.

        identify_screen runs on every captured frame (~5 fps, forever), so an
        unconditional line is 5 lines/s of noise into execution.txt. Instead: one line
        when the verdict signature changes (match->abstain, abstain->match, different
        node_id) and one per `_IDENTIFY_LOG_HEARTBEAT_SECONDS` otherwise, so a stable
        screen still yields a timing sample rather than silence. The heartbeat line
        carries how many frames have passed since the previous one (`frames=N`, this
        frame included), so a quiet stretch is legible as a rate, not as a gap.

        Never raises and never touches `result` — the overlay verdict is identical
        whether or not this fires.
        """
        try:
            sig = identify_screen_verdict(result)
            now = time.time()
            prev = self._identify_state.get(device_id)
            changed = prev is None or prev[0] != sig
            folded = 0 if prev is None else prev[2] + 1
            if not changed and (now - prev[1]) < _IDENTIFY_LOG_HEARTBEAT_SECONDS:
                self._identify_state[device_id] = (sig, prev[1], folded)
                return
            self._identify_state[device_id] = (sig, now, 0)
            _log_duration(IDENTIFY_SCREEN_PHASE, (time.perf_counter() - started) * 1000.0,
                          f"{identify_screen_detail(result)} site=monitor device={device_id} "
                          f"{'on-change' if changed else 'heartbeat'} frames={folded}")
        except Exception as e:
            logger.debug(f"[localize] _log_identify_screen failed for {device_id}: {e}")

    def _update_tick_motion(self, device_id: str, thumb):
        """Advance the per-cell tick-to-tick change streak; return the 4x4 MOVING mask (cells that
        changed on each of the last MOVING_BOX_TICKS ticks), or None before a second tick."""
        import numpy as np
        prev = self._tick_motion.get(device_id)
        changed = changed_cells(prev[0], thumb) if prev else None
        if changed is None:
            self._tick_motion[device_id] = (thumb, None)
            return None
        streak = prev[1] if prev[1] is not None else np.zeros(changed.shape, dtype=int)
        streak = np.where(changed, streak + 1, 0)
        self._tick_motion[device_id] = (thumb, streak)
        return streak >= MOVING_BOX_TICKS

    def _update_motion_state(self, device_id: str, motion: Optional[dict]) -> bool:
        """Track the fused motion state per device and decide if the NEXT tick must
        force a matcher call regardless of the gate.

        Returns True when the gate should be bypassed for this tick, i.e. when the
        state just flipped from 'live'/'motion' to 'static'/'ui' AND the new state
        has now been held for >= GATE_TRANSITION_FORCE_SECONDS. The force flag is
        one-shot per edge (`forced`): the next tick returns False and the gate returns
        to its normal decision until the state changes again. With no motion dict at all
        this returns False (the gate then defaults to "run the matcher").

        The previous state is preserved until the current state changes again, so a
        single motion→static edge is enough — we do not need a sustained settle
        streak in the gatekeeper on top of this; the gatekeeper has its own
        CONFIRM window and that is the input we read here.
        """
        try:
            if not isinstance(motion, dict):
                return False
            current = motion.get("state") or "static"
            now = time.time()
            entry = self._motion_state.get(device_id)
            if entry is None:
                # First observation: nothing to force yet — the screen is freshly
                # tracked and any settled result will come from the first matcher run.
                self._motion_state[device_id] = {"prev": current, "current": current, "since": now,
                                                 "forced": False}
                return False
            if current != entry["current"]:
                entry["prev"] = entry["current"]
                entry["current"] = current
                entry["since"] = now
                entry["forced"] = False
            prev = entry["prev"]
            held = now - entry["since"]
            # One-shot per edge (TASK-107 goal 6): without the flag every later tick of the
            # settled state forced the matcher too, so a carousel (band) on a 'ui' state after
            # a live->ui edge never got gated again.
            if (prev in ("live", "motion")) and (current in ("static", "ui")) \
                    and held >= GATE_TRANSITION_FORCE_SECONDS and not entry.get("forced"):
                entry["forced"] = True
                return True
            return False
        except Exception as e:
            logger.debug(f"[localize] _update_motion_state failed for {device_id}: {e}")
            return False

    def _enqueue_match_run_async(self, *args) -> None:
        """Hand a match_runs push to the background sender; drop it when 32 are already waiting."""
        if self._match_run_thread is None:
            self._match_run_thread = threading.Thread(target=self._match_run_sender, daemon=True,
                                                      name="localize-match-runs")
            self._match_run_thread.start()
        try:
            self._match_run_q.put_nowait(args)
        except queue.Full:
            pass

    def _match_run_sender(self) -> None:
        while True:
            args = self._match_run_q.get()
            self._enqueue_match_run(*args)

    def _enqueue_match_run(self, device_id: str, userinterface_name: str,
                            result: Dict[str, Any], out: Dict[str, Any],
                            frame_path: str) -> None:
        """BUG-0565: push one match_runs entry to the Redis queue.

        The monitor never blocks on Supabase.  The vpt-match-runs-writer
        service (modeled on vpt-discard-incidents) drains the queue
        and inserts rows.

        Channel selection:
          - verdict changed vs. last emit (per device) → `change` channel
          - unknown / low_confidence / no_signal → `alert` channel
          - otherwise → `normal` channel (worker throttles)
        """
        try:
            from shared.src.lib.queue.match_runs_queue import (
                build_payload, push, CHANNEL_NORMAL,
            )
            from shared.src.lib.utils.monitor_profile import resolve_monitor_profile

            # Profile: read the same env this host used to start.  For a
            # device with DEVICE{N}_MONITOR_PROFILE set, pass the index;
            # otherwise the helper falls back to the host-level profile.
            device_index = None
            m = re.match(r'^device(\d+)$', device_id or '', re.IGNORECASE)
            if m:
                try:
                    device_index = int(m.group(1))
                except ValueError:
                    device_index = None
            profile = resolve_monitor_profile(device_index)

            # Compute a 64-bit dhash from the live frame so the
            # screen_fingerprints counter can dedupe across runs of the
            # same unknown screen.  Falls back to None if the hash fails
            # (the worker handles None cleanly).
            dhash_int: Optional[int] = None
            try:
                from shared.src.lib.utils.image_hash import dhash_hex
                import cv2 as _cv2
                img = _cv2.imread(frame_path, _cv2.IMREAD_GRAYSCALE)
                if img is not None:
                    h = dhash_hex(img, 16, 256)  # 256-bit dhash
                    # Truncate to 63 bits so it fits in a bigint.
                    dhash_int = int(h[:15], 16)
            except Exception:
                dhash_int = None

            # Severity routing.
            kind = (out.get('kind') or 'unknown').lower()
            is_alert = kind in ('unknown', 'low_confidence', 'no_signal', 'live', 'overlay')

            # Verdict change detection (per device, in-memory only).
            change = False
            try:
                prev = self._last_match.get(device_id) or {}
                prev_kind = (prev.get('kind') or '').lower()
                prev_node = prev.get('node')
                cur_node = out.get('node')
                if prev_kind and prev_kind != kind:
                    change = True
                elif prev_node != cur_node and not (prev_node is None and cur_node is None):
                    change = True
            except Exception:
                change = False

            # Frame URL: prefer the same one the API uses.  The monitor's
            # stream is at /stream/<capture_dir>/; we just store the path
            # so the worker can resolve it if needed.
            frame_url = frame_path if frame_path else None

            payload = build_payload(
                team_id=self.team_id or 'unknown',
                host_name=os.environ.get('HOST_NAME', 'unknown'),
                userinterface_name=userinterface_name,
                source='monitor_localize',
                result=result,
                device_id=device_id,
                profile=profile,
                dhash=dhash_int,
                frame_url=frame_url,
            )
            severity = 'change' if change else ('alert' if is_alert else 'normal')
            push(payload, severity=severity)
        except Exception as e:
            # Never let the queue path break the matcher.  The matcher
            # result is already returned to the caller; we are best-effort.
            logger.debug(f'[localize] _enqueue_match_run: {e}')

    def _log_gate_skip(self, device_id: str, gate_reason: str, force_match: bool) -> None:
        """Throttled trail for the motion gate: log the gate decision on CHANGE, plus a
        30 s heartbeat. Same BUG-0093 shape as `_log_identify_screen`, so a sustained
        live stretch still leaves one `localize.gate` line per interval instead of
        silence, and a real transition (e.g. motion→static tail forcing a match) gets
        its own `force` line on the override tick. Never raises.
        """
        try:
            sig = f"{gate_reason}:{'force' if force_match else 'skip'}"
            now = time.time()
            prev = self._gate_log_state.get(device_id)
            changed = prev is None or prev[0] != sig
            folded = 0 if prev is None else prev[2] + 1
            if not changed and (now - prev[1]) < _GATE_LOG_HEARTBEAT_SECONDS:
                self._gate_log_state[device_id] = (sig, prev[1], folded)
                return
            self._gate_log_state[device_id] = (sig, now, 0)
            tag = "on-change" if changed else "heartbeat"
            logger.info(f"[localize] gate={gate_reason} device={device_id} "
                        f"{'force' if force_match else 'skip'} {tag} frames={folded}")
        except Exception as e:
            logger.debug(f"[localize] _log_gate_skip failed for {device_id}: {e}")

    def _record_change(self, device_id: str, frame_path: str, out: Dict[str, Any],
                       reason: Optional[str]) -> None:
        """Forensic trail: on a verdict CHANGE, log it with a DURABLE reference to the
        frame — so a false positive spotted during long live monitoring (any screen,
        any time) can be fetched and used to fine-tune.

        We do NOT copy the frame: hot_cold_archiver already archives captures to cold
        (`captures/{hour}/`, ~1fps, 24h rolling), so we just log WHERE it lands instead
        of duplicating it (no extra disk, no extra cleanup). The hot file dies in ~60s,
        so we compute the cold path from the frame's mtime — the archiver names a slot
        `capture_{seconds_today*5:06d}.jpg`, identical for any frame in that second, so
        the computed path is exact (the cold copy may be a neighbouring frame of the
        same second — accepted; missing a rare sub-second case is fine, another comes).
        Best-effort; never affects localization. Signature compare ⇒ one line per real
        screen change. `no_signal` logs at WARNING (should never occur on live)."""
        try:
            state = out.get("state")
            sig = state or out.get("node") or "unknown"
            if self._last_sig.get(device_id) == sig:
                return
            self._last_sig[device_id] = sig

            verdict = (out.get("state_label") or out.get("node") or "unknown")
            src = os.path.basename(frame_path or "")
            # Durable cold reference, mirroring hot_cold_archiver.calculate_time_based_name
            # (captures → capture_{seconds_today*5:06d}.jpg under captures/{hour}/).
            cold, ts = "", ""
            try:
                import datetime as _dt
                d = _dt.datetime.fromtimestamp(os.path.getmtime(frame_path))
                ts = d.isoformat(timespec="seconds")
                name = f"capture_{(d.hour * 3600 + d.minute * 60 + d.second) * 5:06d}.jpg"
                if "/hot/captures/" in frame_path:
                    root = frame_path.split("/hot/captures/")[0] + "/captures"
                elif "/captures/" in frame_path:
                    root = frame_path.split("/captures/")[0] + "/captures"
                else:
                    root = os.path.dirname(frame_path)
                cold = os.path.join(root, str(d.hour), name)
            except Exception:
                pass

            line = (f"[localize] {device_id} screen={verdict} "
                    f"conf={out.get('confidence', 0):.2f} excluded={out.get('excluded', 0)}/"
                    f"{out.get('total', 0)} hot={src} cold={cold} t={ts}"
                    + (f" reason={reason}" if reason else ""))
            if state == "no_signal":
                logger.warning(line + "  <- no_signal: unexpected on a live broadcast")
            else:
                logger.info(line)
        except Exception as e:
            logger.debug(f"[localize] _record_change failed for {device_id}: {e}")
