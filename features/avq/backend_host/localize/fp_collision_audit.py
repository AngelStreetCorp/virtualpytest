#!/usr/bin/env python3
"""False-positive audit for the multi-region fingerprint idea, over every node of a UI.

For each node: download its stored screenshot, compute the OLD signature (full-frame dHash, as stored)
and the NEW signature (region dHashes: full/top/center/left/bottom). Then 1-vs-N:
  - per region, count pairs of DIFFERENT nodes within the self-drift floor (a wrong node as close as a
    node's own EN/GE/build drift = a false positive),
  - OLD collisions  = pairs whose full-frame dHash is within the floor,
  - NEW collisions  = pairs confusable in EVERY region (max-region separation < floor) — i.e. no region
    can tell them apart. NEW >= OLD separation always (full is one of the regions), so NEW can only
    REMOVE collisions, never add them; the question is how many it removes and which region does it.

  python3 fp_collision_audit.py example_tv
"""
import sys, tempfile, cv2, itertools
sys.path.insert(0, "/opt/virtualpytest")
import os
os.chdir("/opt/virtualpytest")
from dotenv import load_dotenv
load_dotenv("/opt/virtualpytest/.env")
from shared.src.lib.utils.supabase_utils import get_supabase_client
from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils
from backend_host.src.controllers.verification.image_helpers import ImageHelpers

T = 14                                  # FP_SELF_DRIFT_FLOOR — a different node within this = false positive
H = ImageHelpers(None, None)
REGIONS = ['full', 'top', 'center', 'left', 'bottom']


def region_crops(gray):
    h, w = gray.shape
    return {
        'full': gray,
        'top': gray[0:int(0.20 * h), :],
        'center': gray[int(0.22 * h):int(0.78 * h), int(0.20 * w):int(0.80 * w)],
        'left': gray[:, 0:int(0.20 * w)],
        'bottom': gray[int(0.80 * h):, :],
    }


def main():
    uiname = sys.argv[1] if len(sys.argv) > 1 else "example_tv"
    sb = get_supabase_client()
    cf = get_cloudflare_utils()
    ui = sb.table("userinterfaces").select("id").eq("name", uiname).execute().data[0]["id"]
    trees = sb.table("navigation_trees").select("id,name").eq("userinterface_id", ui).execute().data
    tmp = tempfile.mkdtemp(prefix="fpaudit_")
    nodes = []                          # {label, old_dhash, regions:{r:hex}}
    n_dl = n_fail = 0
    for t in trees:
        for n in sb.table("navigation_nodes").select("node_id,label,data").eq("tree_id", t["id"]).execute().data:
            d = n.get("data") or {}
            key = d.get("screenshot")
            old = (d.get("fingerprint") or {}).get("dhash")
            if not key:
                continue
            lp = os.path.join(tmp, key.replace("/", "_").replace(":", "_"))
            try:
                if key.startswith("http"):          # stored as a full (now-401) public URL — the OBJECT
                    from urllib.parse import urlparse   # is in R2; use its path as the signed key
                    key = urlparse(key).path.lstrip("/")
                got = cf.download_file(key, lp).get("success") and os.path.exists(lp)
                if not got:
                    n_fail += 1; continue
                img = cv2.imread(lp)
                if img is None:
                    n_fail += 1; continue
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                regs = {r: H._dhash_hex(c) for r, c in region_crops(gray).items()}
                nodes.append({'label': n['label'], 'nid': n['node_id'], 'old': old, 'regions': regs})
                n_dl += 1
            except Exception as e:
                n_fail += 1
    print(f"=== {uiname}: {n_dl} nodes audited ({n_fail} download/decode fails) | floor T={T} bits ===\n")

    # dedupe: same node_id (a menu node + its subtree-head copy share one screenshot — NOT a collision)
    pairs = [(i, j) for i, j in itertools.combinations(range(len(nodes)), 2)
             if nodes[i]['nid'] != nodes[j]['nid']]
    # per-region collision counts
    print("Per-region collisions (DIFFERENT-node pairs within T) — lower = more discriminative:")
    for r in REGIONS:
        c = sum(1 for i, j in pairs if H._dhash_hamming(nodes[i]['regions'][r], nodes[j]['regions'][r]) < T)
        print(f"  {r:7}: {c:4d} colliding pairs")
    # OLD (full-frame stored dhash) vs NEW (confusable in EVERY region)
    old_coll, new_coll = [], []
    for i, j in pairs:
        a, b = nodes[i], nodes[j]
        if a['old'] and b['old'] and H._dhash_hamming(a['old'], b['old']) < T:
            old_coll.append((a['label'], b['label'], H._dhash_hamming(a['old'], b['old'])))
        sep = max(H._dhash_hamming(a['regions'][r], b['regions'][r]) for r in REGIONS)   # best separator
        if sep < T:
            new_coll.append((a['label'], b['label'], sep))
    print(f"\nOLD (full-frame dHash) colliding pairs: {len(old_coll)}")
    print(f"NEW (multi-region, confusable in EVERY region) colliding pairs: {len(new_coll)}")
    print("\nResidual NEW collisions (genuinely indistinguishable in all 5 regions):")
    for a, b, s in sorted(new_coll, key=lambda x: x[2])[:25]:
        print(f"  [{s:2d}] {a}  <->  {b}")
    # nodes the OLD signature would confuse but NEW separates (the win)
    new_keys = {(x[0], x[1]) for x in new_coll}
    fixed = [(a, b, s) for a, b, s in old_coll if (a, b) not in new_keys]
    print(f"\nOLD false-positives that NEW now separates: {len(fixed)} (sample):")
    for a, b, s in fixed[:12]:
        print(f"  old_dist={s:2d}  {a}  vs  {b}")
    # per-node 1-vs-N: nearest OTHER node under OLD vs NEW (which region saves it)
    print("\nPer-node nearest-OTHER (sample of the tightest 18) — old=full-frame, new=best-region:")
    rows = []
    for i, a in enumerate(nodes):
        others = [j for j in range(len(nodes)) if nodes[j]['nid'] != a['nid']]
        if not others or not a['old']:
            continue
        oj = min(others, key=lambda j: H._dhash_hamming(a['old'], nodes[j]['old']) if nodes[j]['old'] else 999)
        od = H._dhash_hamming(a['old'], nodes[oj]['old']) if nodes[oj]['old'] else 999
        nj = min(others, key=lambda j: max(H._dhash_hamming(a['regions'][r], nodes[j]['regions'][r]) for r in REGIONS))
        nd = max(H._dhash_hamming(a['regions'][r], nodes[nj]['regions'][r]) for r in REGIONS)
        bestr = min(REGIONS, key=lambda r: H._dhash_hamming(a['regions'][r], nodes[nj]['regions'][r]))
        rows.append((od, a['label'], nodes[oj]['label'], nd, nodes[nj]['label'], bestr))
    for od, al, ol, nd, nl, br in sorted(rows)[:18]:
        flag = "FP!" if od < T else "   "
        print(f"  {flag} {al:22} old:{ol[:20]:20}({od:2d})  new:{nl[:20]:20}(sep {nd:2d}, via {br})")


if __name__ == "__main__":
    main()
