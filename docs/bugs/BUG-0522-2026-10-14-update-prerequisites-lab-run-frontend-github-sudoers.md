# BUG-0522 — Platform update prerequisites on the lab: frontend never updated, GitHub check always KO, reconcile helper writable by the service user

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0522                                                     |
| Reported  | 2026-10-14                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend_server platform update / sudoers                     |
| Fixed in  | build 90145 |
| Commit    | `fix/prereq-lab`                                             |

---

## Symptom

Running the TASK-101 prerequisites on node1 (server `.env` has `GITHUB_TOKEN`, no `VPT_GITHUB_TOKEN`, no
`FRONTEND_DEPLOY_HOST`):

1. `frontend_ssh` said N/A "No separate frontend VM" although node1 has one, and the pull deploy then
   skipped the frontend for good. The older Code deployment buttons still reached the VM because
   `server_system_routes.py` carried the lab IP as a default (`DEFAULT_FRONTEND_DEPLOY_HOST`).
2. `github` was KO: `could not read Username for 'https://github.com': terminal prompts disabled` even with a
   token set. The check passed `-c http.extraHeader=Authorization: Bearer <token>` in argv (visible in `ps`)
   and GitHub git-over-HTTPS wants Basic auth.
3. `host_sudo` was KO for the reconcile (the drop-in was not installed, as expected), but the drop-in as written
   granted root on `/opt/virtualpytest/setup/proxmox/node/reconcile_feature_units.sh`, a file owned by the
   service user: whoever can write it gets root.

## Root cause

1. Two readers of `FRONTEND_DEPLOY_HOST` with different rules (none vs a hardcoded lab default).
2. The token was handed to git as a header in argv instead of through the askpass mechanism the bundle builder
   already used for GitLab and overlay clones; the core clone and the source listing sent no credentials at all
   although the core is a private repository.
3. The sudoers rule named a path inside the service user's own tree.

## Fix

1. One resolver, `frontend_ssh.config()`: a host or IP = separate VM over SSH, `local` = the frontend runs on
   the server VM (built and restarted at the end of the server leg), `none` = no frontend, unset = KO "Set
   FRONTEND_DEPLOY_HOST (host, local or none)". The hardcoded lab IP is gone; `_frontend_remote_config()` uses
   the same resolver.
2. `shared/src/lib/utils/git_auth.py`: user `x-access-token`, password = token (`VPT_GITHUB_TOKEN`, else
   `GITHUB_TOKEN`) through a 0700 askpass script in a private temp directory that is removed afterwards. Used by
   the prerequisites check, the core and overlay clones and the candidate listing of `customer_bundle.py`. The
   token is only offered to github.com.
3. The drop-in grants `/usr/local/sbin/vpt-reconcile-feature-units` (root-owned copy, with its lib in
   `/usr/local/lib/vpt-update/`), installed by `setup/sudoers/install_vpt_update_sudoers.sh`. Every caller uses it;
   the check says "installed reconcile helper is older than the tree" when the copies differ.

## Verification

`python3 -m pytest -q tests/backend_server/test_platform_update*.py tests/rollout tests/backend_host/test_bundle_apply.py`
(token absent from every argv, askpass file gone afterwards, frontend modes, helper path, stale helper). On the lab:
set `FRONTEND_DEPLOY_HOST=192.168.x.105`, run `install_vpt_update_sudoers.sh` on the server and every host, press
Re-check: the three checks leave KO.
