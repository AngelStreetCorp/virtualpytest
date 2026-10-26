# BUG-0758 — The dashboard said "1 in error" on a host with nothing red on the card

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0758                                                     |
| Reported  | 2026-10-21                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

The dashboard header showed a red **"1 in error"** badge for `vpt-pi4`.angelstreet.io.
Opening the host card showed nothing wrong: Server Services online, Core green (Stream,
Host API), Services "2 running · 4 idle" with a **green** LED, the 4 idle rows collapsed
under a grey **Optional (4)** and 4 more under **Not installed (4)**. No red row anywhere,
and the badge could never point at one — the services that tripped it are exactly the ones
the card hides.

## Root cause

Two views of "is this host broken?" that asked different questions.

`hostHasError()` in
[frontend/src/components/dashboard/HostsDevicesView.tsx](../../frontend/src/components/dashboard/HostsDevicesView.tsx)
counted a host in error when `operational_status` was `error`/`degraded`, **or** when any
service had `!optional && status ∈ {stopped, error, stuck}`.

The Services panel asks a different question. `classify()` in
[frontend/src/components/dashboard/hostServices.ts](../../frontend/src/components/dashboard/hostServices.ts)
computes `expected` from the device monitoring profiles (falling back to the backend's
`critical` flag) and only calls a row `down` when it is **expected and not running**. An
unneeded service that is stopped becomes `idle`, which is routed to the muted Optional group
and keeps the accordion LED green.

On a healthy TASK-144 host those two answers diverge. The backend stops what no device
profile asks for and demotes it (`backend_host/src/lib/utils/system_info_utils.py`):

```python
for service in services:
    if service.get('status') != 'stopped':
        continue
    unit = service.get('resolved_name') or service.get('name')
    if unit in not_needed_units:
        service['critical'] = False
        service['not_needed'] = True
```

It flips `critical`, **not** `optional` — `optional` still reads `false`, so the badge's
`!optional` test flagged it. Live payload captured from `vpt-nipogi`:

```
overall_status: online
  vpt-stream          active         critical=True  optional=False
  vpt-host            active         critical=True  optional=False
  vpt-monitor-img     stopped        critical=False optional=False  not_needed=True
  vpt-archiver        stopped        critical=False optional=False  not_needed=True
  vpt-kpi             stopped        critical=False optional=False  not_needed=True
  vpt-monitor-audio   stopped        critical=False optional=False  not_needed=True
```

Four "down services", one host counted in error, nothing red on screen.

The same predicate also fed `getDownHostServices()`, so the Auto-fix button was enabled with
the tooltip "Auto-fix 4 down services" on a perfectly healthy host — and following it would
have started the four services TASK-144 deliberately stopped.

A second, quieter path: `operational_status === 'degraded'` counted as an error, but a
critical-but-`not_installed` service is filed under the collapsed "Not installed (N)" list and
never gets a dot, so a degraded host produced a red badge with nothing to click either.

## Fix

New [frontend/src/components/dashboard/hostHealth.ts](../../frontend/src/components/dashboard/hostHealth.ts)
holds the verdict, **derived from the panel's own model** (`buildHostServices`) instead of a
second copy of the rule that can drift:

- `severity = 'error'` when the Services card has at least one `down` row (that is precisely
  what turns its LED red) or when the backend reports the host in error.
- `severity = 'warning'` when nothing is down but the host runs a different build than the
  server, or the backend reports it degraded.
- `severity = 'ok'` otherwise.

Because the badge is now a function of the rendered rows, **the badge cannot fire without
something red on screen** — the invariant the old code violated.

`hostHasError()`, `getDownHostServices()`, the errors-only filter and the favourite chips all
go through it, so the Auto-fix button now only offers services that are genuinely down.
`isVersionMismatch()` moved into the same module so the badge and the version line cannot
disagree about what a mismatch is.

A code/version mismatch is a **warning, not an error**: a build behind its server is a deploy
to schedule, nothing is broken. That is now an amber `{count} in warning` chip beside the red
one, the version line and its `VersionMismatchIcon` turn amber instead of red, and warning
hosts stay out of the errors-only filter.

## Verification

`frontend/src/components/dashboard/hostHealth.test.ts` (12 tests) pins the behaviour, with
the captured `vpt-nipogi` payload as the regression case:

- the real payload is `ok`, 0 down rows, 0 down services (was: 4 down services → badge);
- the `optional:false` + `stopped` + profile-unneeded shape is not an error;
- a service a `tv_app` profile *does* need, stopped or stuck, is still an error and still
  reaches the Auto-fix list;
- an offline host is still an error with no service data at all;
- a `not_installed` service never lights the badge (the card draws no dot for it);
- degraded and a version mismatch are `warning`, not `error`; a real error outranks both.

`tsc --noEmit`, `eslint --max-warnings 0` + `ui-check`, and `i18n-check` are green, and the
whole dashboard suite passes (11 files, 107 tests). The 6 failures in
`navigationExecutionUtils.test.ts` and `ReleaseNotesView.test.tsx` are pre-existing on
`origin/main` and unrelated.