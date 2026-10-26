# BUG-0184 — Verification timeouts meant seconds for web and video checks but milliseconds for every other type

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0184                                                     |
| Reported  | 2026-09-28                                                   |
| Status    | Fixed (pending deploy; migration applied to node1 + QualiAI) |
| Severity  | Medium — wrong waits and misleading labels, no data loss      |
| Area      | backend_host / frontend / db / verification                  |
| Fixed in  | build 90145 |
| Commit    | `a757ca11b`                                                  |

---

## Symptom

Found while making the image-comparison video (TASK-28 video 6). An image check saved with
`timeout: 5`, meant as 5 seconds, ran as a 5 ms single-shot check, and the comparison report said
so ("Timeout: 5ms"). The node editor labels every verification row "Timeout (ms)", yet the web
check next to it stored `15`, which really was 15 seconds.

## Root cause

`params.timeout` of a verification had no single unit:

- image, text, adb, appium: milliseconds, divided by 1000 at the params boundary
  (`backend_host/src/controllers/verification/image.py`, `text.py`, `adb.py`, `appium.py`)
- web (Playwright) and video: seconds, read raw
  (`backend_host/src/controllers/web/playwright_verifications.py`,
  `video_verification_helpers.py`), and the shared executor special-cased video as seconds
- the editor (`VerificationControls.tsx`) says "Timeout (ms)" for all of them, and several param
  descriptions said "(seconds)" even for types that read ms

So a value typed in the editor meant 1000x different things depending on the check type.

## Fix

Every verification `timeout` is milliseconds, for every type, and shown as ms everywhere:
web and video controllers convert ms at the params boundary like the others, the executor's
seconds special case is gone, descriptions, MCP examples and seeds say ms, and reports print
"Timeout: 5000 ms". Stored data is converted by
`setup/db/migrations/20260928d_verification_timeout_web_video_to_ms.sql`, which multiplies
numeric web/video timeouts by 1000 in node verifications, edge action sets (KPI references),
variant overrides and test case graphs. It is guarded (`public.data_migrations`) so a second run
is skipped, and skips tables a database does not have.

Image/text timeouts that are suspiciously small (< 100, probably typed as seconds) are not
converted; the query to find them is at the bottom of the migration file.

## Verification

- `tsc --noEmit` clean, touched Python compiles, backend_host tests pass (5 failures also fail on
  unmodified `main`).
- Migration applied 2026-09-28: node1 lab DB (nodes=8, testcases=8) and QualiAI (nodes=24; no
  `userinterface_variants` table there, skipped). A re-run on node1 reported "already applied".
  After: web 10/15/20/65 s read 10000/15000/20000/65000, video 60/75 s read 60000/75000.
- Until the code is deployed, hosts read the migrated web values as seconds, capped at 60 s: a
  failing web check waits 60 s instead of its own timeout. Deploy the code on node1 and QualiAI.
