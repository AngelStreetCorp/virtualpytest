# BUG-0199 — BUG-0151's audit stopped at four callers: three more host→server callbacks still throw away a 401 in silence

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                      |
|-----------|----------------------------------------------------------------------------|
| ID        | BUG-0199                                                                   |
| Reported  | 2026-09-30 (found while diagnosing a customer install pinned mid-window)    |
| Severity  | Medium — silent loss of script progress, early device release and deployment status |
| Status    | Fixed (pending deploy)                                                     |
| Area      | `shared/src/lib/executors/script_executor.py` · `backend_host/src/services/deployment_scheduler.py` |
| Fixed in  | Unreleased                                                                 |
| Related   | [BUG-0151](BUG-0151-2026-09-21-host-execution-events-rejected-401-since-server-lockdown.md) (same defect, one caller), `be7dfa7c95` (the lockdown) |
| Commit    | this commit                                                                |

---

## How it surfaced

A customer install had **every** Navigation-editor verification time out. The host finished each
run in ~500 ms, recorded it, and emitted its completion event; the browser never received
anything and waited out its 20–25 s budget.

The cause was [BUG-0151](BUG-0151-2026-09-21-host-execution-events-rejected-401-since-server-lockdown.md),
already fixed here on 2026-09-21 — but that install is pinned to `main-2026.09.08-8713`, which
**straddles the break**:

```
be7dfa7c95  2026-09-07  /server/* closed by default — require a credential   ← IS in their build
d6f0ff0f28  2026-09-21  execution events carry the service credential again  ← is NOT
```

Fourteen days wide, and their build sits inside it. So their host posts execution events with no
credential, the server answers 401, and the pre-fix `_post_with_retry` **returns on any response
without checking the status** — no log, no retry, event gone. Hot-fixed on the host by hand;
permanently fixed by any build past `d6f0ff0f28`.

## The actual bug in our tree

BUG-0151 stated the lockdown affected four host→server calls and that "three of the four were
updated". **There were more than four.** A sweep of every `buildServerUrl` caller found three
still wrong today:

| call site | credential | checks the answer | consequence on an auth-enforcing server |
|---|---|---|---|
| `script_executor.py:402` `server/script/progress` | **missing** | no, and wrapped in `except Exception: pass` | live progress during a script run silently never updates |
| `script_executor.py:2359` `server/script/releaseDevice` | **missing** | no | early device release never happens — the device stays locked through the report/video/upload tail, with nothing saying so |
| `deployment_scheduler.py:204` `server/deployment/executionComplete` | present | **no** | a refused notification is indistinguishable from a delivered one |

The shared defect is not the missing header — it is that **a rejection is a response, not an
exception**, so `try/except` around a bare `requests.post` reports success for a 401. Every one of
these is fire-and-forget, so nothing downstream notices either.

`host_script_routes.py:101` (`taskComplete`) is the pattern the rest should copy: it sends the
credential *and* logs both outcomes, which is why it kept working and was visible in the log
throughout the investigation.

## Fix

All three now send `server_auth_headers()` where it was missing and log a rejection with its
status and body. They stay best-effort — a refused progress update still must not fail a script —
but a refusal is now loud instead of invisible.

Verified afterwards that no `buildServerUrl` POST under `backend_host/src` or `shared/src` is left
without `server_auth_headers()`.

## What made this expensive to find, worth recording

The customer's host was *also* out of disk ([BUG-0198](BUG-0198-2026-09-30-disk-full-invisible-and-reported-as-test-failure.md)),
which broke verifications in a second, unrelated way at the same time. Three hypotheses were
chased and disproved before the right one, each because a diagnostic came back empty for the
wrong reason:

- `journalctl -u vpt-server` on the **host** (no such unit there) — read as "no events arriving";
- `docker logs` without `sudo` — read as "no failures logged";
- a `git merge-base` against a tag that does not exist locally, which fails and so answered "not
  in their build" for everything asked of it;
- `tcpdump` on port 5109 for a window with no verification in it.

The one that settled it was replaying the event by hand with `curl`: identical request **with**
`X-API-Key` → 200 and the editor resolved instantly; **without** it → `401 {"error":"Authentication
required"}`. That is the whole bug in two commands.
