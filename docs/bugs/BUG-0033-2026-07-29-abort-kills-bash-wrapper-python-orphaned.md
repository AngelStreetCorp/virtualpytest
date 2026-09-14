# BUG-0033 — Script abort kills the bash wrapper, python keeps running (force take-control)

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0033                                                     |
| Reported  | 2026-07-29                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High (two actors on one device after every takeover of a live run) |
| Area      | shared/script_executor — process kill on abort/timeout       |
| Fixed in  | build 8713                                                   |
| Commit    | `e9111a393`                                                  |

---

## Symptom

A user force-took control of a device running a script. The UI reported the takeover
succeeded (`aborted: true` all the way up), the lock was cleared — but the python test
script kept running in the background and kept driving the STB underneath the user.

Same visible outcome as [BUG-0006](BUG-0006-2026-07-20-scheduled-script-survives-force-take-control.md),
different mechanism. BUG-0006 fixed the registry key so the abort *finds* the process;
its "left alone" notes already warned that `terminate()`/`kill()` only reach the direct
child. That residual is this bug — and it is worse than noted: it isn't only the script's
*own* subprocesses that survive, the script itself always did.

## Root cause

On Linux hosts `ScriptExecutor._execute_script_subprocess` launches every script as a
compound shell command (`shared/src/lib/executors/script_executor.py`):

```
bash -c "source venv/bin/activate && python <script.py> <args>"
```

Because the command is compound (`&&`), bash cannot exec-optimize — it stays alive as the
parent and forks python as a separate child. The Popen handle registered in
`_running_processes_by_device` is the **bash wrapper**, and `abort_running_script()` did
`process.terminate()` / `process.kill()` — signalling **only the bash pid**. bash exits
with SIGTERM (it does not forward signals to a foreground child), python is reparented to
init and keeps running. Reproduced empirically: after `terminate()`, bash is gone and the
python child survives.

Four knock-on effects made it invisible and unrecoverable:

1. **The abort reported success.** `process.wait(timeout=5)` returned instantly (bash did
   die), so the host answered `{success: true, aborted: true}` — truthful about bash,
   false about the script.
2. **The lock was cleared on that answer.** `abort_and_force_unlock` saw `aborted=True`
   and released — the exact split-brain its docstring warns about: lock says free,
   orphaned python keeps driving the device.
3. **The orphan became unkillable.** The `finally` block unregistered the process, so a
   second abort attempt returned "No running script found".
4. **The run even completed normally.** python inherited the stdout pipe, so the host's
   streaming loop never saw EOF — it kept consuming the orphan's output and eventually
   posted a normal completion and report.

The 1-hour timeout kill path had the same flaw (`process.kill()` on the wrapper only).

## Fix

`shared/src/lib/executors/script_executor.py`:

- **Scripts launch in their own process group** — `start_new_session=True` on the Popen
  (POSIX; skipped on Windows, which launches python directly with no wrapper).
- **New `_kill_process_tree()`** used by both `abort_running_script()` and the timeout
  path: `os.killpg(pgid, SIGTERM)`, wait 5s, escalate to `SIGKILL` on the group.
  One signal takes bash, python, and anything the script itself spawned (ffmpeg, adb, …)
  atomically — closing BUG-0006's grandchild residual too. `ProcessLookupError` guarded
  (group already gone). Windows counterpart: `taskkill /PID <pid> /T /F`.

## Verification

Local empirical repro on macOS (same POSIX semantics as the Pi hosts):

- **Old behavior reproduced:** `bash -c "source … && python3 …"`, `terminate()` on the
  wrapper → bash exits rc=-15, python survives as an orphan.
- **New behavior verified:** same launch with `start_new_session=True`, script also
  spawning a grandchild `sleep 60`; one `killpg(SIGTERM)` → group empty, no bash, no
  python, no sleep survivors.
- `py_compile` clean.

**Still to confirm on a deployed host:** run a script, force take control mid-execution,
check `journalctl` shows the abort and `pgrep -f <script>` comes back empty.

## Notes / left alone

- BUG-0006's other residuals stand: testcases still take no device lock, the synchronous
  testcase path is still unabortable, plain `/takeControl` still doesn't abort testcases,
  and the registry holds one process per device.
- `_kill_process_tree` won't reach a process that calls `setsid()` itself and leaves the
  group — no current script does.
