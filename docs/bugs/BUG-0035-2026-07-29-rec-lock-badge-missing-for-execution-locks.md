# BUG-0035 — Rec lock badge intermittently missing while a script is running

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0035                                                     |
| Reported  | 2026-07-29                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium (users take devices they believe are free)            |
| Area      | frontend rec lock badge / lock_reason contract / lock_changed emit |
| Fixed in  | build 8713                                                   |
| Commit    | `9e406abf3`                                                  |

---

## Symptom

While a script is running on a device, the lock icon is sometimes absent from the
Rec preview card (`RecHostPreview`) and the stream modal (`RecHostStreamModal`).
Not systematic — some runs show it, some don't, some show it late.

## Root cause

The badge required a *parsed script name*, not merely a lock. Three stacked defects
decided whether that name resolved, and each launch path hit a different combination:

1. **`useDeviceScriptLabel` only understood two `lock_reason` prefixes**
   (`script_execute:` and `deployment:`), but the producers emit three shapes:
   ad-hoc scripts send `script_execute:<name>` (parses ✓), the deployment scheduler
   sends `deployment_execute:<uuid>` (✗ — `deployment` prefix requires a colon right
   after), and campaigns send `campaign_execute:<uuid>` (✗). Unparsed reasons fell
   back to the running.log script name.
2. **The running.log fallback only polls for scheduler runs.** `useRunningScriptName`
   gates on `device.has_running_deployment`, which is computed by the deployment
   scheduler and rides the host→server ping cycle. Ad-hoc campaign runs never set it
   (no badge at all, for the whole run); scheduled runs set it only once the next
   ping propagated (badge appears late, or never for short runs).
3. **`/server/script/execute` never emitted `lock_changed` on acquire** — every other
   acquire path (takeControl, takeover, `acquireExecutionLock`, campaign execute)
   does. Ad-hoc script runs therefore only became visible at the frontend's 15s
   fallback poll; a script shorter than the poll interval was never seen as locked.

Net effect per launch path: ad-hoc scripts = badge delayed ≤15s (invisible for short
runs); scheduled deployments = badge tied to ping-cycle lag; ad-hoc campaigns = no
badge ever. "Not systematic" was the three paths interleaving.

Verified against production data (`device_control_sessions` vs `script_results`):
locks are held correctly server-side for the full run — the failure was purely in
whether the frontend showed them. (An apparent lock/run gap on host-clone-1 turned
out to be ~21s clock skew between that host and the server, not a real gap.)

## Fix

- **`useDeviceScriptLabel.ts`** — the badge now shows whenever a
  `script_execution` / `deployment_execution` lock exists. Generic
  `<kind>:<value>` parse; UUID values (campaign/deployment ids) defer to
  running.log, then to a generic kind label (`script` / `deployment`), so the
  label always resolves and can never suppress the icon. Old-format
  `deployment_execute:<uuid>` from not-yet-redeployed hosts renders as
  `deployment` (verified in unit cases).
- **`deployment_scheduler.py`** — lock_reason now carries the human-readable
  deployment name (`deployment:<name>`), the format the hook always documented.
- **`server_script_routes.py` `/script/execute`** — emits `lock_changed`
  (`is_locked: true`) right after acquiring, so viewers update immediately
  instead of at the next 15s poll.

## Verification

- Node unit run of the extracted label logic: 7/7 cases pass (ad-hoc script,
  new + old scheduler reason, campaign with/without running.log, manual lock,
  no lock).
- `py_compile` clean on both python files; `tsc --noEmit` introduces no new
  errors (one pre-existing unrelated error in `VerificationItem.tsx`).
- DB cross-check of lock sessions vs script runs described above.

## Notes / left alone

- **Server restart still wipes in-memory locks** while scripts keep running on
  hosts — those runs show unlocked until they complete, and a plain takeControl
  during that window won't abort them (no lock → no owner_type → no abort
  fan-out). Rebuilding locks from host state on re-registration is a design
  change, left open.
- Testcases still take no device lock (BUG-0006 note stands), so testcase runs
  legitimately show no badge.
