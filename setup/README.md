# setup/ — installers

User-facing guides live in `docs/get-started/` (start at `docs/get-started/README.md`).
This folder holds the scripts those guides run.

| Folder | What | Entry point |
|---|---|---|
| `docker/` | the whole platform as containers on one machine; vendored self-hosted Supabase | `setup/docker/launch.sh` |
| `local/linux/` | native installers, one per role, each registering a systemd unit; `install_all.sh` = all roles on one machine, `install_core.sh` = developer subset, `setup/local/linux/shared/write_env.sh` = fills the `.env` files | `setup/local/linux/install_all.sh` |
| `local/macos/` | host role as launchd services | `setup/local/macos/backend_host/install_host_macos.sh` |
| `local/windows/` | host role as Windows services (NSSM) | `setup/local/windows/backend_host/install_host_windows.ps1` |
| `db/` | database schema (`schema/`, applied in order by `apply_schema.sh` on a fresh DB) and dated `migrations/` for existing databases | `setup/db/apply_schema.sh` |
| `proxmox/` | multi-VM layout: storage-VM scripts (`vm/`), and the operator tooling that ships code to a running fleet (`node/deploy_customer.sh`, `node/update_core.sh`, bundles) | `docs/get-started/proxmox.md` |

Rules the installers follow:

- **No `.env` is ever committed or baked into an image.** Templates are `.env.example`
  files; installers copy and fill them (`write_env.sh`, `launch.sh`).
- **A user-set value is never overwritten** by a re-run; only placeholders are.
- **Fresh installs are open mode** (`SERVER_OPEN_MODE=true`) and say so at the end.
- Every path a doc names must exist — `scripts/docs/check_paths.sh` runs in CI.
