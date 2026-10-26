# setup/proxmox/node — fleet operations

Scripts run **from a jump host** (the Proxmox node or an operator machine) against VMs that
already exist and already have their role installed. Installing a role is
`docs/get-started/proxmox.md`; this folder is what happens afterwards.

| Script | What | Doc | CI |
|---|---|---|---|
| `update_core.sh <branch>` | fetch the branch, rsync the tree to every VM listed at the top of the script (server, frontend, hosts, runners, Windows hosts), restart the services. Edit the `*_IP` lines for your fleet (or ship the file through a customer bundle). | `update_core.sh.md` (full reference); header of the script for the built-in `--help` | — |
| `deploy_customer.sh` | same delivery pipeline for a pinned platform version merged with a customer overlay repository (`DISABLED_FEATURES`, branding, custom scripts) | `DEPLOY_CUSTOMER.md` | — |
| `build_customer_bundle.sh` | package that merged tree as an offline `.tar.gz` / `.zip` with a manifest and checksum | `DEPLOY_CUSTOMER.md` | — |
| *(manual steps)* | bring an install that is behind `main` level: migrations, unit renames, server units, sudoers, per-node deploy script | `UPGRADE_EXISTING_INSTALL.md` | — |
| `deploy_bundle.sh <archive>` | verify the archive's `.sha256`, back up `REPO_DIR`, unpack the bundle in its place, run `update_core.sh` on it (TASK-99) | `DEPLOY_CUSTOMER.md` | — |
| `reconcile_feature_units.sh` | enable / disable per-feature systemd units on hosts after a feature-set change | `DEPLOY_CUSTOMER.md` | — |
| `test_update_core_skip_leased.sh` | dry check of the host selection (`--hosts`, `--skip-leased`) and of the per-target deploy ledger — never deploys | — | `deploy-harness.yml` |
| `test_update_core_summary.sh` | dry check of the deploy summary (a host whose restart was deferred is not reported as OK), of the env-driven config block and of the installer's value-aware merge — never deploys, never skips | — | `deploy-harness.yml` |
| `test_update_core_stale_code.sh` | dry check of the stale-code report: a line counts only when it IS `<service> <epoch>`, so the banner `run_ssh` prints is never read as a service — never deploys, never skips | — | `deploy-harness.yml` |

The three `test_update_core_*.sh` harnesses are local-only: they cut functions out of
`update_core.sh` and run them against fake output, so they never contact a host and take about a
second. They run in `.github/workflows/deploy-harness.yml` on **every push and every pull
request** — in their own workflow, not in `regression.yml`, whose jobs all sit behind the night
gate. For this repo GitHub Actions is the gate: the integration lane's own test command is a
syntax check (`bash -n .githooks/pre-push`).

`test_update_core_skip_leased.sh` needs a lease CLI. It uses the frozen copy in
`fixtures/vpt-lease` (a snapshot of the operator's own CLI, kept in the repo so the harness can
never skip for want of a tool), or `$VPT_LEASE_BIN` if you point it at another one. In CI it
**fails** rather than skipping: a skipped check is a green run that tested nothing.

Assumptions every script makes: SSH as the operator user with a key, passwordless `sudo` on
the VMs, the `vpt_user` service account, `/opt/virtualpytest`, systemd units `vpt-server`,
`vpt-frontend-prod`, `vpt-host` already installed by the role installers, `.env` files already
present (never overwritten), database migrations applied separately
(`setup/db/migrations/`, see `DEPLOY_CUSTOMER.md`).
