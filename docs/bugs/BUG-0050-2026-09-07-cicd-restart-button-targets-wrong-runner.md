# BUG-0050 — CI/CD restart button restarts the wrong runner (wrong VM, wrong unit)

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0050                                                     |
| Reported  | 2026-09-07                                                   |
| Status    | Fixed (pending deploy)                                        |
| Severity  | Medium (restart button silently acts on an unrelated runner)  |
| Area      | `features/cicd/backend_server/__init__.py`                    |
| Fixed in  | build 8713                                                   |
| Commit    | `b904465bb`                                                   |

---

## Symptom

On **Test → Report › CI/CD Reports**, clicking the ↺ restart button on a runner card reports
success but does not restart that runner. Depending on which card was clicked it either restarts
a runner on a different VM, or restarts a different repo's runner on the right VM.

Both failure modes only became reachable on 2026-09-07, when the CI fleet was rebuilt from a
single runner on one VM into eight runners across two VMs.

## Root cause

Two independent defects in `restart_runner()`, both from assuming one runner per VM.

**1. Every unknown runner name resolved to VM 163.** `_DEFAULT_RUNNER_HOSTS` contained a single
entry:

```python
_DEFAULT_RUNNER_HOSTS = {
    'ci-runner-v3': '192.168.x.163',
}
```

`_runner_host()` falls back to `CI_RUNNER_HOST` (default `192.168.x.163`) for anything not in that
map. After the rebuild none of the live runner names (`vpt-163-1..3`, `vpt-164-1..3`,
`sample-app-163-1`, `sample-app-164-1`) were present, so a restart of any **VM 164** runner opened an SSH
session to **VM 163** and restarted a runner there instead.

**2. The remote command picked an arbitrary unit.** The unit was selected with a wildcard plus
`head -1`:

```sh
U=$(systemctl list-units --all --no-legend 'actions.runner.*.service' | awk '{print $1}' | head -1)
```

That was unambiguous while a VM hosted one runner. With four units per VM it resolves to whichever
sorts first. Verified on VM 164:

```
$ systemctl list-units --all --no-legend "actions.runner.*.service" | awk '{print $1}' | head -1
actions.runner.angelstreet-sample-app.sample-app-164-1.service
```

So restarting *any* of `vpt-164-1`, `vpt-164-2` or `vpt-164-3` would have restarted the **sample-app**
runner — taking down sample-app CI capacity while leaving the actually-stuck virtualpytest runner
running. Combined with defect 1, a restart request for `vpt-164-2` restarted `sample-app-163-1`.

The route still returned `{'success': true}` with the `systemctl status` output of the wrong unit,
so the UI reported success either way.

## Fix

`features/cicd/backend_server/__init__.py`:

- `_DEFAULT_RUNNER_HOSTS` now maps all eight runner names to their VM. The `CI_RUNNER_HOSTS`
  env override and the `CI_RUNNER_HOST` fallback are unchanged.
- The remote command selects the unit belonging to the requested runner, falling back to the old
  any-runner match and then to the hand-written `github-runner` unit older VMs used:

```sh
N=<shlex-quoted name>
U=$(systemctl list-units --all --no-legend "actions.runner.*.$N.service" | awk '{print $1}' | head -1)
U=${U:-$(systemctl list-units --all --no-legend 'actions.runner.*.service' | awk '{print $1}' | head -1)}
U=${U:-github-runner}
```

The runner name comes from the URL path, so it is passed through `shlex.quote()` before being
interpolated into the remote shell command.

## Verification

Unit resolution checked on VM 164 for all four of its runners (no restart issued):

```
vpt-164-1   -> actions.runner.AngelStreetCorp-virtualpytest.vpt-164-1.service
vpt-164-2   -> actions.runner.AngelStreetCorp-virtualpytest.vpt-164-2.service
vpt-164-3   -> actions.runner.AngelStreetCorp-virtualpytest.vpt-164-3.service
sample-app-164-1 -> actions.runner.angelstreet-sample-app.sample-app-164-1.service
```

Each name now resolves to its own unit; the pre-fix `head -1` selection returned
`actions.runner.angelstreet-sample-app.sample-app-164-1.service` for all four.

## Related

- `docs/agent/execution/PERIODIC_TEST_RUN.md` — runner topology, updated in the same commit.
- [BUG-0043](BUG-0043-2026-09-03-ci-pipeline-dead-runner-offline-reports-never-saved.md) — the
  earlier incident that introduced the restart button's host map.
