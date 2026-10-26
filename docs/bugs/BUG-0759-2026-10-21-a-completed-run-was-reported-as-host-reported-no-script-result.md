# BUG-0759 — A run that completed on the host was reported as "host reported no script result"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0759                                                     |
| Reported  | 2026-10-21                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High (EVERY legitimately failing script run was reported to its consumer as an infrastructure fault; a reader is told the host never reported anything, when the report, the DB row and the uploads all exist) |
| Area      | backend / testing                                            |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

`GET /server/script/status/<task_id>` returns a task that says the host never reported a
result — while the host, in the same minutes, finished the run, wrote a script-result row,
generated the report and uploaded every artifact:

```
status  = failed
error   = host reported no script result
```

but on the host, for the very same run id:

```
Report generated successfully
📊 Report URL captured: …/youtube_video_check_60be7382-…/report.html
📝 Logs uploaded: …/execution.txt
📦 metadata value: {'code_version': 'main-2026.10.21-89534', … 'video_result': {…}}
  - script_result_id: 60be7382-4f85-4627-8019-679aa1fc5552
  - success: False
  - execution_time_ms: 36144
Updating script execution:
```

So the run produced everything a run produces. The task simply never learned it.

The **run** being reported as failed is defensible on its own — the script's verdict was negative
([BUG-0756](BUG-0756-2026-10-21-a-web-video-test-never-confirms-playback.md)). The **error
string** is not: it claims the host reported nothing, which is false, and it replaces the real
reason (a failed playback check) with an infrastructure-sounding one.

Seen on both runs of a parallel pair on `host-clone-2`, 2026-10-21, build `main-2026.10.21-89534`.

## Root cause

**One line.** `task_complete` filled in the reason itself, and the sentence it filled in was
wrong for the commonest case (`backend_server/src/routes/server_script_routes.py:1329`):

```python
if not run_success and not error:
    error = result.get('stderr') or 'host reported no script result'
```

A script that ran and printed `SCRIPT_SUCCESS:false` **did report** — the test failed, which
is the outcome the run exists to produce. The executor merges stderr into stdout and sends
`stderr: ''` on a clean run (`shared/src/lib/executors/script_executor.py:1654`), so the
`or` fell straight through to the invented sentence. The verdict (`_derive_run_success`) was
already correct; only the words a consumer saw were not. Every failing test therefore
announced itself as a host fault.

What the evidence rules out:

- the host did not crash — `vpt-host` was `active` before, during and after, and the same
  process served both runs;
- the host did not fail to execute — the script ran to completion in 36 s and reported;
- it is not specific to parallel runs, to a browser script, or to this host.

The gap is between two truths the platform keeps: the host's own script-result row (which exists,
with an id, a verdict and a duration) and the task record the API serves. Something in between
fails to carry the result back. Whether the result is written to a table the task reader does not
poll, whether the callback fires with a payload shape the reader does not match, or whether the
reader times out before the run finishes (36 s here, which is short), all fit the evidence.

## Fix

The reason is now chosen by what the callback actually carried
(`_describe_failed_run()`):

1. **stderr**, if the host phrased the failure — its sentence is the reason;
2. **a failed marker** (`script_success is False`) — *"The test ran and reported a failed
   result"*, with the report URL, because the consumer needs the report, not a sentence
   about the host;
3. **otherwise** — *"host reported no script result"*, which is now reachable only in the
   one case it ever described: the host really did say nothing.

The `or` that produced the wrong answer is gone from the call site.

## Verification

`tests/backend/test_failed_run_reason.py` (12 tests): a failed test is never described
as a silent host, is described as failed and carries the report URL, survives a missing
report URL, a silent host still gets the old wording, stderr beats the generic message and is
truncated at 500 characters, a nonsense payload cannot explode it, a successful marker never
acquires a reason — and a guard reads the call site's source so the old rule cannot creep back
in beside the helper.

> **Related, filed independently by the QA sweep 2026-10-22:**
> [BUG-0811](BUG-0811-2026-10-22-results-api-reports-a-running-run-as-finished-and-failed.md)
> — `/server/script-results/getAllScriptResults` creates a row with `completed_at` already
> set, so a run reads as instant-failed for its whole duration. Different feed, same family:
> the result layer misrepresenting a run's state. Whoever fixes one should look at the other.

## Verification

Once fixed, a run that completes with a negative verdict has to read:

```
status  = failed
error   = the script's own reason (the playback verdict), or no error at all
script_success = false
```

and never `host reported no script result`. Both a solo run and a run beside another one have to
be checked: if this is a timing race, a single run may pass while a pair fails.
## Sightings

- also seen by QA sweep 2026-10-22 (OPS-05): the stuck "host reported no script result" execution for host-clone-2 stays in `running`, locks the host_vnc targets and makes the Device page poll a missing running.log every 2 s (filed as BUG-0780).
