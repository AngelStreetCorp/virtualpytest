# BUG-0091 — VPT smoke scripts built the host URL from the server origin and always 404'd

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0091                                                                    |
| Reported  | 2026-09-15                                                                  |
| Status    | Fixed (pending deploy)                                                      |
| Severity  | Medium (two of the five platform self-test scripts could never pass)         |
| Area      | `test_scripts/vpt/smoke_device_control.py` · `test_scripts/vpt/smoke_video_stream.py` · `shared/src/lib/utils/build_url_utils.py` |
| Fixed in  | build 8887                                                                                                                        |

---

## Symptom

`smoke_device_control` (TC051) and `smoke_video_stream` (TC053) failed on every
run, disk and virtual alike:

```
✅ Hosts registered (5 found): HTTP 200 (7ms)
❌ Host 'host-clone-1' health endpoint: HTTP 404
❌ Devices accessible on 'host-clone-1' (0 found): HTTP 404
❌ Device info retrievable for 'host-clone-1_Host': HTTP 404
❌ 1/4 checks OK
```

Step 1 (a server call) passed; every step that touched the *host* API 404'd.

## Root cause

`/server/system/getAllHosts` publishes two different addresses per host:

| field | value | meaning |
|---|---|---|
| `host_url` | `/host/host-clone-1` | **browser-relative** — a route only the reverse proxy resolves |
| `host_api_url` | `http://192.168.x.109:6109` | the direct origin the server itself uses in `call_host()` |

Both scripts took `host_url` and prefixed the backend server's origin:

```python
host_url = server_url.rstrip("/") + host_url   # http://192.168.x.103:5109/host/host-clone-1
```

The backend server on :5109 does not serve `/host/<name>` — only the nginx proxy
does — so every host call 404'd. Verified from the host:

```
http://192.168.x.103:5109/host/host-clone-1/health  -> 404
http://192.168.x.109:6109/health                    -> 200
```

The comment in the code ("the reverse proxy resolves; from a script we must prefix
the server origin") states the first half correctly and then draws the wrong
conclusion: prefixing the *API* origin does not put you behind the proxy.

## Why it was never caught

**These scripts do not run in CI.** `cicd.ci_jobs` over the last 30 days contains
`lint`, `typecheck`, `e2e-smoke`, `e2e-viewport`, `api-smoke`, `api-routes`,
`frontend-component-tests`, `backend-server-tests`, `web-script-local-debug` — and
no job that executes `test_scripts/vpt/smoke_*`. The platform's own five smoke
scripts (TC050–TC054) are only ever run by hand.

## Fix

`_get_host_absolute_base_url()` in `shared/src/lib/utils/build_url_utils.py`
already implemented the correct rule (prefer `host_api_url`, accept `host_url`
only when it carries a scheme) but was private and used in exactly one place.
Promoted to **`get_host_api_origin(host_info)`** with the reasoning documented, old
private name kept as an alias, and both smoke scripts now call it instead of
hand-rolling the URL. `smoke_device_control` also gains an explicit failure when a
host publishes no absolute URL, rather than firing requests at `''`.

## Follow-up (done)

Added the `vpt-smoke` CI job (`.github/workflows/regression.yml`) driving
`tests/test_scripts/run_vpt_smoke.py`. It runs all five scripts through the real
execute path — `POST /server/script/execute`, then polls
`/server/script/status/<task_id>` — because `@script` needs a host and a device and
so cannot run standalone on a runner. Verified against the deployed environment
before wiring in: **5/5 passed**.

The runner treats a completion carrying no `script_success` marker and no exit code
as a **failure**, not a pass — the same rule as [BUG-0089](BUG-0089-2026-09-15-virtual-script-materialize-failure-reported-as-success.md).

Note the job inherits the suite-wide `continue-on-error: true`, so a red smoke run
shows in the CI/CD dashboard and the `ci_jobs` table but does not fail the GitHub
check. That is deliberate consistency with the other jobs, not an endorsement — see
the note in the release entry.
