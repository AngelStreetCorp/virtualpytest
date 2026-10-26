# BUG-0543 — The VM agent's db-backup action fails with "read-only file system"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                  |
|-----------|--------------------------------------------------------|
| ID        | BUG-0543                                               |
| Reported  | 2026-10-15                                             |
| Status    | Fixed (pending deploy)                                 |
| Severity  | Major (Platform update step 1 cannot take a fresh backup) |
| Area      | infra / VM agent                                       |
| Fixed in  | build 90145 |
| Commit    | see branch fix/db-backup-unit                          |

---

## Symptom

On the lab database VM, `POST /actions/db-backup` started the backup and it exited 1 with
`open /data/backups/vpt_postgres_….dump: read-only file system`.

## Root cause

The agent runs under `ProtectSystem=strict`, `ProtectHome=yes`, `PrivateTmp=yes`. It started
`/usr/local/bin/vpt-db-backup.sh` as a child process, which inherits that sandbox, so `/data/backups` was read-only.

## Fix

The backup is its own systemd one-shot unit, `vpt-db-backup.service` (no sandbox). The agent only runs
`systemctl start --no-block` on it and reads state from `systemctl show` and `journalctl -u`; the JSON answer is
unchanged. The agent stays sandboxed, with no `ReadWritePaths`. `install.sh --action db-backup` installs the unit.

## Verification

Re-run `install.sh` with the same flags, then `POST /actions/db-backup`: the dump appears in `/data/backups`, and
`GET /actions/db-backup` ends with `exit_code: 0`.
