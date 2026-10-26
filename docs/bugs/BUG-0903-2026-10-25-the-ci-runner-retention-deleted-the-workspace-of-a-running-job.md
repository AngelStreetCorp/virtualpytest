# BUG-0903 — The CI runner retention deleted the workspace of a running job

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0903                                                     |
| Reported  | 2026-10-25                                                   |
| Status    | Fixed (pending deploy + runner install)                      |
| Severity  | High                                                         |
| Area      | platform (CI runner retention)                               |
| Fixed in  | build 90145 |
| Commit    | see branch `fix/e79-runner-retention-live-guard`             |

---

## Symptom

A CI run failed with three job failures that share one signature:

```
fatal: could not open '.git/objects/pack/tmp_pack_r2pD7X' for reading: No such file or directory
fatal: fetch-pack: invalid index-pack output
##[error]Directory '/home/<user>/runners/vpt-N/_work/<repo>/<repo>' does not exist
```

The **workspace tree disappeared while `actions/checkout` was fetching into it**.
The same error is in the runner's own log, in
`~/runners/vpt-N/_diag/Worker_<timestamp>-utc.log`, and the log's name says the
job started four seconds before the cleanup ran.

Nothing was wrong with the merged change: it was a documentation change, and
the other self-hosted jobs of the same run passed.

## Root cause

`/usr/local/bin/ci-runner-retention.sh` — the script that reclaims the disk
the self-hosted runners use — was **hand-installed on each runner VM**: not in
the repo, not deployed by `update_core.sh`, not covered by a test. Three
defects in it, all of them silent:

1. **The busy-runner guard could never match.** The policy is "a runner with a
   live job is never touched", and the guard looked for
   `<runner>/bin/Runner.Worker`. The runner runs a **versioned** binary,
   `<runner>/bin.2.338.0/Runner.Worker`, so the fixed path is not in the
   command line: `pgrep` found nothing and **every runner looked idle**, on
   every VM, since the runners were upgraded. The guard had never applied
   once.
2. **The age filter asked the wrong question.** The predicate was
   `find "$r/_work" -mindepth 1 -maxdepth 1 -not -name '_*' -mtime +3`, i.e.
   "is this tree more than three days old". The mtime of `_work/<repo>` is
   when the tree was **created**; the runner reuses one tree per repository
   for days. So a tree that is days old was deleted **while a job was running
   inside it** — and, the other way round, a dead tree younger than four days
   was never reclaimed, so the retention did not do what it says.
3. **The hard-disk branch had the same exposure.** Above 85 % on the runners
   disk the script dropped the age filter entirely and wiped the workspace of
   every runner it believed was idle — and it believed all of them were idle.
   That branch did not fire the night of the incident (the disk was at 60 %),
   but it was one full disk away from deleting every runner's live workspace
   at once.

The cleanup also checked the liveness **once, up front**, and deleted minutes
later, and it never said what it had done: the incident had to be
reconstructed from the CI log, because the journal only said how much space
was free before and after.

## Fix

The script is now versioned, tested and reviewed:
`setup/proxmox/vm/runner/ci-runner-retention.sh`, with its systemd units and
its documentation next to it (`setup/proxmox/vm/runner/README.md`).
`install_runner.sh` installs it and its units.

- **The guard matches the versioned path.** It matches the runner directory
  followed by any `bin.<version>` directory
  (`<runner>/bin[^/]*/Runner.Worker`), so it covers the layout the runner
  really uses and does not assume a fixed one.
- **The liveness is re-checked immediately before every `rm -rf`**, inside the
  loop that deletes: a runner that takes a job between the first check and the
  delete is not touched.
- **The age filter asks about the job, not about the directory.** A workspace
  is reclaimed when the newest thing inside it — the checkout, the files the
  job wrote — is older than `KEEP_DAYS`. The top-level directory's mtime is
  not the signal any more.
- **A tree a live process holds is never deleted**: the script refuses to
  `rm -rf` a path that is the working directory of a live process, or that a
  live process has an open file in. This holds in the hard-disk pass too,
  where only the age filter is dropped, never the safety rules.
- **Every runner gets a decision line** — `skip <runner>: job running`,
  `skip <runner>: in use`, or the number of workspaces reclaimed and the
  bytes they freed — so the next incident can be diagnosed from the VM alone.
- **The two runs are serialised by a lock.** The daily pass and the 15-minute
  check are two different systemd units, so systemd does not serialise them:
  both could walk the same workspaces at the same time. A lock file
  (`/run/ci-runner-retention.lock`) is taken for the whole run, and a run that
  does not get it logs `another run in progress, skipping` and deletes
  nothing.

## Verification

`tests/test_ci_runner_retention.py` (16 cases), run with:

```
timeout 300 python3 -m pytest tests/test_ci_runner_retention.py -q
```

Every case builds a temporary tree that mimics
`~/runners/<name>/{_work,_diag,bin.2.338.0}`; no case touches a runner VM.

- The guard sees a live `bin.2.338.0/Runner.Worker` (**negative control**:
  the pre-fix pattern still misses that very process, so the case fails on
  the pre-fix tree).
- A tree that is five days old but was checked out seconds ago is kept; an
  idle five-day-old tree is reclaimed. The cases assert the **decision**, not
  the arithmetic of `-mtime +3`.
- The workspace of a busy runner survives, and the log says
  `skip vpt-1: job running`.
- Above the hard threshold the pass still reclaims the free tree and still
  keeps the tree a live process holds (`skip vpt-1: in use`) and the tree of a
  busy runner — the fix must not trade a CI red for a disk-full red.
- Every runner gets a decision line with the reclaimed bytes.
- The run lock, in the normal path and in the hard-disk pass (age filter off): with the lock held by another process, the run logs
  `another run in progress, skipping` and deletes nothing — the workspace it
  would have reclaimed is still there.

## Not in this change

Installing the corrected script and units on the runner VMs changes files and
systemd units on hosts: that is the owner's change to apply, not this one.
This branch only brings the code under version control and makes it safe.

## VM install (2026-10-25, owner approved Q232)

Installed by hand on VM 163 (cicd-runner) and VM 164 (cicd-clone-1), reached through the `proxmox` hop:

1. Backup of the old script and units: `/root/ci-retention-backup-20261025/` on each VM.
2. `sudo install -m 0755 ci-runner-retention.sh /usr/local/bin/`; each `.tmpl` installed as `/etc/systemd/system/<name>` (without `.tmpl`); `daemon-reload`; `enable --now` both timers. The daily timer moved from 03:30 local to 08:30 UTC.
3. Verified: `ci-runner-retention.sh --dry-run`, `--check-busy ~/runners/vpt-N` (idle with no job), `systemctl start ci-runner-retention-check.service` (journal: "below 80% - nothing to do").
4. Found while verifying: the units run as root, so `$HOME` is `/root` and the script logged `no runners root at /root/runners - nothing to do`. The VMs got a drop-in `<unit>.service.d/runners-root.conf` with `Environment=RUNNERS_ROOT=/home/jndoye/runners`; the `.service.tmpl` files now carry the same line, so a fresh `install_runner.sh` needs no drop-in.

Rollback: copy the backup files back, remove the two `.service.d` drop-ins, `daemon-reload`.
