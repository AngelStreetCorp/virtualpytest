#!/usr/bin/env python3
"""Collision benchmark — DIFFERENT-node fingerprint pairs within the self-drift floor.

A different node within FP_SELF_DRIFT_FLOOR (14) bits is a false-positive risk (a wrong node as close
as a node's own drift). Compares OLD (full-frame dHash) vs NEW (multi-region): a NEW collision is a pair
confusable in EVERY region (no region separates them), so multi-region can only REMOVE collisions, never
add them. Uses the STORED fingerprint regions (exactly what the matcher compares), de-duped by node_id.

  python3 bench_collisions.py example_tv      # or example_tv_autobuild
"""
import itertools
import sys

import _bench_common as B

REGIONS = ['full', 'top', 'center', 'left', 'bottom']


def main():
    uiname = sys.argv[1] if len(sys.argv) > 1 else "example_tv"
    H, _sb, cf, nodes = B.load_nodes(uiname)
    ncrop = B.inject_node_crops(H, cf, nodes)            # v6: focused-crop dHash per node (audit-only)
    T = B.FLOOR
    ham = H._dhash_hamming
    items = [{"label": x["label"], "nid": x["node_id"], "dhash": x["fingerprint"]["dhash"],
              "regions": x["fingerprint"].get("regions") or {"full": x["fingerprint"]["dhash"]},
              "crop": x["fingerprint"].get("crop")}
             for x in nodes]
    pairs = [(i, j) for i, j in itertools.combinations(range(len(items)), 2)
             if items[i]["nid"] != items[j]["nid"]]

    print(f"### Collisions — {uiname} ({len(items)} nodes · {len(pairs)} different-node pairs · floor T={T} bits)\n")
    print("Per-region collisions (different-node pairs within T — lower = more discriminative):\n")
    print("| Region | colliding pairs |")
    print("|---|--:|")
    for r in REGIONS:
        c = sum(1 for i, j in pairs
                if r in items[i]["regions"] and r in items[j]["regions"]
                and ham(items[i]["regions"][r], items[j]["regions"][r]) < T)
        print(f"| {r} | {c} |")

    old, new, v6 = [], [], []
    for i, j in pairs:
        a, b = items[i], items[j]
        if ham(a["dhash"], b["dhash"]) < T:
            old.append((a["label"], b["label"], ham(a["dhash"], b["dhash"])))
        common = [r for r in REGIONS if r in a["regions"] and r in b["regions"]]
        if common:
            sep = max(ham(a["regions"][r], b["regions"][r]) for r in common)  # best separating region
            if sep < T:
                new.append((a["label"], b["label"], sep))
                # v6: a pair still collides only if the focused CROP can't separate it either.
                # max-fusion: sep6 = max(region_sep, crop_dist). No crop on either side -> crop
                # can't help -> falls back to region sep (so v6 >= v5 separation, never worse).
                sep6 = max(sep, ham(a["crop"], b["crop"])) if (a["crop"] and b["crop"]) else sep
                if sep6 < T:
                    v6.append((a["label"], b["label"], sep6))

    print(f"\n**OLD (full-frame dHash) colliding pairs: {len(old)} · "
          f"NEW v5 (multi-region, confusable in EVERY region): {len(new)} · "
          f"NEW v6 (+ focused crop, {ncrop} nodes crop-able): {len(v6)}**\n")
    if v6:
        print("Residual v6 collisions (indistinguishable in all regions AND the focused crop):\n")
        print("| sep | node A | node B |")
        print("|--:|---|---|")
        for a, b, s in sorted(v6, key=lambda x: x[2])[:30]:
            print(f"| {s} | `{a}` | `{b}` |")
    v6keys = {(x[0], x[1]) for x in v6}
    crop_fixed = [(a, b) for a, b, _ in new if (a, b) not in v6keys]
    fixed = [(a, b) for a, b, _ in old if (a, b) not in {(x[0], x[1]) for x in new}]
    print(f"\nOLD false-positives that multi-region (v5) now SEPARATES: {len(fixed)}")
    print(f"v5 residual collisions that the focused crop (v6) ADDITIONALLY separates: {len(crop_fixed)}")


if __name__ == "__main__":
    main()
