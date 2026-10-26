# update_core.sh — reference

The fleet deploy script that runs on the **Proxmox jump host** (`proxmox` for `node1-vpt`,
`proxmox3` for `node3-qualiai`). One script per Proxmox node; each copy knows its own VM
targets via the `*_IP` lines at the top.

Canonical source: `setup/proxmox/node/update_core.sh` in this repo. The copy on proxmox
(`/home/<user>/update_core.sh`) is **manually installed** from the repo — the script and the
file on disk can drift, and the deploy runs the **copy on the node**, not the repo file.
After any change to the script in the repo, install it on every proxmox node that runs it:

```bash
# report the drift, change nothing
python3 setup/proxmox/node/install_update_core.py --node proxmox --check
# install it: backs the old copy up, merges the repo's script with the node's fleet
# config, syntax-checks the result and only then swaps it in
python3 setup/proxmox/node/install_update_core.py --node proxmox --install
```

**Do not `scp` the repo file over the node's copy.** The repo file is the template (default
targets for a fresh node); the node's copy carries that node's fleet targets (`SERVER_IP`,
`HOST_IPS`, `HOST_WINDOWS_IPS`, `DOCKER_IPS`, `SSH_USER`). A blind copy replaces them with
the template's, and the node then deploys to the wrong VMs — silently, and worse than the
drift it was meant to fix. The installer merges instead: the repo's script with the node's
config values.

A node whose copy is too far from the repo to install wholesale (an older variant with its
own layout) cannot be merged this way; patch the change into it by hand, with a backup and
a `bash -n`, and keep the node's copy in sync with its own checkout.

**Run the installer from a checkout that is up to date.** It reads the script from the checkout
it runs in, so a checkout that is behind `origin/main` holds the *old* script — installing from
it would roll the node back to the version the repo has already replaced. The installer
compares the local copy with `origin/main`'s copy of the same file and refuses to install a
stale one; `--check` then judges the node against `origin/main` and says plainly that the
local copy is stale. Update the checkout (`git fetch origin && git pull`) and run again.
`--force` overrides the refusal — it is there for the deliberate rollback, not for a stale
checkout.

See also:

- `setup/proxmox/node/README.md` — sibling scripts in this folder.
- `setup/proxmox/node/DEPLOY_CUSTOMER.md` — customer-bundle variant of the same pipeline.
- `~/update_core.md` on proxmox — post-mortem from a past rsync ownership-drift incident.
  Keep both files; they cover different ground.
- `docs/agent/infra/DEPLOY.md` — the full deploy workflow and the agent-lease rules this
  script enforces.

## When to use it

- Pushing a new commit on a branch to a running fleet (debug, preprod, prod, a feature
  branch).
- Restarting a single aux service on every host (e.g. `vpt-stream` after a config change)
  without re-deploying code.

## What it does

Default (no flags): **full deploy** of every VM listed in the script's header.

1. **Git pull** in `REPO_DIR` (default `~/virtualpytest`) directly from GitHub — skipped
   when `REPO_DIR` is an extracted offline bundle (`BUNDLE_MANIFEST.txt` present, no
   `.git`; see `DEPLOY_CUSTOMER.md`).
2. Print `VERSION.txt` (source-controlled / written by the bundle builder).
3. **Rsync** the tree to each target VM as `vpt_user`, excluding volatile paths
   (`frontend/dist`, `frontend/public/docs`, `playwright-report*`, generated
   artifacts, overlay-owned files).
4. **Restart** the matching core systemd services on each VM and reconcile per-feature
   systemd units on hosts. Auxiliary services restart only with `--restart`.

## Usage

```text
bash update_core.sh [branch] [--frontend] [--server] [--host] [--host-windows]
                    [--force] [--skip-leased] [--skip-hosts a,b] [--hosts a,b]
                    [--restart [service]]
```

The branch argument is optional and can appear before or after flags. If omitted, the
script deploys whatever branch the local `REPO_DIR` is currently on.

| Flag | Effect |
|---|---|
| `--server` | rsync + restart the **server** VM (`SERVER_IP`, `vpt-server.service` and server aux services). |
| `--frontend` | rsync + restart the **frontend** VM (`FRONTEND_IP`, `vpt-frontend-prod.service`). |
| `--host` | rsync + restart every host in `HOST_IPS` + `RUNNER_IPS` (`vpt-host.service`). |
| `--host-windows` | rsync + restart every Windows host in `HOST_WINDOWS_IPS` (Cygwin target). |
| `--hosts a,b` | deploy only these hosts (implies `--host` for them). A name this node does not know — a typo, or a host that was retired from the node's list — is **dropped** with a `WARNING: --hosts names not in this node's host lists (dropped): …` line, and the deploy goes on with the names the node knows; the dropped names are recorded in the deploy note as `dropped (unknown host)`, never in `SKIPPED_HOSTS` (no catch-up deploy is queued for a host that no longer exists). The deploy **aborts** only when EVERY requested name is unknown, or when the request names no host at all (`--hosts ,`). |
| `--skip-hosts a,b` | drop these hosts from this run. |
| `--skip-leased` | a host of this run's host lists that another agent leases is synced **without** a lease — its `vpt-host` restart is deferred to the catch-up deploy (printed as `SYNC ONLY (leased by <agent>): <host>`); a leased host that is not part of this run (a Windows host, a secondary server) is dropped and printed as `SKIPPED (leased by <agent>): <host>`. The server part is then blocked only by `server` and env-wide leases, not by per-host leases. The last output line `SKIPPED_HOSTS=…` lets the deploy runner queue a catch-up deploy for the dropped ones. |
| _(automatic)_ | **Down and unreachable hosts are skipped, never failed.** Hosts named in `~/.vpt-down-hosts` (one per line, `#` comments; ignored when `--hosts` names them) are dropped, then one parallel `ssh true` preflight (6 s) drops any host with no route. Printed as `SKIPPED (down on purpose…)` / `SKIPPED (unreachable, no ssh)` and recorded in the deploy note as `skipped (down|unreachable)`. They are not in `SKIPPED_HOSTS`, so no catch-up deploy is queued for them. `VPT_SKIP_PROBE=1` turns the preflight off. |
| _(automatic)_ | **vpt-host is restarted only when the host code changed.** A hash of the git trees `backend_host shared features scripts setup requirements.txt` is stored on the host (`~/.vpt_host_code_id`) after each healthy restart. If it matches and the unit is active, the files are still rsynced but `vpt-host` is not restarted (`restart skipped: host code unchanged`, deploy note `no restart (host code unchanged)`). Frontend-, docs- and test-only pushes no longer restart hosts under long runs. `VPT_FORCE_HOST_RESTART=1` forces it; a dirty tree or a bundle without `.git` always restarts. |
| _(automatic)_ | **Pinned hosts for long runs.** Hosts listed in `~/.vpt-pinned-hosts` (same format as `.vpt-down-hosts`) are left on the code they have by every push-driven deploy (full, `--host`, `--skip-leased`): printed as `SKIPPED (pinned…)`, noted `skipped (pinned)`, never in `SKIPPED_HOSTS` (no catch-up). A deploy that names them with `--hosts a,b` updates them; the manager runs that in an idle gap. **Servers too:** the node's own server and the Pi servers restart only when `backend_server shared features scripts setup requirements.txt` changed (marker `~/.vpt_server_code_id`). |
| `--restart [service]` | restart-only mode. On its own: skip git pull + rsync, just restart aux services on host VMs. With a service name (`vpt-stream`, `vpt-monitor-img`, `vpt-monitor-subtitle`, `vpt-monitor-audio`, `vpt-archiver`, `vpt-avq`, `vpt-kpi`): only that one, still only if already active. With a deploy target: deploy first, then restart aux services on the hosts. |
| `--force` | deploy even if a lease blocks. **Footgun** — only when the user explicitly says to. |
| `--help` / `-h` | print the built-in usage. |

### Examples

```bash
# Full deploy, current branch, on the local proxmox
ssh proxmox "bash update_core.sh"

# Frontend-only hot push of a feature branch
ssh proxmox "bash update_core.sh feat/login-ux --frontend"

# Server + hosts of one branch, frontend untouched
ssh proxmox "bash update_core.sh main --server --host"

# Just the stream service on every host (no rsync)
ssh proxmox "bash update_core.sh --restart vpt-stream"

# Deploy only one host, full env
ssh proxmox "bash update_core.sh main --host --hosts vpt-pi1"

# Drop a host for this run only (e.g. it's running a long script)
ssh proxmox "bash update_core.sh main --skip-hosts labox-mobile"

# Full deploy but skip any host another agent has leased
ssh proxmox "bash update_core.sh main --skip-leased"
```

## Fleet topology (top of the script)

These constants select the targets. The copy on each Proxmox node is its own list — a
fresh `setup/proxmox/node/update_core.sh` from the repo ships **defaults**, not the live
fleet. Edit the `*_IP` lines for your node before running, or ship the file through a
customer bundle.

Every target is read from the environment, with the value in the script as its default
(`HOST_IPS="${HOST_IPS:-<this node's hosts>}"`), so one deploy can be pointed somewhere
else without editing the file:

```bash
HOST_IPS=<host-a>,<host-b> bash ~/update_core.sh main --host
```

The installer (`install_update_core.py`) merges the node's own targets into that shape, so
the node's fleet stays the default and the environment still wins over it.

| Constant | Role |
|---|---|
| `SERVER_IP` | VM running `vpt-server` and the server aux services. |
| `FRONTEND_IP` | VM running `vpt-frontend-prod`. |
| `HOST_IPS` | comma-separated hosts running `vpt-host`. |
| `RUNNER_IPS` | optional comma-separated CI runner VMs. |
| `HOST_WINDOWS_IPS` | optional Windows hosts (Cygwin target). |
| `DOCKER_IPS` | optional hosts whose Docker-compose stacks are rebuilt from source. |

An alias that does not resolve in the node's `~/.ssh/config` is **skipped silently** —
check the live `*_IP` lines with `ssh -G <alias>` if a target looks configured but is
never deployed to.

## Services

| Tier | Unit(s) | When restarted |
|---|---|---|
| Server | `vpt-server.service` | on `--server` / full deploy. |
| Server aux (restarted after `vpt-server`, only if already active) | `vpt-heatmap`, `vpt-discard-incidents`, `vpt-discard-scripts` | on `--server` / full deploy. |
| Frontend | `vpt-frontend-prod.service` | on `--frontend` / full deploy. |
| Host | `vpt-host.service` | on `--host` / full deploy. |
| Host aux (only if already active) | `vpt-stream`, `vpt-monitor-img`, `vpt-monitor-subtitle`, `vpt-monitor-audio`, `vpt-archiver`, `vpt-avq`, `vpt-kpi` | only with `--restart`, alongside a deploy or by itself. |
| Windows host | `vpt-host` scheduled task | on `--host-windows`. |

Aux-service restarts are best-effort: a failure here never aborts the deploy, it is
collected and reported in the `SERVICE RESTART FAILED` summary.

## Agent-lease model

`update_core.sh` enforces the shared lease registry (`vpt-lease`) on this node's env
(`LEASE_ENV`). Before deploying, it computes the resources this run would touch and
asks the registry whether any other agent holds them.

| Run | Lease resources checked |
|---|---|
| `--server` (or anything that restarts the server) | `*` (the whole env) |
| `--frontend` | `frontend` |
| `--host` | each named host in `HOST_IPS` + `RUNNER_IPS` |
| `--host-windows` | each named host in `HOST_WINDOWS_IPS` |
| Hosts given by **IP** (not name) | cannot be matched to a lease name, count as `*` |
| `--restart <service>` for a single background service | no lease (starts in seconds) |

If anyone else holds one of those resources, the script aborts with exit 3 and prints
who holds what. `--force` overrides.

While the deploy runs it holds its own lease on the same resources, released on exit
(including on failure). `VPT_LEASE_AGENT=<id>` names the deploying agent so its own
leases do not block it.

### Parallelism — what is and is not safe

- **One `update_core.sh` per Proxmox node, serially.** Within a node, two
  `update_core.sh` calls race on the shared `REPO_DIR` and overlap on the lease
  resources. Concretely, `--server` and `--frontend` cannot run in parallel: the
  first holds `*` (which includes `frontend`), the second wants `frontend` and
  finds it held. The right pattern is to run them as two calls if you really need
  the scope split, **serially**.
- **Different Proxmox nodes in parallel is fine.** `proxmox` (node1-vpt) and
  `proxmox3` (node3-qualiai) are independent envs, separate lease registries.
- **Different feature branches on the same node is not safe.** They share
  `REPO_DIR` and would corrupt each other mid-rsync.
- **`--skip-leased` is the way to share the env with a long-running test.** A busy
  host of this run is synced without a lease and its `vpt-host` restart is deferred;
  the catch-up deploy that restarts it is queued by the runner.
- **`--restart <service>` needs no lease** because the service starts in seconds.
  `vpt-host` and `vpt-stream` are not in that list.

## Environment variables

| Variable | Default | Effect |
|---|---|---|
| `REPO_DIR` | `~/virtualpytest` | source tree to rsync from. Used as git checkout or extracted offline bundle (when `BUNDLE_MANIFEST.txt` is present). |
| `SSH_USER` | `$(id -un)` | the operator account on the proxmox host; passed to ssh on every target. |
| `SSH_KEY` | `~/.ssh/id_ed25519` | SSH key for target VMs. |
| `VPT_LEASE_AGENT` | — | names the deploying agent in the lease registry; own leases do not block it. Pass `mac:TASK-NN` or `codebox:<branch>`. |
| `LEASE_REGISTRY_HOST` | — | if `~/bin/vpt-lease` is not on this node, the script SSHes to this host to call it. |
| `LEASE_ENV` | set per node | the env name passed to `vpt-lease check` (e.g. `node1-vpt`, `node3-qualiai`). |
| `BUNDLE_MANIFEST` | auto | when present in `REPO_DIR`, the git pull is skipped. |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success (including `--skip-leased` with nothing left to deploy — `SKIPPED_HOSTS=…` printed for the runner to catch up). |
| 1 | usage error or a deploy step failed. |
| 3 | lease guard aborted the run (someone else holds a resource this run would touch). |
| 127 | `vpt-lease` registry not reachable; the script logs `no lease registry configured — skipping` and continues only when the registry is not configured (otherwise it aborts). |

## Common failures and first checks

- **rsync `Permission denied` / code 23** on a target VM. Almost always ownership
  drift on `/opt/virtualpytest` (root-owned dirs/files after a manual fix or a
  different user's rsync). See `~/update_core.md` on proxmox for the one-shot
  repair:
  ```bash
  find /opt/virtualpytest -not -user vpt_user -printf '%u:%g %m %p\n' | head
  ```
- **`SERVICE RESTART FAILED`** lines at the end. The deploy succeeded but an aux
  service (e.g. `vpt-monitor-img`) failed to come back. Re-run with
  `bash update_core.sh --restart <service>` to retry; the restart is
  best-effort by design.
- **Stale frontend bundle**. `--frontend` rsyncs source but not the built bundle
  when the target runs a build step on its own. Check
  `frontend/dist/...` on the frontend VM.
- **Lease held by another agent**. `vpt-lease list` shows who; either wait
  (the skill's 3–5 min loop) or, with explicit user approval, use
  `--skip-leased` / `--skip-hosts <busy-host>` to deploy around it.

## Editing the script

The script is a single bash file. Keep it readable: header comment block, then
constants, then `usage()`, then arg parsing, then functions, then the flow. The
built-in `usage()` must stay accurate — it is what `--help` prints and what
every run logs on `-h`.

After any change, run `bash update_core.sh --help` to verify the usage block,
and ship the file to every Proxmox node that runs it:
```bash
# report the drift, change nothing
python3 setup/proxmox/node/install_update_core.py --node proxmox --check
# install it: merges the repo's script with the node's fleet config, backs the old
# copy up, syntax-checks the result and only then swaps it in
python3 setup/proxmox/node/install_update_core.py --node proxmox --install
```
Do not `scp` the file over the node's copy (see the top of this page): that replaces the
node's fleet targets with the template's.
