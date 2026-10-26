# BUG-0893 — A deploy left the services that register screens running the code from days earlier, and said nothing

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                             |
|-----------|-------------------------------------------------------------------|
| ID        | BUG-0893                                                          |
| Reported  | 2026-10-24                                                        |
| Status    | Fixed (pending deploy)                                            |
| Severity  | High                                                             |
| Area      | deploy (update_core.sh) / monitoring (screen registry)            |
| Fixed in  | build 90145 |
| Commit    | (the TASK-162 branch)                                             |

---

## Symptom

The screen-label coverage metric went from **5 to 17 overnight**, and every one of the 12 new
unfinished rows was a screen the platform had **just created without a fingerprint**. The fix for
exactly that (BUG-0867, the freeze path must store the fingerprint) had been merged, deployed and
verified — in the files on disk.

The running code was five hours old.

## Root cause

**Screens are registered by a service the deploy does not restart.**

- `vpt-host.service` runs the host application.
- `vpt-monitor-img.service` runs `backend_host/scripts/capture_monitor.py`, which imports
  `MonitorLocalizer` (the Localize monitor) and `IncidentManager` (the freeze path). **Everything
  that creates a screen row lives there.**

`update_core.sh` restarts `vpt-host` and, on request, a list of aux services — but that restart is
**opt-in** (`--restart`; the default run's own comment reads *"deploy everything (no aux restart)"*).
An ordinary deploy therefore pushes the new code to the disk, restarts `vpt-host`, and leaves every
aux service running the code it was started with.

**And nothing could see it.** The deploy's bookkeeping is the code marker
(`~/.vpt_host_code_id`): it records the host code id of the last successful `vpt-host` restart, and
the deploy skips a host whose marker already matches. That marker tracks the **host** service. For
the aux services there was no signal at all — "the files on disk are new" and "the code that runs is
new" were indistinguishable, so a deploy that had changed the code under a running service reported
success and left it running the old code.

Measured on 2026-10-24, from the service start times:

| host | service | running code from |
|---|---|---|
| the Pi site | `vpt-monitor-img` | 5.5 hours earlier (the Localize monitor and the freeze path) |
| the Pi site | `vpt-monitor-subtitle`, `vpt-monitor-audio`, `vpt-archiver`, `vpt-avq`, `vpt-kpi` | **five days** earlier |
| `vpt-mf1` | `vpt-monitor-audio`, `vpt-archiver`, `vpt-avq`, `vpt-kpi` | two days earlier |

The leased-host path has the same shape: the code is synced, the restart is deferred to the
catch-up deploy, and the aux services are not restarted by either.

## Fix

**The deploy now says which services are still on the previous code.** When a deploy changes the
host code, it compares each aux service's start time with the moment it pushed the code, and prints
the ones that started earlier — per host, with the date each started — plus a
`STILL RUNNING THE PREVIOUS CODE` block in the deploy summary. One SSH round trip per host.

It **never restarts anything by itself**. Restarting the capture monitor drops frames for every
device on that host, which is exactly why the aux restart is opt-in; the change makes the manual
step *findable* instead of *remembered*, which is what it was missing.

The deployment rule itself is unchanged and documented
(`docs/agent/infra/DEPLOY.md`): `--restart` restarts the aux services, and the lease is what decides
when that is safe.

## Verification

- `bash -n setup/proxmox/node/update_core.sh` clean.
- **`setup/proxmox/node/test_update_core_stale_code.sh`** (new, 15 checks): the report function is
  cut out of the script and run against a fake ssh output that goes through the **real** `run_ssh`,
  so the banner `run_ssh` prints before the ssh output is part of what the parser has to cope with.
  It asserts that exactly the stale services are named, that a fresh service is not, that the
  banner is never read as a service, that a service which was not asked about is ignored, that a
  line whose second field is not a plain number is dropped, and that the progress event carries the
  phase the parser accepts. Run against the first version of this report it fails with `h1:==>` among
  the stale services — the defect it exists to catch.

  **How a line is accepted.** A line counts only when it *is* what the remote command prints —
  `<service> <epoch>`, the second field all digits — and the service is one of the ones that was
  asked about. The first version skipped one line of the output instead of the two that `run_ssh`
  prints before it, so the banner was read as a service named `==>` with the digit `1` of the host
  name scraped out of it as its epoch; that compares as ancient, so every deploy would have
  reported a phantom service as stale. Scraping digits out of the field was the wrong cure for
  that: the whole line is matched now, so a malformed epoch is dropped rather than turned into a
  wrong number (`17 21 86` would have become the epoch `172186`).
- **`tests/rollout/test_deploy_progress.py`** (new case): the `stale-code` note survives the
  parser, carries no duration and never turns a healthy host card into a failure. Without the
  phase in `PHASES` the event is counted as ignored and dropped, which is the defect this case
  catches.
- Exercised against the live hosts with two reference points (code pushed 1 hour ago, and 1 day ago):
  the services are reported exactly when their start time precedes the push, and a service started
  *after* the reference is not reported. `vpt-mf1`'s capture monitor (restarted by hand earlier that
  morning) is reported against the recent reference and not against the older one — as it should be.

**The note is in the deploy record, not in the deployment view.** `deploy_progress.py` parses the
`stale-code` event, so it is counted and kept; the deployment view keeps its own list of the four
phases of a deploy (`rsync | install | restart | health`) and does not render a fifth column for
this. The human-readable output is the primary channel — the banner line per service and the
`STILL RUNNING THE PREVIOUS CODE` block in the deploy summary.

## The CI gate

**Nothing tested the parse.** The two harnesses that sat next to `update_core.sh` covered the host
selection and the deploy summary — not this report — which is exactly why the banner was read as a
service and shipped. A test that existed only on a branch, or only behind a nightly, would have left
the same hole open.

The three `update_core.sh` harnesses now run in their own workflow,
**`.github/workflows/deploy-harness.yml`**: every push, every pull request, `ubuntu-latest`, about a
second, no host, no credential, no self-hosted runner.

**Not behind the night gate.** Every job in `regression.yml` carries `needs: [night-gate]`, and the
gate defers everything between 07:00 and 24:00 UTC. A change merged in the afternoon would have got a
green run that tested nothing, and this parse would only have surfaced at the 00:07 nightly: the gate
would postpone the hole, not close it. For this repo GitHub Actions is the gate — the integration
lane's own test command is `bash -n .githooks/pre-push && echo merge-gate-noop-ok`.

**And the harness may not skip.** `test_update_core_skip_leased.sh` needs the lease CLI, which lives in
no git repository. Measured in a CI-like environment (`env -i PATH=/usr/bin:/bin HOME=/nonexistent-home`),
it printed `SKIP: no vpt-lease at …` and **exited 0** — a green run that tested nothing, the very thing
the workflow exists to prevent. Two changes close that:

- A **frozen copy of the CLI is in the repository** (`setup/proxmox/node/fixtures/vpt-lease`, a snapshot
  of the operator's own copy with its source digest in the header), so the harness always has an
  oracle. The copy keeps its registry in `VPT_LEASE_DIR`, so the fake leases the harness creates never
  reach the real fleet's registry.
- The harness **fails instead of skipping**: no CLI at all is a `FAIL` when `CI` is set and a loud
  `SKIP` (never a pass) outside CI, and an explicit `$VPT_LEASE_BIN` that is missing or that writes to
  the shared registry is a `FAIL`, never a silent fallback to a different CLI.

The workflow and the fixture are both on `scripts/security/internal-paths.txt`: they are internal CI,
and the public snapshot must not run a harness whose oracle it does not have.

## Prevention

- **A deploy that changes the code under a running service must say so.** "The files on disk are
  new" is not "the code that runs is new", and the difference is invisible to a marker that tracks
  one service.
- **The service that does the work is the service that must be restarted.** The screen registry is
  written by `vpt-monitor-img`, not by `vpt-host` — a gap that only shows up when the thing that
  writes the data is not the thing the deploy restarts.
- **A metric that moves overnight is an alarm, not a log line.** The jump from 5 to 17 was visible
  only in the 07:10 coverage report; nothing told anyone between 11:26 the previous day and 07:10
  the next morning.
