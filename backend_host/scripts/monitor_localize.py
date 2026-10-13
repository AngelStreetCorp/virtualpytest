"""Per-frame screen identification for the monitoring overlay (Localize).

The capture monitor already decodes every frame for freeze/blackscreen. This
adds a cheap (~few ms) "where am I?" identification on top, throttled to ~1/sec,
written into the per-frame JSON as `localize` so the frontend overlay can show
the current node the same way it shows freeze.

It is OPT-IN per device: only runs when `DEVICE{N}_USERINTERFACE` is set in the
host `.env` (the same var the controller/scripts already use for navigation
defaults). When unset, `localize_frame()` returns None and no field is written.

Unlike `NavigationExecutor.localize()` this runs in the standalone vpt-monitor
process, so it loads node fingerprints straight from the DB (base `data.fingerprint`,
no variant resolution) and uses ONLY the deterministic dHash + focus layers — it
does NOT run the title-translation layer (a network/LLM call), which is too heavy
for a per-second loop. The result is the single best candidate by confidence, or
"unknown" when nothing is recognized — which is all the overlay needs.
"""

import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Sequence

from shared.src.lib.utils.phase_timing import (
    t0 as _phase_t0,
    log_duration as _log_duration,
)
from shared.src.lib.utils import cv2_io

logger = logging.getLogger("capture_monitor")

# How long a UI's loaded fingerprint set is reused before re-querying the DB.
# Lets a re-fingerprint (backfill / Reset fingerprint) be picked up without a
# monitor restart, without querying the DB on every frame.
_FP_TTL_SECONDS = 300

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
#   'full'              → SKIP, reason 'live'     (full-frame distributed motion)
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
        OR `motion.kind == 'full'`              → 'live'
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
    runs in the standalone vpt-monitor process, which must not import the navigation
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
        from collections import deque
        self._pct_window: Dict[str, deque] = {}

    def _get_helpers(self):
        if self._helpers is None:
            from backend_host.src.controllers.verification.image_helpers import ImageHelpers
            # captures_path / av_controller are unused by the matching methods we call.
            self._helpers = ImageHelpers(None, None)
        return self._helpers

    def _resolve_ui(self, device_id: str) -> Optional[tuple]:
        """Map device_id ('device4') -> (DEVICE4_USERINTERFACE, DEVICE4_VARIANT), cached.

        Returns None when no userinterface is configured (feature disabled). Variant
        defaults to 'base' when DEVICE{N}_VARIANT is unset — same as scripts/goto.
        """
        if device_id in self._ui_by_device:
            return self._ui_by_device[device_id]
        resolved = None
        m = re.match(r"device(\d+)$", device_id or "")
        if m:
            n = m.group(1)
            val = os.getenv(f"DEVICE{n}_USERINTERFACE")
            ui = val.strip() if val and val.strip() else None
            if ui:
                var = (os.getenv(f"DEVICE{n}_VARIANT") or "base").strip() or "base"
                resolved = (ui, var)
        self._ui_by_device[device_id] = resolved
        if resolved:
            logger.info(f"[localize] Enabled for {device_id} → userinterface "
                        f"'{resolved[0]}' variant '{resolved[1]}'")
        return resolved

    def _load_node_fps(self, userinterface_name: str) -> List[Dict[str, Any]]:
        """Fingerprinted+verified nodes for a UI (base data.fingerprint), TTL-cached."""
        cached = self._fps_by_ui.get(userinterface_name)
        if cached and (time.time() - cached["ts"]) < _FP_TTL_SECONDS:
            return cached["node_fps"]

        node_fps: List[Dict[str, Any]] = []
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
        self._fps_by_ui[userinterface_name] = {"ts": time.time(), "node_fps": node_fps}
        # Best-effort cache of the userinterface record (id, name, company,
        # is_media). `company` is the opt-in metadata the per-frame payload
        # carries; `is_media` drives the Tier-2 `playback` arm. See
        # _screen_state and the gate log for the same record.
        self._ui_meta_by_name[userinterface_name] = {"ts": time.time(), "ui": ui_record}
        return node_fps

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

    def localize_frame(self, device_id: str, frame_path: str,
                       motion: Optional[dict] = None) -> Optional[Dict[str, Any]]:
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
            gate_reason = gate_motion_decision(motion) if motion is not None else None
            force_match = self._update_motion_state(device_id, motion)
            if gate_reason and not force_match:
                cached = self._last_match.get(device_id)
                if cached is not None:
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
                    self._log_gate_skip(device_id, gate_reason, force_match=False)
                    return out
                # No cache (very first frame is gated): fall through and run the
                # matcher so we have SOMETHING to serve next time we skip.

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
                _out = {"node": None, "confidence": 0.0, "excluded": 0, "total": 0}
                if _tier2:
                    _out.update(_tier2)
                return _out

            import cv2
            img = cv2_io.imread(frame_path)
            if img is None:
                return None

            helpers = self._get_helpers()

            # Run identify_screen on EVERY frame — the exact same method (and node set)
            # NavigationExecutor.localize (the Localize button / MCP) runs, with NOTHING
            # in front of it, so the overlay verdict is byte-for-byte the popover's.
            # (We deliberately do NOT gate this on a full-frame dHash-delta: that is a
            # MOTION signal, not a screen-identity one. On the app grid a tile-to-tile
            # focus move is only ~3 bits — below any motion threshold — so a dHash gate
            # would freeze the verdict on the previous tile, e.g. show apps_netflix while
            # Disney is focused. Correctness over the ~1/sec matcher cost.)
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
            }
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
                          f"{identify_screen_detail(result)} site=monitor "
                          f"{'on-change' if changed else 'heartbeat'} frames={folded}")
        except Exception as e:
            logger.debug(f"[localize] _log_identify_screen failed for {device_id}: {e}")

    def _update_motion_state(self, device_id: str, motion: Optional[dict]) -> bool:
        """Track the fused motion state per device and decide if the NEXT tick must
        force a matcher call regardless of the gate.

        Returns True when the gate should be bypassed for this tick, i.e. when the
        state just flipped from 'live'/'motion' to 'static'/'ui' AND the new state
        has now been held for >= GATE_TRANSITION_FORCE_SECONDS. The force flag is
        one-shot: once the matcher runs and updates `_last_match`, the gate returns
        to its normal decision on the following tick. With no motion dict at all
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
                self._motion_state[device_id] = {"prev": current, "current": current, "since": now}
                return False
            if current != entry["current"]:
                entry["prev"] = entry["current"]
                entry["current"] = current
                entry["since"] = now
            prev = entry["prev"]
            held = now - entry["since"]
            if (prev in ("live", "motion")) and (current in ("static", "ui")) \
                    and held >= GATE_TRANSITION_FORCE_SECONDS:
                return True
            return False
        except Exception as e:
            logger.debug(f"[localize] _update_motion_state failed for {device_id}: {e}")
            return False

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
