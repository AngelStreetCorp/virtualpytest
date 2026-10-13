# BUG-0219 — `update_core.sh`: every deploy that touches hosts stopped at "trim_host: command not found"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0219                                                     |
| Reported  | 2026-10-01                                                   |
| Status    | Fixed — node1's live `~/update_core.sh` patched 2026-10-01; node3's copy still has the bug |
| Severity  | High — a full, `--host` or `--restart` deploy did nothing; `--frontend` and `--server` alone still worked |
| Area      | `setup/proxmox/node/update_core.sh` (and the live copies on proxmox / proxmox3) |
| Fixed in  | Unreleased                                                   |
| Commit    | this commit                                                  |

---

## Symptom

`ssh proxmox "VPT_LEASE_AGENT=codebox:TASK-36 bash update_core.sh main"` printed the targets,
then `update_core.sh: line 642: trim_host: command not found`, and exited 127 before
pulling or syncing anything. Proxmox stayed on the previous commit and no lease was left
behind. Found while deploying the TASK-36 server fix (BUG-0215) after the lease registry
showed node1 free.

## Root cause

`678e36e9d` ("lease check covers only what the deploy touches") added `add_lease_hosts`,
which runs at load time when hosts are deployed and calls `trim_host`. `trim_host` was
defined about 100 lines further down, next to the host deploy loop, so it did not exist yet
when the lease block ran. A `--frontend` or `--server` deploy never called `add_lease_hosts`,
which is why those still worked.

## Fix

`trim_host` is defined just before the lease block. The live copy on proxmox
(`~/update_core.sh`) got the same move, with a backup at
`~/update_core.sh.bak-20261001-trimhost`. node3's live copy (`proxmox3:~/update_core.sh`)
has the same ordering (use at line 464, definition at 539) and was not changed.

## Verification

- `bash -n` passes on both node1 copies.
- The same full deploy (`update_core.sh main`, `89602040d`) then ran: 12 targets OK. labox-tablet
  failed on `No route to host` (192.168.0.173 unreachable), which is unrelated.
