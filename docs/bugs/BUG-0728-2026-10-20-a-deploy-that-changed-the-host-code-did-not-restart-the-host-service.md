# BUG-0728 — A deploy that changed the host code did not restart the host service

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0728                                                     |
| Reported  | 2026-10-20                                                   |
| Status    | Fixed                                                        |
| Severity  | High (hosts run the previous code after a deploy that shipped new code) |
| Area      | infra / deploy                                               |
| Fixed in  | build 90145 |
| Commit    | 0377fd771                                                    |

---

## Symptom

A deploy that changed the **host** code (`backend_host/`, `shared/`, `features/`,
`requirements.txt`) pushed the new code to the hosts and reported success, but `vpt-host`
was **not restarted** — the hosts kept running the previous code until something else
restarted the service:

```
==> [host-clone-2] vpt-host.service NOT restarted: its code is unchanged since the last restart (cb8d4c4ca6); VPT_FORCE_HOST_RESTART=1 forces it
VPT_PROGRESS {"host":"host-clone-2","role":"host","phase":"restart","state":"skipped","ts":"2026-10-20T17:44:16Z","detail":"code unchanged"}
```

Found while verifying a browser fix: the new module was on the host
(`/opt/virtualpytest/shared/src/lib/utils/browser_port_allocator.py`) but the service still
ran the code from before, so the fix had no effect until the service was restarted by hand.

## Root cause

### 1. The code id was computed before the git pull

The deploy decides whether `vpt-host` needs a restart by comparing two ids: the id of the
host-code tree it is about to push, and the marker on the host (`~/.vpt_host_code_id`,
written after the last healthy restart). Both are the SHA-1 of

```bash
git ls-tree -r HEAD -- backend_host shared features requirements.txt | grep -Ev '\tshared/src/lib/game(2048)?/' | sha1sum
```

The id was computed **before the git pull** (`compute_host_code_id` was called while the
deploy script set up, the pull happens later in Step 1). So the id described the tree of the
**previous** deploy, and the marker had been written the same way — the check compared
"the deploy before last" with "the one before it".

Measured on the deploy that shipped the browser fix:

| tree | host-code id |
|---|---|
| `427743b38` (before the previous deploy) | `64ff49850e…` |
| `12035efb0` (the previous deploy — it changed no host code) | `64ff49850e…` ← the id the deploy compared with the marker |
| `2e74d65e05ad` (**the deploy being shipped** — changed `shared/` and `backend_host/`) | `3e50ad963327…` |

The two ids the deploy compared were equal, so it reported "code unchanged" and skipped the
restart — while pushing a tree whose host code had changed.

### 2. The deploy runs the node's copy, not the repo's — so the fix was never on the node

The first fix (compute the id after the pull) landed in the repo and was merged, and the
deploy that carried it still did not restart `vpt-host`. The reason: **the deploy does not
run the repo's script**.

The deploy env config says:

```json
{ "node1-vpt": { "ssh": "proxmox", "cmd": "bash update_core.sh" } }
```

That relative path resolves to `/home/<user>/update_core.sh` on the Proxmox node — a copy
that lives *outside* the repo checkout. The repo's `setup/proxmox/node/update_core.sh` is
the **template** for that copy (default targets for a fresh node); the copy on the node
carries the node's own fleet targets and is refreshed by hand.

So the fix was in the repo, in the merge, in the deploy's tree — and on the node the deploy
still ran the old script, which computed the id before the pull. Measured on node1:

| what | computes the id |
|---|---|
| repo `setup/proxmox/node/update_core.sh` (after the fix) | after the pull ✓ |
| node `~/update_core.sh` (what the deploy actually runs) | before the pull ✗ |

The node's copy is also why the documented "just `scp` it to every proxmox node" is unsafe:
the repo file and the node's copy have **different fleet targets**
(`SERVER_IP`, `HOST_IPS`, `HOST_WINDOWS_IPS`, `DOCKER_IPS`, `SSH_USER`), and a blind copy
replaces the node's targets with the template's — the node then deploys to the wrong VMs,
silently.

## Fix

1. `compute_host_code_id` and `compute_server_code_id` are now called **after** the git
   pull, so the id describes the tree that is actually pushed
   (`setup/proxmox/node/update_core.sh`).

2. `setup/proxmox/node/install_update_core.py` installs the repo's script on a node
   **without losing the node's fleet config**: it merges the repo's script with the node's
   config values (the node wins for every key it sets, the repo wins for new keys), backs
   the old copy up, and syntax-checks the result before it goes live.

   ```bash
   # report the drift, change nothing
   python3 setup/proxmox/node/install_update_core.py --node proxmox --check
   # install it (backup + bash -n + the merge diff)
   python3 setup/proxmox/node/install_update_core.py --node proxmox --install
   ```

Nothing else changes in the deploy logic: a deploy that does not touch the host code still
finds the same id and still leaves the service alone, and a dirty checkout or an offline
bundle still forces a restart (the id stays empty).

## Verification

`tests/rollout/test_deploy_host_code_id.py` (4 tests):

- the id changes when the host code changes;
- the id is computed after the git pull in the deploy script;
- a deploy that changes the host code produces an id different from the marker of the last
  restart (so the service is restarted);
- a docs-only deploy produces the same id (so the service is left alone).

`tests/rollout/test_install_update_core.py` (10 tests): the installer keeps the node's fleet
targets, takes the deploy logic from the repo, keeps a config key only the node knows and
one only the repo knows, reports a config-only difference as no logic drift, and produces a
script that passes `bash -n`.

Live, on node1 (`proxmox`), 2026-10-20:

- `--check` before the install reported exactly the intended drift (the two `compute_*`
  calls before the pull instead of after it) and nothing else;
- `--install` wrote the merged script and kept every fleet value the node had set — its own
  server list, its own host list, its Windows host, its docker stack and its deploy account —
  while the deploy logic came from the repo; it left a timestamped backup beside the old copy;
- `--check` after the install reports the node's deploy script in sync with the repo;
- node3 (`proxmox3`) runs an older variant of the script (its own targets, a different
  source tree), so it got the same two-line move applied with exact-match anchors, a backup
  and a `bash -n` — its diff against the backup is only that move.

The next deploy on node1 computes the id of the tree it pushes, compares it with the
marker of the last restart (`cb8d4c4ca6…` = the previous deploy's tree) and restarts
`vpt-host` — the check that had been comparing the deploy before last with the one before
it.
