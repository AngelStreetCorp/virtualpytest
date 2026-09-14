# BUG-0048 — Re-running a virtual script tries a non-existent disk file

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0048                                                     |
| Reported  | 2026-09-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend                                                     |
| Fixed in  | —                                                            |
| Commit    | `3cb7388ad`                                                          |

---

## Symptom

Clicking the **rerun** (↻) icon on a completed *virtual script* run in the
**Last Executions** list fails: the host reports the script cannot be found. A disk
script re-runs fine; only virtual scripts break.

## Root cause

Virtual scripts execute by `virtual_script_id` (the host materializes the DB source
to a temp file) — `script_name` alone is just the report label and has no matching
file on disk. The rerun path threw the id away:

- `RerunPayload` (`type: 'script'`) in `frontend/src/types/pages/RunTests_Types.ts`
  carried only `scriptName / hostName / deviceId / parameters` — no `virtualScriptId`.
- The launch-time capture in `executeScriptOnDevices` (`RunTests.tsx`) built that
  payload without the id, and `handleRerun` rebuilt the override without it.
- So on rerun, `virtual_script_id` was `undefined` and the host looked for a disk
  file named after the virtual script (e.g. `goto.py`), which does not exist.

## Fix

Thread `virtual_script_id` through the whole rerun chain (`frontend/`):

- `RunTests_Types.ts` — add optional `virtualScriptId` to the `RerunPayload` script
  variant.
- `RunTests.tsx` — capture `exec.virtualScriptId` into the launch-time
  `rerunPayload`; add `virtualScriptId` to the `executeScriptOnDevices` override type
  and consume it (drop the old `as any`); pass `payload.virtualScriptId` from
  `handleRerun` into the override.

Because the id pins the exact `dev`/`test`/`prod` row that ran, a rerun replays the
same version. (Queued-deployment execution of virtual scripts remains a separate
follow-up — the scheduler doesn't persist/forward `virtual_script_id` yet.)

## Verification

1. Run a virtual script from Run Tests; wait for it to complete.
2. Click the rerun (↻) icon on that row → it runs again and produces a report
   (previously: "script not found").
3. Confirm the rerun's report identifies the same script/version as the original.
