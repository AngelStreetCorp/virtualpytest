# BUG-0224 — Test Prompt: the step overlay never showed when the browser's clock was ahead

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0224                                                     |
| Reported  | 2026-10-01                                                   |
| Status    | Fixed — deployed and verified 2026-10-01                     |
| Severity  | Medium — a viewer whose clock is more than 5 s ahead of the host never sees live steps on the stream |
| Area      | `features/ai-test/frontend/hooks/useTestPromptPage.ts` |
| Fixed in  | Unreleased                                                   |
| Commit    | this commit                                                  |

---

## Symptom

In the TASK-36 browser check on host-clone-1, Run graph passed, but the stream preview never
grew and `ScriptRunningOverlay` never appeared. During the run the page fetched the host's
`running.log` and got this run's log (`start_time` 13:12:08 by the host's clock), but
discarded it.

## Root cause

The page kept a `running.log` only if its `start_time`, written by the host, was no more than
5 s before the moment Run was clicked by the browser's clock. The two clocks are different
machines. Measured against an outside reference, the browser machine (codebox) was 23 s
fast and host-clone-1 8 s fast, so every new log looked 15 s too old. Any viewer whose clock
is ahead of the host by more than 5 s hits this.

A second cause showed up after that fix was deployed. `useRunningLog` stopped polling after
three failed fetches, and a 404 counted as a failure. A run writes `running.log` only once its
first block starts, so a run that began with no log on disk got three 404s (6 s) and was never
polled again. Earlier runs had hidden this, because a previous graph run's log was still on
disk.

## Fix

The check uses only host-written times. When Run is clicked, the page reads the device's
`running.log` once, before starting the run, and keeps its `start_time` (none on a 404).
During the run, a log with any other `start_time` is this run's. `useRunningLog`'s own
12-hour stale-log filter is unchanged.

`useRunningLog` no longer counts a 404 as a failure. All three callers (Test Prompt, the
stream modal's deployment and AI runs, and the running-script name) poll only while a run is
active, so a 404 means "not written yet". Network errors and other statuses still stop
polling after three.

Separately, the two skewed clocks were fixed. Both machines lacked the Hetzner NTP drop-in
from the 2026-05-19 rollout (generic NTP is blocked upstream). `vpt-hetzner.conf` was applied on
codebox and host-clone-1; both now sync from `ntp1.hetzner.de`, after corrections of −22.6 s and
−8.3 s.

## Verification

- `tsc --noEmit` passes.
- After the frontend deploy: Run graph from the page on host-clone-1 shows the overlay
  (TASK-36 task doc §2.7).
