# BUG-0433 — A dropped TLS session cost a background loop a whole cycle and logged an unreadable error

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0433                                                     |
| Reported  | 2026-10-07                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | shared / backend_server                                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

The server journal filled with errors from background work that had already recovered:

```
[@section_cache:prewarm] overview failed: {'message': 'JSON could not be generated',
  'code': 500, 'hint': 'Refer to full message for details',
  'details': "b'<html>\r\n<head><title>500 Internal Server Error</title></head>…nginx/1.26.3…"}
SSL: DECRYPTION_FAILED_OR_BAD_RECORD_MAC (_ssl.c:2546)
SSL: WRONG_VERSION_NUMBER
```

Five such TLS failures in a week, all within seconds of a service start. The analytics
sections pre-warm every 30 s and the snapshot sweeper runs every 15 min, so one blip simply
burned a whole cycle — and the log line was a PostgREST error dict with a raw HTML body
inside it, long enough to bury the rest of the journal.

## Root cause

Two separate-looking symptoms, one cause: a transport failure on the way to Supabase, not a
query problem.

This platform reaches the Supabase REST API over the **public hostname of the main server**
(`SUPABASE_URL=https://<main server>/supabase`), so every request from a host crosses the
main server's nginx. `vpt-server` starts with only `network.target` — no ordering against
anything Supabase-related — and its pre-warm loop begins the instant the process does. The
first cycles therefore race the far end: a TLS session that has not settled fails the read
(`DECRYPTION_FAILED_OR_BAD_RECORD_MAC`), a peer answering on the wrong port fails the
handshake (`WRONG_VERSION_NUMBER`), and a proxy whose upstream is not up yet answers with an
HTML 500 that supabase-py reports as `JSON could not be generated`.

Nothing is lost — `_refresh` deliberately keeps a good stale value, and both loops retry on
their next tick — but the code treated a first, transient failure as the final answer for
that cycle, and printed the raw exception.

## Fix

`shared/src/lib/database/transient_retry.py`:

- `is_transient(exc)` classifies a failure as the *path's* fault — an `ssl.SSLError`,
  `RemoteDisconnected`, `IncompleteRead`, `ConnectionReset`, a timeout, or one of the
  observed markers (`DECRYPTION_FAILED_OR_BAD_RECORD_MAC`, `WRONG_VERSION_NUMBER`,
  `JSON could not be generated`, 5xx HTML). Deliberately conservative: when in doubt it
  says *not* transient.
- `call_with_retry(fn, label=…, attempts=3, sleep=…)` retries only those, with a growing
  delay, and logs one compact line. A real API answer — a PostgREST JSON error, a 4xx, a
  missing table — is re-raised on the **first** attempt, so retrying can never hide a bug
  behind a slower trace.
- `brief(exc)` collapses an exception to one readable line, so a dict or HTML body cannot
  swallow the journal again.

Wired into the two call sites that produced the noise:

- `section_cache.start_prewarm` — retries per section, and passes the module's own `_sleep`
  rather than `time.sleep`, so a wait inside the gevent greenlet does not block the hub the
  request path runs on.
- `report_snapshots_db.list_purgeable` — a pure read, so retrying it is safe; without it the
  purge backlog sat untouched for a full 15-minute cycle after one dropped session.

`_refresh` and the sweeper's own error lines now use `brief()`.

## Verification

- `tests/shared/test_transient_retry.py` — 16 tests: each observed failure classifies as
  transient, real API errors never retry, a non-transient error surfaces on attempt one,
  delays grow, one log line per retry, and the helper validates its own arguments.
- `tests/shared/test_report_snapshots_db.py` and `tests/backend_server/test_analytics.py`
  pass unchanged.
- After deploy: restart a server while the Supabase path is slow and confirm the journal
  shows one `[@db:transient]` line per blip followed by recovery, instead of a
  full-cycle failure; the sweeper still purges on its first successful pass.

## Not addressed here

The upstream itself — the nginx 500 while the far end comes up — is infrastructure, not
application code, and is left to the platform owners. This change makes the application
survive it quietly instead of logging it loudly.
