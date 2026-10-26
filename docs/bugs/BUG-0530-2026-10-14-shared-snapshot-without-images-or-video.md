# BUG-0530 — Shared snapshot shows no screenshots and no video

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0530                                                     |
| Reported  | 2026-10-14                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend / report sharing                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

A shared report link (`/server/share/<key>/`, game_clashofclans_llm on vpt-pi1) opens with every
screenshot, the mosaic, the timeline and the video missing ("not included in the snapshot").

## Root cause

`report_snapshot_builder._head_total` HEADs every referenced object back to back. The storage
proxy answered a burst of those HEADs with `403 Forbidden` (the server log shows 14 in a row at
build time; the same HEADs succeed minutes later), and any failed HEAD was treated as "object
gone". All 17 assets were neutralised, the snapshot was stored with 0 assets (manifest
`missing_sources` = all 17) and reported as a success.

## Fix

`shared/src/lib/utils/report_snapshot_builder.py`: a failed HEAD is retried (4 attempts, growing
pause) before the key counts as missing, and a build where **every** referenced asset is missing
now fails with `storage_error` instead of publishing an empty snapshot.

Also: the report's Timeline link targets `timeline.html`, an HTML page a snapshot never copies, so it read "not included". `rewrite_report_html` now points that link at the sibling `timeline.jpg`.

## Verification

Existing snapshot/share tests pass. The broken link must be re-created (old snapshots are frozen).
