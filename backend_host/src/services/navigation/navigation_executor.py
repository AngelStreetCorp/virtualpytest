"""
Navigation Execution System

Unified navigation executor with complete tree management, pathfinding, and execution capabilities.
Consolidates all navigation functionality without external dependencies.
"""

import os
import time
import threading
import uuid
import json
from typing import Dict, List, Optional, Any, Tuple

# Core imports
from  backend_host.src.services.navigation.navigation_pathfinding import find_shortest_path
from shared.src.lib.utils.navigation_exceptions import NavigationTreeError, UnifiedCacheError, PathfindingError, DatabaseError
from shared.src.lib.utils.navigation_cache import populate_unified_cache
from shared.src.lib.utils.phase_timing import (
    t0 as _phase_t0,
    log_duration as _log_duration,
    log_phase as _log_phase,
)

# Helper functions (extracted for maintainability)
from backend_host.src.services.navigation.navigation_executor_helpers import (
    find_node_by_label,
    find_edges_from_node,
    find_edge_by_target_label,
    find_edge_with_action_command,
    get_node_sub_trees_with_actions,
    find_action_in_nested_trees
)

# Tree management functions (extracted for maintainability)
from backend_host.src.services.navigation.navigation_executor_tree_manager import (
    load_navigation_tree as tree_manager_load_navigation_tree,
    discover_complete_hierarchy as tree_manager_discover_complete_hierarchy,
    format_tree_for_hierarchy as tree_manager_format_tree_for_hierarchy,
    build_unified_tree_data as tree_manager_build_unified_tree_data
)
from shared.src.lib.utils import cv2_io


# Auto-mode verification: skip a step's verification iff BOTH the edge's
# confidence and the destination node's confidence are at or above this
# threshold. Below it (or no data at all) → verify. The last step in a
# path is always verified regardless of mode.
AUTO_VERIFY_CONFIDENCE_THRESHOLD = 0.7

# Allowed verification modes for navigation execution. CLI / frontend / route
# layers must pass exactly one of these. Default is 'end' — verify only the
# last step's destination.
VERIFICATION_MODES = ('end', 'each', 'auto')


# How long a "where am I?" probe may spend before deciding we are somewhere else. Five of them:
# am I at the target / at home (no tracked position), is the stale position still right, am I
# already at the target the context names, and is the target that is one edge away already
# showing (a position-tracking bug check).
#
# All of them run before a command reaches the device, and all used to honour the node's own
# verification timeouts — which are sized for "wait for this screen to appear after we acted on
# it", not for "is it showing right now". On the youtube-android-mobile tree that was 60s for the
# target (WaitForVideoToAppear) plus 20s+20s for home: 101 seconds of a 139-second run spent
# before the first tap, on a phone that was plainly sitting on its launcher.
#
# A screen that IS showing answers in well under a second (0.2-0.7s for the element checks, 2.1s
# for the motion one). Getting this wrong in the tight direction is cheap: the probe says "not
# here", and navigation either takes the edge it was about to take anyway (one step away) or
# starts from entry (no, stale or wrong position) — slower, and on a web tree whose entry edge
# resets the app, the state built so far is reset with it.
#
# The one-step-away probe was the uncapped one that cost the most: on a TodoMVC web tree
# (2026-09-29) it waited out every leg of the next node's 10 s web verifications before each hop
# after the first — 60 s of a 108 s testcase, for a screen that was never there.
POSITION_PROBE_TIMEOUT_MS = 5000

# How long a position whose verifications just PASSED is trusted without probing it again
# (BUG-0195). The one-step-away probe above ran before every hop after the first even when the
# previous hop had verified the position milliseconds earlier: it checked the TARGET's
# verifications, which are not showing yet, so each of its legs waited out the 5 s cap — 347 s of
# 597 s over 16 TodoMVC testcases (2026-09-30). Worse, a target verified by text the current
# screen also shows "passed", the hop was skipped and the action under test never ran.
#
# Only a node whose own verifications ran and passed is marked (`last_verified_node_id` +
# `last_verified_timestamp`): not a destination without verifications, not a hop that skipped
# verification, not a position set by update_current_position. Anything that sends the device
# commands outside a navigation (testcase action blocks, ad-hoc /host/action/executeBatch)
# forgets the mark. `VPT_POSITION_TRUST_SECONDS` (host .env), read at each navigation;
# 0 turns the skip off.
POSITION_TRUST_SECONDS_DEFAULT = 10.0


def position_trust_seconds() -> float:
    """VPT_POSITION_TRUST_SECONDS, or the default when unset or unusable. Never negative."""
    raw = os.environ.get('VPT_POSITION_TRUST_SECONDS', '')
    if not str(raw).strip():
        return POSITION_TRUST_SECONDS_DEFAULT
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return POSITION_TRUST_SECONDS_DEFAULT


def forget_position_verification(nav_context: Optional[Dict[str, Any]], reason: str = '') -> None:
    """Something may have changed the screen since the position was verified: stop trusting it.

    The tracked position itself is kept (it is still the best guess); only the verified mark goes,
    so the next one-step navigation probes again.
    """
    if not isinstance(nav_context, dict):
        return
    had_mark = bool(nav_context.get('last_verified_timestamp') or nav_context.get('last_verified_node_id'))
    nav_context['last_verified_timestamp'] = 0
    nav_context['last_verified_node_id'] = None
    if had_mark:
        print(f"[@navigation_executor] Position no longer counts as just verified ({reason or 'device commands sent'})")


# --------------------------------------------------------------------------
# identify_screen timing (TASK-68 row 6).
#
# identify_screen is the cost a Tier-3 model is compared AGAINST, and until now
# its elapsed time was swallowed by the enclosing nav.hop.verify_destination
# aggregate (frame capture + fingerprint match + OCR + verification logic all in
# one number). These wrappers give it its own `⏱ localize.identify_screen` line,
# so the row-1/row-2 probe supplies the CPU delta and load automatically.
#
# The matching itself is untouched: the same method on the same (img, node_fps)
# runs, and the SAME dict object comes back. Only a line is added. Timing and the
# detail string are best-effort -- if either fails the call still returns exactly
# what the matcher returned (phase_timing's contract: never raises, never changes
# a result), and an exception from identify_screen itself still propagates to the
# caller's own handler unchanged.
#
# The detail reports the VERDICT and the counts, so a reader can tell a match from
# an abstain (and a low-confidence match from a confident one) without opening the
# frame. Keys are identify_screen's own result keys, read off
# image_helpers.ImageHelpers.identify_screen (see its docstring + the tail at the
# end of the method): `candidates` (top entry carries `node_id` and `confidence`),
# `excluded_count`, `total`, and `state` when nothing matched. `reason` is
# deliberately NOT logged here -- it is the abstain-door input TASK-68 row 7 owns.
#
# monitor_localize.py carries the same two helpers verbatim: the standalone
# vpt-monitor process must not import this module (it would drag the whole
# navigation stack into the capture loop), so the small formatter is duplicated
# rather than shared. Keep the two copies in step.
# --------------------------------------------------------------------------

IDENTIFY_SCREEN_PHASE = 'localize.identify_screen'


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


def run_identify_screen(helpers, img, node_fps: List[Dict[str, Any]], site: str) -> Dict[str, Any]:
    """`helpers.identify_screen(img, node_fps)` plus one `⏱ localize.identify_screen` line.

    Returns the matcher's own result, unmodified. `site` names the call site so two
    callers sharing the phase name stay distinguishable in the log.
    """
    started = _phase_t0()
    result = helpers.identify_screen(img, node_fps)      # outside the try: its errors are the caller's
    try:
        _log_duration(IDENTIFY_SCREEN_PHASE, (time.perf_counter() - started) * 1000.0,
                      f"{identify_screen_detail(result)} site={site}")
    except Exception:
        pass
    return result


class NavigationExecutor:
    """
    Standardized navigation executor that orchestrates action and verification execution
    to provide complete navigation functionality.
    
    CRITICAL: Do not create new instances directly! Use device.navigation_executor instead.
    Each device has a singleton NavigationExecutor that preserves current position and tree state.
    """
    
    @classmethod
    def get_for_device(cls, device):
        """
        Factory method to get the device's existing NavigationExecutor.
        
        RECOMMENDED: Use device.navigation_executor directly instead of this method.
        
        Args:
            device: Device instance
            
        Returns:
            The device's existing NavigationExecutor instance
            
        Raises:
            ValueError: If device doesn't have a navigation_executor
        """
        if not hasattr(device, 'navigation_executor') or not device.navigation_executor:
            raise ValueError(f"Device {device.device_id} does not have a NavigationExecutor. "
                           "NavigationExecutors are created during device initialization.")
        return device.navigation_executor
    
    def __init__(self, device, _from_device_init: bool = False):
        """Initialize NavigationExecutor"""
        # Validate required parameters - fail fast if missing
        if not device:
            raise ValueError("Device instance is required")
        if not device.host_name:
            raise ValueError("Device must have host_name")
        if not device.device_id:
            raise ValueError("Device must have device_id")
        
        # Warn if creating instance outside of device initialization
        if not _from_device_init:
            import traceback
            print(f"⚠️ [NavigationExecutor] WARNING: Creating new NavigationExecutor instance for device {device.device_id}")
            print(f"⚠️ [NavigationExecutor] This may cause state loss! Use device.navigation_executor instead.")
            print(f"⚠️ [NavigationExecutor] Call stack:")
            for line in traceback.format_stack()[-3:-1]:  # Show last 2 stack frames
                print(f"⚠️ [NavigationExecutor]   {line.strip()}")
        
        # Store instances directly
        self.device = device
        self.host_name = device.host_name
        self.device_id = device.device_id
        self.device_model = device.device_model
        self.device_name = device.device_name
        self.unified_graph = None
        # Preview cache: (tree_id, current_node, target_node) -> preview_result
        self._preview_cache = {}
        
        # Async execution tracking (for navigation polling)
        self._executions: Dict[str, Dict[str, Any]] = {}  # execution_id -> execution state
        self._lock = threading.Lock()

    def _mark_position_verified(self, node_id: str) -> None:
        """`node_id`'s own verifications just ran and passed on the live screen (BUG-0195)."""
        nav_context = self.device.navigation_context
        nav_context['last_verified_node_id'] = node_id
        nav_context['last_verified_timestamp'] = time.time()

    @staticmethod
    def _recently_verified_age_s(nav_context: Dict[str, Any], node_id: str) -> Optional[float]:
        """Seconds since `node_id` was verified, when that is within the trust window; else None."""
        trust_s = position_trust_seconds()
        verified_at = nav_context.get('last_verified_timestamp') or 0
        if trust_s <= 0 or not verified_at or not node_id or nav_context.get('last_verified_node_id') != node_id:
            return None
        age_s = time.time() - verified_at
        return age_s if 0 <= age_s <= trust_s else None

    @staticmethod
    def _verification_phase_detail(verification_result: Optional[Dict[str, Any]]) -> str:
        """'success=.. legs=passed/total' for the ⏱ lines around verify_node calls."""
        try:
            vr = verification_result or {}
            detail = f"success={vr.get('success')} legs={vr.get('passed_count', 0)}/{vr.get('total_count', 0)}"
            if vr.get('has_verifications') is False:
                detail += ' has_verifications=False'
            return detail
        except Exception:
            return ''

    def _sync_unified_graph(
        self,
        tree_id: str,
        team_id: str,
        userinterface_name: str = None,
    ):
        """Refresh `self.unified_graph` from the variant-aware cache.

        The cache key includes the active variant (see VARIANT.md §6), but
        `self.unified_graph` is a per-executor snapshot that becomes stale on
        variant switch — call this at the entry of any code path that reads
        the graph for the current execution scope so the snapshot tracks
        `device.navigation_context['variant']`.

        Returns the freshly-loaded graph (or None if neither cache nor DB
        could supply one). On miss this attempts a single populate via
        `load_navigation_tree` so cold caches self-heal.
        """
        if not tree_id or not team_id:
            return self.unified_graph
        from shared.src.lib.utils.navigation_cache import get_cached_unified_graph
        variant = None
        if hasattr(self.device, 'navigation_context') and self.device.navigation_context:
            variant = self.device.navigation_context.get('variant')
        cached = get_cached_unified_graph(tree_id, team_id, variant=variant)
        if not cached and userinterface_name:
            try:
                self.load_navigation_tree(userinterface_name, team_id)
                cached = get_cached_unified_graph(tree_id, team_id, variant=variant)
            except Exception as load_exc:
                print(f"[@navigation_executor:_sync_unified_graph] Auto-populate failed: {load_exc}")
        if cached is not None:
            self.unified_graph = cached
        return cached

    def localize(self, team_id: str, userinterface_name: str, tree_id: str = None) -> Dict[str, Any]:
        """Identify which node the live device screen matches (Localize).

        Captures the current frame, fingerprints it (dHash + focus), and ranks it
        against every active node's stored fingerprint in the ACTIVE VARIANT's graph
        by exclusion — returns ranked candidates (never guesses between true ties)
        plus how many nodes were confidently excluded. Variant is read from
        `device.navigation_context['variant']`, so scripts/goto/MCP all localize in
        the same scope they execute in. tree_id is resolved from userinterface_name
        when not supplied (device-control has only the UI name, not a tree id).
        """
        import cv2
        from backend_host.src.controllers.verification.image_helpers import ImageHelpers

        variant = (getattr(self.device, 'navigation_context', None) or {}).get('variant')

        # 1. Resolve the root tree id from the userinterface when not given
        if not tree_id:
            load = self.load_navigation_tree(userinterface_name, team_id)
            if not load.get('success'):
                return {'success': False, 'error': load.get('error', 'Failed to load navigation tree'), 'candidates': []}
            tree_id = load.get('tree_id')

        # 2. Variant-aware graph (self-heals a cold cache via load_navigation_tree).
        #    The cached unified graph is the load-once source for candidates — it is
        #    rebuilt only on change (tree/node/edge save), never per call.
        graph = self._sync_unified_graph(tree_id, team_id, userinterface_name)
        if graph is None:
            return {'success': False, 'error': 'Navigation graph unavailable', 'candidates': []}

        # 2. Collect candidate nodes (variant-resolved). A node is a localize
        #    candidate only if it has a fingerprint AND at least one verification —
        #    a node with no verification is deemed unrecognizable (e.g. live) and
        #    is excluded from the list entirely (no point fingerprinting/testing it).
        node_fps = []
        for node_id, data in graph.nodes(data=True):
            if (data.get('variant_state') or {}).get('active') is False:
                continue
            # Localize is FINGERPRINT-based: a node with a stored fingerprint is recognizable on its
            # own — do NOT require a hand-authored verification (that gate wrongly excluded
            # fingerprint-only nodes from the candidate set).
            fp = data.get('__fingerprint')
            if fp and fp.get('dhash'):
                node_fps.append({'node_id': node_id, 'label': data.get('label', node_id), 'fingerprint': fp})
        if not node_fps:
            return {'success': False, 'variant': variant, 'candidates': [], 'total': 0,
                    'error': 'No fingerprinted nodes for this interface — capture screenshots first'}

        # 3. Capture the live frame
        av_controller = self.device._get_controller('av')
        if not av_controller:
            return {'success': False, 'error': 'No AV controller for device', 'candidates': []}
        frame_path = av_controller.take_screenshot()
        img = cv2_io.imread(frame_path) if frame_path else None
        if img is None:
            return {'success': False, 'error': 'Failed to capture current frame', 'candidates': []}

        # Build a public URL to the captured frame so the UI can show "what was localized"
        # in a new tab (esp. on failure). Same host stream/capture URL the screenshot
        # button uses. Non-fatal: a URL-build failure must never break localize.
        frame_url = self._frame_url_from_path(frame_path)

        # 4. Identify the screen — the SINGLE shared Localize implementation
        #    (dHash+focus match → title disambiguation → dHash fallback narrowing →
        #    capture-state fallback). The monitor overlay calls the SAME method, so
        #    both produce identical results from the same frame + node set. No
        #    confidence floor (whatever match_fingerprint returns), no graph-based
        #    child-priority (best candidate by confidence) — see identify_screen.
        helpers = ImageHelpers(None, av_controller)
        # Timed as its own phase (TASK-68 row 6): this is the number a model call is
        # compared against, and nav.hop.verify_destination cannot separate it from
        # frame capture / OCR. Logged BEFORE confirm_low_confidence / shadow so the
        # window is the matcher alone.
        result = run_identify_screen(helpers, img, node_fps, 'mcp')
        result.update({'success': True, 'variant': variant, 'frame_url': frame_url})

        # A low-confidence single answer is kept only when Jev confirms it, else "unknown" (TASK-47 G13);
        # the monitor calls the same function, so both give the same verdict.
        from backend_host.src.controllers.verification.jev_second_opinion import (
            confirm_low_confidence, localize_shadow)
        confirm_low_confidence(helpers, img, node_fps, result, team_id=team_id, cache_key=userinterface_name)

        # Shadow second opinion (TASK-47 G13): ties / abstain only, background, logged,
        # never changes `result` and never waits. No-op when Jev is off.
        localize_shadow(helpers, img, node_fps, result, team_id=team_id,
                        userinterface_name=userinterface_name, tree_id=tree_id)

        print(f"[@navigation_executor:localize] variant={variant or 'base'} "
              f"candidates={[c['node_id'] for c in (result.get('candidates') or [])[:5]]} "
              f"excluded={result.get('excluded_count', 0)}/{result.get('total', 0)}"
              f"{' state=' + result['state'] if result.get('state') else ''}")

        # 6. Classifier diagnostics: the same fields the per-frame `localize` worker
        #    writes to `analysis_data.localize` (motion / freeze / blackscreen / macroblocks /
        #    loaded / overlay / playback / error). The popover surfaces them so an operator
        #    can tell at a glance why a match did or didn't happen. We read the latest
        #    `analysis_data_*.json` instead of recomputing — the worker is the canonical
        #    source for the Tier-2 cascade and a fresh motion verdict, and the staleness
        #    is bounded by the worker's poll interval (~1s). Fully non-fatal: a missing
        #    JSON or a parse error leaves `classifier_diagnostics=None` so the matcher
        #    verdict is unchanged.
        result['classifier_diagnostics'] = self._read_classifier_diagnostics(frame_path)

        # 7. The two fingerprints behind the verdict, for the popover's Copy rows (TASK-88 row 9):
        #    the live frame's (same layers as compute_fingerprint, minus the OCR ones, so no extra
        #    tesseract call) and the stored one of the top node. Plus every candidate node's label
        #    for the "Which screen was it?" dropdown. Device-control only — identify_screen and the
        #    per-frame monitor payload are untouched.
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        result['live_fingerprint'] = {'v': helpers.FINGERPRINT_VERSION, 'dhash': helpers._dhash_hex(gray),
                                      'regions': helpers._region_dhashes(gray),
                                      'crop': helpers._focus_crop_hex(img), 'focus': result.get('live_focus')}
        top = ((result.get('candidates') or [None])[0] or (result.get('ranked') or [None])[0]
               or result.get('best_excluded') or {})
        fp_by_id = {nf['node_id']: nf['fingerprint'] for nf in node_fps}
        result['matched_fingerprint'] = fp_by_id.get(top.get('node_id'))
        result['nodes'] = sorted(({'node_id': nf['node_id'], 'label': nf['label']} for nf in node_fps),
                                 key=lambda n: str(n['label']).lower())
        return result

    def _capture_folder(self) -> Optional[str]:
        """Map this device to its capture folder (e.g. 'capture3' for 'device3').

        Used to locate the per-frame metadata JSON. The mapping is the standard
        'deviceN' → 'captureN' convention. Returns None for an unrecognised id so
        callers can fall back without an extra try/except.
        """
        did = getattr(self, 'device_id', '') or ''
        if did.startswith('device'):
            n = did[len('device'):]
            if n.isdigit():
                return f'capture{n}'
        return None

    def _latest_analysis_data(self, frame_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Return the most recent per-frame analysis_data JSON for this device.

        Looks in the standard metadata path the capture_monitor writes to (HOT mode
        first, COLD fallback). Picks the highest-numbered `capture_*.json` whose
        mtime is the most recent — that is the worker's most recent verdict for this
        device. Returns None if the dir is missing, the file is unreadable, or the
        JSON does not parse; the caller treats None as 'diagnostics unavailable'.
        """
        import glob
        from shared.src.lib.utils.storage_path_utils import get_metadata_path
        cap = self._capture_folder()
        if not cap:
            return None
        meta_dir = get_metadata_path(cap)
        if not os.path.isdir(meta_dir):
            return None
        # Prefer the file with the highest mtime so a slow worker doesn't make us read
        # a half-written older one. The capture_monitor writes atomically (temp +
        # rename), so the highest mtime is always the latest full payload.
        files = sorted(glob.glob(os.path.join(meta_dir, 'capture_*.json')),
                       key=lambda p: os.path.getmtime(p), reverse=True)
        for path in files[:3]:                                  # check the top 3 in case one is mid-write
            try:
                with open(path) as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
            except Exception:
                continue
        return None

    def _read_classifier_diagnostics(self, frame_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Read motion / freeze / blackscreen / macroblocks / Tier-2 from the latest
        per-frame analysis_data JSON. Returns None if anything is missing — the
        popover then renders a 'diagnostics unavailable' line for this call.

        Best-effort: any failure (missing file, malformed JSON, missing keys) returns
        a partial dict with the keys that DID parse, never raises.
        """
        data = self._latest_analysis_data(frame_path)
        if not data:
            return None
        out: Dict[str, Any] = {}
        # Motion (kind, pct, state, raw_state) — all four keys if present
        motion = data.get('motion')
        if isinstance(motion, dict):
            motion_out = {}
            for k in ('kind', 'pct', 'state', 'raw_state'):
                if k in motion:
                    motion_out[k] = motion[k]
            if motion_out:
                out['motion'] = motion_out
        # Capture-state booleans
        for k in ('freeze', 'blackscreen', 'macroblocks'):
            if k in data:
                out[k] = data[k]
        # Tier-2 cascade (loaded / overlay / playback / error) lives under
        # `analysis_data.localize.*` when the monitor is running on this device.
        loc = data.get('localize') or {}
        if isinstance(loc, dict):
            for k in ('loaded', 'overlay', 'playback', 'error'):
                if k in loc and loc[k] is not None:
                    out[k] = loc[k]
        return out or None

    def _frame_url_from_path(self, frame_path: Optional[str]) -> Optional[str]:
        """Turn a locally-captured frame path into the public host stream/capture URL.

        Mirrors the screenshot button (host_av_routes take_screenshot): same
        buildCaptureUrlFromPath helper + host registry instance. Fully non-fatal —
        any failure returns None so localize never breaks over a missing URL.
        """
        if not frame_path:
            return None
        try:
            from shared.src.lib.utils.build_url_utils import buildCaptureUrlFromPath
            from backend_host.src.lib.utils.host_utils import get_host_instance
            host = get_host_instance()
            return buildCaptureUrlFromPath(host.to_dict(), frame_path, self.device_id)
        except Exception as e:
            print(f"[@navigation_executor:localize] frame_url build failed (non-fatal): {e}")
            return None

    def _localize_among_children(self, parent_node_id: str, team_id: str, userinterface_name: str,
                                 frame_path: Optional[str] = None) -> Optional[str]:
        """Localize-dispatch (docs/agent/NAVIGATION_DISPATCH.md): a menu node (has_subtree) remembers
        its last child, so the step that ENTERED it landed on an unknown child, not the menu. Match
        the live frame against ONLY this menu's subtree children (their stored fingerprints) and
        return the actual child node_id — or None if the node has no subtree / no fingerprinted
        children / no confident match. Self-contained: matches `__fingerprint` directly via the
        production matcher, so it needs no per-child verification (unlike localize()). Cheap no-capture
        exit when the node isn't a dispatch menu, so it is safe to call after every step."""
        try:
            g = self.unified_graph
            if g is None or parent_node_id not in g:
                return None
            # Resolve the subtree this menu OWNS (parent_node_id -> child_tree_id). Do NOT derive it
            # from cross-tree successors: the tab ring's reverse edges point back into the PARENT tree,
            # so a leaf tab would localize against the whole parent tree (the spurious "17 candidates").
            owned_tree = (g.graph.get('parent_child_map') or {}).get(parent_node_id)
            if not owned_tree:
                return None                                  # not a dispatch menu — cheap no-capture exit
            candidates = []
            for nid, d in g.nodes(data=True):
                if d.get('tree_id') == owned_tree:           # only this menu's own children (tabs)
                    fp = d.get('__fingerprint')
                    if fp and fp.get('dhash'):
                        candidates.append({'node_id': nid, 'label': d.get('label', nid), 'fingerprint': fp})
            if not candidates:
                return None
            import cv2
            from backend_host.src.controllers.verification.image_helpers import ImageHelpers
            av = self.device._get_controller('av')
            # Reuse the step's already-settled end-screenshot (captured post-final_wait_time). A fresh
            # take_screenshot() here races the HLS stream mid-navigation and returns a transitional /
            # black frame ("low-content frame"); the step frame is the same settled image goto already has.
            frame = frame_path if (frame_path and os.path.exists(frame_path)) else (av.take_screenshot() if av else None)
            img = cv2_io.imread(frame) if frame else None
            if img is None:
                return None
            helpers = ImageHelpers(None, av)
            result = run_identify_screen(helpers, img, candidates, 'dispatch')  # same matcher, timed
            cands = result.get('candidates', [])
            actual = cands[0]['node_id'] if cands else None
            print(f"[@navigation_executor:dispatch] menu {parent_node_id}: localized child {actual} "
                  f"(of {len(candidates)} candidates)"
                  + (f" — {result.get('reason')}" if not actual and result.get('reason') else ""))
            return actual
        except Exception as e:
            print(f"[@navigation_executor:dispatch] _localize_among_children failed: {e}")
            return None

    def localize_check(self, node_id: str, team_id: str, userinterface_name: str,
                       tree_id: Optional[str] = None) -> Dict[str, Any]:
        """Independent 'are we actually on this node?' cross-check for verification.

        Runs Localize and judges THIS node against the result, so a node's
        hand-authored verification can be compared with what the fingerprint says:
          - true    : this node is in the localize candidate set
          - false   : this node has a fingerprint but was excluded (we're elsewhere)
          - unknown : no fingerprint for this node, or localize unavailable
        Returns the verdict plus the live dhash/focus and (on false) the best match.
        """
        # Pass the tree through when the caller has it: without it localize takes
        # the `if not tree_id` branch and reloads the whole tree via TreeManager on
        # every single call, warm cache included — three extra DB round trips for a
        # tree the caller already identified (BUG-0200).
        result = self.localize(team_id, userinterface_name, tree_id=tree_id)
        block = {
            'focus': result.get('live_focus'),
            'excluded_count': result.get('excluded_count', 0),
            'total': result.get('total', 0),
            'candidates': result.get('candidates', []),
            # Public URL of the captured frame so the UI can show "what was localized"
            # in a new tab (present on success AND failure).
            'frame_url': result.get('frame_url'),
        }
        if not result.get('success'):
            return {**block, 'verdict': 'unknown', 'reason': result.get('error', 'localize unavailable')}

        # Named capture-side state (no UI node on screen) — report it as the reason.
        if result.get('state'):
            return {**block, 'verdict': 'unknown', 'state': result['state'],
                    'reason': result.get('state_hint') or result['state']}

        # Does this node carry a stored fingerprint? (unknown vs false)
        has_fp = False
        try:
            if self.unified_graph is not None and node_id in self.unified_graph:
                has_fp = bool((self.unified_graph.nodes[node_id].get('__fingerprint') or {}).get('dhash'))
        except Exception:
            has_fp = False

        cands = result.get('candidates', [])
        match = next((c for c in cands if c.get('node_id') == node_id), None)
        if match:
            return {**block, 'verdict': 'true', 'confidence': match.get('confidence')}
        if not has_fp:
            return {**block, 'verdict': 'unknown', 'reason': 'no fingerprint stored for this node'}
        best = cands[0] if cands else None
        return {**block, 'verdict': 'false',
                'best_match': {'node_id': best['node_id'], 'label': best['label'],
                               'confidence': best['confidence']} if best else None}

    def clear_preview_cache(self, tree_id: str = None, team_id: str = None,
                             variant: Optional[str] = None):
        """Clear preview cache for a specific tree (or all trees if tree_id=None).

        Save handlers in the editor route invalidations through whichever
        tree the user was editing — frequently a subtree id. Preview cache
        keys are stored under the ROOT tree id (see get_navigation_preview),
        so we resolve subtree → root before filtering or the clear silently
        misses every entry.

        When `variant` is provided, only drop entries scoped to that variant
        (the 4th key component). Without this, a variant-scoped unified
        cache clear would leave stale preview results behind — get_navigation_preview
        returns the dict entry instead of recomputing from the (now-missing)
        graph, so target nodes that were precomputed pre-clear keep returning
        success while never-previewed targets fail with UnifiedCacheError.
        """
        if tree_id:
            from shared.src.lib.utils.navigation_cache import _resolve_root_tree_id
            resolved = (
                _resolve_root_tree_id(tree_id, team_id)
                if team_id else None
            ) or tree_id
            # Match either the raw or resolved tree id defensively, in case
            # an old entry was cached with the unresolved id during rollout.
            ids_to_match = {tree_id, resolved}
            keys_to_delete = [
                k for k in self._preview_cache.keys()
                if k[0] in ids_to_match and (variant is None or k[3] == variant)
            ]
            for key in keys_to_delete:
                del self._preview_cache[key]
            scope = f" (variant={variant})" if variant else ""
            if resolved != tree_id:
                print(f"[@navigation_executor:clear_preview_cache] Cleared {len(keys_to_delete)} cached previews for tree {tree_id}{scope} (resolved subtree → root {resolved})")
            else:
                print(f"[@navigation_executor:clear_preview_cache] Cleared {len(keys_to_delete)} cached previews for tree {tree_id}{scope}")
        else:
            # Clear entire cache
            count = len(self._preview_cache)
            self._preview_cache = {}
            print(f"[@navigation_executor:clear_preview_cache] Cleared all {count} cached previews")
    
    def get_available_context(self, userinterface_name: str, team_id: str) -> Dict[str, Any]:
        """Get available navigation context using cache when possible"""
        # First check if we have a cached unified graph for this interface
        from shared.src.lib.database.userinterface_db import get_userinterface_by_name
        from shared.src.lib.database.navigation_trees_db import get_root_tree_for_interface
        from shared.src.lib.utils.navigation_cache import get_cached_unified_graph
        
        # Get interface and root tree ID (mode rides device.navigation_context,
        # same channel as variant)
        ui_mode = (self.device.navigation_context or {}).get('ui_mode', 'dev') or 'dev'
        interface_info = get_userinterface_by_name(userinterface_name, team_id, mode=ui_mode)
        if not interface_info:
            raise ValueError(f"Interface '{userinterface_name}' not found (mode={ui_mode})")
            
        root_tree_info = get_root_tree_for_interface(interface_info['id'], team_id)
        if not root_tree_info:
            raise ValueError(f"No root tree found for interface '{userinterface_name}'")
            
        tree_id = root_tree_info['id']
        
        # Check cache first - avoid reloading if already cached
        cached_graph = get_cached_unified_graph(tree_id, team_id, variant=(self.device.navigation_context or {}).get('variant'))
        if cached_graph:
            print(f"[@navigation_executor] Using cached unified graph for '{userinterface_name}' (tree: {tree_id})")
            # Extract available nodes from cached graph - use labels, not node IDs
            available_nodes = []
            for node_id, node_data in cached_graph.nodes(data=True):
                if node_id != 'root':  # Skip root node
                    label = node_data.get('label', node_id)  # Use label if available, fallback to node_id
                    if label:  # Only add non-empty labels
                        available_nodes.append(label)
            
            print(f"[@navigation_executor] Extracted {len(available_nodes)} node labels: {available_nodes}")
            
            return {
                'service_type': 'navigation',
                'device_id': self.device_id,
                'device_model': self.device_model,
                'userinterface_name': userinterface_name,
                'tree_id': tree_id,
                'available_nodes': available_nodes,
                'cross_tree_capabilities': len(cached_graph.nodes()) > 10,  # Estimate based on graph size
                'unified_graph_nodes': len(cached_graph.nodes()),
                'unified_graph_edges': len(cached_graph.edges())
            }
        
        # Cache miss - load tree hierarchy and populate cache
        print(f"[@navigation_executor] Cache miss for '{userinterface_name}' - loading tree hierarchy")
        tree_result = self.load_navigation_tree(userinterface_name, team_id)
        
        # Fail fast - no fallback
        if not tree_result['success']:
            raise ValueError(f"Failed to load navigation tree: {tree_result['error']}")
        
        # Extract nodes directly from tree_result (load_navigation_tree returns 'nodes', not 'root_tree')
        nodes = tree_result['nodes']
        # Extract node labels (not node_name) for consistency with cached path
        available_nodes = []
        for node in nodes:
            label = node.get('label') or node.get('node_name')  # Try label first, fallback to node_name
            if label:
                available_nodes.append(label)
        
        print(f"[@navigation_executor] Extracted {len(available_nodes)} node labels from tree result: {available_nodes}")
        
        return {
            'service_type': 'navigation',
            'device_id': self.device_id,
            'device_model': self.device_model,
            'userinterface_name': userinterface_name,
            'tree_id': tree_id,
            'available_nodes': available_nodes,
            'cross_tree_capabilities': tree_result.get('cross_tree_capabilities', False),
            'unified_graph_nodes': tree_result.get('unified_graph_nodes', 0),
            'unified_graph_edges': tree_result.get('unified_graph_edges', 0)
        }
    
    def _build_result(self, success: bool, message: str, tree_id: str, target_node_id: str, 
                     current_node_id: Optional[str], start_time: float, **kwargs) -> Dict[str, Any]:
        """Build standardized result dictionary"""
        result = {
            'success': success,
            'tree_id': tree_id,
            'target_node_id': target_node_id,
            'current_node_id': current_node_id,
            'execution_time': time.time() - start_time,
            'transitions_executed': 0,
            'total_transitions': 0,
            'actions_executed': 0,
            'total_actions': 0
        }
        
        if success:
            result['message'] = message
        else:
            result['error'] = message
            
        result.update(kwargs)
        return result
    
    
    async def execute_single_edge_step(
        self,
        *,
        tree_id: str,
        userinterface_name: str,
        edge_id: str,
        action_set_id: str,
        target_node_id: str,
        actions: List[Dict],
        retry_actions: Optional[List[Dict]] = None,
        failure_actions: Optional[List[Dict]] = None,
        current_node_id: Optional[str] = None,
        team_id: str = None,
        final_wait_time: int = 0,
    ) -> Dict[str, Any]:
        """Run a single edge step (used by the Edge Selection panel "Run" button).

        Builds a navigation_path of length 1 with the request's literal
        actions inline, with the step's `verifications` cleared so the
        per-step loop never calls verify_node. Edge "Run" is **action-only**
        — it executes the actions, queues KPI on success, records the edge
        row, and returns. No node verification, no node_metrics row. Verifying
        is exclusively a navigation/goto concern.
        """
        from shared.src.lib.utils.navigation_cache import get_cached_unified_graph

        graph = get_cached_unified_graph(tree_id, team_id, variant=(self.device.navigation_context or {}).get('variant'))

        # Self-heal on cold cache: host restart, take-control still in
        # background, structural edit (delete/bulk save) that wiped the host
        # graph. Re-load from DB and repopulate before declaring failure.
        # First-call cost is one DB hierarchy fetch (~0.5–1s); subsequent
        # calls are warm.
        if not graph and userinterface_name:
            print(
                f"[@navigation_executor:execute_single_edge_step] Cache miss for tree "
                f"{tree_id} — auto-populating from DB (interface={userinterface_name})",
                flush=True,
            )
            try:
                self.load_navigation_tree(userinterface_name, team_id)
                graph = get_cached_unified_graph(tree_id, team_id, variant=(self.device.navigation_context or {}).get('variant'))
            except Exception as load_exc:
                print(
                    f"[@navigation_executor:execute_single_edge_step] ❌ Auto-populate "
                    f"failed: {load_exc}",
                    flush=True,
                )

        if not graph or target_node_id not in graph.nodes:
            # Surface the silent failure so the next regression lands in
            # journalctl instead of disappearing into the per-execution
            # LoggingManager buffer (which only the frontend ever sees).
            reason = (
                f"no cached graph for tree {tree_id}"
                if not graph
                else f"target node {target_node_id} not in graph"
            )
            print(
                f"[@navigation_executor:execute_single_edge_step] ❌ Cache miss: {reason} "
                f"(team={team_id}, action_set={action_set_id}) → returning 0/0",
                flush=True,
            )
            return self._build_result(
                False,
                f"Cache miss for tree {tree_id} or node {target_node_id} not in graph",
                tree_id, target_node_id, current_node_id, time.time(),
            )

        # Find the edge in the cached graph to recover destination verifications
        # and the action_set's KPI references / use_verifications_for_kpi flag.
        # Match on action_set_id, NOT edge_id: navigation_graph.py mangles the
        # DB edge_id when adding the reverse direction (it appends "_reverse"),
        # so lookups by raw edge_id silently miss whichever direction the user
        # didn't store as the canonical row. action_set_ids are direction-
        # distinguishing (e.g. "home_apps_to_home_tvguide" vs the reverse) and
        # appear on exactly one edge in the graph.
        original_edge_data = None
        from_node_id = None
        for u, v, data in graph.edges(data=True):
            if v != target_node_id:
                continue
            action_sets = data.get('action_sets') or []
            if any((s or {}).get('id') == action_set_id for s in action_sets):
                original_edge_data = data
                from_node_id = u
                break
        if original_edge_data is None:
            print(
                f"[@navigation_executor:execute_single_edge_step] ❌ No edge with "
                f"action_set_id={action_set_id} → {target_node_id} in cached graph "
                f"(tree={tree_id}) → returning 0/0",
                flush=True,
            )
            return self._build_result(
                False,
                f"Edge with action_set_id={action_set_id} → {target_node_id} not in cached graph",
                tree_id, target_node_id, current_node_id, time.time(),
            )

        target_node = graph.nodes[target_node_id]
        from_node = graph.nodes.get(from_node_id, {}) if from_node_id else {}

        step_dict = {
            'edge_id': edge_id,
            'action_set_id': action_set_id,
            'from_node_id': from_node_id,
            'to_node_id': target_node_id,
            'from_node_label': from_node.get('label', ''),
            'to_node_label': target_node.get('label', ''),
            'to_tree_id': original_edge_data.get('to_tree_id', tree_id),
            'actions': actions,
            'retryActions': retry_actions or [],
            'failureActions': failure_actions or [],
            # Empty verifications: edge Run is action-only. KPI lookup uses
            # unified_graph.nodes[target] directly when use_verifications_for_kpi
            # is set, so the KPI scan still has its visual anchor even though
            # we don't run verify_node against the live device.
            'verifications': [],
            'final_wait_time': final_wait_time,
            'original_edge_data': original_edge_data,
        }

        # Interactive Edge "Run" → build a verification report for any repeat_until
        # ("press until appears/disappears") leg so the panel can link to the
        # evidence that drove pass/fail. The flag is read by ActionExecutor and
        # reset in finally so CLI/goto batches on this device never pay the cost.
        self.device.action_executor.report_repeat_until = True
        try:
            nav_result = await self.execute_navigation(
                tree_id=tree_id,
                userinterface_name=userinterface_name,
                target_node_id=target_node_id,
                target_node_label=target_node.get('label'),
                navigation_path=[step_dict],
                current_node_id=current_node_id,
                frontend_sent_position=True,
                team_id=team_id,
                verification_mode='end',  # irrelevant since step has no verifications
            )
        finally:
            self.device.action_executor.report_repeat_until = False

        # Adapt the navigation-shaped result to the action-batch shape that
        # the frontend Run button consumes (useAction.executeActions reads
        # passed_count / total_count). The navigation result uses
        # actions_executed / total_actions for the same numbers; without
        # this re-keying the frontend toast shows "0/0 passed" even on a
        # fully successful run.
        if isinstance(nav_result, dict) and 'passed_count' not in nav_result:
            nav_result = dict(nav_result)
            nav_result['passed_count'] = nav_result.get('actions_executed', 0)
            nav_result['total_count'] = nav_result.get('total_actions', 0)
            # 'results' is inspected by formatExecutionResults — supply an
            # empty list so the formatter doesn't choke on undefined.
            nav_result.setdefault('results', [])
        return nav_result

    async def execute_single_node_verification(
        self,
        *,
        tree_id: str,
        node_id: str,
        verifications: List[Dict],
        userinterface_name: str,
        image_source_url: Optional[str] = None,
        team_id: str = None,
        generate_success_report: bool = False,
    ) -> Dict[str, Any]:
        """Run verifications against a single node (Node panel "Run" button).

        Mirrors `execute_single_edge_step` for verifications: dispatches the
        primitive (`VerificationExecutor.execute_verifications`) and writes
        exactly one `node_metrics` row via `record_node_execution`. Stamps
        the same script/variant context that goto's per-step recording uses,
        so panel and CLI runs aggregate into the same row.

        No edge row, no KPI queue — there is no action and no measurement
        anchor. Recording lives here (not in VerificationExecutor) so the
        single-owner rule is preserved: NavigationExecutor is the only thing
        that writes execution_results.
        """
        from shared.src.lib.database.execution_results_db import record_node_execution

        nav_context = getattr(self.device, 'navigation_context', {}) or {}
        script_id = nav_context.get('script_id')
        script_ctx = nav_context.get('script_context', 'direct')
        variant = nav_context.get('variant')
        is_test = bool(nav_context.get('is_test', False))

        start_time = time.time()
        verify_result = await self.device.verification_executor.execute_verifications(
            verifications=verifications,
            userinterface_name=userinterface_name,
            image_source_url=image_source_url,
            team_id=team_id,
            tree_id=tree_id,
            node_id=node_id,
            generate_success_report=generate_success_report,
        )
        execution_time_ms = int((time.time() - start_time) * 1000)
        success = bool(verify_result.get('success'))
        message = verify_result.get('message') or ('Node verification passed' if success else 'Node verification failed')
        error_details = None if success else {'error': verify_result.get('error') or message}

        # A batch that could not run (host out of disk) is not a measurement of this
        # node: recording it would drag every node's success rate down for the
        # duration of the outage and call an infrastructure failure a test result
        # (BUG-0198). The caller still gets the error through verify_result.
        if verify_result.get('execution_error'):
            print(f"[@navigation_executor:execute_single_node_verification] "
                  f"Not recording node metrics — {verify_result.get('execution_error')}: {message}")
            return verify_result

        record_node_execution(
            team_id=team_id,
            tree_id=tree_id,
            node_id=node_id,
            host_name=self.host_name,
            device_model=self.device_model,
            device_name=self.device_name,
            success=success,
            execution_time_ms=execution_time_ms,
            message=message,
            error_details=error_details,
            script_result_id=script_id,
            script_context=script_ctx,
            variant=variant,
            is_test=is_test,
        )

        # Independent Localize cross-check: does the fingerprint agree we're on
        # this node? Surfaced under verify_result['localize'] (true/false/unknown
        # + live dhash/focus). Best-effort — never fail verification on it.
        try:
            verify_result['localize'] = self.localize_check(
                node_id, team_id, userinterface_name, tree_id=tree_id
            )
        except Exception as loc_err:
            print(f"[@navigation_executor] localize_check failed (non-fatal): {loc_err}")

        return verify_result

    def _attach_verification_to_step(self, step_result, verification_result, context):
        """Surface the verify_node result on an 'already at destination' step.

        A short-circuited "already at target" otherwise records a bare step with
        no evidence of *what* was checked — which hides false-positive position
        verifications (e.g. an OCR fuzzy match) during debugging. Mirror the
        exact fields a normal navigation step carries so the report renders the
        verification (per-verification score, extracted text, cropped images)
        identically, and push verification screenshots into the upload set."""
        if not verification_result:
            return step_result
        step_result['verification_results'] = verification_result.get('results', [])
        step_result['verification_screenshots'] = verification_result.get('verification_screenshots', [])
        step_result['verification_count'] = verification_result.get('total_count', 0)
        step_result['verification_passed_count'] = verification_result.get('passed_count', 0)
        for verif_screenshot in verification_result.get('verification_screenshots', []):
            if verif_screenshot and context and hasattr(context, 'add_screenshot'):
                context.add_screenshot(verif_screenshot)
        return step_result

    @staticmethod
    def _verified_frame_path(verification_result: Dict[str, Any]) -> Optional[str]:
        """The frame a passing node verification was judged on.

        Each verification leg returns its evidence frame as `screenshot_path`
        (captured right after the leg ran, see VerificationExecutor
        `_execute_single_verification`). Prefer a leg that passed; fall back to
        the batch's `verification_screenshots`. None when nothing was captured."""
        results = verification_result.get('results') or []
        for leg in results:
            if leg.get('success') and leg.get('screenshot_path'):
                return leg['screenshot_path']
        for path in verification_result.get('verification_screenshots') or []:
            if path:
                return path
        return None

    @staticmethod
    def _failed_frame_path(verification_result: Dict[str, Any]) -> Optional[str]:
        """The frame a FAILED node verification was judged on: the first leg that
        failed and carries its evidence `screenshot_path`. None when there is none
        (no fallback: a passing leg's frame is not the frame that failed)."""
        for leg in verification_result.get('results') or []:
            if not leg.get('success') and leg.get('screenshot_path'):
                return leg['screenshot_path']
        return None

    @staticmethod
    def _start_training_thread(fn) -> None:
        threading.Thread(target=fn, name='training-hook-navigation', daemon=True).start()

    @staticmethod
    def _screen_groups(graph, userinterface_name=None):
        """TASK-27 step 4k: the screen groups of the already-loaded unified graph, with the
        core overrides of this userinterface (pure data, no DB), or None when there is no
        graph or it cannot be grouped. Runs in the training thread only; never raises."""
        if graph is None:
            return None
        try:
            from shared.src.lib.ai import screen_groups
            return screen_groups.from_graph(graph, screen_groups.overrides_for(userinterface_name))
        except Exception as e:
            print(f"[@navigation_executor:training] no screen groups (label kept per node): {e}")
            return None

    def _record_training_samples(self, verification_result: Dict[str, Any], node_id: str,
                                 node_label: Optional[str], tree_id: str, team_id: str,
                                 userinterface_name: str, edge_id: Optional[str] = None,
                                 runner=None) -> None:
        """TASK-27 step 3c: a verified node is a free `screen-id` sample (label_source
        'run'), plus an unlabelled `focus` sample (the detector's OCR as model_answer,
        label_source 'none') when the focus detector finds a labelled box on that frame.

        Off the hot path: the switch is checked here (env only, cheap); everything
        else — frame lookup, focus signature (OCR), upload — runs in a daemon thread.
        Never raises and never delays or fails navigation. `runner` is injectable
        for tests (default: a daemon thread)."""
        try:
            from shared.src.lib.ai import training_samples
            if not training_samples.enabled():
                return
        except Exception as e:
            print(f"[@navigation_executor:training] hook skipped: {e}")
            return

        device_model = self.device_model
        graph = self.unified_graph

        def _work():
            try:
                frame_path = self._verified_frame_path(verification_result)
                if not frame_path:
                    print(f"[@navigation_executor:training] no verification frame for node {node_id} - skipped")
                    return
                node_data = {}
                try:
                    if graph is not None and node_id in graph.nodes:
                        node_data = graph.nodes[node_id] or {}
                except Exception:
                    node_data = {}
                label = node_label or node_data.get('label') or node_id
                source_ref = {'tree_id': node_data.get('tree_id') or tree_id,
                              'node_id': node_id, 'edge_id': edge_id}
                common = dict(team_id=team_id, device_model=device_model,
                              userinterface=userinterface_name, node_id=node_id,
                              label_source='run', source_ref=source_ref)

                # Step 4k: the answer is the screen GROUP (Home with any tab focused is
                # "home"), from the graph already loaded here; the row's node_id stays the
                # node. No grouping (no graph, node outside it) keeps the pre-4k label,
                # which features/ai-dataset/scripts/regroup_screen_labels.py converts later.
                groups = self._screen_groups(graph, userinterface_name)
                truth = (groups.label_for(node_id, label) if groups is not None else None) \
                    or {'node_id': node_id, 'label': label}
                training_samples.record_sample(
                    frame_path, family='screen-id', ground_truth=truth, **common)

                import cv2
                from backend_host.src.controllers.verification.image_helpers import ImageHelpers
                img = cv2_io.imread(frame_path, cv2.IMREAD_COLOR)
                if img is None or img.size == 0:
                    return
                focus = ImageHelpers(None, None)._focus_signature(img) or {}
                focus_label = focus.get('label')
                if focus.get('kind') != 'box' or not focus_label:
                    return
                # The focus label is OCR from the detector, never checked by the run:
                # it is the model answer; teacher/human labelling supplies the truth later.
                focus_kw = dict(common, label_source='none')
                training_samples.record_sample(
                    frame_path, family='focus', model_answer={'focused': focus_label},
                    ground_truth=None, focus_label=focus_label,
                    # _focus_signature gives the box CENTRE only (normalized), no width/height.
                    boxes={'focus': {'cx': focus.get('x'), 'cy': focus.get('y')}},
                    **focus_kw)
            except Exception as e:
                print(f"[@navigation_executor:training] hook failed (non-fatal): {e}")

        try:
            (runner or self._start_training_thread)(_work)
        except Exception as e:
            print(f"[@navigation_executor:training] could not start hook: {e}")

    def _record_failed_verification_sample(self, verification_result: Dict[str, Any],
                                           expected_node_id: str, expected_label: Optional[str],
                                           tree_id: str, team_id: str, userinterface_name: str,
                                           edge_id: Optional[str] = None, runner=None) -> None:
        """TASK-27 step 4d: a node verification that ran and FAILED where the device was
        expected to be on that screen (after an edge's actions, or "already at target"
        per the context) is a hard `screen-id` candidate. Not called from the position
        probes (one-step, no-position, home): those fail routinely off-screen. The true screen is unknown, so the sample carries no label
        (`ground_truth=None`, `label_source='none'`, `node_id=None`) and the expectation
        goes in `model_answer` `{'expected_node_id', 'expected_label', 'expected_group',
        'verified': False}` (`expected_group`: the step-4k screen group name, or None).
        Forced past pass-1 dedup (a failure candidate). One sample per failed
        verification, on the frame of the failed leg; skipped when there is none.

        Same rules as `_record_training_samples`: switch checked first, work in a
        daemon thread, never raises, never changes the navigation result, and never
        writes execution results (CONTRACTS rule 19)."""
        try:
            from shared.src.lib.ai import training_samples
            if not training_samples.enabled():
                return
        except Exception as e:
            print(f"[@navigation_executor:training] failed-verification hook skipped: {e}")
            return
        if not verification_result or not verification_result.get('has_verifications', True):
            return

        device_model = self.device_model
        graph = self.unified_graph

        def _work():
            try:
                frame_path = self._failed_frame_path(verification_result)
                if not frame_path:
                    print(f"[@navigation_executor:training] no failed-verification frame for node "
                          f"{expected_node_id} - skipped")
                    return
                node_data = {}
                try:
                    if graph is not None and expected_node_id in graph.nodes:
                        node_data = graph.nodes[expected_node_id] or {}
                except Exception:
                    node_data = {}
                label = expected_label or node_data.get('label') or expected_node_id
                # Step 4k: the expected screen group too ("home" for home_apps), or None.
                groups = self._screen_groups(graph, userinterface_name)
                group = groups.group_of(expected_node_id) if groups is not None else None
                training_samples.record_sample(
                    frame_path, family='screen-id', team_id=team_id, device_model=device_model,
                    userinterface=userinterface_name, node_id=None,
                    model_answer={'expected_node_id': expected_node_id, 'expected_label': label,
                                  'expected_group': group['label'] if group else None,
                                  'verified': False},
                    ground_truth=None, label_source='none',
                    source_ref={'tree_id': node_data.get('tree_id') or tree_id,
                                'node_id': expected_node_id, 'edge_id': edge_id},
                    # Near-duplicate check yes, cap no: a verifier that keeps failing on
                    # the same screen stores it once, and distinct failures are all kept.
                    force=False, skip_cap=True)
            except Exception as e:
                print(f"[@navigation_executor:training] failed-verification hook failed (non-fatal): {e}")

        try:
            (runner or self._start_training_thread)(_work)
        except Exception as e:
            print(f"[@navigation_executor:training] could not start failed-verification hook: {e}")

    async def execute_navigation(self,
                          tree_id: str,
                          userinterface_name: str,  # MANDATORY for reference resolution
                          target_node_id: str = None,
                          target_node_label: str = None,
                          navigation_path: List[Dict] = None,
                          current_node_id: Optional[str] = None,
                          frontend_sent_position: bool = False,  # NEW: Did frontend explicitly send position?
                          image_source_url: Optional[str] = None,
                          team_id: str = None,
                          context=None,
                          verification_mode: str = 'end',
                          # When True: do NOT record per-step rows in `context.step_results` —
                          # record ONE summary row at the end with `step_category='recovery'`.
                          # Used by the validation script's Phase-1 reposition so a multi-hop
                          # pathfinder back to the next step's `from_node` shows up as a single
                          # "Recovery → X" row in the report instead of 5 expanded transitions.
                          is_recovery: bool = False,
                          # When True: forget any tracked position and skip the "am I already
                          # at the target / at home?" probes, so the path starts with the
                          # tree's entry edge. TestCaseExecutor sets it on a web testcase's
                          # first navigation (see BUG-0190). Ignored with navigation_path or
                          # is_recovery, which never probe from an unknown position.
                          start_from_entry: bool = False) -> Dict[str, Any]:
        
        print(f"\n[@navigation_executor:execute_navigation] 🎯 EXECUTE NAVIGATION CALLED:")
        print(f"[@navigation_executor:execute_navigation]   → tree_id: {tree_id}")
        print(f"[@navigation_executor:execute_navigation]   → target_node_id: {target_node_id}")
        print(f"[@navigation_executor:execute_navigation]   → target_node_label: {target_node_label}")
        print(f"[@navigation_executor:execute_navigation]   → current_node_id: {current_node_id}")
        print(f"[@navigation_executor:execute_navigation]   → frontend_sent_position: {frontend_sent_position}")
        print(f"[@navigation_executor:execute_navigation]   → userinterface_name: {userinterface_name}\n")
        """
        Execute navigation to target node using ONLY unified pathfinding with nested tree support.
        Enhanced with all capabilities from old goto_node method.
        
        Args:
            tree_id: Navigation tree ID
            userinterface_name: User interface name (REQUIRED for reference resolution, e.g., 'example_androidtv')
            target_node_id: ID of the target node to navigate to (mutually exclusive with target_node_label)
            target_node_label: Label of the target node to navigate to (mutually exclusive with target_node_id)
            navigation_path: Optional pre-computed navigation path (for validation scripts)
                           If provided, pathfinding is skipped and this path is executed directly
            current_node_id: Optional current node ID for starting point
            image_source_url: Optional image source URL
            team_id: Team ID for security
            context: Optional ScriptExecutionContext for tracking step results
            start_from_entry: Navigate from the entry node without probing the screen first
            
        Returns:
            Dict with success status and navigation details
        """
        start_time = time.time()
        _t_nav_total = _phase_t0()

        # 🔄 AUTO-SYNC every call: variant cache key means `self.unified_graph`
        # can be stale if a previous call ran under a different variant. The
        # helper always re-fetches from the variant-aware cache (cheap dict
        # lookup) and auto-populates from DB on cold cache.
        if team_id:
            _t = _phase_t0()
            synced = self._sync_unified_graph(tree_id, team_id, userinterface_name)
            _log_phase('nav.sync_unified_graph', _t)
            if synced:
                print(f"[@navigation_executor:execute_navigation] ✅ unified_graph synced ({len(synced.nodes)} nodes, variant={(self.device.navigation_context or {}).get('variant') or 'base'})")
            elif not self.unified_graph:
                print(f"[@navigation_executor:execute_navigation] ⚠️ No cached graph found for tree {tree_id}")
        
        # Validate parameters - either navigation_path OR target must be provided
        if navigation_path:
            # Pre-computed path mode (validation scripts AND execute_single_edge_step).
            # target_node_id / target_node_label are accepted alongside the path —
            # they're informational (used for logging / final-result fields). The
            # actual target is implicit in navigation_path[-1].to_node_id.
            if not target_node_id and not target_node_label:
                # Fill from the path so downstream logging is meaningful.
                target_node_id = navigation_path[-1].get('to_node_id')
            print(f"[@navigation_executor:execute_navigation] 🔄 Pre-computed path mode: {len(navigation_path)} transitions provided")
        else:
            # Normal pathfinding mode (goto scripts)
            if not target_node_id and not target_node_label:
                return self._build_result(
                    False, 
                    "Either target_node_id, target_node_label, or navigation_path must be provided",
                    tree_id, None, current_node_id, start_time
                )
            
            if target_node_id and target_node_label:
                return self._build_result(
                    False, 
                    "Cannot provide both target_node_id and target_node_label - use only one",
                    tree_id, target_node_id, current_node_id, start_time
                )
        
        # Resolve target_node_label to target_node_id if label provided
        if target_node_label:
            # Warm the unified graph with the FULL hierarchy first. get_node_id's own _sync is
            # called without userinterface_name, so on a cold cache (e.g. a UI never navigated this
            # process) it cannot load and the label — especially a SUBTREE node — won't resolve. We
            # have the UI name here, so populate the cache before resolving.
            _t = _phase_t0()
            if userinterface_name:
                self._sync_unified_graph(tree_id, team_id, userinterface_name)
            try:
                target_node_id = self.get_node_id(target_node_label, tree_id, team_id)
                _log_phase('nav.resolve_target_label', _t, f"label={target_node_label}")
                print(f"[@navigation_executor:execute_navigation] Resolved label '{target_node_label}' to node_id '{target_node_id}'")
            except ValueError as e:
                return self._build_result(
                    False,
                    f"Could not resolve target_node_label '{target_node_label}' to node_id: {str(e)}",
                    tree_id, None, current_node_id, start_time
                )

        # Recovery-mode helper. When execute_navigation is invoked by the
        # validation script's Phase-1 reposition (is_recovery=True), every
        # individual step normally written via context.record_step_immediately
        # is suppressed. Instead this writes ONE summary row at the end with
        # step_category='recovery' so the report shows a single "Recovery → X"
        # entry rather than the 5+ intermediate transitions that pathfinding
        # produced. KPI/DB writes (_record_step_execution_results) are NOT
        # suppressed — edge metrics still aggregate per-step.
        #
        # The eager `recovery_start_screenshot_path` capture below is what
        # gives the recovery row its "before" image; the end image is taken
        # inside the helper at the moment the summary is recorded.
        recovery_start_screenshot_path = ""
        if is_recovery and context:
            try:
                from shared.src.lib.utils.device_utils import capture_screenshot_for_script
                _label_for_capture = target_node_label or target_node_id or 'unknown'
                screenshot_id = capture_screenshot_for_script(
                    self.device, context, f"recovery_start_{_label_for_capture}"
                )
                if screenshot_id and context.screenshot_paths:
                    recovery_start_screenshot_path = context.screenshot_paths[-1]
                    print(f"📸 [@navigation_executor:execute_navigation] Recovery start screenshot captured: {screenshot_id}")
            except Exception as e:
                print(f"[@navigation_executor:execute_navigation] ⚠️ Recovery start screenshot failed: {e}")

        def _record_recovery_summary(success: bool, message: str = '',
                                     screenshot_path: str = '') -> None:
            if not (is_recovery and context):
                return
            from datetime import datetime
            elapsed_ms = int((time.time() - start_time) * 1000)
            end_str = datetime.now().strftime('%H:%M:%S')
            target_label = target_node_label or target_node_id or 'unknown'
            from_label = (self.device.navigation_context.get('previous_node_label')
                          or self.device.navigation_context.get('current_node_label')
                          or 'unknown')

            # End-screenshot — captured at the moment recovery wraps up.
            # Falls back to whatever the caller passed in screenshot_path.
            recovery_end_screenshot_path = screenshot_path or ''
            if not recovery_end_screenshot_path:
                try:
                    from shared.src.lib.utils.device_utils import capture_screenshot_for_script
                    end_screenshot_id = capture_screenshot_for_script(
                        self.device, context, f"recovery_end_{target_label}"
                    )
                    if end_screenshot_id and context.screenshot_paths:
                        recovery_end_screenshot_path = context.screenshot_paths[-1]
                        print(f"📸 [@navigation_executor:execute_navigation] Recovery end screenshot captured: {end_screenshot_id}")
                except Exception as e:
                    print(f"[@navigation_executor:execute_navigation] ⚠️ Recovery end screenshot failed: {e}")

            context.record_step_immediately({
                'success': bool(success),
                'message': f"Recovery → {target_label}",
                'from_node': from_label,
                'to_node': target_label,
                'execution_time_ms': elapsed_ms,
                'start_time': end_str,
                'end_time': end_str,
                'actions': [],
                'verifications': [],
                'screenshot_path': recovery_end_screenshot_path,
                'step_start_screenshot_path': recovery_start_screenshot_path,
                'step_end_screenshot_path': recovery_end_screenshot_path,
                'step_category': 'recovery',
                'error': None if success else message,
            })
            if hasattr(context, 'write_running_log'):
                context.write_running_log()

        # Update shared navigation context with team_id
        if team_id:
            self.device.navigation_context['team_id'] = team_id
        
        # Store previous position before navigation attempt
        nav_context = self.device.navigation_context
        nav_context['previous_node_id'] = nav_context['current_node_id']
        nav_context['previous_node_label'] = nav_context['current_node_label']
        
        # Get target node label for logging (if unified graph is available)
        # Note: target_node_label might already be set if provided as input parameter
        if not target_node_label:
            if self.unified_graph or (tree_id and team_id):
                try:
                    target_node_label = self.get_node_label(target_node_id, tree_id, team_id)
                except ValueError:
                    print(f"[@navigation_executor:execute_navigation] Could not find label for node_id '{target_node_id}' - will use ID for logging")
                    target_node_label = target_node_id
        
        try:
            from backend_host.src.services.navigation.navigation_pathfinding import find_shortest_path
            from shared.src.lib.utils.navigation_exceptions import UnifiedCacheError, PathfindingError
            
            # A pre-computed path or a recovery never probes from an unknown position, so
            # there is nothing for start_from_entry to skip there.
            start_from_entry = bool(start_from_entry) and not navigation_path and not is_recovery
            if start_from_entry:
                # Fresh start: whatever is on screen was left by someone else (an ad-hoc
                # command, a previous run, a person at the controls). A probe can only
                # tell that the screen LOOKS like a node, not that the app state behind
                # it is fresh — the entry edge is what resets that state. So forget the
                # tracked position and do not probe: pathfinding starts at entry.
                if nav_context.get('current_node_id'):
                    print(f"[@navigation_executor:execute_navigation] Testcase fresh start: discarding tracked position {nav_context.get('current_node_id')} ({nav_context.get('current_node_label', 'unknown')})")
                nav_context['current_node_id'] = None
                nav_context['current_node_label'] = None
                nav_context['current_tree_id'] = None
                nav_context['position_timestamp'] = 0
                nav_context['last_verified_timestamp'] = 0
                nav_context['last_verified_node_id'] = None
                print(f"[@navigation_executor:execute_navigation] Testcase fresh start: navigating from entry (position probes skipped)")
            # SIMPLE RULE: Frontend is source of truth when it sends position (even if None)
            elif frontend_sent_position:
                if current_node_id:
                    # Frontend says "start from this node"
                    nav_context['current_node_id'] = current_node_id
                    nav_context['current_node_label'] = self.get_node_label(current_node_id, tree_id, team_id)
                    print(f"[@navigation_executor:execute_navigation] Starting from frontend position: {current_node_id} ({nav_context['current_node_label']})")
                else:
                    # Frontend says "I don't know position" → clear backend, use entry
                    if nav_context.get('current_node_id'):
                        print(f"[@navigation_executor:execute_navigation] Frontend cleared position (was: {nav_context.get('current_node_id')})")
                    nav_context['current_node_id'] = None
                    nav_context['current_node_label'] = None
                    print(f"[@navigation_executor:execute_navigation] Starting from entry (frontend doesn't know position)")
            else:
                # Frontend didn't send position → trust backend (set by previous navigation in script)
                # BUT verify if position is stale (>30s old)
                if nav_context.get('current_node_id'):
                    position_timestamp = nav_context.get('position_timestamp', 0)
                    time_since_position = time.time() - position_timestamp if position_timestamp else 999
                    
                    if time_since_position > 30:
                        # Position is stale (>30s old) - verify before trusting
                        print(f"[@navigation_executor:execute_navigation] ⏰ Backend position is {int(time_since_position)}s old - verifying before use")
                        stale_node_id = nav_context['current_node_id']
                        stale_node_label = nav_context.get('current_node_label', 'unknown')

                        _t = _phase_t0()
                        verification_result = await self.device.verification_executor.verify_node(
                            node_id=stale_node_id,
                            userinterface_name=userinterface_name,
                            team_id=team_id,
                            tree_id=tree_id,
                            probe_timeout_ms=POSITION_PROBE_TIMEOUT_MS
                        )
                        _log_phase('nav.stale_position_verify', _t,
                                   f"node={stale_node_label} age_s={int(time_since_position)} cap_ms={POSITION_PROBE_TIMEOUT_MS} "
                                   f"{self._verification_phase_detail(verification_result)}")

                        if not verification_result.get('has_verifications', True):
                            # Node has no verifications - we can't disprove the position, so trust it
                            # and continue rather than re-navigating from entry every time.
                            print(f"[@navigation_executor:execute_navigation] ⚠️ No verifications on {stale_node_label} - trusting stale position and continuing")
                            nav_context['position_timestamp'] = time.time()
                            # Trusted, not verified: nothing passed, so no verified mark (BUG-0195).
                            nav_context['last_verified_timestamp'] = 0
                            nav_context['last_verified_node_id'] = None
                        elif verification_result.get('success'):
                            print(f"[@navigation_executor:execute_navigation] ✅ Stale position verified - still at {stale_node_label}")
                            # Update timestamp to mark as fresh
                            nav_context['position_timestamp'] = time.time()
                            self._mark_position_verified(stale_node_id)
                        else:
                            print(f"[@navigation_executor:execute_navigation] ❌ Stale position verification failed - clearing position (was: {stale_node_label})")
                            # Clear stale position - we're not there anymore
                            nav_context['current_node_id'] = None
                            nav_context['current_node_label'] = None
                            nav_context['current_tree_id'] = None
                            nav_context['position_timestamp'] = 0
                            nav_context['last_verified_timestamp'] = 0
                            nav_context['last_verified_node_id'] = None
                            print(f"[@navigation_executor:execute_navigation] Starting from entry (stale position cleared)")
                    else:
                        print(f"[@navigation_executor:execute_navigation] Starting from backend position: {nav_context['current_node_id']} ({nav_context.get('current_node_label', 'unknown')}) [{int(time_since_position)}s old]")
                else:
                    print(f"[@navigation_executor:execute_navigation] Starting from entry (no position tracked)")
            
            # Skip "already at target" optimization if using pre-computed path (validation mode)
            if navigation_path:
                print(f"[@navigation_executor:execute_navigation] Pre-computed path mode - skipping position checks")
            else:
                print(f"[@navigation_executor:execute_navigation] Navigating to '{target_node_label or target_node_id}' using unified pathfinding")
            
            # Check if already at target BEFORE pathfinding - but ONLY if we know our current position
            # Skip this check if using pre-computed path (validation needs to test the transition)
            current_position = nav_context.get('current_node_id')
            if not navigation_path:
                print(f"[@navigation_executor:execute_navigation] Current position: {current_position}, Target: {target_node_id}")
            
            # 🔍 POSITION TRACKING BUG DETECTION: If position tracking says we're elsewhere but target is close,
            # check where we really are to catch stale position tracking (e.g., "android_home" vs "home" confusion).
            # Skip when the frontend just supplied the position — it's fresh and authoritative, no need to second-guess.
            #
            # BUG-0195, in this order:
            #   1. the current node's own verifications passed within the trust window (the previous hop
            #      just verified it) → nothing to catch, no probe;
            #   2. otherwise check the CURRENT node first: showing (the cheap, expected answer) → take
            #      the edge. The target used to be checked alone, so a target verified by text the
            #      current screen also shows "passed" and the hop under test was skipped;
            #   3. current not showing → check the target: showing → correct the position, skip the hop;
            #   4. neither showing → the tracked position is wrong: clear it (the no-position flow
            #      below takes over) instead of taking the edge from a screen we are not on.
            one_step_target_probe = None       # the target's failed check, reused by the no-position flow
            position_disproved_node_id = None  # the tracked node whose check just failed
            if not navigation_path and current_position and current_position != target_node_id and not frontend_sent_position:
                # Quick pathfinding check: is target reachable in 1 step?
                from shared.src.lib.utils.navigation_cache import get_cached_unified_graph
                cached_graph = get_cached_unified_graph(tree_id, team_id, variant=(self.device.navigation_context or {}).get('variant'))
                if cached_graph and current_position in cached_graph.nodes and target_node_id in cached_graph.nodes:
                    # Check if target is a direct neighbor (1 step away)
                    probe_target = False
                    current_check = None
                    if cached_graph.has_edge(current_position, target_node_id):
                        tracked_label = nav_context.get('current_node_label') or current_position
                        verified_age_s = self._recently_verified_age_s(nav_context, current_position)
                        if verified_age_s is not None:
                            _t = _phase_t0()
                            print(f"[@navigation_executor:execute_navigation] ⏭ Target is 1 step away; '{tracked_label}' "
                                  f"was verified {verified_age_s:.1f}s ago - trusting it, no position probe")
                            _log_phase('nav.probe_skipped_recently_verified', _t,
                                       f"from={tracked_label} target={target_node_label or target_node_id} "
                                       f"verified_age_ms={int(verified_age_s * 1000)} trust_s={position_trust_seconds():g}")
                        else:
                            print(f"[@navigation_executor:execute_navigation] 🔍 Target is 1 step away - checking the current node first to catch position tracking bugs")
                            _t = _phase_t0()
                            current_check = await self.device.verification_executor.verify_node(
                                node_id=current_position,
                                userinterface_name=userinterface_name,
                                team_id=team_id,
                                tree_id=tree_id,
                                probe_timeout_ms=POSITION_PROBE_TIMEOUT_MS
                            )
                            _log_phase('nav.probe_current_one_step_away', _t,
                                       f"node={tracked_label} target={target_node_label or target_node_id} "
                                       f"cap_ms={POSITION_PROBE_TIMEOUT_MS} {self._verification_phase_detail(current_check)}")
                            if current_check.get('success') and current_check.get('has_verifications', True):
                                print(f"[@navigation_executor:execute_navigation] ✅ Still at '{tracked_label}' - taking the edge to '{target_node_label or target_node_id}'")
                                self._mark_position_verified(current_position)
                            else:
                                probe_target = True
                    if probe_target:
                        print(f"[@navigation_executor:execute_navigation] 🔍 '{tracked_label}' not confirmed - verifying if already at the target")
                        _t = _phase_t0()
                        verification_result = await self.device.verification_executor.verify_node(
                            node_id=target_node_id,
                            userinterface_name=userinterface_name,
                            team_id=team_id,
                            tree_id=tree_id,
                            probe_timeout_ms=POSITION_PROBE_TIMEOUT_MS
                        )
                        _log_phase('nav.probe_target_one_step_away', _t,
                                   f"from={nav_context.get('current_node_label')} target={target_node_label or target_node_id} "
                                   f"cap_ms={POSITION_PROBE_TIMEOUT_MS} {self._verification_phase_detail(verification_result)}")

                        # If we're ACTUALLY at the target visually, update position and skip navigation
                        if verification_result.get('success') and verification_result.get('has_verifications', True):
                            current_label = nav_context.get('current_node_label', 'unknown')
                            print(f"[@navigation_executor:execute_navigation] ⚠️ POSITION TRACKING BUG DETECTED!")
                            print(f"[@navigation_executor:execute_navigation]   System thought we were at: {current_position} ({current_label})")
                            print(f"[@navigation_executor:execute_navigation]   But verification confirms we're already at: {target_node_id} ({target_node_label or target_node_id})")
                            print(f"[@navigation_executor:execute_navigation] ✅ Correcting position and skipping navigation")
                            self._record_training_samples(verification_result, target_node_id, target_node_label,
                                                          tree_id, team_id, userinterface_name)
                            
                            # Correct the position tracking
                            self.update_current_position(target_node_id, tree_id, target_node_label)
                            self._mark_position_verified(target_node_id)
                            nav_context['current_node_navigation_success'] = True
                            
                            # Record dummy step showing position correction
                            if context:
                                from datetime import datetime
                                from shared.src.lib.utils.device_utils import capture_screenshot_for_script
                                
                                screenshot_path = ""
                                screenshot_id = capture_screenshot_for_script(self.device, context, f"position_corrected_{target_node_label or target_node_id}")
                                if screenshot_id and context.screenshot_paths:
                                    screenshot_path = context.screenshot_paths[-1]
                                
                                dummy_step_result = {
                                    'success': True,
                                    'from_node': target_node_label or target_node_id,
                                    'to_node': target_node_label or target_node_id,
                                    'message': f"Position tracking corrected: {current_label} → {target_node_label or target_node_id}",
                                    'already_at_destination': True,
                                    'position_tracking_bug_detected': True,
                                    'execution_time_ms': 0,
                                    'start_time': datetime.now().strftime('%H:%M:%S'),
                                    'end_time': datetime.now().strftime('%H:%M:%S'),
                                    'actions': [],
                                    'step_category': 'navigation',
                                    'step_end_screenshot_path': screenshot_path,
                                    'screenshot_path': screenshot_path
                                }
                                self._attach_verification_to_step(dummy_step_result, verification_result, context)
                                if not is_recovery:
                                    context.record_step_immediately(dummy_step_result)
                                    if hasattr(context, 'write_running_log'):
                                        context.write_running_log()

                            return self._build_result(
                                True,
                                f"Position tracking bug detected and corrected - already at '{target_node_label or target_node_id}'",
                                tree_id, target_node_id, current_node_id, start_time,
                                transitions_executed=0,
                                total_transitions=0,
                                actions_executed=0,
                                total_actions=0,
                                path_length=0,
                                already_at_target=True,
                                position_tracking_bug_corrected=True,
                                unified_pathfinding_used=True,
                                navigation_path=[],
                                final_position_node_id=target_node_id
                            )
                        elif current_check.get('has_verifications', True):
                            # Neither the tracked node nor the target is showing: the tracked
                            # position is wrong, and taking its edge would act on a screen we are
                            # not on. Forget it; the no-position flow below re-locates (home, else
                            # entry), reusing this target check instead of repeating it.
                            print(f"[@navigation_executor:execute_navigation] ❌ Neither '{tracked_label}' nor "
                                  f"'{target_node_label or target_node_id}' is showing - clearing the tracked position")
                            position_disproved_node_id = current_position
                            one_step_target_probe = verification_result
                            nav_context['current_node_id'] = None
                            nav_context['current_node_label'] = None
                            nav_context['current_tree_id'] = None
                            nav_context['position_timestamp'] = 0
                            nav_context['last_verified_timestamp'] = 0
                            nav_context['last_verified_node_id'] = None
                            current_position = None
                        else:
                            # The tracked node has no verifications: nothing disproves it.
                            print(f"[@navigation_executor:execute_navigation] Target not showing and '{tracked_label}' has no verifications to check - proceeding from the tracked position")

            # ACTION NODE OPTIMIZATION: If target is an action node and we're at its parent, just execute the action
            from shared.src.lib.utils.navigation_cache import get_cached_unified_graph
            unified_graph = get_cached_unified_graph(tree_id, team_id, variant=(self.device.navigation_context or {}).get('variant'))
            if unified_graph and not navigation_path:
                target_node_data = unified_graph.nodes.get(target_node_id, {})
                if target_node_data.get('node_type') == 'action':
                    # Find parent node (source of edge leading to action node)
                    parent_node_id = None
                    action_edge_data = None
                    for pred_id in unified_graph.predecessors(target_node_id):
                        parent_node_id = pred_id
                        action_edge_data = unified_graph.edges.get((pred_id, target_node_id), {})
                        break  # Action nodes typically have one parent
                    
                    parent_node_data = unified_graph.nodes.get(parent_node_id, {}) if parent_node_id else {}
                    parent_label = parent_node_data.get('label', parent_node_id)
                    
                    print(f"[@navigation_executor:execute_navigation] 🎯 ACTION NODE detected: {target_node_label or target_node_id}")
                    print(f"[@navigation_executor:execute_navigation]   → Parent: {parent_label} ({parent_node_id})")
                    print(f"[@navigation_executor:execute_navigation]   → Current position: {current_position}")
                    
                    if current_position and current_position == parent_node_id:
                        print(f"[@navigation_executor:execute_navigation] ✅ Already at parent '{parent_label}' - executing action directly")
                        
                        # Build single-step path with edge actions
                        action_sets = action_edge_data.get('action_sets', [])
                        forward_set = action_sets[0] if action_sets else {}
                        
                        single_step_path = [{
                            'transition_number': 1,
                            'step_number': 1,
                            'from_node_id': parent_node_id,
                            'to_node_id': target_node_id,
                            'from_node_label': parent_label,
                            'to_node_label': target_node_label or target_node_id,
                            'actions': forward_set.get('actions', []),
                            'retryActions': forward_set.get('retry_actions') or [],
                            'failureActions': forward_set.get('failure_actions') or [],
                            'verifications': target_node_data.get('verifications', []),
                            # Per-direction final_wait_time lives on the action_set.
                            'final_wait_time': forward_set.get('final_wait_time', 0),
                            'edge_id': action_edge_data.get('edge_id', 'unknown'),
                            'description': f"Execute action: {target_node_label or target_node_id}"
                        }]
                        
                        # Use this path for execution (skip pathfinding)
                        navigation_path = single_step_path
                        print(f"[@navigation_executor:execute_navigation] Using direct action execution (1 step, skipping full navigation)")
            
            if current_position and current_position == target_node_id and not navigation_path:
                print(f"[@navigation_executor:execute_navigation] 🔍 Context indicates already at target '{target_node_label or target_node_id}' - verifying...")
                
                # Always verify we're actually at this node (context may be stale or corrupted)
                _t = _phase_t0()
                verification_result = await self.device.verification_executor.verify_node(
                    node_id=target_node_id,
                    userinterface_name=userinterface_name,  # MANDATORY parameter
                    team_id=team_id,
                    tree_id=tree_id,
                    probe_timeout_ms=POSITION_PROBE_TIMEOUT_MS
                )
                _log_phase('nav.verify_already_at_target', _t,
                           f"target={target_node_label or target_node_id} cap_ms={POSITION_PROBE_TIMEOUT_MS} "
                           f"{self._verification_phase_detail(verification_result)}")

                # Only trust verification if verifications are defined AND passed
                if verification_result.get('success') and verification_result.get('has_verifications', True):
                    print(f"[@navigation_executor:execute_navigation] ✅ Verified at target '{target_node_label or target_node_id}' - no navigation needed")
                    self._record_training_samples(verification_result, target_node_id, target_node_label,
                                                  tree_id, team_id, userinterface_name)
                    # Update position to ensure consistency, then mark it verified
                    self.update_current_position(target_node_id, tree_id, target_node_label)
                    self._mark_position_verified(target_node_id)
                    # Mark navigation as successful
                    nav_context['current_node_navigation_success'] = True
                    
                    # Record dummy step to show from/target nodes in report
                    if context:
                        from datetime import datetime
                        from shared.src.lib.utils.device_utils import capture_screenshot_for_script
                        
                        # Capture screenshot to show verified destination state
                        screenshot_path = ""
                        screenshot_id = capture_screenshot_for_script(self.device, context, f"already_at_{target_node_label or target_node_id}")
                        if screenshot_id and context.screenshot_paths:
                            screenshot_path = context.screenshot_paths[-1]
                            print(f"📸 [@navigation_executor:execute_navigation] Screenshot captured for 'already at destination': {screenshot_id}")
                        
                        dummy_step_result = {
                            'success': True,
                            'from_node': target_node_label or target_node_id,
                            'to_node': target_node_label or target_node_id,
                            'message': f"{target_node_label or target_node_id} → {target_node_label or target_node_id}",
                            'already_at_destination': True,
                            'execution_time_ms': 0,
                            'start_time': datetime.now().strftime('%H:%M:%S'),
                            'end_time': datetime.now().strftime('%H:%M:%S'),
                            'actions': [],
                            'step_category': 'navigation',
                            'step_end_screenshot_path': screenshot_path,
                            'screenshot_path': screenshot_path
                        }
                        self._attach_verification_to_step(dummy_step_result, verification_result, context)
                        if not is_recovery:
                            context.record_step_immediately(dummy_step_result)
                            # Auto-write to running.log for frontend overlay
                            if hasattr(context, 'write_running_log'):
                                context.write_running_log()

                    _record_recovery_summary(True, 'already at target')
                    return self._build_result(
                        True,
                        f"Already at target '{target_node_label or target_node_id}'",
                        tree_id, target_node_id, current_node_id, start_time,
                        transitions_executed=0,
                        total_transitions=0,
                        actions_executed=0,
                        total_actions=0,
                        path_length=0,
                        already_at_target=True,
                        unified_pathfinding_used=True,
                        navigation_path=[],
                        final_position_node_id=target_node_id
                    )
                elif not verification_result.get('has_verifications', True):
                    print(f"[@navigation_executor:execute_navigation] ⚠️ No verifications defined for target node - cannot verify position, proceeding with navigation from entry")
                    # Clear position since we can't verify
                    nav_context['current_node_id'] = None
                    nav_context['current_node_label'] = None
                    nav_context['last_verified_timestamp'] = 0
                    nav_context['last_verified_node_id'] = None
                else:
                    print(f"[@navigation_executor:execute_navigation] ⚠️ Verification failed - context corrupted, proceeding with navigation")
                    # TASK-27 4d: context said we were here, the check failed on this frame.
                    self._record_failed_verification_sample(verification_result, target_node_id,
                                                            target_node_label, tree_id, team_id,
                                                            userinterface_name)
                    # Clear corrupted position and verification timestamp
                    nav_context['current_node_id'] = None
                    nav_context['current_node_label'] = None
                    nav_context['last_verified_timestamp'] = 0
                    nav_context['last_verified_node_id'] = None
            elif start_from_entry:
                # No "already at target" / "already at home" probe: see the fresh-start
                # block above. Pathfinding below starts at the entry node.
                pass
            elif not current_position and not navigation_path:
                if one_step_target_probe is not None:
                    # The one-step probe above just cleared a disproved position after checking
                    # this same target: reuse that answer rather than wait out the check again.
                    print(f"[@navigation_executor:execute_navigation] No current position - target '{target_node_label or target_node_id}' was checked a moment ago (not showing)")
                    verification_result = one_step_target_probe
                else:
                    # No current position - verify if already at destination before starting navigation
                    print(f"[@navigation_executor:execute_navigation] No current position - checking if already at target '{target_node_label or target_node_id}'")

                    _t = _phase_t0()
                    verification_result = await self.device.verification_executor.verify_node(
                        node_id=target_node_id,
                        userinterface_name=userinterface_name,
                        team_id=team_id,
                        tree_id=tree_id,
                        probe_timeout_ms=POSITION_PROBE_TIMEOUT_MS
                    )
                    _log_phase('nav.probe_target_no_position', _t,
                               f"target={target_node_label or target_node_id} cap_ms={POSITION_PROBE_TIMEOUT_MS} "
                               f"{self._verification_phase_detail(verification_result)}")

                # Only skip navigation if verifications exist AND passed
                if verification_result.get('success') and verification_result.get('has_verifications', True):
                    print(f"[@navigation_executor:execute_navigation] ✅ Already at target '{target_node_label or target_node_id}' - no navigation needed")
                    self._record_training_samples(verification_result, target_node_id, target_node_label,
                                                  tree_id, team_id, userinterface_name)
                    self.update_current_position(target_node_id, tree_id, target_node_label)
                    self._mark_position_verified(target_node_id)
                    nav_context['current_node_navigation_success'] = True
                    
                    # Record dummy step to show from/target nodes in report
                    if context:
                        from datetime import datetime
                        from shared.src.lib.utils.device_utils import capture_screenshot_for_script
                        
                        screenshot_path = ""
                        screenshot_id = capture_screenshot_for_script(self.device, context, f"already_at_{target_node_label or target_node_id}")
                        if screenshot_id and context.screenshot_paths:
                            screenshot_path = context.screenshot_paths[-1]
                            print(f"📸 [@navigation_executor:execute_navigation] Screenshot captured for 'already at destination': {screenshot_id}")
                        
                        dummy_step_result = {
                            'success': True,
                            'from_node': target_node_label or target_node_id,
                            'to_node': target_node_label or target_node_id,
                            'message': f"{target_node_label or target_node_id} → {target_node_label or target_node_id}",
                            'already_at_destination': True,
                            'execution_time_ms': 0,
                            'start_time': datetime.now().strftime('%H:%M:%S'),
                            'end_time': datetime.now().strftime('%H:%M:%S'),
                            'actions': [],
                            'step_category': 'navigation',
                            'step_end_screenshot_path': screenshot_path,
                            'screenshot_path': screenshot_path
                        }
                        self._attach_verification_to_step(dummy_step_result, verification_result, context)
                        if not is_recovery:
                            context.record_step_immediately(dummy_step_result)
                            if hasattr(context, 'write_running_log'):
                                context.write_running_log()

                    _record_recovery_summary(True)
                    return self._build_result(
                        True,
                        f"Already at target '{target_node_label or target_node_id}'",
                        tree_id, target_node_id, current_node_id, start_time,
                        transitions_executed=0,
                        total_transitions=0,
                        actions_executed=0,
                        total_actions=0,
                        path_length=0,
                        already_at_target=True,
                        unified_pathfinding_used=True,
                        navigation_path=[],
                        final_position_node_id=target_node_id
                    )
                elif not verification_result.get('has_verifications', True):
                    print(f"[@navigation_executor:execute_navigation] ⚠️ No verifications defined for '{target_node_label or target_node_id}' - cannot verify position, proceeding with navigation from entry")
                else:
                    # Not at target - check if at home as fallback starting position
                    # IMPORTANT: Only check home if target is NOT home (avoid duplicate verification)
                    print(f"[@navigation_executor:execute_navigation] Not at target '{target_node_label or target_node_id}' - checking if at HOME as fallback position")
                    
                    # Find home node by trying common variations: "home", "Home", "HOME"
                    home_id = None
                    home_node_label = None
                    for potential_home_label in ["home", "Home", "HOME"]:
                        try:
                            home_id = self.get_node_id(potential_home_label, tree_id, team_id)
                            home_node_label = potential_home_label
                            print(f"[@navigation_executor:execute_navigation] Found home node: {home_id} (label: {home_node_label})")
                            break
                        except ValueError:
                            continue
                    
                    # Only verify home if: (1) home exists, (2) target is NOT home, (3) home is not
                    # the tracked node the one-step probe just found missing
                    if home_id and home_id == position_disproved_node_id:
                        print(f"[@navigation_executor:execute_navigation] Home was checked a moment ago (not showing) - will navigate from entry")
                    elif home_id and home_id != target_node_id:
                        print(f"[@navigation_executor:execute_navigation] Target is not home - verifying if at home")
                        _t = _phase_t0()
                        home_verification = await self.device.verification_executor.verify_node(
                            node_id=home_id,
                            userinterface_name=userinterface_name,
                            team_id=team_id,
                            tree_id=tree_id,
                            probe_timeout_ms=POSITION_PROBE_TIMEOUT_MS
                        )
                        _log_phase('nav.probe_home_no_position', _t,
                                   f"cap_ms={POSITION_PROBE_TIMEOUT_MS} {self._verification_phase_detail(home_verification)}")

                        if home_verification.get('success') and home_verification.get('has_verifications', True):
                            print(f"[@navigation_executor:execute_navigation] ✅ Already at HOME - will navigate from HOME → {target_node_label or target_node_id}")
                            self._record_training_samples(home_verification, home_id, home_node_label,
                                                          tree_id, team_id, userinterface_name)
                            # Update position to home so pathfinding starts from there
                            self.update_current_position(home_id, tree_id, home_node_label)
                            self._mark_position_verified(home_id)
                            # Continue to pathfinding (don't return)
                        else:
                            print(f"[@navigation_executor:execute_navigation] Not at home - will navigate from entry")
                    elif home_id == target_node_id:
                        print(f"[@navigation_executor:execute_navigation] Target IS home - skipping duplicate home verification")
                    else:
                        print(f"[@navigation_executor:execute_navigation] No home node found in tree - will navigate from entry")
            else:
                # Positions don't match - proceed with navigation
                print(f"[@navigation_executor:execute_navigation] Current position ({current_position}) != target ({target_node_id}) - proceeding with navigation")
            
            # Use unified pathfinding with current navigation context position (unless path already provided)
            if not navigation_path:
                _t = _phase_t0()
                navigation_path = find_shortest_path(
                    tree_id,
                    target_node_id,
                    team_id,
                    nav_context.get('current_node_id'),
                    variant=(nav_context or {}).get('variant'),
                )
                _log_phase('nav.pathfinding', _t,
                           f"from={nav_context.get('current_node_label') or 'entry'} steps={len(navigation_path or [])}")

                if not navigation_path:
                    # Empty path but not at target - this is an error
                    nav_context['current_node_navigation_success'] = False
                    return self._build_result(
                        False, 
                        f"No unified path found to '{target_node_label or target_node_id}'",
                        tree_id, target_node_id, current_node_id, start_time,
                        unified_pathfinding_used=True
                    )
                
                print(f"[@navigation_executor:execute_navigation] Found path with {len(navigation_path)} steps")
            else:
                print(f"[@navigation_executor:execute_navigation] Using pre-computed path with {len(navigation_path)} steps (pathfinding skipped)")
            
            # Execute navigation sequence with early stopping for navigation functions
            transitions_executed = 0
            actions_executed = 0
            # Verification report URL produced by a repeat_until ("press until
            # appears/disappears") leg, bubbled to the result so the Edge Run
            # panel can link to the evidence. Last non-empty across steps wins.
            repeat_until_report_url = None
            # Per-action results accumulated across steps so the Edge Selection
            # panel (single-edge-step path) shows the same per-press trace as the
            # Edit Edge dialog instead of just the X/Y summary.
            step_action_results = []
            # Backstop against conditional-recovery loops: the sibling nodes we
            # have already landed-on-and-recovered-from in THIS navigation. If a
            # conditional edge resolves to a sibling we've already recovered from,
            # we're cycling — fail fast instead of re-splicing the same path.
            conditional_recovery_landings = set()
            # Set when a FINAL-HOP conditional edge legitimately resolved to one
            # of its sibling outcomes instead of the exact requested target. The
            # navigation still SUCCEEDS (a conditional destination is ambiguous by
            # design), but we carry the actual landing so the success result /
            # frontend can show "passed — arrived on <sibling>, not <requested>".
            arrived_on_sibling = None
            # to_node_id of the last hop whose destination verifications ran AND passed (None when
            # the last hop did not verify): the end of the navigation marks the position verified
            # only from this (BUG-0195).
            hop_verified_node_id = None
            total_actions = sum(len(step.get('actions', [])) for step in navigation_path)
            # NOTE: navigation_path can grow/shrink mid-loop when a conditional
            # edge lands on a sibling and we splice in a recovery path (see the
            # `navigation_path[step_num:] = recovery_path` site below). Read
            # `len(navigation_path)` at the point of use rather than caching a
            # `total_steps` here — otherwise "last step" and progress logs go
            # stale after recovery.

            # Verification mode: 'end' (default) | 'each' | 'auto'.
            # Determines which steps run verify_node on their destination node.
            # KPI queueing is independent — every successful step queues KPI
            # regardless of mode.
            if verification_mode not in VERIFICATION_MODES:
                print(f"[@navigation_executor:execute_navigation] Unknown verification_mode '{verification_mode}', falling back to 'end'")
                verification_mode = 'end'

            # Fetch the per-scope metrics map once if Auto mode needs to make
            # confidence-based skip decisions. NULL p_variant = base scope.
            metrics_map = None
            if verification_mode == 'auto':
                metrics_map = self._fetch_metrics_for_auto_mode(tree_id, team_id)
                if metrics_map is None:
                    print(f"[@navigation_executor:execute_navigation] Auto-mode metrics fetch failed; falling back to 'each'")
                    verification_mode = 'each'

            print(f"[@navigation_executor:execute_navigation] verification_mode={verification_mode}")

            for i, step in enumerate(navigation_path):
                step_num = i + 1
                from_node = step.get('from_node_label', 'unknown')
                to_node = step.get('to_node_label', 'unknown')
                from_node_id = step.get('from_node_id')  # UUID
                to_node_id = step.get('to_node_id')  # UUID
                
                print(f"[@navigation_executor:execute_navigation] Step {step_num}/{len(navigation_path)}: {from_node} → {to_node}{' [recovered]' if step.get('is_recovery') else ''}")
                _step_detail = f"hop={step_num}/{len(navigation_path)} {from_node}->{to_node}"
                _t_step = _phase_t0()

                # Step start screenshot - capture BEFORE action execution (like old goto_node)
                step_start_screenshot_path = ""
                if context:
                    _t = _phase_t0()
                    from shared.src.lib.utils.device_utils import capture_screenshot_for_script
                    step_name = f"step_{step_num}_{from_node}_{to_node}"
                    screenshot_id = capture_screenshot_for_script(self.device, context, f"{step_name}_start")
                    if screenshot_id:
                        # Get the actual path from context - it's the last added screenshot
                        if context.screenshot_paths:
                            step_start_screenshot_path = context.screenshot_paths[-1]
                        print(f"📸 [@navigation_executor:execute_navigation] Step-start screenshot captured: {screenshot_id}")
                    _log_phase('nav.hop.start_screenshot', _t, _step_detail)

                step_start_time = time.time()
                
                # Execute actions using device's existing executor
                actions = step.get('actions', [])
                retry_actions = step.get('retryActions', [])
                failure_actions = step.get('failureActions', [])

                # Virtual cross-tree edges (ENTER_SUBTREE / EXIT_SUBTREE) carry
                # synthetic `enter_subtree(tree_id=…)` / `exit_subtree(...)`
                # actions that exist only to mark a tree-context boundary in
                # the unified graph. They must NOT be dispatched to the device
                # — the BLE/IR remote rightfully says "unknown command". Skip
                # the action_executor call, treat as a no-op tree boundary,
                # and proceed straight to the next step. Position tracking is
                # still updated below as the step "succeeded" (we crossed the
                # boundary in the graph, no device interaction needed).
                step_is_virtual = bool(step.get('is_virtual')) or step.get('transition_type') in ('ENTER_SUBTREE', 'EXIT_SUBTREE')
                if step_is_virtual or (actions and all(
                        (a or {}).get('command') in ('enter_subtree', 'exit_subtree') for a in actions)):
                    print(f"[@navigation_executor:execute_navigation] ⤷ Step {step_num} is a virtual {step.get('transition_type', 'cross-tree')} edge — skipping device dispatch")
                    actions = []
                    retry_actions = []
                    failure_actions = []
                
                # Consolidated action count logging
                total_step_actions = len(actions) + len(retry_actions) + len(failure_actions)
                if total_step_actions > 0:
                    action_summary = f"{len(actions)}"
                    if len(retry_actions) > 0:
                        action_summary += f"+{len(retry_actions)}r"
                    if len(failure_actions) > 0:
                        action_summary += f"+{len(failure_actions)}f"
                    print(f"[@navigation_executor:execute_navigation] Step {step_num}: {action_summary} actions")
                
                # Direct measurement (Option B): we time each phase with its
                # own clock so the meaning matches the column name. No
                # subtraction tricks.
                #
                #   action_total_ms       — time spent inside ActionExecutor
                #                           (initial + retry, if any)
                #   verification_total_ms — time spent inside verify_node()
                #                           (initial + post-retry, if any)
                #   final_wait_ms         — the per-edge settle delay
                #
                # Edge action time = action_total_ms + final_wait_ms — what
                # gets averaged into edge_metrics.avg_action_time_ms. Pure
                # "how long is this edge to traverse"; never includes verify.
                #
                # Verification time = verification_total_ms — averages into
                # node_metrics.avg_verification_time_ms.
                action_total_ms = 0

                if actions:
                    # Update context for this navigation step
                    self.device.action_executor.tree_id = tree_id
                    self.device.action_executor.edge_id = step.get('edge_id')
                    self.device.action_executor.action_set_id = step.get('action_set_id')

                    # Use orchestrator for unified logging
                    from backend_host.src.orchestrator import ExecutionOrchestrator
                    action_call_start = time.time()
                    result = await ExecutionOrchestrator.execute_actions(
                        device=self.device,
                        actions=actions,
                        retry_actions=retry_actions,
                        failure_actions=failure_actions,
                        team_id=team_id,
                        context=context,
                        userinterface_name=userinterface_name,
                    )
                    action_total_ms += int((time.time() - action_call_start) * 1000)
                    _log_duration('nav.hop.actions', (time.time() - action_call_start) * 1000,
                                  f"{_step_detail} actions={len(actions)} success={result.get('success')}")

                    actions_executed += result.get('passed_count', 0)

                    if result.get('results'):
                        step_action_results.extend(result['results'])

                    if result.get('verification_report_url'):
                        repeat_until_report_url = result['verification_report_url']

                    # ✅ Track last action timestamp for zapping detection sync
                    if result.get('results'):
                        last_action_result = result['results'][-1]  # Get last executed action
                        last_action_timestamp = last_action_result.get('action_timestamp')
                        if last_action_timestamp:
                            nav_context['last_action_timestamp'] = last_action_timestamp
                else:
                    # No actions to execute, just mark as successful
                    result = {'success': True, 'main_actions_succeeded': True}

                # Settle delay defined per-edge. Applied AFTER actions (main/retry/
                # failure — whichever ran) and BEFORE verification, so verify_node
                # reads a settled screen. Per-image verification waits are separate
                # and stack on top of this if both are configured.
                final_wait_ms = step.get('final_wait_time', 0)
                if final_wait_ms > 0:
                    print(f"[@navigation_executor:execute_navigation] Step {step_num} final wait: {final_wait_ms}ms")
                    _t = _phase_t0()
                    time.sleep(final_wait_ms / 1000.0)
                    _log_phase('nav.hop.final_wait_sleep', _t, f"{_step_detail} final_wait_time={final_wait_ms}")

                # Execute verifications after actions (if any). Whether to verify
                # is decided per-step by verification_mode:
                #   - 'each' → always verify
                #   - 'end'  → only the last step verifies
                #   - 'auto' → last step always; intermediate steps verify only
                #     when both edge and node confidence < AUTO_VERIFY_CONFIDENCE_THRESHOLD
                #     (or no metrics available).
                # KPI queueing below is independent of this decision.
                verification_result = {'success': True, 'has_verifications': False, 'results': []}
                verification_total_ms = 0
                step_verifications = step.get('verifications', [])
                # Live-length read: see total_steps note above. After conditional
                # recovery splices the tail, the old i may no longer be the last
                # step (or may have become it).
                is_last_step = (i == len(navigation_path) - 1)
                # Conditional steps land on the target OR a sibling. For them the
                # retry/failure recovery is DEFERRED until after the sibling check
                # (below) — running it now (BACK/HOME, POWER) would navigate away
                # from a perfectly valid sibling landing before we ever look.
                is_conditional_step = bool(
                    step.get('is_conditional')
                    or step.get('original_edge_data', {}).get('is_conditional')
                )
                should_verify = self._should_verify_step(
                    step=step,
                    is_last_step=is_last_step,
                    verification_mode=verification_mode,
                    metrics_map=metrics_map,
                )
                if step_verifications and should_verify:
                    print(f"[@navigation_executor:execute_navigation] Executing {len(step_verifications)} verifications for step (mode={verification_mode}, last={is_last_step})")

                    to_node_id = step.get('to_node_id')
                    verification_start_time = time.time()
                    verification_result = await self.device.verification_executor.verify_node(
                        node_id=to_node_id,
                        userinterface_name=userinterface_name,
                        team_id=team_id,
                        tree_id=tree_id,
                        image_source_url=image_source_url,
                    )
                    verification_total_ms = int((time.time() - verification_start_time) * 1000)
                    _log_duration('nav.hop.verify_destination', verification_total_ms,
                                  f"{_step_detail} {self._verification_phase_detail(verification_result)}")
                    print(f"[@navigation_executor:execute_navigation] Verifications: {verification_result.get('passed_count', 0)}/{verification_result.get('total_count', 0)} passed")

                    # ✅ VERIFICATION-DRIVEN RECOVERY: main actions succeeded
                    # but verifications failed. Escalate retry_actions →
                    # failure_actions, re-verifying after each stage.
                    #
                    # action_executor only runs retry/failure on a *device
                    # command* failure; it never sees this branch because the
                    # keys were pressed fine — we're just on the wrong screen.
                    # This is the common case, so failure_actions would
                    # otherwise be dead code on every goto/KPI run.
                    verification_recovery_eligible = (
                        result.get('success', False)
                        and result.get('main_actions_succeeded', False)
                        and not verification_result.get('success', True)
                    )
                    # Non-conditional steps recover here (retry → failure). Conditional
                    # steps defer this to AFTER the sibling check (see below) so a valid
                    # sibling landing isn't trampled by recovery actions.
                    if verification_recovery_eligible and (retry_actions or failure_actions) and not is_conditional_step:
                        _t_rec = _phase_t0()
                        rec = await self._run_verification_recovery(
                            step=step,
                            retry_actions=retry_actions,
                            failure_actions=failure_actions,
                            verification_result=verification_result,
                            userinterface_name=userinterface_name,
                            team_id=team_id,
                            tree_id=tree_id,
                            image_source_url=image_source_url,
                            context=context,
                            nav_context=nav_context,
                        )
                        _log_phase('nav.hop.verification_recovery', _t_rec, _step_detail)
                        action_total_ms += rec['action_ms']
                        verification_total_ms += rec['verification_ms']
                        verification_result = rec['verification_result']
                        if rec['result'] is not None:
                            result = rec['result']  # Use recovering stage result for KPI tracking
                elif step_verifications and not should_verify:
                    print(f"[@navigation_executor:execute_navigation] Skipping verification for step {i+1}/{len(navigation_path)} (mode={verification_mode}, intermediate step with sufficient confidence)")

                # Edge action time = how long the actions ran (initial + retry)
                # plus the per-edge settle. Never includes verification time.
                # Aggregates into edge_metrics.avg_action_time_ms.
                action_time_ms = action_total_ms + final_wait_ms
                # Kept for the validation report's per-step "execution_time_ms"
                # field (legacy field name; means "wall-clock for this step").
                step_total_wall_time_ms = int((time.time() - step_start_time) * 1000)
                step_execution_time = step_total_wall_time_ms

                # Note: ActionExecutor now handles screenshots during action execution
                # No need for redundant main action screenshot here

                # Step end screenshot - capture AFTER action execution (like old goto_node)
                step_end_screenshot_path = ""
                if context:
                    _t = _phase_t0()
                    from shared.src.lib.utils.device_utils import capture_screenshot_for_script
                    screenshot_id = capture_screenshot_for_script(self.device, context, f"{step_name}_end")
                    if screenshot_id:
                        # Get the actual path from context - it's the last added screenshot
                        if context.screenshot_paths:
                            step_end_screenshot_path = context.screenshot_paths[-1]
                        print(f"📸 [@navigation_executor:execute_navigation] Step-end screenshot captured: {screenshot_id}")
                    _log_phase('nav.hop.end_screenshot', _t, _step_detail)

                # Determine final error message - verification error takes precedence over action error
                final_error = None
                debug_report_url = None  # ✅ NEW: Track debug report URL
                if not verification_result.get('success', True):
                    # Verification failed - use verification error
                    final_error = verification_result.get('error', 'Verification failed')
                    # ✅ NEW: Get debug report URL if available
                    debug_report_url = verification_result.get('debug_report_url')
                elif not result.get('success', False):
                    # Actions failed - use action error
                    final_error = result.get('error', 'Action failed')
                
                # If context is provided, record the step result (like old goto_node)
                _t = _phase_t0()
                if context:
                    from datetime import datetime
                    step_start_timestamp = datetime.fromtimestamp(step_start_time).strftime('%H:%M:%S')
                    step_end_timestamp = datetime.now().strftime('%H:%M:%S')
                    
                    # Extract action name for labeling (like old goto_node)
                    action_name = "navigation_step"  # Default fallback
                    step_actions = step.get('actions', [])
                    if step_actions and len(step_actions) > 0:
                        first_action = step_actions[0]
                        if isinstance(first_action, dict) and first_action.get('command'):
                            action_name = first_action.get('command')
                    
                    step_result = {
                        'success': result.get('success', False) and verification_result.get('success', True),  # Both actions AND verifications must succeed
                        'screenshot_path': step_end_screenshot_path,  # Use step end screenshot since ActionExecutor handles action screenshots
                        'screenshot_url': result.get('screenshot_url'),
                        'step_start_screenshot_path': step_start_screenshot_path,
                        'step_end_screenshot_path': step_end_screenshot_path,
                        'message': f"Navigation step: {from_node} → {to_node}",  # Will be updated with step number
                        'execution_time_ms': step_execution_time,
                        'start_time': step_start_timestamp,
                        'end_time': step_end_timestamp,
                        'from_node': from_node,
                        'to_node': to_node,
                        'action_name': action_name,  # Store action name like old goto_node
                        'actions': step.get('actions', []),
                        'retry_actions': step.get('retryActions', []),  # Include retry actions
                        'failure_actions': step.get('failureActions', []),  # Include failure actions
                        'action_results': result.get('results', []),  # Individual action results with categories and screenshots
                        'action_screenshots': result.get('action_screenshots', []),  # All action screenshots
                        'verifications': step.get('verifications', []),
                        'verification_results': verification_result.get('results', []),  # From verification execution
                        'verification_screenshots': verification_result.get('verification_screenshots', []),  # All verification screenshots
                        'error': final_error,  # Verification error takes precedence over action error
                        'debug_report_url': debug_report_url,  # ✅ NEW: Include debug report URL for frontend
                        'step_category': 'navigation'
                    }
                    
                    # Add verification screenshots to main screenshot collection for R2 upload
                    # This ensures cropped verification result images get uploaded to R2
                    for verif_screenshot in verification_result.get('verification_screenshots', []):
                        if verif_screenshot and context and hasattr(context, 'add_screenshot'):
                            context.add_screenshot(verif_screenshot)
                    
                    # Record step immediately - step number shown in table.
                    # Suppressed in recovery mode; a single summary row is
                    # written when execute_navigation returns.
                    if not is_recovery:
                        context.record_step_immediately(step_result)
                    # Auto-write to running.log for frontend overlay
                    if hasattr(context, 'write_running_log'):
                        context.write_running_log()
                    # Simple message without redundant step number
                    step_result['message'] = f"{from_node} → {to_node}"
                    _log_phase('nav.hop.record_report_step_and_running_log', _t, _step_detail)

                # ─── Single-write recording: edge row (+ node row if verified) ────
                # ActionExecutor and VerificationExecutor are pure primitives now;
                # NavigationExecutor owns all execution_results writes.
                action_success = result.get('success', False) and result.get('main_actions_succeeded', False)
                # `verifications_ran` is True only when we actually called verify_node
                # for this step. With verification_mode='end' / 'auto', many
                # intermediate steps will skip verification → no node row written
                # for those visits, no verification anchor for KPI.
                verifications_ran = bool(step_verifications) and should_verify
                verification_success = verification_result.get('success', True)
                verification_evidence_list = verification_result.get('verification_evidence_list', [])

                # A CONDITIONAL edge whose destination verify FAILED means the device
                # landed on a valid sibling — an EXPECTED divergence, not a failure.
                # Skip the intended-target step's record ENTIRELY (row AND KPI): its
                # action_set is SHARED with the sibling, so a row here is a redundant
                # NULL/failed duplicate that pollutes that action_set's KPI and its
                # success-rate. The conditional-recovery branch below records the real
                # source→sibling SUCCESS instead, and the spliced sibling→target step
                # records its own. A conditional edge that diverges and CANNOT recover
                # therefore leaves no per-step row — the overall navigation still fails
                # with a clear error. Non-conditional verify failures are unaffected
                # and still record their failure row + skip KPI + failure report.
                conditional_divergence = bool(
                    is_conditional_step and action_success
                    and verifications_ran and not verification_success
                )

                step_execution_result_id = None
                _t = _phase_t0()
                if not conditional_divergence:
                    step_execution_result_id = self._record_step_execution_results(
                        step=step,
                        team_id=team_id,
                        action_success=action_success,
                        verification_success=verification_success,
                        verifications_ran=verifications_ran,
                        action_time_ms=action_time_ms,
                        verification_time_ms=verification_total_ms,
                        action_error_details=result.get('error_details'),
                        verification_error_details=verification_result.get('error_details'),
                        action_message=result.get('error') or '',
                        verification_message=verification_result.get('error') or '',
                    )
                _log_phase('nav.hop.db_execution_results', _t, f"{_step_detail} verifications_ran={verifications_ran}")

                # TASK-27: destination verified -> screen-id (+ focus) sample, off the hot path.
                hop_verified_node_id = to_node_id if (
                    verifications_ran and verification_result.get('success')
                    and verification_result.get('has_verifications', True)) else None
                _t = _phase_t0()
                if (verifications_ran and verification_result.get('success')
                        and verification_result.get('has_verifications', True)):
                    self._record_training_samples(verification_result, to_node_id,
                                                  step.get('to_node_label'), tree_id, team_id,
                                                  userinterface_name, edge_id=step.get('edge_id'))
                # TASK-27 4d: destination check ran after the edge's actions and failed ->
                # unlabelled screen-id candidate. Not for a conditional divergence (a valid
                # sibling landing, not a wrong screen).
                elif (verifications_ran and not verification_success and not conditional_divergence
                        and verification_result.get('has_verifications', True)):
                    self._record_failed_verification_sample(verification_result, to_node_id,
                                                            step.get('to_node_label'), tree_id, team_id,
                                                            userinterface_name, edge_id=step.get('edge_id'))
                _log_phase('nav.hop.training_samples', _t, _step_detail)

                # Per-step KPI queue: vpt-kpi.service is event-driven, so this
                # costs nothing extra vs the old end-of-path queue. Each step
                # gets its own measurement; for goto with N steps we fire N
                # requests, each tied to its own execution_result_id.
                # (step_execution_result_id stays None for a conditional divergence,
                # so this is skipped — the recovery branch emits the real success.)
                _t = _phase_t0()
                if action_success and step_execution_result_id:
                    kpi_references = self._resolve_kpi_references(step)
                    if kpi_references:
                        nav_context = self.device.navigation_context
                        # KPI start = THIS step's action completion. Read it from
                        # the step's own action result — NOT nav_context, which is
                        # device-scoped and persists across steps and separate edge
                        # runs. A step whose own action didn't refresh it (no main
                        # actions / no-op action set → "Last Action: N/A") would
                        # otherwise inherit a STALE earlier timestamp via
                        # dict.get(key, default) (the default only applies when the
                        # key is absent, not when it holds an old value). That stale
                        # start is what inflated KPI to e.g. 2597ms — action_ts ~2s
                        # before the before-action frame — for a ~600ms transition.
                        action_completion_timestamp = step_start_time
                        if result.get('results'):
                            _step_action_ts = result['results'][-1].get('action_timestamp')
                            if _step_action_ts:
                                action_completion_timestamp = _step_action_ts
                        before_action_screenshot = result.get('before_action_screenshot')
                        action_screenshots = result.get('action_screenshots', [])
                        after_action_screenshot = action_screenshots[-1] if action_screenshots else None
                        action_details = None
                        if result.get('results'):
                            action_details = result['results'][-1].get('action_details')

                        # verification_timestamp anchors the KPI scan when
                        # destination was verified (most accurate). If no
                        # verification ran, kpi_executor falls back to forward
                        # scan from action_timestamp + last_action_wait_ms.
                        kpi_verification_timestamp = (
                            time.time() if verifications_ran and verification_success
                            and verification_result.get('has_verifications', True) else None
                        )

                        # When the live verifier RAN against the destination
                        # and FAILED, the destination wasn't on screen — and
                        # the KPI scan with a tighter window can't find what
                        # the live verifier (with its own polling timeout)
                        # already missed. Tell kpi_executor to skip the scan
                        # entirely and record a clean failure, rather than
                        # spending 10 s on a doomed exhaustive walk that just
                        # hits the deadline. Differs from "no verifications
                        # configured" / "verify mode = end skipped this step",
                        # where the scan is still useful.
                        live_verification_failed = bool(
                            verifications_ran
                            and verification_result.get('has_verifications', True)
                            and not verification_success
                        )

                        self._write_kpi_request_file(
                            execution_result_id=step_execution_result_id,
                            step=step,
                            action_timestamp=action_completion_timestamp,
                            verification_timestamp=kpi_verification_timestamp,
                            team_id=team_id,
                            userinterface_name=userinterface_name,
                            kpi_references=kpi_references,
                            before_action_screenshot_path=before_action_screenshot,
                            action_screenshot_path=after_action_screenshot,
                            action_details=action_details,
                            verification_evidence_list=verification_evidence_list,
                            live_verification_failed=live_verification_failed,
                            # Verification failure report (built at line ~1389 from
                            # verification_result). Carried so kpi_executor's
                            # short-circuit can store it as kpi_report_url.
                            live_verification_report_url=debug_report_url,
                        )
                _log_phase('nav.hop.kpi_queue', _t, _step_detail)

                # Check if EITHER actions OR verifications failed - both must succeed for step to continue
                step_failed = not result.get('success', False) or not verification_result.get('success', True)
                
                if step_failed:
                    # Determine which component failed
                    if not verification_result.get('success', True):
                        error_msg = verification_result.get('error', 'Verification failed')
                        error_details = verification_result.get('error_details', {})
                        failure_type = "verification"
                        # ✅ Extract debug report path and URL if available
                        debug_report_path = verification_result.get('debug_report_path')
                        debug_report_url = verification_result.get('debug_report_url')
                    else:
                        error_msg = result.get('error', 'Unknown error')
                        error_details = result.get('error_details', {})
                        failure_type = "action"
                        debug_report_path = None
                        debug_report_url = None
                    
                    print(f"[@navigation_executor:execute_navigation] NAVIGATION STEP FAILED:")
                    print(f"[@navigation_executor:execute_navigation]   Step {step_num}/{len(navigation_path)}: {from_node} → {to_node}")
                    print(f"[@navigation_executor:execute_navigation]   Failure type: {failure_type}")
                    print(f"[@navigation_executor:execute_navigation]   Error: {error_msg}")
                    print(f"[@navigation_executor:execute_navigation]   Execution time: {step_execution_time}ms")
                    
                    # Log additional error details if available
                    if error_details:
                        if error_details.get('edge_id'):
                            print(f"[@navigation_executor:execute_navigation]   Edge ID: {error_details.get('edge_id')}")
                        if error_details.get('actions_count'):
                            print(f"[@navigation_executor:execute_navigation]   Actions attempted: {error_details.get('actions_count')}")
                        if error_details.get('retry_actions_count'):
                            print(f"[@navigation_executor:execute_navigation]   Retry actions attempted: {error_details.get('retry_actions_count')}")
                        if error_details.get('failure_actions_count'):
                            print(f"[@navigation_executor:execute_navigation]   Failure actions attempted: {error_details.get('failure_actions_count')}")
                        
                        # Log specific actions that failed
                        failed_actions = error_details.get('actions', [])
                        if failed_actions:
                            print(f"[@navigation_executor:execute_navigation]   Failed actions:")
                            for j, action in enumerate(failed_actions):
                                cmd = action.get('command', 'unknown')
                                params = action.get('params', {})
                                print(f"[@navigation_executor:execute_navigation]     {j+1}. {cmd}: {params}")
                    
                    # Collected so the error payload can surface BOTH the target's
                    # report and every sibling's report (set by the sibling check below).
                    sibling_reports = []
                    # Populated only when sibling verification PASSED but no graph
                    # path exists from that sibling back to the requested target.
                    # The KPI script reads this from error_details to know that
                    # the conditional resolved to a known sibling and can swap
                    # the measurement target to the sibling's edge instead of
                    # grinding through N guaranteed-fail iterations.
                    sibling_landed = None

                    def _emit_recovered_kpi(reached_node_id, reached_label):
                        """Record a POSITIVE source→reached-node KPI for a conditional
                        divergence we recover from. The step's action DID reach
                        `reached_node_id` (a verified sibling sharing this edge's
                        action_set), so we measure action→reached-node as a SUCCESS —
                        replacing the skip we suppressed above. Best-effort: any failure
                        here is swallowed and never affects the navigation result.
                        Only fires when we actually suppressed a conditional skip."""
                        if not conditional_divergence:
                            return
                        try:
                            sib_edge = (self.unified_graph.edges.get((from_node_id, reached_node_id), {})
                                        if self.unified_graph else {}) or {}
                            sib_step = dict(step)
                            sib_step['to_node_id'] = reached_node_id
                            sib_step['to_node_label'] = reached_label or sib_step.get('to_node_label')
                            if sib_edge.get('edge_id'):
                                sib_step['edge_id'] = sib_edge['edge_id']
                            if sib_edge:
                                sib_step['original_edge_data'] = sib_edge
                            # action_set_id is SHARED between conditional siblings — keep step's.
                            sib_erid = self._record_step_execution_results(
                                step=sib_step,
                                team_id=team_id,
                                action_success=True,
                                verification_success=True,
                                verifications_ran=True,
                                action_time_ms=action_time_ms,
                                verification_time_ms=verification_total_ms,
                            )
                            if not sib_erid:
                                return
                            # Measure until the SIBLING screen renders → use the sibling
                            # node's own verifications (what actually verified it).
                            sib_refs = None
                            if self.unified_graph and reached_node_id in self.unified_graph.nodes:
                                sib_refs = self.unified_graph.nodes[reached_node_id].get('verifications')
                            if not sib_refs:
                                sib_refs = self._resolve_kpi_references(sib_step)
                            if not sib_refs:
                                return
                            _act_ts = step_start_time
                            if result.get('results'):
                                _t = result['results'][-1].get('action_timestamp')
                                if _t:
                                    _act_ts = _t
                            self._write_kpi_request_file(
                                execution_result_id=sib_erid,
                                step=sib_step,
                                action_timestamp=_act_ts,
                                verification_timestamp=time.time(),
                                team_id=team_id,
                                userinterface_name=userinterface_name,
                                kpi_references=sib_refs,
                                before_action_screenshot_path=result.get('before_action_screenshot'),
                                action_screenshot_path=(result.get('action_screenshots') or [None])[-1],
                                action_details=(result['results'][-1].get('action_details') if result.get('results') else None),
                                verification_evidence_list=[],
                                live_verification_failed=False,
                            )
                            print(f"[@navigation_executor:execute_navigation] 📊 Recovered KPI recorded: "
                                  f"{from_node} → {reached_label} (success; replaces suppressed skip)")
                        except Exception as _e:
                            print(f"[@navigation_executor:execute_navigation] ⚠️  Recovered KPI emit failed (non-fatal): {_e}")

                    # CONDITIONAL EDGE RECOVERY: If verification failed after successful action, try sibling edges
                    if failure_type == "verification" and result.get('success', False):
                        print(f"[@navigation_executor:execute_navigation] 🔄 Verification failed - checking for conditional edge siblings")
                        recovery_result = await self._try_conditional_edge_siblings(
                            step=step,
                            from_node_id=from_node_id,
                            expected_target_node_id=to_node_id,
                            target_node_id=target_node_id,  # Final destination
                            userinterface_name=userinterface_name,
                            team_id=team_id,
                            tree_id=tree_id,
                            context=context,
                            image_source_url=image_source_url,
                            max_attempts=3
                        )
                        sibling_reports = recovery_result.get('sibling_reports', []) or []
                        # Script report: the failed step already links the target's
                        # report inline; attach the siblings' reports too so the step
                        # shows every possible landing of the conditional was checked.
                        if context and sibling_reports and not recovery_result.get('success'):
                            step_result['sibling_reports'] = sibling_reports

                        if recovery_result.get('success'):
                            # Successfully recovered - update position and continue
                            actual_node = recovery_result.get('actual_node_id')
                            print(f"[@navigation_executor:execute_navigation] ✅ Conditional edge recovery succeeded → landed at {actual_node}")
                            
                            # Update device position
                            self.device.current_node_id = actual_node
                            
                            # Check if we reached final destination
                            if actual_node == target_node_id:
                                print(f"[@navigation_executor:execute_navigation] 🎯 Reached final destination via conditional edge")
                                _emit_recovered_kpi(actual_node, self.unified_graph.nodes.get(actual_node, {}).get('label') if self.unified_graph else None)
                                transitions_executed += 1
                                # Exit step loop and continue to final verification
                                break
                            elif actual_node in conditional_recovery_landings:
                                # We've already recovered from this exact sibling
                                # earlier in this navigation and looped back to it.
                                # Re-pressing the same conditional gives the same
                                # result — stop now instead of spinning forever.
                                print(f"[@navigation_executor:execute_navigation] 🛑 Conditional recovery loop: "
                                      f"already landed on sibling {actual_node} before — aborting")
                                actual_label = self.unified_graph.nodes.get(actual_node, {}).get('label') if self.unified_graph else None
                                sibling_landed = {
                                    'node_id': actual_node,
                                    'node_label': actual_label,
                                    'from_node_id': from_node_id,
                                    'from_node_label': from_node,
                                }
                                # Fall through to failure handling below
                            else:
                                # Forward-only recovery: search a path from the
                                # landed sibling to the target with the SOURCE node
                                # excluded, so we can never route back through the
                                # conditional edge that just diverged (the infinite
                                # loop). If no forward path exists, recovery fails
                                # and the navigation stops with a clean error.
                                conditional_recovery_landings.add(actual_node)
                                print(f"[@navigation_executor:execute_navigation] 🔍 Searching FORWARD recovery path: {actual_node} → {target_node_id} (excluding source {from_node_id})")
                                recovery_path = self._find_recovery_path(
                                    current_node_id=actual_node,
                                    target_node_id=target_node_id,
                                    tree_id=tree_id,
                                    team_id=team_id,
                                    exclude_node_ids={from_node_id}  # Forward-only: never route back through the diverging source
                                )

                                if recovery_path:
                                    print(f"[@navigation_executor:execute_navigation] ✅ Found recovery path with {len(recovery_path)} steps")
                                    # Tag each recovery step so the frontend can render a
                                    # "recovered" badge and the host logs are easy to grep
                                    # ("[recovered]" suffix). recovered_from_node_label is
                                    # the sibling we actually landed on, which the goto
                                    # panel uses to explain the divergence to the user.
                                    actual_label = self.unified_graph.nodes.get(actual_node, {}).get('label') if self.unified_graph else None
                                    _emit_recovered_kpi(actual_node, actual_label)
                                    for rec_step in recovery_path:
                                        rec_step['is_recovery'] = True
                                        if actual_label:
                                            rec_step['recovered_from_node_label'] = actual_label
                                        rec_step['recovered_from_node_id'] = actual_node
                                    # IN-PLACE splice: the for-loop's iterator is bound to
                                    # this list object at iteration start. A `navigation_path
                                    # = navigation_path[:step_num] + recovery_path` rebind
                                    # creates a NEW list and the iterator silently keeps
                                    # walking the ORIGINAL one — which is exactly how the
                                    # 2026-05-28 bug let step N+1 execute the original
                                    # (now-wrong) edge instead of the recovery tail. Mutating
                                    # the existing list lets enumerate() pick up the new tail
                                    # on the next iteration.
                                    navigation_path[step_num:] = recovery_path
                                    transitions_executed += 1
                                    continue  # Continue with next step in updated path
                                elif to_node_id == target_node_id:
                                    # FINAL-HOP conditional: this edge was the last
                                    # step toward the goto target, and the device
                                    # resolved to one of the edge's valid sibling
                                    # outcomes. A conditional destination is
                                    # ambiguous by design (we can't pick the branch),
                                    # so landing on any sibling is a SUCCESS — we
                                    # just record that we arrived on the sibling, not
                                    # the exact requested node. (We only reach here
                                    # AFTER trying a forward path to the exact target
                                    # and finding none.)
                                    actual_label = self.unified_graph.nodes.get(actual_node, {}).get('label') if self.unified_graph else None
                                    print(f"[@navigation_executor:execute_navigation] ✅ Conditional final hop resolved to sibling "
                                          f"'{actual_label}' (requested '{to_node}') — accepting as success (arrived on sibling)")
                                    self.update_current_position(actual_node, tree_id, actual_label)
                                    _emit_recovered_kpi(actual_node, actual_label)
                                    arrived_on_sibling = {
                                        'node_id': actual_node,
                                        'node_label': actual_label,
                                        'requested_node_id': target_node_id,
                                        'requested_node_label': target_node_label or to_node,
                                    }
                                    transitions_executed += 1
                                    break  # Done — go to success completion
                                else:
                                    print(f"[@navigation_executor:execute_navigation] ❌ No recovery path found from {actual_node} to {target_node_id}")
                                    # Conditional was an INTERMEDIATE hop and the
                                    # real target is unreachable from this sibling →
                                    # genuine failure. Surface the sibling identity
                                    # so the caller can see the conditional resolved,
                                    # just not toward the asked-for destination.
                                    actual_label = self.unified_graph.nodes.get(actual_node, {}).get('label') if self.unified_graph else None
                                    sibling_landed = {
                                        'node_id': actual_node,
                                        'node_label': actual_label,
                                        'from_node_id': from_node_id,
                                        'from_node_label': from_node,
                                    }
                                    # Fall through to failure handling below
                        elif is_conditional_step and (retry_actions or failure_actions):
                            # No sibling matched — the device is on neither the target
                            # nor any valid alternative. NOW run the deferred retry/
                            # failure recovery (BACK/HOME, POWER) and re-verify the
                            # target. If it recovers we're back on plan; continue.
                            print(f"[@navigation_executor:execute_navigation] 🔄 No sibling matched - running deferred retry/failure recovery")
                            rec = await self._run_verification_recovery(
                                step=step,
                                retry_actions=retry_actions,
                                failure_actions=failure_actions,
                                verification_result=verification_result,
                                userinterface_name=userinterface_name,
                                team_id=team_id,
                                tree_id=tree_id,
                                image_source_url=image_source_url,
                                context=context,
                                nav_context=nav_context,
                            )
                            action_total_ms += rec['action_ms']
                            if rec['verification_result'].get('success', True):
                                print(f"[@navigation_executor:execute_navigation] ✅ Deferred recovery succeeded → back on target {to_node_id}")
                                self.device.current_node_id = to_node_id
                                transitions_executed += 1
                                continue  # Back on plan; proceed with next step
                        # ✅ SIMPLIFIED: Skip logging for conditional edge recovery attempts (internal technical detail)
                        # Don't confuse user with "no siblings found" messages

                    # NAVIGATION FUNCTIONS: Stop immediately on ANY step failure (no recovery attempts)
                    print(f"🛑 [@navigation_executor:execute_navigation] STOPPING navigation - navigation functions do not recover from failures")

                    # Mark navigation as failed AND clear tracked position. After
                    # an action/verify failure the device's actual screen is
                    # genuinely unknown — the action may or may not have taken
                    # effect. Leaving the previous position cached would let the
                    # next call fire pre-computed actions from the wrong place.
                    nav_context['current_node_navigation_success'] = False
                    self.clear_current_position()
                    
                    detailed_error_msg = f"Navigation failed at step {step_num} ({from_node} → {to_node}): {failure_type} failed - {error_msg}"
                    
                    # Build error details with debug report path if available
                    build_error_details = {
                        'step_number': step_num,
                        'total_steps': len(navigation_path),
                        'from_node': from_node,
                        'to_node': to_node,
                        'execution_time_ms': step_execution_time,
                        'original_error': error_msg,
                        'action_details': error_details
                    }
                    
                    # ✅ Add debug report path and URL to error details if available
                    if debug_report_path:
                        build_error_details['debug_report_path'] = debug_report_path
                        print(f"[@navigation_executor:execute_navigation] Including debug_report_path in error: {debug_report_path}")
                    if debug_report_url:
                        build_error_details['debug_report_url'] = debug_report_url
                        print(f"[@navigation_executor:execute_navigation] Including debug_report_url in error: {debug_report_url}")

                    # ✅ Surface ALL failure reports — the target (expected) branch
                    # plus every conditional sibling that was checked and also failed.
                    # The frontend renders this as a list so the user sees why each
                    # possible landing failed, not just the expected one.
                    verification_reports = []
                    if debug_report_url:
                        verification_reports.append({
                            'label': to_node,
                            'kind': 'target',
                            'debug_report_url': debug_report_url,
                            'error': error_msg,
                        })
                    for rep in sibling_reports:
                        verification_reports.append({
                            'label': rep.get('label'),
                            'kind': 'sibling',
                            'debug_report_url': rep.get('debug_report_url'),
                            'error': rep.get('error'),
                        })
                    if verification_reports:
                        build_error_details['verification_reports'] = verification_reports
                        print(f"[@navigation_executor:execute_navigation] Including {len(verification_reports)} verification report(s) in error (target + {len(sibling_reports)} sibling)")

                    # Sibling-landed payload: only populated when sibling
                    # verification passed but no graph path back to the
                    # original target was found. KPI measurement uses this
                    # to swap the measured edge to the sibling's edge after
                    # the first failure instead of pointlessly retrying N
                    # times against an unreachable target.
                    if sibling_landed:
                        build_error_details['sibling_landed_node_id'] = sibling_landed['node_id']
                        build_error_details['sibling_landed_node_label'] = sibling_landed['node_label']
                        build_error_details['failed_step_from_node_id'] = sibling_landed['from_node_id']
                        build_error_details['failed_step_from_node_label'] = sibling_landed['from_node_label']
                        print(f"[@navigation_executor:execute_navigation] Sibling landed on '{sibling_landed['node_label']}' ({sibling_landed['node_id']}); surfaced in error_details for caller-side recovery")

                    _record_recovery_summary(False, detailed_error_msg)
                    return self._build_result(
                        False,
                        detailed_error_msg,
                        tree_id, target_node_id, current_node_id, start_time,
                        transitions_executed=transitions_executed,
                        total_transitions=len(navigation_path),
                        actions_executed=actions_executed,
                        total_actions=total_actions,
                        error_details=build_error_details,
                        verification_report_url=repeat_until_report_url,
                        results=step_action_results,
                        # Surface the (possibly recovery-spliced) path so the
                        # frontend's NodeGotoPanel can replace its preview steps
                        # with what actually ran. Without this, the panel keeps
                        # showing the original pre-execution preview and the user
                        # never sees the sibling re-route.
                        navigation_path=navigation_path,
                    )
                
                # LOCALIZE-DISPATCH (docs/agent/NAVIGATION_DISPATCH.md): a has_subtree menu remembers
                # its last child, so the step that just entered it landed on an UNKNOWN child, not the
                # menu. Localize among the children and re-route from the real one. Fail-safe &
                # contained: only fires for menus (cheap no-capture exit otherwise), wrapped in
                # try/except inside the helper, and degrades to the original open-loop path on any
                # error / no-match. Reuses the conditional-recovery splice (in-place navigation_path
                # slice assignment) so enumerate() picks up the new tail.
                _t = _phase_t0()
                if to_node_id and not step_failed:   # fire even when the menu IS the target (act-then-sense)
                    try:
                        # Reuse the step's already-settled frame when the run accumulates them (script
                        # navigates populate context.screenshot_paths); MCP/goto leave it empty, so the
                        # helper falls back to a capture.
                        _frame = step_end_screenshot_path or (
                            context.screenshot_paths[-1] if (context and getattr(context, 'screenshot_paths', None)) else None)
                        actual_child = self._localize_among_children(
                            to_node_id, team_id, userinterface_name, frame_path=_frame)
                        if actual_child and actual_child != to_node_id:
                            if actual_child == target_node_id:
                                self.device.current_node_id = actual_child
                                navigation_path[step_num:] = []          # remembered child IS the target
                                print(f"[@navigation_executor:dispatch] already on target {actual_child}; truncating path")
                            elif to_node_id == target_node_id:
                                # The menu IS the goto target: we entered on a remembered tab. Act-then-
                                # sense records WHICH tab (no re-route — we're on the menu; the tab is a
                                # sub-state). Reported as the final position (a PASS) via arrived_on_sibling.
                                _lbl = lambda nid: (self.unified_graph.nodes[nid].get('label', nid)
                                                    if (self.unified_graph is not None and nid in self.unified_graph) else nid)
                                self.device.current_node_id = actual_child
                                arrived_on_sibling = {
                                    'node_id': actual_child, 'node_label': _lbl(actual_child),
                                    'requested_node_label': target_node_label or _lbl(to_node_id)}
                                print(f"[@navigation_executor:dispatch] target menu {to_node_id}; sensed actual tab {actual_child}")
                            else:
                                _disp = self._find_recovery_path(
                                    current_node_id=actual_child, target_node_id=target_node_id,
                                    tree_id=tree_id, team_id=team_id, exclude_node_ids={to_node_id})
                                if _disp:
                                    self.device.current_node_id = actual_child
                                    _disp[0]['is_recovery'] = True              # badge ONLY the re-route point
                                    _disp[0]['recovered_from_node_id'] = actual_child  # (one recovery, not per-step)
                                    navigation_path[step_num:] = _disp   # in-place splice
                                    print(f"[@navigation_executor:dispatch] re-routed {actual_child} → "
                                          f"{target_node_id} ({len(_disp)} steps)")
                    except Exception as _e:
                        print(f"[@navigation_executor:dispatch] hook error: {_e}; continuing open-loop")
                _log_phase('nav.hop.localize_dispatch', _t, _step_detail)
                _log_phase('nav.hop.total', _t_step, _step_detail)

                transitions_executed += 1

            # Get final destination for consolidated success message
            final_step = navigation_path[-1] if navigation_path else {}
            final_node_id = final_step.get('to_node_id')
            final_tree_id = final_step.get('to_tree_id', tree_id)
            
            # Update current location in context after successful navigation.
            # When we arrived on a conditional sibling, the device is on THAT
            # node, not the requested (un-reached) target — track the real one.
            if context and hasattr(context, 'current_node_id') and final_node_id:
                context.current_node_id = arrived_on_sibling['node_id'] if arrived_on_sibling else final_node_id
            
            # Consolidated success message with timing and final position
            total_time = int((time.time() - start_time) * 1000)
            print(f"[@navigation_executor] Navigation to '{target_node_label or target_node_id}' completed successfully in {total_time}ms → {final_node_id}")

            # The end-of-path verification + KPI queue blocks were removed when
            # recording moved to per-step. Per-step verification on the LAST step
            # IS the final verification (verify_node on the destination), and
            # _write_kpi_request_file fires inside the loop with the per-step
            # verification_timestamp. Net effect: one verify_node call per
            # destination instead of two, and KPI queue per step instead of
            # only the final one.

            # Update position if navigation succeeded (but NOT for action nodes)
            # Track final position for frontend
            final_position_node_id = nav_context.get('current_node_id')  # Default: where we were
            _t = _phase_t0()

            if arrived_on_sibling:
                # Conditional final hop landed on a sibling. Position was already
                # set to it above; keep it rather than overwriting with the
                # requested target the device never reached.
                final_position_node_id = arrived_on_sibling['node_id']
            elif navigation_path:
                # Check if final node is an action node - actions don't update device position
                from shared.src.lib.utils.navigation_cache import get_cached_unified_graph
                unified_graph = get_cached_unified_graph(tree_id, team_id, variant=(self.device.navigation_context or {}).get('variant'))
                if unified_graph:
                    final_node_data = unified_graph.nodes.get(final_node_id, {})
                    if final_node_data.get('node_type') == 'action':
                        # For action nodes, find the parent (second-to-last step) and update position to that
                        # The parent is where we actually "are" after executing the action
                        if len(navigation_path) >= 1:
                            # Get the from_node of the last step (that's the parent)
                            parent_node_id = navigation_path[-1].get('from_node_id')
                            parent_node_label = navigation_path[-1].get('from_node_label')
                            if parent_node_id:
                                self.update_current_position(parent_node_id, tree_id, parent_node_label)
                                final_position_node_id = parent_node_id
                                print(f"[@navigation_executor] Action executed - position updated to parent: {parent_node_label} ({parent_node_id})")
                            else:
                                print(f"[@navigation_executor] Action executed - no parent found, position unchanged: {nav_context.get('current_node_label', 'unknown')}")
                        else:
                            print(f"[@navigation_executor] Action executed - empty path, position unchanged: {nav_context.get('current_node_label', 'unknown')}")
                    else:
                        self.update_current_position(final_node_id, tree_id, target_node_label)
                        final_position_node_id = final_node_id  # Position updated to target
                else:
                    # Fallback: update position if no graph available
                    self.update_current_position(final_node_id, tree_id, target_node_label)
                    final_position_node_id = final_node_id
            _log_phase('nav.update_final_position', _t, f"node={final_position_node_id}")
            _log_phase('nav.total', _t_nav_total,
                       f"target={target_node_label or target_node_id} hops={len(navigation_path)} success=True")

            # Verified mark (BUG-0195): only when the hop that reached the final position ran its
            # verifications and they passed. Not for a destination without verifications, a
            # skipped verification, an action node (position = its parent) or a sibling landing.
            if (not arrived_on_sibling and hop_verified_node_id
                    and hop_verified_node_id == final_position_node_id):
                self._mark_position_verified(final_position_node_id)
            else:
                nav_context['last_verified_timestamp'] = 0
                nav_context['last_verified_node_id'] = None
            
            # Mark navigation as successful
            nav_context['current_node_navigation_success'] = True
            
            # Count cross-tree transitions
            cross_tree_transitions = len([step for step in navigation_path if step.get('tree_context_change')])

            _record_recovery_summary(True)
            if arrived_on_sibling:
                success_message = (
                    f"Passed — arrived on conditional sibling '{arrived_on_sibling['node_label']}', "
                    f"not the requested '{arrived_on_sibling['requested_node_label']}' "
                    f"({len(navigation_path)} steps)"
                )
            else:
                success_message = f"Successfully navigated to '{target_node_label or target_node_id}' in {len(navigation_path)} steps"
            return self._build_result(
                True,
                success_message,
                tree_id, target_node_id, current_node_id, start_time,
                transitions_executed=transitions_executed,
                total_transitions=len(navigation_path),
                actions_executed=actions_executed,
                total_actions=total_actions,
                path_length=len(navigation_path),
                cross_tree_transitions=cross_tree_transitions,
                unified_pathfinding_used=True,
                navigation_path=navigation_path,  # Include full transition data for AI/frontend
                final_position_node_id=final_position_node_id,  # Where device actually is after navigation
                arrived_on_sibling=arrived_on_sibling,  # Set when a final-hop conditional resolved to a sibling
                verification_report_url=repeat_until_report_url,  # repeat_until evidence (Edge Run panel)
                results=step_action_results,  # per-action trace (Edge Selection panel)
            )

        except (UnifiedCacheError, PathfindingError) as e:
            print(f"❌ [@navigation_executor:execute_navigation] Unified navigation failed: {str(e)}")
            # Mark navigation as failed AND clear tracked position (see per-step
            # failure block above for the rationale).
            self.device.navigation_context['current_node_navigation_success'] = False
            self.clear_current_position()
            _record_recovery_summary(False, str(e))
            return self._build_result(
                False,
                str(e),
                tree_id, target_node_id, current_node_id, start_time,
                unified_pathfinding_required=True
            )
        except Exception as e:
            error_msg = f"Unexpected navigation error to '{target_node_label or target_node_id}': {str(e)}"
            print(f"❌ [@navigation_executor:execute_navigation] ERROR: {error_msg}")
            # Mark navigation as failed AND clear tracked position.
            self.device.navigation_context['current_node_navigation_success'] = False
            self.clear_current_position()
            _record_recovery_summary(False, error_msg)
            return self._build_result(
                False,
                error_msg,
                tree_id, target_node_id, current_node_id, start_time,
                unified_pathfinding_used=True
            )
    
    def get_execution_status(self, execution_id: str) -> Dict[str, Any]:
        """
        Get status of async navigation execution (called by route polling).
        
        Returns:
            {
                'success': bool,
                'execution_id': str,
                'status': 'running' | 'completed' | 'error',
                'result': dict (if completed),
                'error': str (if error),
                'progress': int,
                'message': str
            }
        """
        with self._lock:
            if execution_id not in self._executions:
                return {
                    'success': False,
                    'error': f'Execution {execution_id} not found'
                }
            
            execution = self._executions[execution_id].copy()
        
        return {
            'success': True,
            'execution_id': execution['execution_id'],
            'status': execution['status'],
            'result': execution.get('result'),
            'error': execution.get('error'),
            'progress': execution.get('progress', 0),
            'message': execution.get('message', ''),
            'tree_id': execution.get('tree_id'),
            'target_node_id': execution.get('target_node_id'),
            'elapsed_time_ms': int((time.time() - execution['start_time']) * 1000)
        }
    
    def get_navigation_preview(self, tree_id: str, target_node_id: str,
                             current_node_id: Optional[str] = None, team_id: str = None,
                             variant: Optional[str] = None) -> Dict[str, Any]:
        """
        Get navigation preview without executing - used by frontend NodeGotoPanel
        Expects unified cache to be pre-populated by tree loading

        Args:
            tree_id: Tree ID for pathfinding
            target_node_id: Target node UUID
            current_node_id: Optional current position
            team_id: Team ID
            variant: Optional explicit variant scope from the request. Wins
                over device.navigation_context — the canvas can preview a
                variant the device hasn't been switched to yet.

        Returns:
            {
                'success': bool,
                'error': str (if failed),
                'tree_id': str,
                'target_node_id': str,
                'current_node_id': str,
                'transitions': List[Dict],  # Navigation path
                'total_transitions': int,
                'total_actions': int
            }
        """
        # Check cache first (pure function: same inputs = same outputs until tree changes).
        # Key on the ROOT tree id (request can carry a subtree id when the user
        # is editing a subtree) so a request from the root tree and a request
        # from any of its subtrees share the same preview entry.
        # Variant is part of the key because variant overrides change the
        # underlying unified graph; a base preview must not be served when
        # the request is scoped to a variant.
        from shared.src.lib.utils.navigation_cache import _resolve_root_tree_id
        resolved_tree_id = _resolve_root_tree_id(tree_id, team_id) or tree_id
        if variant is None:
            variant = (self.device.navigation_context or {}).get('variant')
        cache_key = (resolved_tree_id, current_node_id or 'root', target_node_id, variant)
        if cache_key in self._preview_cache:
            print(f"[@navigation_executor:get_navigation_preview] ✅ Cache HIT for {target_node_id} from {current_node_id or 'root'} (variant={variant or 'base'})", flush=True)
            return self._preview_cache[cache_key]
        
        try:
            # Get navigation path using unified cache (should be pre-populated by tree loading)
            transitions = find_shortest_path(tree_id, target_node_id, team_id, current_node_id, variant=variant)
            
            success = bool(transitions)
            error_message = 'No navigation path found' if not success else ''
            
            result = {
                'success': success,
                'error': error_message if not success else None,
                'tree_id': tree_id,
                'target_node_id': target_node_id,
                'current_node_id': current_node_id,
                'transitions': transitions or [],
                'total_transitions': len(transitions) if transitions else 0,
                'total_actions': sum(len(t.get('actions', [])) for t in transitions) if transitions else 0
            }
            
            # Cache the result (invalidated when tree changes via populate_cache).
            # cache_key was built above with the resolved root tree id + variant.
            self._preview_cache[cache_key] = result
            print(f"[@navigation_executor:get_navigation_preview] Cached preview for {target_node_id} (variant={variant or 'base'})", flush=True)
            
            return result
            
        except PathfindingError as e:
            # No path found - target node may not exist or be unreachable
            error_message = str(e)
            print(f"[@navigation_executor:get_navigation_preview] ❌ Pathfinding error: {error_message}")
            result = {
                'success': False,
                'error': error_message,
                'tree_id': tree_id,
                'target_node_id': target_node_id,
                'current_node_id': current_node_id,
                'transitions': [],
                'total_transitions': 0,
                'total_actions': 0
            }
            # Don't cache errors
            return result
        
        except UnifiedCacheError as e:
            # Cache missing - this indicates the tree wasn't loaded properly
            print(f"[@navigation_executor:get_navigation_preview] Unified cache missing for tree {tree_id}")
            print(f"[@navigation_executor:get_navigation_preview] This indicates the NavigationEditor didn't load the tree properly")
            result = {
                'success': False,
                'error': f'Navigation tree {tree_id} not loaded. Please reload the NavigationEditor to populate the navigation cache.',
                'tree_id': tree_id,
                'target_node_id': target_node_id,
                'current_node_id': current_node_id,
                'transitions': [],
                'total_transitions': 0,
                'total_actions': 0
            }
            # Don't cache errors
            return result
        
        except Exception as e:
            print(f"[@navigation_executor:get_navigation_preview] Unexpected error: {str(e)}")
            return {
                'success': False,
                'error': f'Navigation preview error: {str(e)}',
                'tree_id': tree_id,
                'target_node_id': target_node_id,
                'current_node_id': current_node_id,
                'transitions': [],
                'total_transitions': 0,
                'total_actions': 0
            }
    
    # ========================================
    # NAVIGATION TREE MANAGEMENT METHODS
    # Note: Core tree management moved to navigation_executor_tree_manager.py for maintainability
    # These wrapper methods maintain backward compatibility with existing code
    # ========================================
    
    def load_navigation_tree(self, userinterface_name: str, team_id: str) -> Dict[str, Any]:
        """Wrapper for tree manager function. Reads the per-run variant name from
        device.navigation_context (set by the script executor from the launch payload).
        Locale probe and device_locale are kept as utilities but no longer wired here
        (reserved for a future auto-detection layer — see ENHANCE_VARIANT.md §9)."""
        storage = {}
        # Variant resolution: explicit per-run variant name from device.navigation_context.
        # Locale probe and device_locale are kept as utilities but no longer wired here.
        variant_name = None
        ui_mode = 'dev'
        if hasattr(self.device, 'navigation_context') and self.device.navigation_context:
            variant_name = self.device.navigation_context.get('variant')
            ui_mode = self.device.navigation_context.get('ui_mode', 'dev') or 'dev'
        result = tree_manager_load_navigation_tree(userinterface_name, team_id, storage, variant_name=variant_name, ui_mode=ui_mode)
        if 'graph' in storage:
            self.unified_graph = storage['graph']
        return result

    def discover_complete_hierarchy(self, root_tree_id: str, team_id: str) -> List[Dict]:
        """Wrapper for tree manager function - maintains backward compatibility"""
        return tree_manager_discover_complete_hierarchy(root_tree_id, team_id)

    def format_tree_for_hierarchy(self, tree_data: Dict, tree_info: Dict = None, is_root: bool = False) -> Dict:
        """Wrapper for tree manager function - maintains backward compatibility"""
        return tree_manager_format_tree_for_hierarchy(tree_data, tree_info, is_root)

    def build_unified_tree_data(self, hierarchy_data: List[Dict], team_id: str) -> List[Dict]:
        """Wrapper for tree manager function - maintains backward compatibility"""
        return tree_manager_build_unified_tree_data(hierarchy_data, team_id)


    # ========================================
    # NODE AND EDGE FINDING METHODS
    # Note: Core finder methods moved to navigation_executor_helpers.py for maintainability
    # These wrapper methods maintain backward compatibility with existing code
    # ========================================

    def find_node_by_label(self, nodes: List[Dict], label: str) -> Dict:
        """Wrapper for helper function - maintains backward compatibility"""
        return find_node_by_label(nodes, label)

    def find_edges_from_node(self, source_node_id: str, edges: List[Dict]) -> List[Dict]:
        """Wrapper for helper function - maintains backward compatibility"""
        return find_edges_from_node(source_node_id, edges)

    def find_edge_by_target_label(self, source_node_id: str, edges: List[Dict], nodes: List[Dict], target_label: str) -> Dict:
        """Wrapper for helper function - maintains backward compatibility"""
        return find_edge_by_target_label(source_node_id, edges, nodes, target_label)

    def find_edge_with_action_command(self, node_id: str, edges: List[Dict], action_command: str) -> Dict:
        """Wrapper for helper function - maintains backward compatibility"""
        return find_edge_with_action_command(node_id, edges, action_command)

    def get_node_sub_trees_with_actions(self, node_id: str, tree_id: str, team_id: str) -> Dict:
        """Wrapper for helper function - maintains backward compatibility"""
        return get_node_sub_trees_with_actions(node_id, tree_id, team_id)

    def find_action_in_nested_trees(self, source_node_id: str, tree_id: str, nodes: List[Dict], edges: List[Dict], action_command: str, team_id: str) -> Dict:
        """Wrapper for helper function - maintains backward compatibility"""
        return find_action_in_nested_trees(source_node_id, tree_id, nodes, edges, action_command, team_id)

    # ========================================
    # KPI MEASUREMENT METHODS
    # ========================================
    
    def _should_verify_step(
        self,
        *,
        step: Dict[str, Any],
        is_last_step: bool,
        verification_mode: str,
        metrics_map: Optional[Dict[str, Any]],
    ) -> bool:
        """Decide whether to run verify_node on a step's destination.

        Last step is always verified regardless of mode (the "did we actually
        arrive?" check at end of navigation). Intermediate steps depend on
        the chosen mode.

        Conditional steps are ALWAYS verified, regardless of mode. After the
        shared action runs the device may land on this target or on a sibling,
        and every following step's actions assume a specific branch — so we
        must verify here to detect the branch and let the conditional-edge
        recovery (see execute_navigation) re-route when it differs.

        The entry transition (ENTRY → home) is ALSO always verified, regardless
        of mode. It's the only confirmation that the device is actually at the
        assumed starting position. If the box is in standby or on a screensaver,
        skipping this check (e.g. under 'end' mode) means we proceed from a wrong
        position and never trigger the verification-driven recovery (retry/
        failure actions such as POWER) that would wake it and re-establish home.
        """
        if is_last_step:
            return True
        if step.get('is_entry_transition'):
            return True
        if step.get('is_conditional') or step.get('original_edge_data', {}).get('is_conditional'):
            return True
        if verification_mode == 'each':
            return True
        if verification_mode == 'end':
            return False
        if verification_mode == 'auto':
            if not metrics_map:
                return True  # no data → verify (safer)
            edge_key = f"{step.get('edge_id')}{('#' + step['action_set_id']) if step.get('action_set_id') else ''}"
            edge_conf = metrics_map.get('edges', {}).get(edge_key, {}).get('confidence')
            node_conf = metrics_map.get('nodes', {}).get(step.get('to_node_id'), {}).get('confidence')
            if edge_conf is None or node_conf is None:
                return True
            return not (edge_conf >= AUTO_VERIFY_CONFIDENCE_THRESHOLD
                        and node_conf >= AUTO_VERIFY_CONFIDENCE_THRESHOLD)
        return True

    def _fetch_metrics_for_auto_mode(
        self,
        tree_id: str,
        team_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Fetch the per-scope metrics map used by Auto mode's skip decision.

        Reads the active variant from device.navigation_context (NULL = base
        scope) and calls the same `get_tree_metrics_optimized` RPC the
        frontend uses, so the confidence values match what the user sees on
        the Edge Selection panel chips.
        """
        try:
            from shared.src.lib.utils.supabase_utils import get_supabase_client
            variant = (getattr(self.device, 'navigation_context', {}) or {}).get('variant')
            supabase = get_supabase_client()
            result = supabase.rpc(
                'get_tree_metrics_optimized',
                {'p_tree_id': tree_id, 'p_team_id': team_id, 'p_variant': variant},
            ).execute()
            if not result.data:
                return None
            data = result.data[0] if isinstance(result.data, list) else result.data
            return {
                'nodes': data.get('nodes') or {},
                'edges': data.get('edges') or {},
            }
        except Exception as e:
            print(f"[@navigation_executor:_fetch_metrics_for_auto_mode] RPC failed: {e}")
            return None

    def _record_step_execution_results(
        self,
        *,
        step: Dict[str, Any],
        team_id: str,
        action_success: bool,
        verification_success: bool,
        verifications_ran: bool,
        action_time_ms: int,
        verification_time_ms: int,
        action_error_details: Optional[Dict] = None,
        verification_error_details: Optional[Dict] = None,
        action_message: str = "",
        verification_message: str = "",
    ) -> Optional[str]:
        """Record one execution_results row for the edge step (always) and
        one for the destination node visit (when verifications ran).

        `action_time_ms` is the edge action duration (action calls + final_wait,
        no verification). Aggregates into edge_metrics.avg_action_time_ms.
        `verification_time_ms` is the verify_node duration (only meaningful
        when verifications_ran). Aggregates into node_metrics.avg_verification_time_ms.

        Returns the edge row's execution_result_id so the caller can attach
        a KPI request to it. ActionExecutor and VerificationExecutor no
        longer write to the DB — this is the single recording point.
        """
        from shared.src.lib.database.execution_results_db import (
            record_edge_execution,
            record_node_execution,
        )

        nav_context = getattr(self.device, 'navigation_context', {}) or {}
        script_id = nav_context.get('script_id')
        script_ctx = nav_context.get('script_context', 'direct')
        variant = nav_context.get('variant')
        is_test = bool(nav_context.get('is_test', False))

        edge_tree_id = step.get('original_edge_data', {}).get('tree_id', step.get('to_tree_id'))
        edge_id = step.get('edge_id')
        action_set_id = step.get('action_set_id')

        step_success = action_success and (verification_success if verifications_ran else True)
        step_error_details = (
            verification_error_details if verifications_ran and not verification_success
            else (action_error_details if not action_success else None)
        )
        step_message = (
            action_message if not action_success
            else (verification_message if verifications_ran and not verification_success
                  else f"{step.get('from_node_label')} → {step.get('to_node_label')}")
        )

        execution_result_id: Optional[str] = None
        if edge_id and edge_tree_id:
            # executed_at is stamped client-side at the start of this insert.
            _t = _phase_t0()
            execution_result_id = record_edge_execution(
                team_id=team_id,
                tree_id=edge_tree_id,
                edge_id=edge_id,
                host_name=self.host_name,
                device_model=self.device_model,
                device_name=self.device_name,
                success=step_success,
                # Edge action time: action calls (initial + retry) + final_wait.
                # Never includes verification time. Aggregates into
                # edge_metrics.avg_action_time_ms via the trigger.
                execution_time_ms=action_time_ms,
                message=step_message,
                error_details=step_error_details,
                action_set_id=action_set_id,
                script_result_id=script_id,
                script_context=script_ctx,
                variant=variant,
                is_test=is_test,
            )
            _log_phase('db.insert_edge_execution_result', _t, f"edge={edge_id} action_time_ms={action_time_ms}")

        # One node row per node visit (was: one row per individual verification
        # in the legacy verification_executor flow). Aggregate node_metrics
        # now reflect "visits" instead of "verification call count" — more
        # interpretable.
        if verifications_ran:
            target_node_id = step.get('to_node_id')
            target_tree_id = step.get('to_tree_id', edge_tree_id)
            if target_node_id and target_tree_id:
                _t = _phase_t0()
                record_node_execution(
                    team_id=team_id,
                    tree_id=target_tree_id,
                    node_id=target_node_id,
                    host_name=self.host_name,
                    device_model=self.device_model,
                    device_name=self.device_name,
                    success=verification_success,
                    execution_time_ms=verification_time_ms,
                    message=verification_message or 'Per-step destination verification',
                    error_details=verification_error_details,
                    script_result_id=script_id,
                    script_context=script_ctx,
                    variant=variant,
                    is_test=is_test,
                )
                _log_phase('db.insert_node_execution_result', _t, f"node={target_node_id}")

        return execution_result_id

    def _resolve_kpi_references(self, step: Dict[str, Any]) -> Optional[List[Dict]]:
        """Look up the KPI reference list for a navigated step.

        Returns the list (possibly empty) or None if the step is malformed
        (caller should skip queueing in that case). Reads from the step dict
        produced by pathfinding (which already embeds the resolved action_set
        + the destination node's verifications via populate_unified_cache).
        """
        target_node_id = step.get('to_node_id')
        action_set_id = step.get('action_set_id')
        if not target_node_id or not action_set_id:
            return None

        original_edge_data = step.get('original_edge_data', {})
        action_sets = original_edge_data.get('action_sets', [])
        if not action_sets:
            return None

        action_set = next((a for a in action_sets if a.get('id') == action_set_id), None)
        if not action_set:
            return None

        # Two sources of KPI references: the action_set's own list, or the
        # destination node's verifications (when use_verifications_for_kpi is
        # set on the action_set).
        if action_set.get('use_verifications_for_kpi', False):
            if not self.unified_graph or target_node_id not in self.unified_graph.nodes:
                return None
            verifs = self.unified_graph.nodes[target_node_id].get('verifications', [])
            if verifs:
                return verifs
            return self._fingerprint_kpi_ref(target_node_id, step.get('to_node_label'))
        # Flag OFF: only the action_set's own frozen kpi_references — NO fingerprint fallback. The
        # fingerprint KPI is opt-in, gated behind "Use target node verifications".
        return action_set.get('kpi_references', [])

    def _fingerprint_kpi_ref(self, target_node_id: str, to_node_label: Optional[str]) -> List[Dict]:
        """KPI fallback for a node with no verifications: use its stored fingerprint as the appear
        signal. The destination screen is 'on' the first frame whose region dHash is within the floor
        of the node's stored fingerprint - exactly the localize signal, no hand-authored reference
        needed. Returns a single `match_fingerprint` verification (routed to the image controller via
        verification_type='image'); [] when the node has no fingerprint."""
        if not self.unified_graph or target_node_id not in self.unified_graph.nodes:
            return []
        fp = self.unified_graph.nodes[target_node_id].get('__fingerprint') or {}
        if not fp.get('dhash'):
            return []
        return [{
            'verification_type': 'image',
            'command': 'match_fingerprint',
            'params': {'fingerprint': fp, 'threshold': 14, 'node_label': to_node_label or ''},
        }]

    def _resolve_kpi_pass_condition(self, step: Dict[str, Any], kpi_references: List[Dict]) -> str:
        """Resolve the verification pass_condition for a KPI scan.

        Mirrors verify_node's priority so the KPI scan reaches the SAME verdict
        as the live navigation verify. Without this, the KPI scan would default
        to 'all' and fail whenever a node passes live under 'any' (e.g. one of
        two destination references is stale) — even though the goto succeeded.

        Priority: 1) first reference's embedded verification_pass_condition,
        2) destination node's verification_pass_condition, 3) 'all'.
        """
        if (kpi_references and isinstance(kpi_references[0], dict)
                and 'verification_pass_condition' in kpi_references[0]):
            return kpi_references[0]['verification_pass_condition']
        target_node_id = step.get('to_node_id')
        if self.unified_graph and target_node_id in self.unified_graph.nodes:
            return self.unified_graph.nodes[target_node_id].get('verification_pass_condition', 'all')
        return 'all'

    def _write_kpi_request_file(
        self,
        *,
        execution_result_id: str,
        step: Dict[str, Any],
        action_timestamp: float,
        verification_timestamp: Optional[float],
        team_id: str,
        userinterface_name: str,
        kpi_references: List[Dict],
        before_action_screenshot_path: Optional[str] = None,
        action_screenshot_path: Optional[str] = None,
        action_details: Optional[Dict] = None,
        verification_evidence_list: Optional[List[Dict]] = None,
        live_verification_failed: bool = False,
        live_verification_report_url: Optional[str] = None,
    ):
        """Write a KPI measurement JSON request to /tmp/kpi_queue/ for vpt-kpi.service.

        The execution_results row has already been INSERTed by
        _record_step_execution_results — kpi_executor.py PATCHes
        kpi_measurement_ms onto that row when the scan completes.
        """
        if os.getenv('HOST_PROFILE', '').strip().lower() == 'lite':
            # Lite hosts (TASK-83) run no vpt-kpi: a request file would never be consumed.
            return
        try:
            target_tree_id = step.get('to_tree_id')
            edge_tree_id = step.get('original_edge_data', {}).get('tree_id', target_tree_id)

            # Last action's wait_time (for forward-scan KPI when no verification anchor)
            actions = step.get('actions', [])
            last_action_wait_ms = 0
            if actions:
                last_action = actions[-1]
                params = last_action.get('params', {})
                if 'wait_time' in params:
                    last_action_wait_ms = int(params['wait_time'])
                elif last_action.get('command') == 'wait' and 'duration' in params:
                    last_action_wait_ms = int(params['duration'] * 1000)

            capture_dir = self.device.get_capture_dir('captures')
            if not capture_dir:
                print(f"⚠️ [NavigationExecutor] No capture_dir for device {self.device_id} - KPI skipped")
                return

            # KPI references store timeout in MILLISECONDS under params.timeout —
            # the SAME field every other reader uses (live verifiers divide
            # params.timeout by 1000; the KPI scan reads kpi_ref['params']['timeout']).
            # The frontend KPI editor writes the user's "Timeout (ms)" there too, so
            # reading params.timeout is what makes the dialog's value (e.g. 12000)
            # actually drive the scan window. Reading a TOP-LEVEL ref['timeout']
            # (which never exists) silently defaulted every KPI to 5000ms.
            timeout_ms = int(max(
                ((ref.get('params') or {}).get('timeout', 5000) for ref in kpi_references),
                default=5000,
            ))

            # Which source produced kpi_references — the destination node's live
            # verifications (use_verifications_for_kpi=True) or the action_set's
            # own frozen kpi_references snapshot (False). Surfaced in the report
            # so a "wrong reference set" can be diagnosed without DB spelunking:
            # editing a node's verifications only propagates to KPI when this is
            # True; otherwise the edge's snapshot is authoritative. See
            # _resolve_kpi_references for the matching priority.
            action_set_id = step.get('action_set_id')
            use_verifications_for_kpi = False
            action_set_kpi_name = ''
            for a in (step.get('original_edge_data', {}) or {}).get('action_sets', []):
                if (a or {}).get('id') == action_set_id:
                    use_verifications_for_kpi = bool(a.get('use_verifications_for_kpi', False))
                    # The edge's own friendly KPI name (Edge Edit dialog → kpi_name).
                    action_set_kpi_name = (a.get('kpi_name') or '').strip()
                    break

            kpi_variant = (getattr(self.device, 'navigation_context', {}) or {}).get('variant')
            # Friendly name for the KPI report header. Priority:
            #   1. A run-level label set by a script on device.navigation_context
            #      (e.g. standby_measurement's standby-mode name — the measured
            #      edge is identical across modes so it must come from the script).
            #   2. The edge action_set's own kpi_name (Edge Edit "KPI display
            #      name"), so EVERY KPI report (kpi_measurement, edge run, goto)
            #      shows it automatically when set — no per-script wiring needed.
            kpi_display_label = (
                (getattr(self.device, 'navigation_context', {}) or {}).get('kpi_display_label')
                or action_set_kpi_name
                or None
            )

            request_data = {
                'execution_result_id': execution_result_id,
                'team_id': team_id,
                'capture_dir': capture_dir,
                'action_timestamp': action_timestamp,
                'verification_timestamp': verification_timestamp,
                'kpi_references': kpi_references,
                # Pass condition ('all' / 'any') from the destination node, so the
                # KPI scan reaches the same verdict as the live nav verify. Without
                # it the scan defaults to 'all' and never matches a node that
                # passes live under 'any'.
                'verification_pass_condition': self._resolve_kpi_pass_condition(step, kpi_references),
                # Diagnostic: which source backed kpi_references (see above).
                'use_verifications_for_kpi': use_verifications_for_kpi,
                'timeout_ms': timeout_ms,
                'device_id': self.device_id,
                'device_model': self.device_model,
                'userinterface_name': userinterface_name,  # MANDATORY for reference resolution
                'last_action_wait_ms': last_action_wait_ms,
                # Run scope (NULL = base) — for diagnostics. The trigger reads
                # NEW.variant straight off execution_results, so kpi_executor
                # does not have to forward it on the PATCH body.
                'variant': kpi_variant,
                # Extended metadata for report
                'host_name': self.host_name,
                'device_name': self.device_name,
                'tree_id': edge_tree_id,
                'action_set_id': step.get('action_set_id'),
                'from_node_label': step.get('from_node_label'),
                'to_node_label': step.get('to_node_label'),
                'last_action': step.get('last_action'),  # Last action pressed
                'kpi_display_label': kpi_display_label,  # Optional run-level friendly name

                'before_action_screenshot_path': before_action_screenshot_path,  # ✅ Before screenshot
                'action_screenshot_path': action_screenshot_path,  # After screenshot
                'action_details': action_details or {},  # ✅ NEW: Action execution details
                'verification_evidence_list': verification_evidence_list or [],  # ✅ NEW: Verification evidence
                # When True, kpi_executor short-circuits: it knows the live
                # verifier already failed against the destination so the
                # scan can't find a match either. Saves the 10 s deadline
                # cost on each genuine navigation failure.
                'live_verification_failed': live_verification_failed,
                # The live destination verifier already generated a self-contained
                # failure report (reference + failed source crop + overlay) when
                # it failed. The short-circuit path doesn't run the KPI scan and
                # so can't build its own report — so it adopts THIS url as the
                # KPI row's kpi_report_url, giving the summary a clickable link
                # to the exact frame/crop that failed instead of an empty cell.
                'live_verification_report_url': live_verification_report_url,
            }
            
            # Write to JSON file queue for standalone KPI executor service (atomic write for inotify)
            kpi_queue_dir = '/tmp/kpi_queue'
            os.makedirs(kpi_queue_dir, exist_ok=True)
            
            request_id = str(uuid.uuid4())
            temp_file = os.path.join(kpi_queue_dir, f'kpi_request_{request_id}.json.tmp')
            final_file = os.path.join(kpi_queue_dir, f'kpi_request_{request_id}.json')
            
            # Atomic write: write to .tmp, then rename (triggers inotify IN_MOVED_TO)
            with open(temp_file, 'w') as f:
                json.dump(request_data, f, indent=2)
            # Windows-safe atomic overwrite (os.rename fails if destination exists)
            os.replace(temp_file, final_file)
            
            print(f"📊 [NavigationExecutor] KPI queued for {step.get('to_node_label')} ({len(kpi_references)} refs, {timeout_ms}ms timeout)")
            print(f"📝 [NavigationExecutor] KPI request file: {os.path.basename(final_file)}")
        
        except ValueError as e:
            # Validation errors from KPIMeasurementRequest - log and skip
            print(f"❌ [NavigationExecutor] KPI validation failed: {e}")
        except Exception as e:
            # Unexpected errors - log and skip
            print(f"❌ [NavigationExecutor] KPI queue error: {e}")
    
    # ========================================
    # POSITION TRACKING METHODS
    # ========================================
    
    def get_current_position(self) -> Dict[str, Any]:
        """Get current navigation position for this device"""
        nav_context = self.device.navigation_context
        return {
            'success': True,
            'device_id': self.device_id,
            'current_node_id': nav_context['current_node_id'],
            'current_node_label': nav_context['current_node_label'],
            'current_tree_id': nav_context['current_tree_id']
        }
    
    def get_node_id(self, node_label: str, tree_id: str = None, team_id: str = None) -> str:
        """
        Get node_id by label using loaded unified graph
        
        Args:
            node_label: Label to search for
            tree_id: Optional tree ID for auto-sync if graph not loaded
            team_id: Optional team ID for auto-sync if graph not loaded
            
        Returns:
            Node ID matching the label
        """
        # Variant-aware refresh — `self.unified_graph` can be stale on variant
        # switch; the cache key includes the active variant so re-fetching is
        # cheap and correct.
        if tree_id and team_id:
            self._sync_unified_graph(tree_id, team_id)

        if not self.unified_graph:
            raise ValueError("Unified graph not loaded - call load_navigation_tree() first or provide tree_id and team_id")

        for node_id, node_data in self.unified_graph.nodes(data=True):
            if node_data.get('label') == node_label:
                return node_id
        raise ValueError(f"Node with label '{node_label}' not found in navigation graph")
    
    def get_node_label(self, node_id: str, tree_id: str = None, team_id: str = None) -> str:
        """
        Find node label by node_id using loaded unified graph
        
        Args:
            node_id: Node ID to search for
            tree_id: Optional tree ID for auto-sync if graph not loaded
            team_id: Optional team ID for auto-sync if graph not loaded
            
        Returns:
            Node label
        """
        # Variant-aware refresh — see comment in get_node_id().
        if tree_id and team_id:
            self._sync_unified_graph(tree_id, team_id)

        if not self.unified_graph:
            raise ValueError("Unified graph not loaded - call load_navigation_tree() first or provide tree_id and team_id")

        if node_id in self.unified_graph.nodes:
            node_data = self.unified_graph.nodes[node_id]
            return node_data.get('label')  # Fallback to node_id if no label

        raise ValueError(f"Node with id '{node_id}' not found in navigation graph")

    async def _run_verification_recovery(
        self,
        *,
        step: Dict,
        retry_actions: List[Dict],
        failure_actions: List[Dict],
        verification_result: Dict[str, Any],
        userinterface_name: str,
        team_id: str,
        tree_id: str,
        image_source_url: Optional[str],
        context,
        nav_context: Dict,
    ) -> Dict[str, Any]:
        """Run the retry → failure recovery stages after a step's verification
        failed. Used by execute_navigation both for normal steps (inline) and as
        the deferred fallback for conditional steps (after the sibling check
        finds no valid alternative landing).

        RETRY vs FAILURE semantics:
          - RETRY actions are an attempt to actually reach the target, so after
            they run we RE-VERIFY the target node. If it now passes, the step is
            recovered.
          - FAILURE actions are terminal cleanup/reset (e.g. POWER cycle to leave
            the box in a known state). They run only if retry didn't recover, and
            we do NOT re-verify after them — a goto must never report success
            purely because a failure/reset action ran. The step stays failed.

        `verification_result` is the step's current (failed) result; it's
        returned unchanged unless a retry re-verify replaces it.

        Returns:
            {
              'verification_result': result to use going forward (success only if retry recovered),
              'result': the recovering retry stage's action result (or None),
              'action_ms': total ms spent running recovery actions,
              'verification_ms': total ms spent on re-verifications,
            }
        """
        from backend_host.src.orchestrator import ExecutionOrchestrator

        action_ms = 0
        verification_ms = 0
        recovering_result = None

        async def _run_stage(stage_name: str, stage_actions: List[Dict]):
            nonlocal action_ms
            print(f"[@navigation_executor:execute_navigation] ⚠️ Verifications failed - attempting {stage_name} actions ({len(stage_actions)})")
            stage_call_start = time.time()
            stage_result = await ExecutionOrchestrator.execute_actions(
                device=self.device,
                actions=stage_actions,
                retry_actions=[],
                failure_actions=[],
                team_id=team_id,
                context=context,
                userinterface_name=userinterface_name,
            )
            action_ms += int((time.time() - stage_call_start) * 1000)
            if stage_result.get('results'):
                last_stage_timestamp = stage_result['results'][-1].get('action_timestamp')
                if last_stage_timestamp:
                    nav_context['last_action_timestamp'] = last_stage_timestamp
            return stage_result

        # Stage 1 — RETRY: run, then re-verify the target.
        if retry_actions:
            stage_result = await _run_stage('retry', retry_actions)
            if not stage_result.get('success', False):
                print(f"[@navigation_executor:execute_navigation] ❌ Retry actions failed - verification remains failed")
            else:
                print(f"[@navigation_executor:execute_navigation] Retry actions succeeded - re-verifying node")
                stage_verif_start = time.time()
                verification_result = await self.device.verification_executor.verify_node(
                    node_id=step.get('to_node_id'),
                    userinterface_name=userinterface_name,
                    team_id=team_id,
                    tree_id=tree_id,
                    image_source_url=image_source_url,
                )
                verification_ms += int((time.time() - stage_verif_start) * 1000)
                print(f"[@navigation_executor:execute_navigation] Post-retry verifications: {verification_result.get('passed_count', 0)}/{verification_result.get('total_count', 0)} passed")
                if verification_result.get('success', True):
                    print(f"[@navigation_executor:execute_navigation] ✅ Retry actions + verifications succeeded")
                    recovering_result = stage_result

        # Stage 2 — FAILURE: cleanup only, runs if retry didn't recover. No re-verify.
        if recovering_result is None and failure_actions:
            await _run_stage('failure', failure_actions)
            print(f"[@navigation_executor:execute_navigation] Failure actions ran (cleanup) - step remains failed, no re-verification")

        return {
            'verification_result': verification_result,
            'result': recovering_result,
            'action_ms': action_ms,
            'verification_ms': verification_ms,
        }

    async def _try_conditional_edge_siblings(
        self,
        step: Dict,
        from_node_id: str,
        expected_target_node_id: str,
        target_node_id: str,
        userinterface_name: str,
        team_id: str,
        tree_id: str,
        context: Any,
        image_source_url: str,
        max_attempts: int = 3
    ) -> Dict[str, Any]:
        """
        Try verifying sibling edges (conditional edges with same action_set_id).
        
        When a verification fails after successful action execution, this tries to verify
        alternative target nodes that share the same action (same action_set_id from same source).
        
        Args:
            step: The failed step dict
            from_node_id: Source node ID
            expected_target_node_id: The target we expected but failed to verify
            target_node_id: Final destination node ID
            userinterface_name: UI name
            team_id: Team ID
            tree_id: Tree ID
            context: Execution context
            image_source_url: Screenshot source
            max_attempts: Max sibling attempts (default 3)
            
        Returns:
            Dict with success=True and actual_node_id if found, or success=False
        """
        print(f"[@navigation_executor:_try_conditional_edge_siblings] Checking for sibling edges from {from_node_id}")
        
        # Get unified graph to find sibling edges
        if not self.unified_graph:
            return {'success': False, 'error': 'No unified graph loaded'}
        
        # Get the edge data for the failed transition
        if not self.unified_graph.has_edge(from_node_id, expected_target_node_id):
            print(f"[@navigation_executor:_try_conditional_edge_siblings] Edge not found in graph")
            return {'success': False, 'error': 'Edge not found'}
        
        failed_edge_data = self.unified_graph.edges[from_node_id, expected_target_node_id]
        
        # ✅ Use pre-computed sibling list from graph (stored during graph creation)
        sibling_node_ids = failed_edge_data.get('sibling_node_ids', [])
        
        if not sibling_node_ids:
            print(f"[@navigation_executor:_try_conditional_edge_siblings] ⚠️ No pre-computed siblings found for this edge")
            return {'success': False, 'error': 'No conditional siblings'}
        
        print(f"[@navigation_executor:_try_conditional_edge_siblings] Found {len(sibling_node_ids)} pre-computed sibling(s)")
        
        # Build sibling edges list with labels
        sibling_edges = []
        for sibling_node_id in sibling_node_ids:
            sibling_node_data = self.unified_graph.nodes.get(sibling_node_id, {})
            sibling_label = sibling_node_data.get('label', sibling_node_id)
            sibling_edges.append({
                'target_node_id': sibling_node_id,
                'target_label': sibling_label,
                'edge_data': self.unified_graph.edges.get((from_node_id, sibling_node_id), {})
            })
            print(f"[@navigation_executor:_try_conditional_edge_siblings] Sibling: {sibling_label} ({sibling_node_id})")
        
        # Try verifying each sibling (max attempts). Collect each failed sibling's
        # debug report so the caller can surface BOTH the target's and the
        # siblings' reports — otherwise the user only sees why the target branch
        # failed, never why the alternative branches failed too.
        attempts = 0
        sibling_reports = []
        for sibling in sibling_edges:
            if attempts >= max_attempts:
                print(f"[@navigation_executor:_try_conditional_edge_siblings] Max attempts ({max_attempts}) reached")
                break

            attempts += 1
            sibling_node_id = sibling['target_node_id']
            sibling_label = sibling['target_label']

            print(f"[@navigation_executor:_try_conditional_edge_siblings] Attempt {attempts}/{max_attempts}: Verifying {sibling_label} ({sibling_node_id})")

            # Verify sibling node
            verification_result = await self.device.verification_executor.verify_node(
                node_id=sibling_node_id,
                userinterface_name=userinterface_name,
                team_id=team_id,
                tree_id=tree_id,
                image_source_url=image_source_url
            )

            if verification_result.get('success'):
                print(f"[@navigation_executor:_try_conditional_edge_siblings] ✅ Verification passed for {sibling_label}")
                return {
                    'success': True,
                    'actual_node_id': sibling_node_id,
                    'actual_node_label': sibling_label,
                    'attempts': attempts
                }
            else:
                print(f"[@navigation_executor:_try_conditional_edge_siblings] ❌ Verification failed for {sibling_label}")
                report_url = verification_result.get('debug_report_url')
                if report_url:
                    sibling_reports.append({
                        'label': sibling_label,
                        'node_id': sibling_node_id,
                        'debug_report_url': report_url,
                        'error': verification_result.get('error', 'Verification failed'),
                    })

        return {
            'success': False,
            'error': f'All {attempts} sibling verification(s) failed',
            'sibling_reports': sibling_reports,
        }
    
    def _find_recovery_path(
        self,
        current_node_id: str,
        target_node_id: str,
        tree_id: str,
        team_id: str,
        exclude_node_ids: set = None
    ) -> Optional[List[Dict]]:
        """
        Find a FORWARD recovery path from the landed sibling to the target.

        Used after a conditional edge resolves to a sibling that isn't the
        requested target. The path is searched with `exclude_node_ids` removed
        from the graph — the caller passes the source node we just diverged
        from, so recovery can only progress forward and can never route back
        through the same conditional edge (which would loop forever). If no
        forward path exists, returns None and the caller fails the navigation.

        Args:
            current_node_id: Where we actually landed (the sibling)
            target_node_id: Where we want to go
            tree_id: Tree ID
            team_id: Team ID
            exclude_node_ids: Nodes to remove from the search (e.g. the source)

        Returns:
            List of navigation steps or None if no forward path found
        """
        try:
            # Use pathfinding to find route from current to target
            recovery_path = find_shortest_path(
                tree_id=tree_id,
                target_node_id=target_node_id,
                team_id=team_id,
                start_node_id=current_node_id,
                variant=(self.device.navigation_context or {}).get('variant'),
                exclude_node_ids=exclude_node_ids,
            )
            
            if recovery_path:
                print(f"[@navigation_executor:_find_recovery_path] Found path with {len(recovery_path)} steps")
                return recovery_path
            else:
                print(f"[@navigation_executor:_find_recovery_path] No path found")
                return None
                
        except Exception as e:
            print(f"[@navigation_executor:_find_recovery_path] Error finding path: {e}")
            return None
    
    def update_current_position(self, node_id: str, tree_id: str = None, node_label: str = None) -> Dict[str, Any]:
        """Update current navigation position for this device"""
        nav_context = self.device.navigation_context
        
        # Clear verification timestamp if position changed
        old_position = nav_context.get('current_node_id')
        if old_position != node_id:
            nav_context['last_verified_timestamp'] = 0
        # Setting a position is a claim, not a verification: callers that just verified the node
        # mark it afterwards (_mark_position_verified). BUG-0195.
        nav_context['last_verified_node_id'] = None
        
        nav_context['current_node_id'] = node_id
        nav_context['current_tree_id'] = tree_id
        nav_context['current_node_label'] = node_label
        # Track when position was set for staleness checks
        nav_context['position_timestamp'] = time.time()
        
        # Only log position updates when called directly (not from navigation completion)
        # Navigation completion already logs the final position
        import inspect
        caller_function = inspect.stack()[1].function
        if caller_function != 'execute_navigation':
            print(f"[@navigation_executor] Position updated: {self.device_id} → {node_id}")
        
        return {
            'success': True,
            'device_id': self.device_id,
            'current_node_id': nav_context['current_node_id'],
            'current_node_label': nav_context['current_node_label'],
            'current_tree_id': nav_context['current_tree_id']
        }
    
    def clear_current_position(self) -> Dict[str, Any]:
        """Clear current navigation position (e.g., when switching interfaces)"""
        nav_context = self.device.navigation_context
        old_position = {
            'node_id': nav_context['current_node_id'],
            'tree_id': nav_context['current_tree_id'],
            'node_label': nav_context['current_node_label']
        }
        
        nav_context['current_node_id'] = None
        nav_context['current_tree_id'] = None
        nav_context['current_node_label'] = None
        nav_context['position_timestamp'] = 0
        nav_context['last_verified_timestamp'] = 0
        nav_context['last_verified_node_id'] = None
        
        print(f"[@navigation_executor] Cleared position for {self.device_id} (was: {old_position['node_id']})")
        
        return {
            'success': True,
            'device_id': self.device_id,
            'previous_position': old_position,
            'current_position': None
        }
