# setup/proxmox/node — fleet operations

Scripts run **from a jump host** (the Proxmox node or an operator machine) against VMs that
already exist and already have their role installed. Installing a role is
`docs/get-started/proxmox.md`; this folder is what happens afterwards.

| Script | What | Doc |
|---|---|---|
| `update_core.sh <branch>` | fetch the branch, rsync the tree to every VM listed at the top of the script (server, frontend, hosts, runners, Windows hosts), restart the services. Edit the `*_IP` lines for your fleet (or ship the file through a customer bundle). | header of the script |
| `deploy_customer.sh` | same delivery pipeline for a pinned platform version merged with a customer overlay repository (`DISABLED_FEATURES`, branding, custom scripts) | `DEPLOY_CUSTOMER.md` |
| `build_customer_bundle.sh` | package that merged tree as an offline `.tar.gz` / `.zip` with a manifest and checksum | `DEPLOY_CUSTOMER.md` |
| `reconcile_feature_units.sh` | enable / disable per-feature systemd units on hosts after a feature-set change | `DEPLOY_CUSTOMER.md` |

Assumptions every script makes: SSH as the operator user with a key, passwordless `sudo` on
the VMs, the `vpt_user` service account, `/opt/virtualpytest`, systemd units `vpt-server`,
`vpt-frontend-prod`, `vpt-host` already installed by the role installers, `.env` files already
present (never overwritten), database migrations applied separately
(`setup/db/migrations/`, see `DEPLOY_CUSTOMER.md`).
