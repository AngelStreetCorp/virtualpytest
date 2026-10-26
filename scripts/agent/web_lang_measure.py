#!/usr/bin/env python3
"""Per-node language-independence measurement for a web userinterface (BUG-0706).

For every node: go there (navigate_to_node), then read the three signals a web screen offers
and compare them with what the tree stored when it was built (maybe in another UI language):

  url    live path, language segment ignored, matches the stored identity URL / the node's
         waitForUrlToMatch pattern
  dhash  Hamming distance (of 256) of the live frame's full-frame dHash to the stored one, and the
         mean over the five region dHashes; "rank" = position of the node's own stored fingerprint
         among all nodes' fingerprints, by that distance (1 = nearest)
  verify the node's own verifications, run by verify_node (pass/fail)

Usage: web_lang_measure.py <userinterface> [--host host-clone-2] [--device host] [--out file.json]
       web_lang_measure.py <userinterface> --separation     (no browser: how far apart the STORED fingerprints are)

--separation prints, per node, the distance to its nearest other node (full dHash and mean of the region dHashes) and how
many nodes have a twin within 10 bits: the number to compare before and after web fingerprints moved from the whole
desktop to the page area (FINGERPRINT.md "Web fingerprints"). Live runs crop the frame to the page area like the host does.
Needs: the lease on the host, the browser logged in. Nothing app-specific is in this file.
"""
import argparse
import base64
import json
import os
import sys

import cv2
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

os.environ.setdefault("UC04_HOST", "host-clone-2")
import bench_tree_build as B  # noqa: E402  (mcp(), sql(): the harness's own helpers)
from backend_host.src.controllers.verification.image_helpers import ImageHelpers  # noqa: E402
from shared.src.lib.utils.image_hash import dhash_hamming  # noqa: E402
from shared.src.lib.utils.localize_identity import url_path  # noqa: E402
from shared.src.lib.utils.web_viewport import crop_to_box, viewport_box  # noqa: E402


def stored_nodes(ui):
    rows = B.sql(
        "select n.node_id, n.data->'fingerprint' as fp from navigation_nodes n join navigation_trees t on t.id=n.tree_id "
        f"join userinterfaces u on u.id=t.userinterface_id where u.name={B.q(ui)} and n.node_id<>'entry-node' order by n.node_id",
        as_json=True)
    return [r for r in rows if r.get("fp")]


def mean_region(a, b):
    ra, rb = a.get("regions") or {}, b.get("regions") or {}
    ds = [dhash_hamming(ra[k], rb[k]) for k in ra if k in rb]
    return round(sum(ds) / len(ds), 1) if ds else None


TWIN_BITS = 10


def separation(ui):
    nodes = stored_nodes(ui)
    fps = {n["node_id"]: n["fp"] for n in nodes}
    rows = []
    for nid, fp in sorted(fps.items()):
        others = {k: v for k, v in fps.items() if k != nid and v.get("dhash")}
        d = {k: dhash_hamming(fp["dhash"], v["dhash"]) for k, v in others.items()}
        r = {k: mean_region(fp, v) for k, v in others.items()}
        near = min(d, key=d.get)
        rows.append((nid, d[near], near, min(x for x in r.values() if x is not None), "viewport" in fp))
        print(f"{nid:26s} nearest {near:24s} dhash {d[near]:3d}  regions {rows[-1][3]:5.1f}  page-area {rows[-1][4]}")
    twins = sum(1 for r in rows if r[1] <= TWIN_BITS)
    print(f"\n{len(rows)} nodes: with a twin within {TWIN_BITS} bits {twins}; mean nearest dhash "
          f"{sum(r[1] for r in rows) / len(rows):.1f}; mean nearest regions {sum(r[3] for r in rows) / len(rows):.1f}; "
          f"stored on the page area {sum(1 for r in rows if r[4])}/{len(rows)}")


def page_area(a_host, a_device):
    """Box of the browser page inside the captured frame, read from the live browser (None: whole frame)."""
    from shared.src.lib.utils.web_viewport import VIEWPORT_JS, viewport_box
    txt = B.mcp("execute_device_action", host_name=a_host, device_id=a_device,
                actions=[{"command": "execute_javascript", "params": {"script": VIEWPORT_JS}}])[0]
    try:
        m = json.loads(txt[txt.index("["):txt.rindex("]") + 1])[0]["result"]
        return m
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ui")
    ap.add_argument("--host", default="host-clone-2")
    ap.add_argument("--device", default="host")
    ap.add_argument("--out")
    ap.add_argument("--separation", action="store_true", help="offline: separation of the stored fingerprints")
    ap.add_argument("--recapture", action="store_true",
                    help="after each node is reached, save its screenshot again: the host stores the fingerprint of the page area")
    a = ap.parse_args()
    if a.separation:
        return separation(a.ui)
    helpers = ImageHelpers(None, None)
    nodes = stored_nodes(a.ui)
    stored = {n["node_id"]: n["fp"] for n in nodes}
    out = []
    for n in nodes:
        nid = n["node_id"]
        txt, _, err = B.mcp("navigate_to_node", host_name=a.host, device_id=a.device, userinterface_name=a.ui,
                            target_node_label=nid, include_screenshot=False)
        nav_ok = not err and "Successfully" in txt
        vtxt, _, verr = B.mcp("verify_node", host_name=a.host, device_id=a.device, userinterface_name=a.ui,
                              node_label=nid, include_screenshot=False)
        if a.recapture and nav_ok:
            tree_id = B.sql("select t.id from navigation_trees t join userinterfaces u on u.id=t.userinterface_id "
                            f"where u.name={B.q(a.ui)} limit 1").strip()
            st, _, serr = B.mcp("save_node_screenshot", tree_id=tree_id, node_id=nid, label=nid, host_name=a.host,
                                device_id=a.device, userinterface_name=a.ui)
            print(f"[recapture] {nid}: {'error ' + st[:120] if serr else 'saved'}", flush=True)
        verify_ok = (not verr) and ("PASS" in vtxt.upper() or "SUCCESS" in vtxt.upper()) and "FAIL" not in vtxt.upper()
        url = B.mcp("execute_device_action", host_name=a.host, device_id=a.device,
                    actions=[{"command": "execute_javascript", "params": {"script": "location.href"}}])[0]
        live_url = ""
        try:
            live_url = json.loads(url[url.index("["):url.rindex("]") + 1])[0]["result"]
        except Exception:
            pass
        _, imgs, _ = B.mcp("capture_screenshot", host_name=a.host, device_id=a.device)
        row = {"node": nid, "navigated": nav_ok, "verify": verify_ok, "live_path": url_path(live_url)}
        sfp = stored[nid]
        ident = (sfp.get("identity") or {}).get("url")
        row["stored_path"] = url_path(ident) if ident else None
        row["url_match"] = bool(ident) and url_path(live_url) == url_path(ident)
        if imgs:
            raw = base64.b64decode(imgs[0])
            img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            m = page_area(a.host, a.device)
            box = viewport_box(m, img.shape[1], img.shape[0]) if m else None
            live = helpers.compute_fingerprint(crop_to_box(img, box))
            if live:
                dists = {k: dhash_hamming(live["dhash"], v["dhash"]) for k, v in stored.items() if v.get("dhash")}
                order = sorted(dists, key=dists.get)
                row.update(dhash=dists.get(nid), regions=mean_region(live, sfp), rank=order.index(nid) + 1 if nid in order else None,
                           nearest=order[0], nearest_dist=dists[order[0]])
        out.append(row)
        print(json.dumps(row), flush=True)
    if a.out:
        json.dump(out, open(a.out, "w"), indent=1)
    n = len(out)
    print(f"\n{n} nodes: url {sum(r['url_match'] for r in out)}/{n}, verify {sum(r['verify'] for r in out)}/{n}, "
          f"dhash rank 1 {sum(1 for r in out if r.get('rank') == 1)}/{n}")


if __name__ == "__main__":
    main()
