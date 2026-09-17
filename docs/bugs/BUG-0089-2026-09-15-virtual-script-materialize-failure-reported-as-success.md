# BUG-0089 — A virtual script that never ran is recorded as SUCCESSFUL

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0089                                                                    |
| Reported  | 2026-09-15                                                                  |
| Status    | Open — deploy warning added, silent-success path not fixed                                  |
| Severity  | High (a run that never executed reports green — the worst possible failure mode) |
| Area      | `setup/proxmox/node/update_core.sh` · `backend_host/src/routes/host_script_routes.py` · `backend_server/src/routes/server_script_routes.py::task_complete` |
| Fixed in  | build 8887                                                                                                                                                 |

---

## Symptom

Every virtual script dispatched to `labox-web` "completed" in ~90 ms. No
`script_results` row was written, no report, no logs — and
`deployment_executions` recorded `status=completed, success=true, error_message=NULL`.

The server log shows a clean, healthy-looking dispatch:

```
[@call_host] 🔗 Connecting to host 'labox-web'
[@route:server_script:execute_script] Host execution started for task 34cced33-…
[@route:server_script:task_complete] Device unlock for labox-web:host: success
[@route:server_script:task_complete] Task 34cced33-… marked as completed
```

Nothing anywhere says the script did not run.

## Root cause — three failures stacked

**1. The deploy silently leaves the tree unwritable.** `update_core.sh` fixed
ownership with:

```bash
run_ssh "$host" "sudo -n find $TARGET_DIR … -exec chown vpt_user:vpt_user {} + 2>/dev/null || true"
```

`<user>` has no passwordless sudo on `labox-web`, so `sudo -n` fails, `2>/dev/null`
eats the message and `|| true` keeps the deploy green. 201 of 219 paths under
`/opt/virtualpytest` stayed `<user>:<user>` (mode 775), so **`vpt_user` could not
write `test_scripts/`** — which is precisely where a virtual script materializes
its `.vs_<uuid>.py`. Every deploy re-breaks it.

**2. The host reports nothing.** `execute_script` returns early when
materialization fails; `execute_async` posts the callback with
`slim_result = {}` and **no `error` key**.

**3. The server reads "no error" as "passed."**
`server_script_routes.py::task_complete`:

```python
script_success = result.get('script_success')
adhoc_success = script_success if script_success is not None else not bool(error)
```

An empty result with no error yields `adhoc_success = True`. A run that never
started is indistinguishable from one that passed.

## Evidence

`labox_w9_replay` and `labox_w10_series_detail` (both virtual) ran green on
labox-web at 15:40. The deploy landed at 19:53. Every virtual run after it
"completed" instantly with no row. After `chmod 777 /opt/virtualpytest/test_scripts`,
a virtual `dailymotion_video_check` ran on labox-web in 72 s with a report —
versus the same script before the fix producing no row at all.

## Fix

**Live:** `chmod 777 /opt/virtualpytest/test_scripts` on `labox-web` (the deploy user owns
it, so no sudo needed). **This does not survive a deploy** — re-apply, or give
`<user>` passwordless sudo there.

**In the repo:** `update_core.sh` no longer swallows the chown failure. It reports
the host, names the consequence, prints the workaround, and lists every affected
host under `⚠️ OWNERSHIP NOT FIXED` in the deploy summary.

## The silent success — closed 2026-09-15

All three parts of the stacked failure are now addressed.

1. **The executor reports its failure.** `_materialize_virtual_script` raises
   (`ValueError` on a missing row, `PermissionError` from the `open()` when
   `test_scripts/` is unwritable) and `execute_script` wraps the whole virtual-script
   path in a `try`, returning `{'success': False, 'exit_code': 1, 'stderr': …}`.
   The evidence was on the wire; nothing read it.

2. **The server stopped reading "no error" as "passed"** (`3853d3692a`).
   `_derive_run_success()` checks, in order: the `SCRIPT_SUCCESS:` marker (the test's
   own verdict, still authoritative) -> a transport error -> the executor's
   `success: False` -> a non-zero exit code -> and finally a callback with no exit
   code and no `script_result_id`, which means the host never ran anything.

3. **One callback, one verdict.** `_derive_run_success` was consulted only for the
   adhoc `deployment_execution` row. The in-memory task record and the outbound
   completion webhook were still on `'failed' if error else 'completed'`, so the same
   run the adhoc row correctly marked failed was reported to an external consumer
   (dmacp) as completed. The verdict is now derived once in `task_complete` and used
   for all three, and a failure the host did not phrase as an error gets a factual
   reason on the wire (`result['stderr']`, else "host reported no script result")
   rather than `status=failed` with `error=None`.

`_derive_run_success` had no tests despite encoding the whole fix;
`tests/shared/test_run_success_derivation.py` now covers the marker outranking
everything, real runs keeping their old verdict (exit 0 with no marker still passes),
and the three BUG-0089 shapes — executor early return, empty callback, malformed
callback. Pure unit tests, no server (`tests/backend_server/` skips without a
reachable deployment).

## Still open — a judgment call, not a defect

`resolve_virtual_script_libs` skips a `_script_libs` entry it cannot fetch with only a
`print`. The run does NOT pass: the script hits `ImportError` and is recorded as a
failure. The cost is diagnosability — a clear "library 'x' not found" becomes a
confusing traceback. Making it raise would be a better error, but the skip is
documented and deliberate ("missing libraries are skipped, not fatal — keeping
resolution best-effort"), so flipping it could break a script that declares an
optional library. Needs a product decision, not a patch.

## Follow-up 2026-09-15 — the warning over-reported

The first night with the warning live, node1's summary listed `vpt-pi1`,
`host-clone-1` and `labox-web` under `⚠️ OWNERSHIP NOT FIXED`; node3 listed none.
Only `labox-web` was real.

`chown` without `-h` dereferences symlinks. The browser profile directories a host
leaves under `backend_host/config/{user_data,webkit_user_data}` contain dangling
`SingletonLock` / `SingletonCookie` / `SingletonSocket` symlinks (Chromium writes
them pointing at a `<host>-<pid>` that is gone). chown prints `cannot dereference`
for each, `find -exec … +` propagates that as exit 1, and the host was flagged
although every real file had been chowned:

    vpt-pi1      chown → rc=1, 9 × cannot dereference   test_scripts owner=vpt_user 775
    host-clone-1 chown → rc=1, 8 × cannot dereference   test_scripts owner=vpt_user 775
    labox-web    sudo: a password is required           test_scripts owner=<deploy user> 775

node3's hosts had never run a browser, so they had no dangling symlinks and no
warning — which is why the noise looked node1-specific.

Two changes in `update_core.sh`:

- `chown -h`, so symlinks are chowned in place and never dereferenced. This is
  the correct behaviour for a deploy tree anyway. Both hosts now exit 0.
- The warning no longer fires on the chown exit status alone. A non-zero chown
  triggers a check of the invariant that actually matters — is
  `test_scripts/` writable by `vpt_user` (owner, or group + group-write, or
  other-write)? — and only a genuine failure is collected.

`labox-web` still fails both: after the 2026-09-15 deploy its `test_scripts` was
back to `<deploy user>:<deploy user> 775`, confirming the live `chmod 777` does
not survive a deploy. It needs passwordless sudo for the deploy user, or
`vpt_user` group membership + group-write — the chmod is a stopgap.

## Root cause of the recurrence — the deploy itself re-breaks it

`chmod 777` "not surviving a deploy" was not a coincidence, and `labox-web` was not
merely unlucky. The push is:

    rsync -az --delete --rsync-path="sudo rsync" …

`-a` implies `-o`/`-g`, and the remote rsync runs as **root**, so it actually applies
them: every push stamps the whole target tree with the *source's* numeric uid/gid —
the deploying user's, uid 1000 on the Proxmox node — and `-p` re-applies the source's
mode. So each deploy deliberately sets `/opt/virtualpytest` to `<deploy user>:<deploy
user> 775`, wiping both the ownership and the `chmod 777`. The `find … -exec chown`
afterwards exists only to undo that damage.

Numeric mapping could never have been right anyway: `vpt_user` is uid 995 on the Pis
and 999 on the VMs.

On `labox-web` the repair cannot run, because its sudoers is a whitelist rather than
`NOPASSWD: ALL`:

    (ALL : ALL) ALL                              <- password required
    (ALL) NOPASSWD: /usr/bin/git, /bin/bash
    (ALL) NOPASSWD: /usr/bin/rsync
    (ALL) NOPASSWD: /usr/bin/git, /bin/systemctl

`rsync` is passwordless, so the push succeeds and the host reports **OK**; `find` and
`chown` are not, so `sudo -n find … -exec chown` is refused and the tree stays
`<deploy user>`-owned. The same whitelist silently skips the feature-unit reconcile
there (`sudo -n test -f …` is refused, which the caller reports as "older tree").

**Fix:** `--chown=vpt_user:vpt_user` on the push. rsync resolves the name on the
receiver, so the per-host uid difference stops mattering, and the tree lands correct
instead of being broken and repaired. It also routes through the one command
`labox-web` *does* grant passwordless. Verified against `labox-web` on a scratch path:
the transferred tree arrived `vpt_user:vpt_user`. rsync is 3.2.7 on every target
(`--chown` needs 3.1+), and `vpt_user` exists on all of them including the CI runner.

The `find … -exec chown -h` step stays as a net for runtime output that a
wrongly-owned process created — it is no longer the only thing keeping
`test_scripts/` writable.

## Resolved 2026-09-15 — deployed and verified

`update_core.sh` with `--chown` installed on node1 (node3 got the two hunks only; its copy is an
older lineage). Full `bash update_core.sh main` run: **11/11 OK, no `OWNERSHIP NOT FIXED`, no
`cannot dereference` anywhere in the log.** `/opt/virtualpytest` and `test_scripts/` are
`vpt_user:vpt_user 775` on every target, `labox-web` included — set by the push, while that host's
`sudo -n find … chown` was still being refused.

`labox-web`'s underlying fault was simply a missing `/etc/sudoers.d/jndoye-nopasswd`
(`jndoye ALL=(ALL) NOPASSWD: ALL`) that every other host in the fleet has; it had only a whitelist
for `rsync`/`git`/`bash`/`systemctl`. Installed 0440 root:root, `visudo -c` clean across all
fragments. Both previously-refused steps now succeed, and the feature-unit reconcile — which had
never run there, its `sudo -n test -f` refusal misreported as "not on the target (older tree)" —
rendered `vpt-avq.service` (dry-run first: `would-render=1 would-remove=0`; the unit is
enabled/active/0 restarts on every comparable host). Final check: writing to `test_scripts/` **as
vpt_user** succeeds.

The silent-success path in `execute_script`/`task_complete` (the section above) is still open —
it is the remaining half of this bug.
