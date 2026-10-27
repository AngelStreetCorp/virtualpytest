#!/usr/bin/env python3
"""Backfill the v6 fingerprint for every node of the example_tv UIs.

v6 = v5 regions + the focused-tile CROP (app-grid sibling) + v4 dhash/focus/title. For each node with a
stored screenshot this (re)computes regions + crop from that screenshot and sets v=6, additively
(dhash/focus/title kept). Mirror of backfill_regions.py. Runs offline on a host with DB + R2.

  python3 features/avq/backend_host/localize/backfill_v6.py                       # dry-run, default UIs (no writes)
  python3 features/avq/backend_host/localize/backfill_v6.py --apply                # write fp back to navigation_nodes.data
  python3 features/avq/backend_host/localize/backfill_v6.py stb-<operator> stb_tv_settings [--apply]   # chosen UIs
  ... --full    recompute the WHOLE fingerprint (dhash, focus, title, regions, crop) with compute_fingerprint,
                for UIs whose stored fp is v1-v4: their old dhash/focus/title no longer agree with what v6 computes
                live, so the additive default leaves them half-stale (measured TASK-47 G13: 59 right / 10 wrong
                additive vs 136 / 8 full). Back the old fp up first.
"""
import os, sys, io, contextlib
os.chdir("/opt/virtualpytest"); from dotenv import load_dotenv; load_dotenv(".env"); sys.path.insert(0, ".")
sys.path.insert(0, "/opt/virtualpytest/backend_host/src")
import cv2
from urllib.parse import urlparse
from shared.src.lib.utils.supabase_utils import get_supabase_client
from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils
from backend_host.src.controllers.verification.image_helpers import ImageHelpers

H = ImageHelpers(None, None); sb = get_supabase_client(); cf = get_cloudflare_utils()
APPLY = "--apply" in sys.argv
FULL = "--full" in sys.argv
if FULL:
    import shutil
    if not shutil.which("tesseract"):   # the title layer is OCR; without it every title would be stored empty
        sys.exit("BF: --full needs tesseract on PATH (the title layer is OCR); not installed here")
UIS = [a for a in sys.argv[1:] if not a.startswith("--")] or ["example_tv", "example_tv_autobuild"]
CACHE = "/tmp/vpt_localize_cache"; os.makedirs(CACHE, exist_ok=True)

for uiname in UIS:
    ui = sb.table("userinterfaces").select("id").eq("name", uiname).execute().data
    if not ui:
        print(f"BF: {uiname}: no such UI, skipped"); continue
    trees = sb.table("navigation_trees").select("id").eq("userinterface_id", ui[0]["id"]).execute().data
    done = skip = crop = 0
    for t in trees:
        for n in sb.table("navigation_nodes").select("node_id,label,data").eq("tree_id", t["id"]).execute().data:
            d = n.get("data") or {}; fp = d.get("fingerprint") or {}; k = d.get("screenshot")
            if not k or not fp.get("dhash"):
                skip += 1; continue
            kk = urlparse(k).path.lstrip("/") if k.startswith("http") else k
            lp = os.path.join(CACHE, kk.replace("/", "_"))
            if not os.path.exists(lp):
                with contextlib.redirect_stdout(io.StringIO()):
                    if not cf.download_file(kk, lp).get("success"):
                        skip += 1; continue
            img = cv2.imread(lp)
            if img is None:
                skip += 1; continue
            if FULL:
                with contextlib.redirect_stdout(io.StringIO()):
                    fp = H.compute_fingerprint(img)
                if not fp:
                    skip += 1; continue
                crop += 1 if fp.get("crop") else 0
                if APPLY:
                    d["fingerprint"] = fp
                    sb.table("navigation_nodes").update({"data": d}).eq("tree_id", t["id"]).eq("node_id", n["node_id"]).execute()
                done += 1
                continue
            with contextlib.redirect_stdout(io.StringIO()):
                fp["regions"] = H._region_dhashes(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
                ch = H._focus_crop_hex(img)
            if ch:
                fp["crop"] = ch; crop += 1
            else:
                fp.pop("crop", None)
            fp["v"] = ImageHelpers.FINGERPRINT_VERSION   # 6
            if APPLY:
                d["fingerprint"] = fp
                sb.table("navigation_nodes").update({"data": d}).eq("tree_id", t["id"]).eq("node_id", n["node_id"]).execute()
            done += 1
    print(f"BF: {uiname}: {done} nodes {'WROTE v6' if APPLY else '(dry-run)'} "
          f"({crop} with crop), {skip} skipped")
