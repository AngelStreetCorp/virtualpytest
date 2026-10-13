# BUG-0342 — Every full deploy reported a failure for the intentionally offline labox-tablet

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0342                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low - false alarm, the deploy itself worked                  |
| Area      | `update_core.sh` host list on the proxmox node (live copy, not in the repo) |
| Fixed in  | Unreleased                                                   |
| Commit    | none: the live `~/update_core.sh` on proxmox was edited      |

---

## Symptom

Every full or host deploy ended with `labox-tablet rsync FAILED`, `FAILED (1): labox-tablet` and `Done (with failures).` (deploys `6a35b60d`, `fd098682`, `6266a743` on 2026-10-04). The manager treated each run as a failed deploy although `update_core` exit code was 0 and all 12 other hosts were `OK`.

## Root cause

`labox-tablet` is switched off on purpose (no resources for it), but it was still in `HOST_IPS` in the live `~/update_core.sh` on proxmox, so every run tried to rsync to an unreachable VM. The repo copy `setup/proxmox/node/update_core.sh` carries a generic host list without that name, so the repo needed no change; proxmox3 (QualiAI node) does not list it either.

## Fix

One line in `~/update_core.sh` on proxmox: `labox-tablet,` removed from `HOST_IPS` (backup `update_core.sh.bak-2026-10-04-tablet` beside it). `labox-tablet` is documented as intentionally offline in the internal infra inventory (`docs/agent/infra/INFRA.md`, gitignored), with how to bring it back: re-add it to `HOST_IPS`, run a host deploy for it, check the emulator audio unit.

## Verification

Applied 2026-10-04: `diff` shows only that one line, `bash -n` passes, `bash update_core.sh --help` still runs, and no deploy was running when it was edited. Not yet verified end to end: the next full deploy should end with no `FAILED` line and no `Done (with failures).`
