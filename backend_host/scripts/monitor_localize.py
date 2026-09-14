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
from typing import Any, Dict, List, Optional

logger = logging.getLogger("capture_monitor")

# How long a UI's loaded fingerprint set is reused before re-querying the DB.
# Lets a re-fingerprint (backfill / Reset fingerprint) be picked up without a
# monitor restart, without querying the DB on every frame.
_FP_TTL_SECONDS = 300



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
        self._helpers = None  # lazy ImageHelpers (only when first enabled device seen)
        # device_id -> last logged verdict signature (node label / state / 'unknown'),
        # so the forensic trail only fires on an actual verdict CHANGE, not per frame.
        self._last_sig: Dict[str, str] = {}

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
        return node_fps

    def localize_frame(self, device_id: str, frame_path: str) -> Optional[Dict[str, Any]]:
        """Identify the screen in `frame_path` for `device_id`.

        Returns None when the feature is disabled for this device (no env var) or
        on any error. When enabled, returns:
            {'node': <label>|None, 'confidence': <0..1>, 'excluded': int, 'total': int,
             'state'?: 'no_signal'|'blackscreen', 'state_label'?: str}
        `node` is None when nothing is recognized (overlay shows "unknown"), or the
        named `state`/`state_label` for a capture-side no-signal / black state.
        """
        resolved = self._resolve_ui(device_id)
        if not resolved:
            return None
        userinterface_name, _variant = resolved
        try:
            # NOTE: non-base variants fall back to base fingerprints here — the
            # standalone monitor does not do variant-override resolution (the enable
            # log records the configured variant). All current devices run 'base'.
            node_fps = self._load_node_fps(userinterface_name)
            if not node_fps:
                return {"node": None, "confidence": 0.0, "excluded": 0, "total": 0}

            import cv2
            img = cv2.imread(frame_path)
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
            result = helpers.identify_screen(img, node_fps)

            cands = result.get("candidates") or []
            top = cands[0] if cands else None
            out = {
                "node": top["label"] if top else None,
                "confidence": top["confidence"] if top else 0.0,
                "excluded": result.get("excluded_count", 0),
                "total": result.get("total", len(node_fps)),
            }
            if result.get("state"):
                out["state"] = result["state"]
                out["state_label"] = result.get("state_label")
            self._record_change(device_id, frame_path, out, result.get("reason"))
            return out
        except Exception as e:
            logger.warning(f"[localize] localize_frame failed for {device_id}: {e}")
            return None

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
