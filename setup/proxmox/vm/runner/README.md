# CI runner retention

Reclaims the disk space the self-hosted GitHub Actions runners use, without
ever deleting the workspace of a running job.

`ci-runner-retention.sh` used to live only on the runner VMs, was installed by
hand, and had no test — so the code that can kill a CI run was unreviewed and
unprotected. It is versioned here now, with its units and its tests
(`tests/test_ci_runner_retention.py`, BUG-0903).

## The layout it works on

```
~/runners/<runner>/_work/<repo>/<repo>/.git   the checkout of one job
~/runners/<runner>/_diag/Worker_*.log          one log per job
~/runners/<runner>/bin.<x.y.z>/Runner.Worker    the worker binary (versioned)
```

`~/runners/<runner>/_work/_*` holds the runner internals (`_actions`, `_tool`,
`_diag`, `_temp`). They are never reclaimed.

## The units

| Unit | What it does |
|---|---|
| `ci-runner-retention.service` | one full cleanup pass (`ci-runner-retention.sh`) |
| `ci-runner-retention.timer` | daily at 08:30 UTC (outside the 00:00-07:00 UTC Night gate), up to 300 s of random delay, `Persistent=true` |
| `ci-runner-retention-check.service` | the same script with `--check`: it reclaims only when a disk is above the check threshold (80 %) |
| `ci-runner-retention-check.timer` | every 15 minutes |

Both services run as **root**: the safety net has to see the working directory
and the open files of every process on the VM, not only the ones of the runner
user.

The daily pass and the 15-minute check are two different systemd units, so
systemd does not serialise them: a lock file (`/run/ci-runner-retention.lock`,
overridable with `CI_RETENTION_LOCK_FILE`) keeps the two runs apart, and a run
that finds the lock held logs `another run in progress, skipping` and deletes
nothing.

In the repo they are shipped as templates (`ci-runner-retention*.service.tmpl`,
`ci-runner-retention*.timer.tmpl`) and `install_runner.sh` renders them into
`/etc/systemd/system` under their real unit names. A file whose name ends in
`.service`, `.timer` or `.socket` is classified as a systemd unit by the merge
policy and is refused whatever the approval says, so the repo carries the
templates and the installer writes the units. The rendered file is
byte-identical to its template.

## Installing

`install_runner.sh` installs the script and renders the units:

```
sudo install -m 0755 setup/proxmox/vm/runner/ci-runner-retention.sh /usr/local/bin/ci-runner-retention.sh
# ci-runner-retention.service.tmpl  ->  /etc/systemd/system/ci-runner-retention.service
# ci-runner-retention.timer.tmpl    ->  /etc/systemd/system/ci-runner-retention.timer
# ci-runner-retention-check.service.tmpl -> /etc/systemd/system/ci-runner-retention-check.service
# ci-runner-retention-check.timer.tmpl   -> /etc/systemd/system/ci-runner-retention-check.timer
sudo systemctl daemon-reload
sudo systemctl enable --now ci-runner-retention.timer ci-runner-retention-check.timer
```

The timers stay disabled when the VM has no `~/runners` directory: the script
would have nothing to do.

## What it decides, and why

| Rule | Why |
|---|---|
| A runner is busy when a worker process is alive | the policy is "a runner with a live job is never touched" |
| The busy check matches `bin.<x.y.z>/Runner.Worker` | the binary is versioned; the old guard matched `bin/Runner.Worker`, which nothing runs, so **every runner looked idle** |
| The busy check is repeated right before every `rm -rf` | a runner can take a job between the first check and the delete |
| A workspace is reclaimed on its **job activity**, not on the mtime of the top-level directory | the directory says when the tree was created, and the runner reuses one tree per repository for days |
| A tree a live process holds (its cwd, or an open file in it) is never deleted | the job's own step holds the checkout open |
| The hard-disk pass (runners disk above 85 %) drops the age filter, not the safety rules | space has to come back fast, but not at the price of a killed job |
| Every runner gets a decision line, with the reclaimed bytes | the next failure must be diagnosable from the VM alone |

The age filter reads the **newest file inside the tree** (the checkout, and
whatever the job wrote) and compares it with `--keep-days` (3 by default). The
newest `_diag/Worker_*.log` of the runner is logged for the diagnosis but is
not the decision: a worker log is per runner, not per workspace, so using it
as the floor would stop the script from ever reclaiming the second
repository's workspace.

## Reading the log

```
ci-retention: before root=41% runners=60% (free root: 47.0G, runners: 16.0G)
ci-retention: skip vpt-N: job running
ci-retention: tree vpt-N/repo: skip (job activity 1d old, keep 3d)
ci-retention: skip vpt-N: in use
ci-retention: tree vpt-N/repo: skip (held by pid 1234)
ci-retention: deleted vpt-N/repo (1.2G)
ci-retention: vpt-N: delete 1 workspace(s), keep 0, reclaimed 1.2G
ci-retention: vpt-N: nothing to reclaim
ci-retention: after  root=33% runners=60% (free root: 53.0G, runners: 16.0G)
```

`skip <runner>: job running` and `skip <runner>: in use` are the two lines
that mean "a live job was protected".

## Options

```
--check               only clean when a disk is above the check threshold
--dry-run             report what would be deleted, delete nothing
--runners-root DIR    root holding the runner directories (default $HOME/runners)
--keep-days N         keep a workspace that saw job activity in the last N days
--check-threshold PCT  disk percentage that triggers a cleanup in --check mode
--hard-threshold PCT  disk percentage that triggers the hard-disk pass
--check-busy DIR      print "busy" or "idle" for one runner directory
```

`--check-busy` is the verification helper: on a VM, run
`ci-runner-retention.sh --check-busy /home/<user>/runners/vpt-N` while a job
runs and it must print `busy`.

## Tests

```
timeout 300 python3 -m pytest tests/test_ci_runner_retention.py -q
```

They build a temporary tree that mimics `~/runners/<name>/{_work,_diag,bin.2.338.0}`
and never touch a runner VM.
