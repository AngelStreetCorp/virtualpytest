#!/usr/bin/env python3
"""Shared setup + node loading for the fingerprint benchmark harness.

Resolves the repo root from this file's location (override with VPT_ROOT), loads the
.env, and exposes helpers to load a UI's node fingerprints from the DB and to fetch the
STORED screenshot for a node (cached under /tmp/vpt_localize_cache).

Matcher under test (backend_host/src/controllers/verification/image_helpers.py):
  v4 = ImageHelpers.match_fingerprint(gray, focus, node_fps)
  v5 = ImageHelpers.match_fingerprint_v5(gray, regions, focus, node_fps)
  regions = _region_dhashes(gray) ; focus = _focus_signature(img_bgr)
To add v6: implement match_fingerprint_v6 there, then add a `v6` column in each bench (see README).
"""
import os
import sys
from urllib.parse import urlparse

ROOT = os.environ.get("VPT_ROOT") or os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../../..")
)
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend_host/src"))
sys.path.insert(0, os.path.join(ROOT, "backend_host/scripts"))   # no_reference_focus_detector
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from shared.src.lib.utils.supabase_utils import get_supabase_client  # noqa: E402
from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils  # noqa: E402
from backend_host.src.controllers.verification.image_helpers import ImageHelpers  # noqa: E402

CACHE = "/tmp/vpt_localize_cache"
FLOOR = ImageHelpers.FP_SELF_DRIFT_FLOOR  # 14


def remote_key(screenshot: str) -> str:
    """Stored screenshot value -> R2 object key (handles bare key OR full pub-*.r2.dev URL)."""
    return urlparse(screenshot).path.lstrip("/") if screenshot.startswith("http") else screenshot


def load_nodes(uiname: str):
    """Return (ImageHelpers, supabase, cloudflare, [ {node_id,label,fingerprint} ... ]) for a UI.

    De-dupes by node_id (a menu node + its subtree-head copy share one fingerprint). Only nodes with a
    stored fingerprint (dhash) are returned — those are the localize candidate set.
    """
    H = ImageHelpers(None, None)
    sb = get_supabase_client()
    cf = get_cloudflare_utils()
    ui = sb.table("userinterfaces").select("id").eq("name", uiname).execute().data[0]["id"]
    trees = sb.table("navigation_trees").select("id").eq("userinterface_id", ui).execute().data
    nodes = []
    seen = set()
    for t in trees:
        for n in sb.table("navigation_nodes").select("node_id,label,data").eq("tree_id", t["id"]).execute().data:
            if n["node_id"] in seen:
                continue
            d = n.get("data") or {}
            fp = d.get("fingerprint")
            if not (fp and fp.get("dhash")):
                continue
            seen.add(n["node_id"])
            nodes.append({"node_id": n["node_id"], "label": n["label"],
                          "fingerprint": fp, "screenshot": d.get("screenshot")})
    return H, sb, cf, nodes


def stored_image(cf, screenshot: str):
    """Download (cached) a node's STORED screenshot. Returns a local path or None."""
    import os as _os
    if not screenshot:
        return None
    _os.makedirs(CACHE, exist_ok=True)
    key = remote_key(screenshot)
    lp = _os.path.join(CACHE, key.replace("/", "_"))
    if not _os.path.exists(lp):
        try:
            if not cf.download_file(key, lp).get("success"):
                return None
        except Exception:
            return None
    return lp


# ── v6 focused-element crop descriptor ─────────────────────────────────────────────────
# Crop computation is the PRODUCTION helper ImageHelpers._focus_crop_hex (single source). Once
# fingerprints are backfilled with fp['crop'], inject_node_crops is a no-op fallback for nodes
# that predate the backfill.
import cv2  # noqa: E402


def focus_crop_hex(H, img_bgr):
    """dHash of the FOCUSED tile's logo, or None. Delegates to the PRODUCTION helper
    (ImageHelpers._focus_crop_hex) so the bench crops byte-identically to the live v6 matcher —
    single source (focus_detector.detect_focus, top box, ring inset)."""
    return H._focus_crop_hex(img_bgr)


def same_screen(pred, exp):
    """Parent and child are the SAME screen: the parent's default state shows its first child focused
    (apps root ≡ apps_netflix, replay ≡ replay_discover), and localize 'provides the children' there.
    True if equal, or one label is the other + '_<child>' (a `_`-boundary prefix). Siblings are NOT
    equal (apps_netflix ≠ apps_disney). A `<state>` display is handled separately by the caller."""
    if not pred or not exp:
        return False
    return pred == exp or pred.startswith(exp + "_") or exp.startswith(pred + "_")


def resolve_top(H, result, img_bgr):
    """Mirror navigation_executor.localize()'s cascade: the matcher's top candidate, else the
    capture-side special-state classifier (black / no-signal) — the layer the raw matcher skips.
    Returns (display, is_state). is_state=True means the frame was correctly named a special state
    (a correct localize outcome even though the matcher abstained)."""
    if result.get("candidates"):
        return result["candidates"][0]["label"], False
    state = H.classify_special_state(img_bgr)
    return (f"<{state}>", True) if state else ("(none)", False)


def inject_node_crops(H, cf, nodes):
    """Populate fp['crop'] on each node from its STORED screenshot (cached download). In-memory
    only — audit-only, nothing written back. Returns the count that got a crop."""
    n = 0
    for x in nodes:
        lp = stored_image(cf, x.get("screenshot"))
        img = cv2.imread(lp) if lp else None
        ch = focus_crop_hex(H, img)
        if ch:
            x["fingerprint"]["crop"] = ch
            n += 1
    return n
