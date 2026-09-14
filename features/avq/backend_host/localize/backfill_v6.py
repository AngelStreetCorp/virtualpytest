#!/usr/bin/env python3
"""Backfill the v6 fingerprint for every node of the example_tv UIs.

v6 = v5 regions + the focused-tile CROP (app-grid sibling) + v4 dhash/focus/title. For each node with a
stored screenshot this (re)computes regions + crop from that screenshot and sets v=6, additively
(dhash/focus/title kept). Mirror of backfill_regions.py. Runs offline on a host with DB + R2.

  python3 features/avq/backend_host/localize/backfill_v6.py            # dry-run (no writes)
  python3 features/avq/backend_host/localize/backfill_v6.py --apply    # write fp back to navigation_nodes.data
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
CACHE = "/tmp/vpt_localize_cache"; os.makedirs(CACHE, exist_ok=True)

for uiname in ["example_tv", "example_tv_autobuild"]:
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
