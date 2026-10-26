# BUG-0341 — A deploy runner restart left an orphaned "running" deploy that blocked the queue

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0341                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium - deploy queue blocked for over an hour               |
| Area      | deploy runner (`ghosty-sessions` repo, not this one) + `vpt-lease deploy` registry on proxmox |
| Fixed in  | build 90145 |
| Commit    | `d6542c4` (orphan sweep) and `31ca260` / `28e9b39` (re-adoption) in ghosty-sessions |

---

## Symptom

Deploy `6406abc8` (node1-vpt, scope full) stayed `state=running` from 11:05 UTC (started 11:05:51) until 12:19 UTC. Its log stopped growing at 11:06 UTC (last line: `systemctl restart vpt-server.service` on vpt-pi1), no `update_core` process was running on proxmox, and every other approved deploy (`fd098682`, `b7b720e7`, `37e2d048`, `9b1ac667`) waited behind it. The registry would only have auto-failed it after 90 minutes.

## Root cause

The `ghosty-sessions` unit was restarted shortly after 11:06 UTC. That killed the deploy runner and its ssh child in the middle of the deploy. After the restart the new runner no longer tracked the deploy, but the registry still said `running`, and nothing finished it.

## Fix

ghosty-sessions `d6542c4` (merge of `mm-orphan-deploy`): the runner finishes a running deploy it does not track as `failed` once its log has been idle for more than 10 minutes. It raises one alert and never re-queues the deploy. The sweep is limited to environments the runner owns, so it cannot fail another runner's deploy (found by the gate review).

## Verification

On the restart at about 12:19 UTC the new code finished `6406abc8` as `failed` (log ends `# orphaned: runner restarted mid-deploy, finished by the runner`, 12:19:31) and the queue moved: `fd098682` started 12:20:01 and finished `done` at 12:23:02. The gate's own check was unit-level (471 of 472 tests; the one failure, `scorecard.test.js`, also fails on main).

Known residual of that first fix: if the old ssh child outlives the runner, the environment is freed while the remote deploy may still be running.

Not re-verified here: the exact time of the earlier restart (the 11:08:19 UTC figure came from the manager, not from a log I could read).

## Second incident, same day

`ghosty-sessions` was restarted at 16:36:43 UTC during frontend deploy `f025aa75` (started 16:36:00). The runner was killed, the orphan sweep finished the deploy as `failed` at 16:46:45 UTC, and task43 had to re-request it. The sweep alone therefore still costs a failed deploy per restart.

## Residual fix: detached deploy child, re-adopted on start

ghosty-sessions merge `31ca260` (commit `28e9b39`):

- The deploy child is spawned detached, with `pid`, `exit`, `run` and `off` files under the deploys state dir.
- On startup the runner re-adopts a `running` deploy whose pid is still alive, or whose `exit` file exists, and finishes it through the normal path.
- The orphan sweep is unchanged and only handles what is left over.
- The systemd unit now has `KillMode=process`, so a restart no longer kills the child. Installed on codebox at 18:15 UTC (backup `ghosty-sessions.service.bak-2026-10-04-killmode`), `daemon-reload` done, ghosty restarted 18:15:49 UTC via `scripts/safe-restart.sh`. `systemctl show` confirms `KillMode=process`.
- `scripts/safe-restart.sh` (added by the ghosty dev session) refuses a restart while a deploy is running. Use it instead of a bare `systemctl restart`.

Verified: 575 tests, run 3 times; a live check on a spare port with a fake deploy script, server killed mid-deploy, the child survived and the deploy finished `done`.

Not verified:

- Behaviour under real systemd with a real deploy. The first restart after the unit install still loses any deploy running at that moment.
- pid reuse after a reboot is not guarded.
- The `pid`/`exit`/`run`/`off` files are never cleaned up.
