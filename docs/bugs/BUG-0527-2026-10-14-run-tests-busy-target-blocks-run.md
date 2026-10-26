# BUG-0527 — Run Tests: a busy target blocks Run instead of queueing

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                  |
|-----------|------------------------|
| ID        | BUG-0527               |
| Reported  | 2026-10-14             |
| Status    | Fixed (pending deploy) |
| Severity  | Medium                 |
| Area      | frontend               |
| Fixed in  | build 90145 |
| Commit    | see git log            |

---

## Symptom

On Run Tests, a device already running a test (yours or someone else's, or a deployment) showed a
lock and could not be used: its checkbox was force-checked and greyed out, **Run** stayed disabled
when only busy devices were picked, and Selected Items said "Select targets first". The operator had
to wait for the device to free up and click Run again.

## Root cause

`RunTests.tsx` removed running and execution-locked targets from `selectedRunnableTargetKeys` (and
from `selectedTargetEntries`), and passed running targets to the target list as disabled +
force-checked. The queue already existed — `splitDevicesByLockState` turns a locked device into a
one-shot deployment that the host deployment scheduler runs when the device frees — but busy
devices were filtered out before it was ever reached, so only Take-Control locks were queued.

## Fix

Busy targets stay selectable and keep their Selected Items row. On Run, `splitDevicesByLockState`
treats any device known to be busy (own running execution, execution lock, running deployment) as
blocked even if `checkLock` fails open, and queues it; free devices start at once. The toast says
how many started and how many were queued. Campaigns have no queue yet (server answers 423), so busy
targets are skipped for a campaign run with a message.
