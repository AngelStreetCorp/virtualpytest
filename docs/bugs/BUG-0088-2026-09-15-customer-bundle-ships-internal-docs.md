# BUG-0088 — Customer bundles and deploys shipped the internal `docs/tasks/` and `docs/agent/` folders

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0088                                                     |
| Reported  | 2026-09-15                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | release / customer packaging                                 |
| Fixed in  | —                                                            |
| Commit    | TBD                                                          |

---

## Symptom

A customer package built by `setup/proxmox/node/build_customer_bundle.sh`, and the tree that
`setup/proxmox/node/deploy_customer.sh` rsyncs to a customer's hosts, contained the whole
`docs/tasks/` and `docs/agent/` folders. Those folders are internal by construction: task
plans and delivery runbooks for *every* customer, pentest findings, and the vendor's own
infrastructure layout. The first packaged delivery carried them.

## Root cause

Both scripts derived their exclude lists from the platform's own update flow, which only
skips build artefacts and secrets (`.git`, `node_modules`, `venv`, `frontend/dist`, `.env`,
`security_report`, …). Nothing ever declared "internal documentation" as a class of files to
withhold, so it travelled with the code like any other folder. The publish deny-list for the
public snapshot (`scripts/security/internal-paths.txt`, TASK-14) existed only for the public
repo, not for the customer path — although a customer must receive nothing the public would
not.

## Fix

- `build_customer_bundle.sh` reads `scripts/security/internal-paths.txt` from the **staged**
  tree (so the list matches the PIN; older PINs get a frozen fallback), adds every entry to
  the pack excludes, and refuses to produce an archive that still lists one of those folders.
- `deploy_customer.sh` adds the same paths to `RSYNC_EXCLUDES`, so neither the core stage nor
  the push carries them.

## Verification

- Pack a temp tree containing `docs/tasks/x.md` and `docs/agent/y.md` with the same tar
  excludes: the listing shows neither, and the hard stop triggers when they are forced in.
- `bash -n` on both scripts.
- Next customer delivery: `list_archive` shows no `docs/tasks/` or `docs/agent/` entry.

## Follow-up on already-delivered targets

`rsync --delete` never removes an *excluded* path on the receiver, so hosts that received an
earlier package still hold the folders. One-time cleanup on each customer target:

```bash
sudo rm -rf /opt/virtualpytest/docs/tasks /opt/virtualpytest/docs/agent /opt/virtualpytest/security_report
```
