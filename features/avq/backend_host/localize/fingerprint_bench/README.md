# Fingerprint-localize benchmark harness

Reusable head-to-head benchmark for the screen-fingerprint matcher, so a new matcher version (v6, …)
can be scored against v4/v5 **on the same screenshots** without re-deriving anything.

## Matcher under test
`backend_host/src/controllers/verification/image_helpers.py` (`ImageHelpers`):
- **v4** `match_fingerprint(gray, focus, node_fps)` — single full-frame dHash + focus.
- **v5** `match_fingerprint_v5(gray, regions, focus, node_fps)` — multi-region dHash (best stable region)
  + the NAV/focus path.
- inputs: `regions = _region_dhashes(gray)`, `focus = _focus_signature(img_bgr)`; helpers `_region_dists`,
  `_dhash_hamming`. Floor = `FP_SELF_DRIFT_FLOOR` (14).
- node fingerprints live in the DB: `navigation_nodes.data.fingerprint = {dhash, regions, focus}`.

## The three benchmarks
| Script | What it measures | What it CAN'T |
|---|---|---|
| `bench_self_match.py <ui>` | each node vs its OWN stored screenshot — collisions, v4-vs-v5 ranking | **zero drift** — cannot show v5 is better |
| `bench_collisions.py <ui>` | different-node pairs within the floor (OLD full-frame vs NEW multi-region) | — |
| `bench_drift.py <ui> <run…>` | **REAL drift** — v4 vs v5 on *different* frames of the same screens | needs local exploration captures |

`bench_drift.py` is the one that actually answers "is v5 better?" — self-match and collisions are
zero-drift and only prove "no regressions / no false positives", not real-world robustness.

## Screenshot sources (this is what was hard to find)
1. **STORED** (the frame each fingerprint was built from): R2 object key `navigation/<ui>/<label>.jpg`.
   Fetched via `get_cloudflare_utils().download_file(key, local)`; cached at `/tmp/vpt_localize_cache/`. Used by
   `bench_self_match` and (as the candidate fingerprints) by all three.
2. **LOCAL DRIFT captures** (different frames = real drift): `features/avq/backend_host/localize/live_runs/<run>/`.
   Each run dir has `state.json` (`nodes`: list/dict, each with `label` + `screenshot` = an **absolute
   local path**) and a `captures/` subdir. The capture for a node is `<run>/captures/<basename(screenshot)>`.
   These live on the **dev machine**, not on the hosts. Best example_tv runs by label-overlap with the
   current node set: `example_tv_autobuild2_clean` (15), `fr_full` (13), `fr_deep2` (12), `fr_deep` (9),
   `fr_hybrid` (8).

## How to run
The scripts resolve the repo root from their own location (override with `VPT_ROOT`) and load `.env`.
They need the matcher + DB + R2 access, so run them on a host that has all three (`host1`/`host3`):

```bash
# copy the harness onto the host (it imports image_helpers + shared libs from the repo root):
rsync -az features/avq/backend_host/localize/fingerprint_bench/ host1:/opt/virtualpytest/features/avq/backend_host/localize/fingerprint_bench/

# self-match + collisions (use the host's DB + R2):
ssh host1 'cd /opt/virtualpytest && sudo -u vpt_user venv/bin/python features/avq/backend_host/localize/fingerprint_bench/bench_self_match.py example_tv'
ssh host1 'cd /opt/virtualpytest && sudo -u vpt_user venv/bin/python features/avq/backend_host/localize/fingerprint_bench/bench_collisions.py example_tv'

# drift — rsync the local capture runs to the host first, then point the script at them:
rsync -az features/avq/backend_host/localize/live_runs/fr_full features/avq/backend_host/localize/live_runs/fr_deep2 \
          features/avq/backend_host/localize/live_runs/example_tv_autobuild2_clean host1:/tmp/bench_runs/
ssh host1 'cd /opt/virtualpytest && sudo -u vpt_user venv/bin/python features/avq/backend_host/localize/fingerprint_bench/bench_drift.py \
             example_tv /tmp/bench_runs/fr_full /tmp/bench_runs/fr_deep2 /tmp/bench_runs/example_tv_autobuild2_clean'
```
Each script prints a markdown table to stdout. Redirect to capture for the doc.

## v6 (implemented) — v5 + focused-element crop tie-break
v6 keeps v5's region/nav identity and adds ONE signal: on same-chrome screens where v5 ties (the app
grid — every tile shares chrome, so regions can't tell `apps_joyn` from `apps_hbomax`), the FOCUSED
TILE's logo decides. Among v5's candidates, v6 re-ranks by the focused-crop dHash distance (region
distance breaks crop ties). With no crop / <2 candidates it is byte-for-byte v5 — so it never regresses.

- **Matcher:** `match_fingerprint_v6(self, live_gray, live_regions, live_focus, live_crop, node_fps)` in
  `image_helpers.py`. Note the extra `live_crop` arg vs v5: the focus detector needs the BGR image
  (colour), which the matcher doesn't get, so the CALLER computes the crop dHash and passes it in.
- **Crops are AUDIT-ONLY** (per the v6 decision): not stored in the DB. `_bench_common.inject_node_crops()`
  computes each node's crop from its STORED screenshot and injects it into `fp['crop']` in memory;
  `_bench_common.focus_crop_hex()` computes the live frame's crop. Both use
  `scripts/no_reference_focus_detector.detect_focus` (top box → crop → `_dhash_hex`).
- **All three benches already emit v6**: `bench_self_match` / `bench_drift` add a `v6 → top` column +
  count; `bench_collisions` adds `NEW v6` (a pair collides only if neither regions NOR the crop separate
  it, `max(region_sep, crop_dist) < T`).

Run all three (drift is the headline — v6 is "better" only if it beats v5 there) and append the tables to
`docs/agent/FINGERPRINT_V5.md`. Known residual: the detector can grab logo art that mimics the focus ring
(DAZN's red-bordered tile), mis-cropping a few tiles — harden `no_reference_focus_detector` (grid/position
prior, prefer a thin uniform ring over a saturated fill) to close those.
