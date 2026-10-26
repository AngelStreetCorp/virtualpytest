# BUG-0545 — Localize recapture saved the wrong screen on nodes without verifications

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                  |
|-----------|--------------------------------------------------------|
| ID        | BUG-0545                                               |
| Reported  | 2026-10-15                                             |
| Status    | Fixed and deployed; the damage restored the same hour  |
| Severity  | Major (117 node screenshots / fingerprints overwritten in five lab trees) |
| Area      | scripts/localize (recapture.py, bench.py harvest-nodes) |
| Fixed in  | — (internal)                                           |
| Commit    | 46844d014                                              |

---

## Symptom

After `scripts/localize/recapture.py` ran on the five STALE trees (stb3_live, stb3_sim, stb3_depth3,
stb_tv_autobuild, stb_tv_autobuild_copy) on vpt-pi1 stb3, the next benchmark answered `signal` on node
rows. The saved screenshots were app splash screens (Netflix, Disney+, Prime Video), store pages, and
the TV guide for every stb3 `home_*` node.

## Cause

The tool saved a node's screenshot whenever `navigate_to_node` reported success. A goto to a node
**without verifications always succeeds**, wherever the box ends up: stb_tv_autobuild has no
verification on any node, and most stb3 `home_*` nodes have none. The trees are also older than the
box's UI (German → English, apps re-ordered), so their edges now land elsewhere.

## Fix

- `recapture.py` skips a node without verifications (listed as `no_verification`) and asks Localize
  before saving: a `signal` frame (black / no signal) is never saved.
- `bench.py harvest-nodes` skips unverified nodes the same way.

## Restore

Fingerprints: the pre-recapture ones (backed up by `refingerprint.py` an hour earlier) put back.
Screenshots: stb3 originals cut out of the MinIO `xl.meta` inline data in the 2026-10-11 backup of the
storage VM and uploaded back; stb_tv_autobuild rows pointed back at their untouched
files in the tree's original storage folder. Every restored picture's dHash equals the row's fingerprint.
Details: [TASK-110 §7](../tasks/TASK-110-localize-accuracy.md).
