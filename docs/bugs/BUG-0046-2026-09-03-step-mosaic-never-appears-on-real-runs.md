# BUG-0046 — Step mosaic never appears on a real run: screenshots already deleted by the time it's built

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0046                                                     |
| Reported  | 2026-09-03                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low (feature silently no-ops; report otherwise unaffected)   |
| Area      | `shared/src/lib/executors/script_executor.py`, `shared/src/lib/utils/report_generation_utils.py` |
| Fixed in  | build 8713                                                   |
| Commit    | `a4982b67b`                                                   |

---

## Symptom

The step-mosaic feature (a compressed JPEG, one tile per step, shipped the same day as
this bug) never showed up on a real script report. The report generation log always
printed `[@report_mosaic] No local step screenshots, skipping mosaic`, even for a
successful run with real captured screenshots.

## Root cause

Found by running a real `goto.py` navigation against device3 (`stb3`) on host `vpt-pi1`
after deploying the mosaic feature, then reading the generated report:
`https://virtualpytest.angelstreet.io/.../script-reports/stb/goto_.../report.html`.

`script_executor.py::generate_report_for_context` calls
`context.upload_screenshots_to_r2()` — which uploads every step's local capture file to
R2 and then **deletes the local "cold" copy** (`cloudflare_utils.upload_files(...,
auto_delete_cold=True)`, the default) — well before it calls
`generate_and_upload_script_report()`. The mosaic builder ran *inside* that later
function, reading `step_results`' screenshot-path fields — the field values were still
local path *strings*, but the files they pointed to were already gone from disk, so
`build_step_mosaic()` found nothing to tile.

## Fix

Moved the mosaic build to `generate_report_for_context`, immediately **before** the
`upload_screenshots_to_r2()` call, while the local captures still exist. The resulting
local JPEG (+ its tile count) is handed to `generate_and_upload_script_report()` via two
new parameters, `mosaic_local_path` / `mosaic_tile_count`, which now just uploads the
pre-built file — the same pattern already used for `test_video_url`. The old
build-from-`step_results` path is kept as a fallback for any other caller that still has
fresh local screenshots when it calls the function directly.

## Verification

- Reproduced on the real run above (log line confirmed, report had no "Test Mosaic" section).
- Local simulation: built a mosaic from fresh frames, **deleted the source frames**
  (mirroring `auto_delete_cold`), then called `generate_and_upload_script_report` with
  the new `mosaic_local_path` — it uploaded the pre-built file directly, with no
  "No local step screenshots" log line, and cleaned up the temp file afterward.
- Not yet re-verified against a second real device run (pending redeploy of this fix).
