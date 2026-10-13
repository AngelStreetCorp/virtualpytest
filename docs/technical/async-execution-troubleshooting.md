# Async executions: why the UI waits, and how to find out

**Symptom class:** a run starts (the POST returns `200` with an `execution_id`) and the UI then
waits until it gives up — "Execution timeout for `<id>`", a spinner that never resolves, a panel
that stays empty. The work itself usually finished fine.

This page is the diagnostic path, the failure modes we have actually hit, and — just as
important — the **diagnostics that lie**. Earlier instance of the same class:
[script_execution_socket_diagnosis.md](script_execution_socket_diagnosis.md) (2026-03-05).

---

## 1. The path an execution result travels

```
browser --POST /server/<domain>/execute*--> server --proxy--> host
                                                               |  runs the work
                                                               |  writes device.<executor>._executions[id]
                                                               v
browser <--/system socket---- server <--POST /server/system/executionEvent--+
   (waitForExecutionSocketEvent)     (emit_system_update -> socketio.emit)
```

| link | code | logs on failure? |
|---|---|---|
| browser to server to host | `auto_proxy.py` (most execute routes are pure passthrough) | yes, HTTP status |
| host runs the work | `host_*_routes.py` `_execute_*_thread` | yes, in the run's log capture |
| host to server callback | `execution_event_utils.py` `emit_execution_event` | **yes, since BUG-0151/0199** — was silent before |
| server to browser | `server_system_routes.py:executionEvent` then `emit_system_update` | **no — silent no-op if socketio is unset** |
| browser waits | `frontend/src/utils/executionSocketWait.ts` | console warn on `connect_error` only |

Two properties worth memorising:

- **The host's status store is written at the same moment as the event**, not when the work
  finishes. So a polling fallback cannot beat a thread that is still doing something after the
  result exists (see §3.3).
- **`waitForExecutionSocketEvent` resolves and disconnects on the first non-`running` status.** A
  second terminal event for the same id is dropped.

## 2. The decisive diagnostics, in order

Run these on the right box. §4 lists the ways each of them silently lies.

**a. Did the host finish?** Ask it directly — this is also exactly what the polling fallback does:

```bash
curl -s "$SERVER_URL/server/<domain>/execution/<execution_id>/status?host_name=<host>&device_id=<device>&team_id=<team>" | head -40
```

| answer | meaning |
|---|---|
| `"status":"completed"` / `"error"` with a result | the host is done; the event never reached the browser, go to (b) |
| `"status":"running"` forever | the host is stuck; read its log for what it is doing after the result |
| `404` / not found | wrong `device_id`, or the execution never registered |

**b. Is the callback being accepted?** Replay it by hand from the **host**:

```bash
SRV=$(sudo grep -h '^SERVER_URL' /opt/virtualpytest/.env | cut -d= -f2- | tr -d '"')
KEY=$(sudo grep -h '^API_KEY'    /opt/virtualpytest/.env | cut -d= -f2- | tr -d '"')
printf '%s' '{"execution_id":"probe","execution_type":"verification","status":"completed"}' > /tmp/probe.json

curl -sS -w '\n^^ no-key: HTTP %{http_code}\n'   -X POST "$SRV/server/system/executionEvent" -H 'Content-Type: application/json'                      -d @/tmp/probe.json
curl -sS -w '\n^^ with-key: HTTP %{http_code}\n' -X POST "$SRV/server/system/executionEvent" -H 'Content-Type: application/json' -H "X-API-Key: $KEY" -d @/tmp/probe.json
```

`401` without the key and `200` with it is the normal, healthy result — `/server/*` has required a
credential since `be7dfa7c95` (2026-09-07). It becomes the *bug* when the host is not sending one
(§3.1).

**c. Is the relay alive?** Start a real run, take its `execution_id` from the browser console, and
fire (b) **with the key and that id** while it is still waiting. If the UI resolves the instant
your curl returns, everything from the server to the browser works and the fault is upstream.

**d. What does the host say it emitted?**

```bash
sudo journalctl -u vpt-host -f -o short-iso | grep -vE 'kpi_measurement|@fuzzy|@l1_match|@navigation:graph'
```

Run **one** execution and **wait 60 s** — see §4.4.

## 3. Failure modes we have actually hit

### 3.1 The callback is rejected and the rejection is thrown away

[BUG-0151](../bugs/BUG-0151-2026-09-21-host-execution-events-rejected-401-since-server-lockdown.md),
[BUG-0199](../bugs/BUG-0199-2026-09-30-three-more-host-callbacks-swallow-401.md)

`/server/*` requires a credential. A host that does not send one gets `401` — and **a rejection is
a response, not an exception**, so `try/except` around a bare `requests.post` reports success.
The event is lost with no log line, no retry, and nothing on the wire to find.

Every async flow degrades to its polling fallback; anything without a fallback simply times out.
Affected in turn: execution events (fixed 2026-09-21), then `script/progress`,
`script/releaseDevice` and `deployment/executionComplete` (fixed 2026-09-30).

**The pattern to copy** — credential *and* both outcomes logged — is `host_script_routes.py`
`taskComplete`. Pinned by `tests/backend_host/test_execution_event_utils.py`.

### 3.2 The host cannot write, and reports it as a test result

[BUG-0198](../bugs/BUG-0198-2026-09-30-disk-full-invisible-and-reported-as-test-failure.md)

A full data mount makes `take_screenshot`'s hot-to-cold copy fail with `ENOSPC`. Before the fix the
generic handler recorded no reason, so a verification reported `0/2 passed` and wrote a
`node_metrics` row: an infrastructure outage indistinguishable from a device that had drifted
off-screen.

It also made runs fail in ~67 ms — fast enough to lose the race against the browser opening its
socket, so the visible symptom was a *timeout*, pointing away from the disk.

Check the mount that actually fills, not `/`:

```bash
df -h; df -i                 # ENOSPC with plenty of space = inodes
du -sh /data/stream/* | sort -h
```

`disk_percent` now reports the fullest of `/`, the stream filesystem and each `captureN/hot`, and
retention tightens as a mount fills.

### 3.3 Something slow runs *after* the result exists

[BUG-0200](../bugs/BUG-0200-2026-09-30-node-verification-runs-under-a-leftover-variant.md)

`execute_single_node_verification` finishes the verification, records it, and *then* runs
`localize_check` — and the event plus the status store are only written after all of that returns.
A cold-variant localize was rebuilding 36 trees because the run never declared its scope, so a
result that existed at 480 ms was reported seconds later. Polling cannot rescue this: the store is
written in the same place as the event.

If the log shows `record_node_execution ✓` and then a `TreeManager` rebuild before
`Log capture completed`, this is what you are looking at.

To put a number on that rebuild on any given host — cold vs warm, same code path the run
takes — use `scripts/measure_cache_warmup.py` (see
[BUG-0202](../bugs/BUG-0202-2026-09-30-takecontrol-warmed-the-wrong-cache-scope.md)).
It was 0.068s on a 14-tree lab hierarchy; it scales with hierarchy size and DB latency.

### 3.4 The browser is connected but nothing is broadcast

The `/system` handshake refuses unauthenticated connections since `9534d7aeff` (2026-09-22). A
refusal produces `connect_error`, which the waiter surfaces as
`Execution timeout for <id>; last socket error: ...`.

**The absence of that suffix is evidence**: the socket connected and had nothing delivered. And a
`42/system,["connected",...]` frame in the devtools polling response proves server-to-client push
works for that client.

`emit_system_update` returns silently when it cannot resolve `socketio`, so a broadcast can vanish
with no log — rule that out before blaming the transport. Server workers are `1`
(`gunicorn_app.py`), so a multi-worker split-brain is not a candidate unless that changes.

## 4. Diagnostics that lie

Every one of these cost real time in the 2026-09-30 investigation.

1. **`journalctl -u <unit>` on the wrong box** prints nothing and exits 0. The host runs
   `vpt-host` / `vpt-stream` / `vpt-kpi`; only the server VM has `vpt-server`. Confirm with
   `systemctl list-units --type=service | grep -i vpt` or `cat /proc/<pid>/cgroup`.
2. **`docker logs` without `sudo`** fails, and with `2>&1 | grep` the error is swallowed by the
   grep. An empty result is not an empty log.
3. **The server's access log is not in journald** on a VM install, so "no `POST /server/...` in the
   journal" says nothing about whether the request arrived. Application prints are there; HTTP
   access lines are not.
4. **A capture window shorter than the retry budget.** `_post_with_retry` logs only after both
   attempts — about 20.5 s on the fire-and-forget path. A 20 s capture ends just before the line
   appears. Wait 60 s.
5. **`tcpdump` on the wrong port, or an idle window.** If `SERVER_URL` is `https://...` the flow is
   443 through the proxy, not 5109 — and the executionEvent POST only happens when something
   executes, so filtering for it during an idle minute finds nothing.
6. **`git merge-base --is-ancestor <commit> <tag>` with a tag that does not exist locally** fails,
   and in `cmd && echo YES || echo no` that reads as "not in that build". Run `git rev-parse <tag>`
   first. Deployment labels are not always git tags: one install's
   `current:main-2026.09.08-8713/prod-2026.09.08-8558` had only the first half as a real tag.
7. **Terminal line-wrapping in a pasted `curl`.** A wrap inside a JSON string yields
   `400 "...could not understand"`; a wrap inside `-H "X-API-Key: ..."` yields a spurious `401`.
   Put the body in a file (`-d @file`) and keep headers on one line.
8. **A verification that "fails" may not have run.** `0/2 passed` together with
   `source_image_path not found` is an infrastructure failure, not a result (§3.2).

## 5. Checking what a host is actually running

A deployment label is not proof. For any suspected fix:

```bash
# on the host
cat /opt/virtualpytest/VERSION.txt            # current:<core>/<overlay>
sudo sed -n '1,60p' /opt/virtualpytest/<path to the file you care about>
```

and locally:

```bash
git rev-parse <tag>                            # does the label resolve at all?
git merge-base --is-ancestor <fix-commit> <tag> && echo in || echo out
git diff <tag> HEAD -- <path>                  # what actually differs
```

Reading the deployed file is the only answer that cannot be wrong. A host pinned between a
lockdown and its fix looks correct in every changelog and is still broken.

Also: a long-lived process keeps running the code it started with. After patching a file in place,
restart the unit — `vpt-host` for the app, `vpt-kpi` for KPI runs, `vpt-stream` for the archiver
(see [BUG-0094](../bugs/BUG-0094-2026-09-15-archiver-never-rotates-capture-root-artifacts.md)).
